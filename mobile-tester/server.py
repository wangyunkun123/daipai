#!/usr/bin/env python3
"""
带拍 · 移动端测试工具 在电脑上启动后，手机浏览器访问 http://<电脑IP>:8888
拍照上传 → 渐进式展示（EXIF→场景→方向→方案按需生成）→ 生图提示词
"""

import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()
from PIL import Image, ImageOps
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, session, redirect, url_for
from knowledge_base import get_all_knowledge_for_prompt, get_style_detail, get_device_adaptation, get_source_quality_map, get_knowledge_files_by_quality, load_series_rhythm
from database import accumulate, query_scene_techniques_for_plans, get_db_stats, migrate_from_json, export_for_claude, import_from_claude, apply_pending_sync, check_and_increment_usage, get_daily_usage, submit_quota_request, get_quota_request_status, get_pending_quota_requests, approve_quota_request, save_usage_session, update_usage_session, save_feedback, get_feedback_stats, export_feedback_markdown, DISLIKE_REASONS, DB_PATH, log_api_call, get_api_call_stats, get_style_technique_panel, get_style_exploration_stats, log_style_exploration, promote_exploration_to_style, delete_exploration, extract_scene_category, seed_from_knowledge_base, seed_practical_techniques, seed_posing_techniques
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# ============================================================
# 配置
# ============================================================
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "daipai2026")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
DOUBAO_FAST_MODEL = "doubao-seed-2.0-lite"  # 方案生成用快速模型——结构化JSON不需要最强推理
EXIF_SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude/skills/daipai/scripts/exif-extract.py")
STYLE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "style_cache.json")  # 已弃用，保留变量以防旧引用
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "10"))  # 每人每天免费次数
MAX_IMAGE_DIM = 2048  # 上传前压缩到最长边2048px，加快上传
VISION_IMAGE_DIM = 1024  # 给豆包视觉用的更小尺寸——场景分析不需要高分辨率，省一半时间
REQUEST_TIMEOUT = 300  # 含大图上传时间
SESSION_TTL = 86400  # 24小时——与前端 localStorage 恢复窗口一致

# 并发控制
_processing_lock = threading.Lock()
_processing = False

# 方案生成并发控制——防止重复 LLM 调用（retry/poll 同时来时只生成一次）
_plan_generating: dict[str, float] = {}  # key: global_cache_key → started_at_timestamp
_plan_generating_lock = threading.Lock()

# Session 存储
_sessions: dict[str, dict] = {}
_SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
# 本地分析留存目录——每次分析完存一份，方便代码改动后对比
_RECENT_DIR = os.path.join(os.path.dirname(__file__), "recent_analyses")

def _session_path(session_id):
    return os.path.join(_SESSIONS_DIR, f"{session_id}.json")

def _img_path(session_id):
    """图片单独存文件——避免 600KB base64 撑爆 JSON"""
    return os.path.join(_SESSIONS_DIR, f"{session_id}.img")

def _save_session(session_id):
    sess = _sessions.get(session_id)
    if not sess:
        return
    try:
        os.makedirs(_SESSIONS_DIR, exist_ok=True)
        # 图片单独写文件——不在 JSON 里塞 base64
        img_b64 = sess.get("img_b64", "")
        if img_b64:
            try:
                with open(_img_path(session_id), "w", encoding="utf-8") as f:
                    f.write(img_b64)
            except Exception as e:
                print(f"[Session] Image save failed {session_id}: {e}", file=sys.stderr, flush=True)
        data = {
            "session_id": session_id,
            "created_at": sess.get("created_at", 0),
            "vision_json": sess.get("vision_json"),
            "exif_summary": sess.get("exif_summary"),
            "exif_data": sess.get("exif_data", {}),
            "device_key": sess.get("device_key"),
            "device_context": sess.get("device_context"),
            "directions": sess.get("directions"),
            "scene_tier": sess.get("scene_tier"),
            "env_context": sess.get("env_context", ""),
            "fold_details": sess.get("fold_details", {}),
            "scene_category": sess.get("scene_category", ""),
            "photo_path": sess.get("photo_path", ""),
            "insight": sess.get("insight", ""),
            "client_ip": sess.get("client_ip"),
            "daily_count_key": sess.get("daily_count_key", ""),
            "plan_cache": sess.get("plan_cache", {}),
            # 只存标记，不存 base64 数据
            "has_img": bool(sess.get("img_b64", "")),
            "scene_mode": sess.get("scene_mode", ""),
        }
        with open(_session_path(session_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Session] Save failed {session_id}: {e}", file=sys.stderr, flush=True)

def _load_session_from_disk(session_id):
    try:
        path = _session_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("created_at", 0) > SESSION_TTL:
            try: os.remove(path)
            except: pass
            # 同时清理图片文件
            try: os.remove(_img_path(session_id))
            except: pass
            return None
        # 从独立文件加载图片（新版）或从 JSON 字段兼容旧数据
        img_b64 = ""
        if data.get("has_img"):
            img_path = _img_path(session_id)
            if os.path.exists(img_path):
                try:
                    with open(img_path, "r", encoding="utf-8") as f:
                        img_b64 = f.read()
                except Exception:
                    pass
        if not img_b64:
            # 兼容旧格式（img_b64 直接存在 JSON 里）
            img_b64 = data.get("img_b64", "") or ""
        sess = {
            "vision_json": data.get("vision_json"),
            "exif_summary": data.get("exif_summary"),
            "exif_data": data.get("exif_data", {}),
            "device_key": data.get("device_key", ""),
            "device_context": data.get("device_context", ""),
            "directions": data.get("directions", []),
            "scene_tier": data.get("scene_tier", "🟈"),
            "plan_cache": {},
            "created_at": data.get("created_at", time.time()),
            "client_ip": data.get("client_ip"),
            "env_context": data.get("env_context", ""),
            "fold_details": data.get("fold_details", {}),
            "scene_category": data.get("scene_category", ""),
            "photo_path": data.get("photo_path", ""),
            "insight": data.get("insight", ""),
            "daily_count_key": data.get("daily_count_key", ""),
            "plan_cache": data.get("plan_cache", {}),
            "img_b64": img_b64,
            "scene_mode": data.get("scene_mode", ""),
        }
        if sess["photo_path"] and not os.path.exists(sess["photo_path"]):
            sess["photo_path"] = ""
        _sessions[session_id] = sess
        print(f"[Session] Restored from disk: {session_id} (img={'yes' if img_b64 else 'no'})", file=sys.stderr, flush=True)
        return sess
    except Exception as e:
        print(f"[Session] Load failed {session_id}: {e}", file=sys.stderr, flush=True)
        return None

def _load_all_sessions():
    try:
        if not os.path.isdir(_SESSIONS_DIR):
            return
        count = 0
        for fn in os.listdir(_SESSIONS_DIR):
            if fn.endswith(".json"):
                sid = fn[:-5]
                if _load_session_from_disk(sid):
                    count += 1
        if count:
            print(f"[Session] Startup: restored {count} sessions from disk", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[Session] Startup load error: {e}", file=sys.stderr, flush=True)

_load_all_sessions()

# 设备档案（精简版）
DEVICE_CONTEXTS = {
    "iphone-17-pro": {
        "name": "iPhone 17 Pro",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2× 人像 / 5× 长焦",
        "strengths": "48MP 主摄细节丰富, 5× 长焦压缩空间, 人像模式自然虚化, 夜景模式强",
        "limits": "5× 以下长焦为数码裁切, 极暗光需稳定支撑",
        "capability": "🟢 全焦段自由, 🟡 极暗光需三脚架, 🔴 无"
    },
    "iphone-17": {
        "name": "iPhone 17",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2× 长焦",
        "strengths": "48MP 主摄, 2× 人像模式, 日常场景全覆盖",
        "limits": "无 5× 长焦, 远摄靠数码变焦, 极暗光中等表现",
        "capability": "🟢 日常全场景, 🟡 远摄需走近, 🔴 体育/野生动物"
    },
    "iphone-pro-13-16": {
        "name": "iPhone Pro (13-16)",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2×-5× 长焦（视型号）",
        "strengths": "三摄系统完整, ProRAW 可选, 人像模式成熟",
        "limits": "无 48MP（13-14）, 长焦画质弱于 17 Pro",
        "capability": "🟢 常规场景, 🟡 极暗/超远焦, 🔴 无"
    },
    "iphone-standard-13-16": {
        "name": "iPhone (13-16)",
        "lenses": "0.5× 超广角 / 1× 主摄",
        "strengths": "主摄素质好, 日常使用足够, 人像模式可用",
        "limits": "无长焦镜头, 远摄/空间压缩效果受限, 夜景模式中等",
        "capability": "🟢 日常记录, 🟡 远摄/人像虚化, 🔴 专业创作"
    },
    "android-flagship": {
        "name": "安卓旗舰",
        "lenses": "0.5×-0.6× 超广角 / 1× 主摄 / 3×-5× 长焦（视型号）",
        "strengths": "大底主摄像素高, 部分机型有 5× 以上潜望长焦, AI 增强可用",
        "limits": "焦段切换不如 iPhone 平滑, 人像虚化各品牌差异大, 色彩一致性弱于 iPhone",
        "capability": "🟢 主摄场景, 🟡 焦段一致性, 🔴 无"
    },
    # ── 小红书热门相机 ──
    "sony-a7m4": {
        "name": "Sony A7M4",
        "lenses": "全画幅可换镜头（常用：24-70 f/2.8, 85 f/1.4, 35 f/1.4）",
        "strengths": "3300万像素全画幅, 对焦快准, 色彩讨喜, 高感优秀, 4K视频",
        "limits": "机身+镜头约1.5kg不便携, 需选对镜头, 直出色彩不如富士",
        "capability": "🟢 人像/风光全场景, 🟡 需搭配镜头, 🔴 无"
    },
    "sony-a7c2": {
        "name": "Sony A7C2",
        "lenses": "全画幅可换镜头（常用：28-60 套头, 40 f/2.5, 24-70 f/2.8）",
        "strengths": "轻便全画幅, 侧翻屏自拍方便, 对焦好, 3300万像素",
        "limits": "取景器小, 握持感一般, 需选对镜头",
        "capability": "🟢 旅行/人像/日常, 🟡 需搭配镜头, 🔴 无"
    },
    "sony-a6400": {
        "name": "Sony A6400 / ZV-E10",
        "lenses": "APS-C 可换镜头（常用：16-50 套头, 适马30 f/1.4, 适马56 f/1.4）",
        "strengths": "轻便入门, 镜头群丰富便宜, 翻转屏, 对焦快",
        "limits": "APS-C高感一般, 无机身防抖(A6400), 直出色彩偏冷",
        "capability": "🟢 日常/人像入门, 🟡 暗光需大光圈镜头, 🔴 无"
    },
    "fujifilm-xt5": {
        "name": "Fujifilm X-T5",
        "lenses": "APS-C 可换镜头（常用：18-55 f/2.8-4, 35 f/1.4, 56 f/1.2）",
        "strengths": "4000万像素, 经典胶片模拟直出色彩无敌, 复古外观, 防抖好",
        "limits": "APS-C画幅, 对焦弱于索尼佳能, 价格偏高, 续航一般",
        "capability": "🟢 街拍/人像/生活, 🟡 运动/体育, 🔴 无"
    },
    "fujifilm-xt50": {
        "name": "Fujifilm X-T50 / X-T30 II",
        "lenses": "APS-C 可换镜头（常用：15-45 套头, XC35 f/2, 适马 30 f/1.4）",
        "strengths": "小巧复古, 胶片模拟丰富直出不用修图, 价格友好, 颜值高",
        "limits": "无机身防抖(X-T30), 续航一般, 对焦中等",
        "capability": "🟢 街拍/日常/旅行, 🟡 暗光需大光圈, 🔴 运动"
    },
    "fujifilm-x100vi": {
        "name": "Fujifilm X100VI",
        "lenses": "固定镜头 23mm f/2（35mm等效）",
        "strengths": "口袋大小, 经典负片模拟直出, 镜间快门, 街拍神器, 颜值天花板",
        "limits": "定焦不可换镜头, 近摄偏软, 溢价严重难买到",
        "capability": "🟢 街拍/旅行/生活记录, 🟡 远摄/大场面, 🔴 人像特写"
    },
    "ricoh-gr3": {
        "name": "Ricoh GR III / GR IIIx",
        "lenses": "固定镜头 28mm f/2.8 (GR3) / 40mm f/2.8 (GR3x)",
        "strengths": "真口袋机, 快拍模式秒拍, 森山大道高对比黑白模式, APS-C画质, 色彩独特",
        "limits": "定焦不可换, 电池小续航差, 对焦慢, 无取景器",
        "capability": "🟢 街拍/快拍/黑白, 🟡 远摄/人像, 🔴 视频"
    },
    "canon-r6ii": {
        "name": "Canon EOS R6 II",
        "lenses": "全画幅可换镜头（常用：24-105 f/4, 50 f/1.8, 85 f/2）",
        "strengths": "肤色色彩科学讨喜, 防抖强, 对焦快, 2400万像素全画幅",
        "limits": "RF镜头群偏贵, 机身偏大, 像素略低于同级",
        "capability": "🟢 人像/活动/视频, 🟡 高像素风光, 🔴 无"
    },
    "other-camera": {
        "name": "其他相机",
        "lenses": "取决于镜头选择",
        "strengths": "可换镜头灵活性, 传感器大于手机, 景深控制好",
        "limits": "需选择正确镜头, 体积大不便携",
        "capability": "🟢 取决于镜头, 🟡 需用户选镜头, 🔴 无自动场景优化"
    },
    "unknown": {
        "name": "待选择",
        "lenses": "未知",
        "strengths": "未知",
        "limits": "未知",
        "capability": "🟡 设备未知, 方案将使用通用指导"
    }
}

# 相机镜头档案
LENSES = {
    "24-70-f2.8": {"name": "24-70mm f/2.8 标准变焦", "focal_range": "24-70mm", "aperture": "f/2.8", "type": "standard zoom"},
    "70-200-f2.8": {"name": "70-200mm f/2.8 长焦变焦", "focal_range": "70-200mm", "aperture": "f/2.8", "type": "telephoto zoom"},
    "16-35-f2.8": {"name": "16-35mm f/2.8 广角变焦", "focal_range": "16-35mm", "aperture": "f/2.8", "type": "wide zoom"},
    "24-105-f4": {"name": "24-105mm f/4 标准变焦", "focal_range": "24-105mm", "aperture": "f/4", "type": "standard zoom"},
    "50-f1.8": {"name": "50mm f/1.8 定焦", "focal_range": "50mm", "aperture": "f/1.8", "type": "standard prime"},
    "50-f1.2": {"name": "50mm f/1.2 定焦", "focal_range": "50mm", "aperture": "f/1.2", "type": "standard prime"},
    "85-f1.4": {"name": "85mm f/1.4 人像定焦", "focal_range": "85mm", "aperture": "f/1.4", "type": "portrait prime"},
    "85-f1.8": {"name": "85mm f/1.8 人像定焦", "focal_range": "85mm", "aperture": "f/1.8", "type": "portrait prime"},
    "35-f1.4": {"name": "35mm f/1.4 广角定焦", "focal_range": "35mm", "aperture": "f/1.4", "type": "wide prime"},
    "28-f2.8": {"name": "28mm f/2.8 广角定焦", "focal_range": "28mm", "aperture": "f/2.8", "type": "wide prime"},
    "kit-lens": {"name": "套机镜头 (18-55mm f/3.5-5.6)", "focal_range": "18-55mm", "aperture": "f/3.5-5.6", "type": "kit zoom"},
    "unknown-lens": {"name": "未知镜头", "focal_range": "未知", "aperture": "未知", "type": "unknown"}
}

# ============================================================
# 设备检测：从 EXIF 映射到设备档案
# ============================================================

def detect_device_from_exif(exif_result):
    """从 EXIF 数据中检测设备型号，返回 (device_key, device_name, is_camera)"""
    if not isinstance(exif_result, dict) or 'error' in exif_result:
        return None, None, False

    device_str = exif_result.get('device', '')
    if not device_str:
        return None, None, False

    dl = device_str.lower()

    # ── iPhone 检测 ──
    if 'iphone' in dl:
        match = re.search(r'iphone\s*(\d+)', dl)
        if match:
            model_num = int(match.group(1))
            if model_num >= 17:
                if 'pro' in dl or 'max' in dl:
                    return 'iphone-17-pro', device_str, False
                return 'iphone-17', device_str, False
            elif model_num >= 13:
                if 'pro' in dl or 'max' in dl:
                    return 'iphone-pro-13-16', device_str, False
                return 'iphone-standard-13-16', device_str, False
        return 'iphone-standard-13-16', device_str, False

    # ── Android 旗舰检测 ──
    android_flagships = [
        'pixel', 'samsung galaxy s', 'samsung galaxy z',
        'xiaomi 1', 'xiaomi m', 'oppo find', 'vivo x',
        'huawei p', 'huawei mate', 'oneplus', 'honor magic'
    ]
    if any(brand in dl for brand in android_flagships):
        return 'android-flagship', device_str, False
    if any(kw in dl for kw in ['android', 'samsung', 'xiaomi', 'oppo', 'vivo', 'huawei', 'oneplus', 'honor', 'redmi', 'poco', 'realme']):
        return 'android-flagship', device_str, False

    # ── 相机品牌精细检测 ──
    camera_brands = ['canon', 'sony', 'nikon', 'fujifilm', 'leica', 'panasonic', 'olympus', 'pentax', 'hasselblad', 'ricoh', 'sigma', 'lumix', 'fuji']

    if any(brand in dl for brand in camera_brands):
        # Sony
        if 'sony' in dl:
            if any(m in dl for m in ['a7m4', 'a7r5', 'a7r4', 'a7r3', 'a7m3', 'a7c2', 'a7c', 'a7cr', 'a7s3', 'a9']):
                return 'sony-a7m4', device_str, True
            if any(m in dl for m in ['a6', 'a5', 'zve10', 'zve1', 'zv-e10', 'zv-e1', 'nex']):
                return 'sony-a6400', device_str, True
            return 'sony-a7m4', device_str, True
        # Fujifilm
        if 'fujifilm' in dl or 'fuji' in dl:
            if any(m in dl for m in ['xt5', 'xt-5', 'x-t5', 'xh2', 'x-h2', 'xh2s', 'gfx']):
                return 'fujifilm-xt5', device_str, True
            if any(m in dl for m in ['xt50', 'xt-50', 'x-t50', 'xt30', 'xt-30', 'x-t30', 'xe4', 'x-e4', 'xs20', 'x-s20', 'xs10', 'x-s10', 'xt200', 'xt-200']):
                return 'fujifilm-xt50', device_str, True
            if any(m in dl for m in ['x100', 'x-100']):
                return 'fujifilm-x100vi', device_str, True
            return 'fujifilm-xt5', device_str, True
        # Ricoh
        if 'ricoh' in dl:
            return 'ricoh-gr3', device_str, True
        # Canon
        if 'canon' in dl:
            if any(m in dl for m in ['r6', 'r5', 'r3', 'r8', 'r7', 'r10', '5d', '6d', '1d']):
                return 'canon-r6ii', device_str, True
            return 'other-camera', device_str, True
        # Nikon
        if 'nikon' in dl:
            if any(m in dl for m in ['z6', 'z7', 'z8', 'z9', 'zf', 'z5', 'z50', 'zfc', 'z30']):
                return 'canon-r6ii', device_str, True  # 用 canon-r6ii 同级配置
            return 'other-camera', device_str, True
        # Leica / Hasselblad / Others
        if any(b in dl for b in ['leica', 'hasselblad', 'pentax', 'olympus', 'panasonic', 'lumix', 'sigma']):
            return 'other-camera', device_str, True
        return 'other-camera', device_str, True

    return None, device_str, False


def get_lens_context(lens_key):
    """获取镜头上下文信息"""
    lens = LENSES.get(lens_key, LENSES.get('unknown-lens'))
    if not lens:
        return ""
    return f"""当前镜头：{lens['name']}
焦段范围：{lens['focal_range']}
最大光圈：{lens['aperture']}
镜头类型：{lens['type']}"""


# ============================================================
# 视觉分析 Prompt（保留核心逻辑）
# ============================================================
VISION_PROMPT = """请详细分析这张照片，输出严格的结构化JSON。必须包含以下6个字段，缺一不可。

## 核心原则：区分[观察]与[推测]

- [观察]：照片中能直接看到的视觉事实（如"天空灰白色""地面无清晰阴影""人物身着米白衬衫"）
- [推测]：从视觉线索推断的结论（如"可能为多云天气""可能为午后"）
- 禁止输出纯感受描述（如"空旷清幽""治愈松弛"）——那是下游AI的工作。

每个字段的值中，请用[观察]或[推测]标注每条信息的性质。

{
  "scene_type": "[观察]室外/室内/半室外 — [推测]具体场景类型及依据（1-2句）",
  "primary_subject": "[观察]画面中最主要的拍摄对象是什么——人/宠物/车辆/建筑/食物/自然景观/其他。尽可能具体，如'橘猫''红色跑车''闺蜜三人'。这将用于网络搜索摄影技巧",
  "people": "人物数量、每人位置/衣着/动作/表情/姿态。如果没有人，写'无人物'。衣着用[观察]标注具体颜色和款式",
  "light": {
    "direction": "[推测]顺光/侧光/逆光/顶光/漫射 — 判断依据",
    "quality": "[推测]硬光/软光/混合 — 判断依据（阴影边缘锐利还是柔和）",
    "color_temp": "[推测]暖/中/冷 — 估算色温K值及依据",
    "special": "[观察]遮阳阴影区/斑驳树影/窗边漫射/混合色温/无特殊",
    "level": "[推测]充足/一般/不足 — 基于画面内容判断的实际环境亮度。室内多盏灯+画面明亮=充足。树荫下但外部天空明亮=一般。真正暗到手持困难=不足。不要参考ISO，只看画面"
  },
  "color": {
    "primary": "[观察]最主导的颜色及位置",
    "secondary": "[观察]次要色及位置",
    "accent": "[观察]强调色及位置"
  },
  "space": {
    "foreground": "[观察]前景有什么",
    "midground": "[观察]中景有什么",
    "background": "[观察]背景有什么",
    "depth": "[观察]浅/中/深 — 判断依据",
    "anchors": "[观察]列出场景中可作为空间锚点的具体物体——门口盆栽、窗边沙发、路边消防栓、树荫边缘等。至少3个。这些将用于下游生成空间化拍摄指令。"
  },
  "composition": "[观察]当前构图方式 + [观察]画面中可利用的构图元素（线条/框架/光影区域）",
  "location_clues": "从画面识别位置线索。检查：招牌文字、建筑风格/颜色、地标轮廓、植被类型、山形地貌、室内装修风格、菜单/包装/标识。能推断具体场所就写场所名（如'太舞滑雪场山顶餐厅后方观景台'），只能到城区级就写级别，完全无法识别写'无法识别'",
  "specific_location": "从 location_clues 中提取最精确的地点名称，用于网络搜索。格式：'国家/城市 + 具体场所'（如'马来西亚亚庇沙皮岛''北京故宫角楼''上海武康路'）。若无明确地点写'无'",
  "distinctive_traits": "🚨不是描述场景中常见的穿着，而是让这张照片区别于同类场景的独特元素。\n- 海边穿泳衣/草帽/度假裙→写'无'（海边常见）；海边穿婚纱→填'婚纱,拖尾头纱'\n- 公园穿T恤/休闲/运动装→写'无'（公园常见）；公园穿汉服→填'汉服,齐胸襦裙'\n- 咖啡厅穿日常装→写'无'；咖啡厅穿旗袍→填'旗袍,珍珠项链'\n- 街头穿T恤/牛仔裤→写'无'；街头穿JK制服→填'JK制服,日系'\n若穿着/造型/道具无独特之处写'无'。\n格式：逗号分隔的3-5个关键词（如'婚纱,拖尾,头纱'）——搜索关键词，非描述句"
}

只输出JSON，不要任何额外文字。不要markdown代码块包裹。"""

# ============================================================
# 方向生成 Prompt（不含方案，方案按需另行生成）
# ============================================================
DIRECTIONS_PROMPT = """你是摄影美学专家。你的知识覆盖摄影史、电影美学、绘画构图、时尚摄影、广告视觉。

## 🧭 工作流程：先探索，后对照，最后标注

你按三个阶段工作：
1. **自由联想**——只看照片视觉数据，打开全部知识自由探索，不受任何限制
2. **知识库对照**——拿到已有风格库，标记哪些是你新发现的、哪些已有记录
3. **设备现实检查**——拿到设备和环境数据，诚实标注可执行性

---

## 阶段 1：自由联想（仅基于视觉数据）

下面是这张照片的视觉数据。沉浸进去——光线、色彩、空间、物体、人物、氛围。

{vision_json}

{exif_summary}

{exif_cross_check}

**现在，忘掉所有限制。** 你是一个看过无数照片、电影、画作的审美者。
这张照片让你联想到什么？从你的全部知识中自由提取——

- 摄影史：某位摄影师的观看方式？某个时代的视觉语言？
- 电影：某部电影的色调/构图/氛围？某个导演的镜头语言？
- 绘画：某个画派的色彩/笔触/空间处理？
- 时尚/广告：某本杂志的视觉风格？某个品牌的审美体系？
- 跨媒介：漫画/游戏/建筑/设计中的视觉语言？
- 社媒趋势：小红书/Instagram/TikTok 上现在什么审美方向在流行？什么话题标签、打卡风格、出片公式在被反复验证？

🚨 不要自我审查。不要想"这个风格用户能拍出来吗"——后面会有人处理可行性。
现在你唯一的任务就是：把这张照片激发的所有审美联想说出来。

为每个联想写出：
- 风格名
- 为什么这张照片的具体视觉元素让你联想到它（引用具体元素）
- 拍出来大概是什么感觉

---

## 阶段 2：知识库对照（区分新旧发现）

好了，下面是我们已有的风格知识库。**它不是用来限制你的——它用来告诉你哪些是新发现。**

{knowledge_context}

为阶段 1 中产生的每个风格方向标注：
- 📚 **已有记录**：这个风格知识库里有 → 可以引用已有知识
- 🆕 **新发现**：知识库里没有 → 标记为 AI 自由探索的新风格

**新发现不是坏事——恰恰相反，这是最有价值的输出。**
把新风格写清楚：它是什么、为什么适合、视觉特征是什么——这样它就可以被录入知识库，下次直接用。

---

## 阶段 3：设备现实检查

最后，拿到现实条件。

{device_context}

{env_context}

现在为每个方向诚实标注：
- 🟢 当前设备可直接拍
- 🟡 需要微调（调整参数/走位/等待光线变化）
- 🟠 需要替代方案（核心效果需要特定器材/条件，给出替代思路）

{fast_path_note}

---

## 输出：三条方向

从你的自由探索中选出三条，写入三个固定槽位：

### 🟢 现在就拍 — 必有
最简单易上手的拍法。利用场景已有的光线/色彩/空间优势。

### 🔥 最出片 — 有则放
最有记忆点的方向——社媒话题性、或这张照片最独特的视觉锚点。尽量不放空。

### ✨ 脑洞大开 — 宁缺毋滥
跨媒介、小众、非典型的视角。必须有至少一个具体视觉锚点支撑。没有就全填空。

---

## 创作原则

1. 每条 direction 的 style_promise/reason 必须引用 ≥1 个视觉素材（光线/色彩/空间锚点/构图元素/人物特征）
2. 三条风格各不相同，覆盖不同审美取向
3. 🟢 必有实质内容。🔥 尽量有内容。✨ 宁缺毋滥
4. 忠于实际光线——硬光不推柔光风格，阴天不推逆光小清新

## style_brief——风格视觉特征速写

每条方向必须输出 style_brief，3-5 个关键词+短描述定义核心视觉特征。
这是给后续方案生成 AI 看的，要精确不要修辞。

格式：
{{
  "essence": "一句话定义这个风格（≤20字）",
  "color": "色彩策略（≤30字，如：高饱和红蓝撞色 / 低饱和粉彩 / 金色暖调）",
  "composition": "构图偏好（≤30字，如：绝对对称居中 / 三分法偏移 / 平面化水平分割）",
  "light": "光线偏好（≤30字，如：全柔光零阴影 / 侧硬光强对比 / 金色逆光）",
  "mood": "情绪氛围（≤20字，如：冷静幽默 / 松弛慵懒 / 冷酷张力）"
}}

🟢 → 基于视觉数据的自然推导，反映当前场景的实际光线和色彩
🔥 → 社媒流行风格，引用该风格在摄影社区中的典型视觉特征
✨ → 跨媒介/小众风格，必须精确描述视觉特征（后续方案 AI 全靠这个理解）

## photo_guide——🆕新风格专属·摄影可执行翻译

🚨 当 kb_status 为 🆕新发现 时，必须填写 photo_guide 字段。
这是给后续方案生成 AI 的「摄影翻译」——把美学概念变成按快门前能做的事。
如果 kb_status 为 📚已有记录，photo_guide 填空字符串 ""。

photo_guide 格式（直接复制这个模板填写）：
🎯 前期拍法（拍摄现场能操作的——不是后期滤镜）：
- 光线核心：（需要什么光质和方向？现场怎么获得或模拟？）
- 色彩控制：（色调偏移方向？饱和度范围？什么颜色该避开？）
- 构图：（景别偏好？留白比例？空间策略？）
- 其他前期操作：（穿搭/场景选择/道具/前景制造——只写前期能做的）
❌ 禁止：（列出绝对不能做的事——硬阴影/特定颜色/杂乱背景等）
📎 技法类比：（从知识库已有风格中找1-2个技法路径最接近的，如"日系清新（柔光+低饱和）"）
📱 后期方向：（仅调色参考——鲜明度/HSL/色温/曲线——不混入前期字段）

🚨 关键原则：
- 每个要点必须回答"拍摄现场怎么做"——不是"画面应该是什么效果"
- ✅ "找纱帘挡在窗户和主体之间柔化光线" ❌ "光线应该柔和温暖"
- photo_guide 是未来入库知识库的草稿——写好了下次有人选这个风格就能直接用

## fold_details——折叠详情文案

每条方向配套一段社媒风文案（字段名 fold_details）。
像小红书博主在分享心得，不说教、不列 bullet、不写学术论文。
写清楚：风格怎么从照片里来的（引用具体视觉元素），为什么这个光/色/场景组合让风格可行。

格式：
fold_details: {{ "now": "▼ 为什么选这个\\n\\n社媒风文案...\\n\\n灵感来源：xxx", "best": "...", "creative": "..." }}

## 口吻
朋友分享的语气。"你"视角。
✅"侧光刚好打在你的侧脸上，球衣红在阴影里更浓了"
❌"建议采用侧光拍摄以突出主体"

## 输出格式
严格JSON，不要markdown包裹。directions 必须是数组 []：

{{
  "insight": "1-2句社媒配文——具体有画面感，不说空话",
  "scene_tier": "🥇",
  "discovery_note": "🆕 如果发现了知识库没有的新风格，在这里简要说明",
  "directions": [
    {{
      "id": "now", "emoji": "🟢", "label": "现在就拍", "subtitle": "零门槛，站在这就能拍",
      "style": "风格名（中文）",
      "kb_status": "📚已有记录 或 🆕新发现",
      "style_promise": "1句话说出拍出来什么效果",
      "reason": "为什么这个风格适合现在这张照片（60-100字）",
      "fit_rationale": "风格-场景适配逻辑（1-2句）",
      "light_annotation": "🟢/🟡/🔴", "device_annotation": "🟢直接拍/🟡微调/🟠替代方案",
      "style_brief": {{"essence":"","color":"","composition":"","light":"","mood":""}},
      "photo_guide": "🆕新发现时填写（格式见上文photo_guide模板）；📚已有记录填空字符串",
      "plans": []
    }},
    {{"id":"best","emoji":"🔥","label":"最出片","subtitle":"发出去会被赞的那种","style":"","kb_status":"","style_promise":"","reason":"","fit_rationale":"","light_annotation":"","device_annotation":"","style_brief":{{"essence":"","color":"","composition":"","light":"","mood":""}},"photo_guide":"","plans":[]}},
    {{"id":"creative","emoji":"✨","label":"脑洞大开","subtitle":"不像游客照的视角","style":"","kb_status":"","style_promise":"","reason":"","fit_rationale":"","light_annotation":"","device_annotation":"","style_brief":{{"essence":"","color":"","composition":"","light":"","mood":""}},"photo_guide":"","plans":[]}}
  ],
  "fold_details": {{ "now": "▼ 为什么选这个\\n\\n...", "best": "...", "creative": "..." }}
}}

🟢必有实质内容。🔥尽量有内容，与🟢互补。✨无灵感时全部null，fold_details.creative空字符串。
directions 必须是数组 []，不是对象 {{}}！"""


# ============================================================
# 🏙️ 场景知识注册表——注入统一流程（不创建平行路径）
# 每增加新场景只需：定义知识 + 关键词 → 自动注入现有 Prompt
# ============================================================
STREET_KNOWLEDGE = """
## 🏙️ 城市街拍知识库

### 六位大师的观看方式

**Henri Cartier-Bresson — 决定性瞬间**
"Photography is the simultaneous recognition, in a fraction of a second, of the significance of an event."
- 核心：等待几何构图与人物动作完美重合的那一瞬
- 技法：50mm镜头、不裁切、画面中每一毫米都有意义
- 启示：不是在按快门，是在识别"这个瞬间值得留下来"

**Saul Leiter — 反射与层次**
- 核心：用窗户、雨水、雾气、遮阳棚做前景——世界是层层叠叠的
- 技法：透过玻璃拍、利用雨雾模糊前景、让色彩渗透而不是并置
- 启示：不用拍清楚全部——朦胧的局部比全景更有诗意

**Alex Webb — 复杂构图**
- 核心：一个画面里同时发生多件事——前景、中景、背景各有故事
- 技法：深景深、鲜艳色彩、等待多个元素同时到位
- 启示：好街拍不是简洁，是有层次的复杂

**Vivian Maier — 街头肖像**
- 核心：用方画幅拍陌生人——不是偷拍，是有尊严的相遇
- 技法：Rolleiflex腰平取景（被摄者不知道被拍）、利用阴影和反射
- 启示：街头的人不是"元素"，是照片的灵魂

**Fan Ho (何藩) — 光与几何**
- 核心：香港街头的戏剧性光影——一束光从巷口斜切进来，一个人恰好走过
- 技法：强侧光、烟雾、几何分割、极简构图中的单点人物
- 启示：先找到光，然后等人走进来

**Daido Moriyama (森山大道) — 粗糙的力量**
- 核心：高对比黑白、颗粒、晃动、倾斜——街头的能量不是秩序
- 技法：不需要对焦完美，需要的是"我在现场"的紧迫感
- 启示：有时糊了比清楚更有力量

### 街拍核心技法

**光线利用：**
- 黄金时刻侧光：最安全也最出片的街拍光线——长阴影拉出空间深度
- 逆光剪影：利用建筑之间的光缝，等人走进光里
- 反射光：玻璃幕墙、水洼、汽车表面——用反射做第二层画面
- 斑驳光：树影、遮阳棚、格栅——碎光是天然的构图工具

**构图公式：**
- 框架构图：门洞、拱廊、窗户、桥洞——在城市里找一个天然画框
- 引导线：人行道边缘、栏杆、建筑线条——把视线引向主体
- 三层空间：前景（遮挡物/虚化）+ 中景（主体）+ 背景（城市语境）
- 对比并置：新与旧、大与小、动与静、明与暗

**拍摄策略：**
- 站定等待法：选好构图站定不动，让城市从你面前流过，等对的元素进入画面
- 预对焦/陷阱对焦：预估人物经过的位置，提前锁定焦点
- 腰平盲拍：相机在腰部，不看屏幕——视角更低、更自然、也不引人注意
- 跟随拍摄：发现有趣的人物，跟着走一段，等他走到合适的光线里

**手机街拍特化：**
- 28mm广角≈手机主摄：天生适合街拍——退一步把人拍进环境里
- 音量键当快门：比屏幕按钮更快、更稳
- 连拍模式+后期选片：决定性瞬间在手机上是概率游戏——多拍
- 曝光补偿下拉：逆光场景下拉-1EV保住高光，人脸可以后期提亮
"""


# ============================================================
# 🐱 宠物拍摄——知识库
# ============================================================
PET_KNOWLEDGE = """
## 🐱 宠物拍摄知识库

### 核心理念
宠物最美的状态永远是做它自己的时候。不是"让宠物配合你"，而是"你去配合宠物"——观察它的习惯、预判它的动作、在它最放松的时刻按下快门。

### 光线策略

**自然光优先——严禁闪光灯**
- 最佳时段：上午9-11点或下午3-5点，光线柔和，色温4500K-5500K，最能真实呈现毛色与质感
- 窗边逆光：早晨或傍晚的柔和光线让宠物毛发边缘发光，质感绝佳
- 严禁闪光灯：会造成红眼效应、扁平化立体感，且对宠物眼睛有害、容易吓到它们
- 简易反光板：白色A4纸或白色浴巾放在暗处反射光线，省钱又好用

**进阶布光**
- 伦勃朗光：让宠物面部与窗户呈45度角，调整位置直到眼睛另一侧阴影区出现倒三角形光斑，充满戏剧张力
- 百叶窗/树影光斑：利用百叶窗投射的平行光带，或午后阳光透过树叶形成的散点光斑，天然营造明暗节奏
- 室内拍摄时关掉顶灯，只留自然窗光——阴影更柔和，质感自然呈现

### 构图法则

**低角度平视——最重要的法则**
- 蹲下、坐下甚至趴下，让手机镜头与宠物眼睛基本持平
- 相比俯拍，平视构图让画面故事感立现，宠物显得更有尊严
- 超广角低角度：手机平贴地面（离地3-5厘米），镜头略仰10-15度，开启0.5x超广角，营造"仰拍英雄感"

**三分法与视线留白**
- 将宠物眼睛置于画面三分线交叉点
- 在宠物视线方向预留1/3画幅空间，画面呼吸感明显提升
- 加入纱帘、绿植等虚化前景，增加层次

**长焦虚化——退后两步更出片**
- 2x或3x长焦在3-5米距离下表现最佳，压缩感强、边缘识别准
- 背景与宠物相距2米以上，选择纯色墙面、远处树林或空旷草地
- 避免广角近拍：主摄凑太近会产生桶状畸变，鼻子变大、耳朵后缩
- 退后两步切长焦，成功率提升十倍

**对角线引导**
- 手臂从镜头斜上方45°伸出零食/逗猫棒，形成天然对角线引导线
- 对焦鼻子，锁定眼神光和耳朵动态

### 抓拍技法

**快门速度是关键**
- 手机专业模式下快门（S）锁到1/500秒以上，光线好可怼到1/1000秒
- 快门低于1/125秒时，90%以上动态画面出现拖影
- 提升至1/250秒后清晰率升至76%，配合自然光成功率可达92%

**连拍是保底大招**
- 长按快门不松手，一秒拍摄十几到几十张，从中筛选眼睛锐利、姿态舒展的一张
- 连拍比单张捕捉率提升90%以上
- 活泼好动的宠物，单张拍摄永远抓不到最精彩瞬间

**连续对焦与运动追焦**
- 切换到连续对焦（AF-C）模式，手机会自动跟踪移动目标
- 各品牌追焦：华为/荣耀「鹰眼精彩抓拍」、小米/红米「AI万物追焦」、OPPO/vivo「运动抓拍」、iPhone「运动模式」
- 追焦锁定：长按屏幕锁定宠物必经位置的对焦和曝光，等宠物自己走进框内

**Live Photo/实况模式**
- 苹果Live Photo，安卓动态照片——连续记录1.5秒内30帧画面
- 单帧快门捕获理想神态的概率低于15%，Live Photo大幅降低错过率

### 最值得抓拍的瞬间
- 打哈欠、伸懒腰的时候——表情最松弛自然
- 专注吃东西、玩玩具的时候——眼神最亮
- 睡觉时的各种奇葩姿势——最治愈
- 喝水时耳朵轻微震颤、追逐玩具途中瞳孔收缩
- 和主人互动的时候——最真实的情感流露

### 引导技巧
- 声音吸引：叫名字、吹口哨、捏塑料袋、摇零食罐子
- 零食/玩具引导：将零食置于手机上方15-30厘米处，稳定触发抬头动作
- 道具增添趣味：小帽子、小围巾、泡泡（逆光下形成透明球体，强化空气感）

### 后期要点
- 阴影+25至+35，高光-15至-25，还原毛发纹理与眼睛高光层次
- 清晰度+10至+15，强化毛发绒感，勿超过+20以免塑料质感
- 对焦务必对在眼睛上——眼睛清晰，整张照片就活了
- 拍完等稳了再动——手机需要0.5-1秒完成多帧合成，过早移动导致糊片

### 安全与伦理
- 观察宠物情绪：出现飞机耳、尾巴狂甩、频繁舔嘴唇等压力信号时，立即停止拍摄
- 不强迫宠物做任何它不愿意的动作
- 出门一定用牵引绳，安全永远第一
"""

# ============================================================
# 🏠 居家生活感——知识库
# ============================================================
HOME_KNOWLEDGE = """
## 🏠 居家生活感拍摄知识库

### 核心理念
不是房子有多贵，而是如何用光线讲好家的故事。居家生活感的核心是"松弛"——慢下来，感受风、光影、布料的触感，然后诚实地记录下来。生活痕迹（翻到一半的杂志、冒着热气的茶杯）比刻意摆放更有感染力。

### 窗光是灵魂

**最佳拍摄时间**
- 下午2点-5点是黄金时段，光线柔和，光影美
- 下午4点半左右落日余晖时分，光影特别美，是氛围感的关键
- 上午9-10点的光线同样柔和可用
- 需要晴天拍摄——阴天室内光线不够，画面会偏黑不通透

**窗边拍摄技巧**
- 利用侧光或侧逆光，让光线从侧面打进来——人物轮廓柔和，自带柔光效果
- 避免面部直冲窗户，不要有太硬的阳光直射脸上
- 拉低曝光是关键技巧——根据环境光照程度调节，让画面更有氛围
- 关掉室内所有顶灯，只让自然光进入——阴影更柔和，质感自然呈现
- 如果光线太强，窗外挂一块白色床单当作柔光幕
- 百叶窗投射的条纹光影是天然的构图利器

### 穿搭法则——氛围感的一半

- 选择宽松舒适、材质柔软的家居服（毛衣、棉麻衬衫、T恤、格子长裤）
- 不要太花哨，简单干净的款式
- 优选低饱和色系：米白、燕麦色、雾灰、藏青
- 天然材质（棉、麻、羊毛）在光影下更显高级
- 避雷：亮片、反光材质、大logo、夸张设计

### 布景与道具

**随手可取的道具**
水杯、枕头、书本、水果、咖啡杯、杂志、眼镜、白色耳机、绿植——和道具互动能避免手足无措

**布景三层次**
创造三个视觉层次：前景（茶几上的果盘）→ 中景（散落的靠垫）→ 背景（窗帘或装饰画），让空间瞬间深邃

**生活痕迹是最佳道具**
翻到一半的杂志、冒着热气的茶杯、搭在沙发上的毯子——这些"未完成状态"比刻意摆放更有感染力

**按下快门前花三分钟清理杂物**
充电线、遥控器、快递盒——干净背景让光线聚焦在美感上

### 构图技巧

**三分法与留白**
- 人物偏左或偏右，留出空白更有呼吸感和故事感
- 将视觉焦点放在三分线交叉点

**不看镜头**
- 侧脸、低头、背影更自然，氛围感拉满
- 回想自己平时宅家做什么，然后真实地去拍

**前景虚化**
- 利用树叶、杯子、窗帘边缘做虚化前景，增加层次感

**框景构图**
- 用窗框、门廊、镜子当作天然相框
- 对镜自拍：镜子是居家摄影最被低估的工具

**俯拍45度**
- 拍桌面/美食时手机抬高45°，加入小物件，生活感满分

**非常规视角**
- 手机贴墙拍走廊、举高俯拍——改变视角就是改变故事
- 手机三脚架调整不同机位，先拍空镜调整构图
- 轻微抖动拍模糊效果，制造朦胧氛围感

### 光线氛围营造

**不同时段的光线性格**
- 清晨（6-8点）：冷调青蓝色，适合拍起床后的慵懒感
- 上午（9-11点）：明亮通透，适合拍干净清爽的居家画面
- 午后（2-5点）：黄金时段，暖调柔光，适合拍温馨氛围
- 傍晚蓝调时刻（日落前后20分钟）：室内开一盏暖灯，窗外冷蓝色调形成冷暖对比

**人造光技巧（没有自然光时）**
- 一盏暖色台灯（2700K-3000K）从侧面打光——模拟窗光效果
- 灯光不要直射——打在墙面或天花板反射回来，光线更柔
- 多光源分层：主光源+环境光+点缀光（如香薰蜡烛）

### 后期调色
- 降低对比度约-15，让光影更柔和
- 色温偏冷一点，营造清透感
- 饱和度降低约-20——低饱和度是高级感王道
- 添加少量锐化和颗粒，提升照片质感
- 推荐App：Snapseed、醒图、VSCO

### 一句话总结
一件舒适的衣服 + 一个宁静的午后 + 一扇有光的窗 + 一部手机 = 属于你的氛围感居家照片
"""
SCENE_KNOWLEDGE_REGISTRY = {
    "street": {
        "keywords": [
            # 直接街景词
            "街道", "街头", "街景", "马路", "路边", "街边", "商业街", "临街",
            "步行街", "巷", "胡同", "弄堂",
            # 城市/建筑相关
            "城市", "商圈", "路口", "人行道", "老城", "古镇", "骑楼",
            "建筑群", "高楼", "CBD", "天际线", "立交桥", "天桥", "地下通道",
            # 文化/活动相关
            "街拍", "photowalk", "citywalk", "闹市", "集市", "市场", "广场"
        ],
        "knowledge_text": STREET_KNOWLEDGE,
        "execution_principles": """
### 站位与等待
- 选好构图后站定不动——这是街拍最重要的原则
- 预估人物/车辆/光影变化的路径，提前锁定焦点
- 给出具体等待位置：站哪、面朝哪、离主体多远

### 时机判断
- 不是"摆姿势"——是"在正确的时间出现在正确的位置"
- 给用户一个触发条件：看到什么就按快门
- 连拍模式：按住快门不放，每秒3-5张，后期从20张里选1张

### 光线优先
- 街拍的光不是你能控制的——先确定光源位置，再决定站哪
- 逆光街拍：曝光补偿-0.7到-1.3，保住高光氛围
- 阴影街拍：找光缝/建筑间隙，让光"切"出一个形状

### 手机街拍特化
- 音量键当快门（比点屏幕快半秒——决定性瞬间的半秒就是成败）
- 28mm主摄退一步拍：把人拍进环境里，不要用人像模式虚化背景
- 腰平高度：手机在腰部位置、屏幕朝上——视角更低、更自然
- 连拍优先：多拍不亏，10张里总有1张表情/步态/光影恰到好处的
""",
        "forbidden_constraints": """
### 街拍特有禁止
- ❌ "让人摆一个自然的姿势"——街拍不是摆拍，是等来的
- ❌ "用人像模式虚化背景"——街拍的背景是城市，是照片的一半灵魂
- ❌ "换个滤镜/后期加颗粒就叫街拍"——颗粒是前期选择
- ❌ "退远一点拍全景"——街拍越近越好
"""
    },
    "pet": {
        "keywords": [
            # 宠物类型
            "猫", "狗", "宠物", "喵", "汪", "毛孩子", "主子", "喵星人", "汪星人",
            "猫咪", "小狗", " puppy", " kitten", "仓鼠", "兔子", "鸟", "鱼",
            # 宠物相关场景
            "遛狗", "逗猫", "吸猫", "撸猫", "撸狗", "萌宠"
        ],
        "knowledge_text": PET_KNOWLEDGE,
        "execution_principles": """
### 低角度平视——铁律
- 蹲下、坐下甚至趴下，手机镜头与宠物眼睛持平
- 俯拍是最常见的错误——让宠物看起来又小又矮
- 超广角贴地：手机离地3-5厘米，镜头略仰，营造英雄感

### 抓拍优先
- 宠物不会摆pose——连拍是唯一正确的方式
- 长按快门不松手，每秒10-30张，从中选1张
- 快门速度锁定1/500秒以上（光线好可到1/1000秒）
- 开启连续对焦（AF-C），锁定宠物必经位置的焦点

### 眼睛是灵魂
- 对焦必须对在眼睛上——眼睛清晰整张照片就活了
- 眼神光（catchlight）是宠物照片从"还行"到"惊艳"的关键
- Live Photo/实况模式：1.5秒内30帧，选神态最佳的一帧

### 光线策略
- 严禁闪光灯——红眼、吓到宠物、对眼睛有害
- 窗边自然光是宠物最好的灯光师
- 百叶窗光斑、树影光斑天然营造明暗节奏

### 引导而非强迫
- 声音吸引：叫名字、吹口哨、摇零食罐
- 零食/玩具置于手机上方15-30厘米，触发抬头动作
- 观察压力信号（飞机耳/尾巴狂甩/舔嘴唇）→ 立即停止
""",
        "forbidden_constraints": """
### 宠物拍摄特有禁止
- ❌ 禁止使用闪光灯——对宠物眼睛有害且会吓到它们
- ❌ 禁止俯拍（站着往下拍）——让宠物看起来矮小且缺乏尊重感
- ❌ 禁止强迫宠物做动作——宠物不是模特，是家人
- ❌ 禁止在主摄近距离拍宠物面部——鼻子变大耳朵后缩，退后两步用长焦
- ❌ 禁止快门低于1/125秒拍动态——拖影废片率90%+
- ❌ 出门不牵绳拍照——安全永远第一
- ❌ 禁止在宠物有压力信号时继续拍摄
"""
    },
    "home": {
        "keywords": [
            # 居家场景
            "室内", "家里", "居家", "卧室", "客厅", "房间", "公寓", "家",
            "沙发", "床", "窗边", "窗前", "阳台",
            # 居家活动
            "宅家", "宅", "窝在", "躺在", "趴窝",
            # 氛围相关
            "生活感", "氛围感", "温馨", "治愈", "松弛", "慵懒"
        ],
        "knowledge_text": HOME_KNOWLEDGE,
        "execution_principles": """
### 窗光是灵魂
- 下午2-5点是黄金时段，光线柔和
- 利用侧光或侧逆光——人物轮廓柔和，自带柔光效果
- 关掉室内所有顶灯，只让自然光进入
- 拉低曝光是关键——让画面更有氛围

### 生活痕迹 > 刻意摆拍
- 翻到一半的杂志、冒着热气的茶杯——这些"未完成状态"最有感染力
- 回想自己平时宅家做什么，然后真实地去拍
- 按下快门前花三分钟清理杂物（充电线、遥控器）

### 不看镜头——氛围感的秘密
- 侧脸、低头、背影比正对镜头自然十倍
- 和道具互动（翻书、端杯子、靠窗发呆）避免手足无措
- 动起来抓拍——放松自然就是最好看的

### 布景三层次
- 前景（茶几上的果盘/窗帘边缘虚化）→ 中景（散落的靠垫/人物）→ 背景（窗帘/装饰画）
- 用窗框、门廊、镜子做天然相框

### 非常规视角
- 手机贴墙拍走廊、举高俯拍——改变视角就是改变故事
- 俯拍45度拍桌面/美食，加入小物件
""",
        "forbidden_constraints": """
### 居家拍摄特有禁止
- ❌ 禁止开顶灯——破坏自然光的柔和氛围，阴影变硬
- ❌ 禁止穿亮片/反光材质/大logo衣服——破坏居家松弛感
- ❌ 禁止背景杂乱（充电线/快递盒/遥控器入镜）——三分钟清理是必须的
- ❌ 禁止人物正对镜头僵硬站立——居家感的核心是"松弛"
- ❌ 禁止阴天纯靠室内自然光拍摄——光线不够画面会偏黑不通透
- ❌ 禁止窗边强光直射面部——过曝且生硬，拉低曝光或用床单柔光
"""
    },
    # 未来场景示例:
    # "cafe": {
    #     "keywords": ["咖啡", "咖啡厅", "甜品店", "茶室", "书吧"],
    #     "knowledge_text": CAFE_KNOWLEDGE,
    #     "execution_principles": "...",
    #     "forbidden_constraints": "..."
    # },
}


def detect_scene_mode(scene_type, vision_json):
    """从 scene_type + vision_json 检测场景模式。
    返回 scene_mode 字符串（如 'street'）或 None（通用模式）。
    """
    if not scene_type:
        return None
    loc_clues = vision_json.get('location_clues', '') if isinstance(vision_json, dict) else ''
    space_text = json.dumps(vision_json.get('space', {}), ensure_ascii=False) if isinstance(vision_json, dict) else ''
    combined = f"{scene_type} {loc_clues} {space_text}"

    for mode_name, config in SCENE_KNOWLEDGE_REGISTRY.items():
        keywords = config.get("keywords", [])
        if any(kw in combined for kw in keywords):
            return mode_name
    return None


def build_scene_execution_context(scene_mode):
    """返回场景执行原则文本，注入 PLANS_PROMPT 的 {scene_execution_context}。"""
    if not scene_mode or scene_mode not in SCENE_KNOWLEDGE_REGISTRY:
        return ""
    principles = SCENE_KNOWLEDGE_REGISTRY[scene_mode].get("execution_principles", "")
    if not principles:
        return ""
    return f"\n## 🎬 场景执行原则\n{principles}\n"



# ============================================================
# 方案生成 Prompt（按需调用，用户选完方向后）
# ============================================================
PLANS_PROMPT = """你是摄影指导——把一条风格方向变成具体可执行的拍摄方案。❌不是旅行规划师/活动策划/游记作者。

## 🚨 核心原则

### 1. 素材绑定（最高优先级）
每条方案的 subject/shooter/gear/enhance 都必须引用「素材清单」中的 ≥1 个具体元素。
❌ "换个角度""注意光线"——放任何照片都能用的 = 废案。
✅ "站粗浮木右侧，利用枯木当前景框，让球衣红色从蓝天中跳出来"

### 2. 前期优先（铁律）
⛔ 方案是教用户在按快门前做什么——不是教用户后期怎么P图。
- subject/shooter/gear/enhance 四个字段必须全部是「拍摄现场就能做的事」
- 风格中的光线/构图/视角/空间要求 → 写进 shooter/enhance（前期）
- 只有色彩倾向/锐度/颗粒 → 写进 quick_edit（后期）
- ⛔ 禁止反向：不能把"改变构图""找光斑""蹲下仰拍"写成后期操作

### 3. 诚实原则——不强凑
🚨 场景给不出9套有意义的方案 → 就少给。3-5套有真差异的方案比9套灌水强百倍。
- 没有好的创意角度 → 不写，不强凑
- 没有真正的视觉焦点转移 → 不写，不强凑
- 方案数量的上限由场景等级决定，下限由场景实际条件决定——场景单调就1-2套

## 场景信息
{vision_json}

## 📦 素材清单（每条方案必须引用 ≥1 个）
{material_inventory}

## 🎯 目标方向
{emoji} {label} — 风格：{style}
效果承诺：{style_promise}
推荐理由：{reason}

### 风格视觉特征（方案设计必须遵循）
{style_brief}

### 这个风格为什么适合这张照片
{direction_detail}

{photo_guide}

## 设备信息
{device_context}

## 风格知识（参考——含前期拍法的必须写入 scheme 的执行字段）
{style_knowledge}

## 设备适配
{device_knowledge}

{scene_execution_context}
{forbidden_constraints}

## 场景等级：{scene_tier}
## 方案数量约束：{tier_constraint}

## 🚨 设备约束
{device_constraints}
{env_context}

## 🎬 第一步：读懂这张照片（先于任何工具选择）

仔细看场景信息和素材清单。在打开任何工具箱之前，先回答三个问题：

1. **这张照片里最打动人的东西是什么？** （光线、色彩、空间、人物状态、某个细节——不是泛泛的"氛围好"）
2. **在当前场景里，有哪些「不同的东西」值得拍？** （不是换滤镜——是换拍摄对象/换角度/换焦点。比如：一棵树下至少可以拍：人与树的空间关系、树皮纹理+人手细节、树冠光斑落在人身上、地面光斑中的影子）
3. **当前光线条件下，什么角度和景别最自然？** （顺光→拍色彩、侧光→拍立体感、逆光→拍氛围和轮廓）

基于这三个答案，确定这批方案的「拍摄动机」——每个方案拍什么、从哪个角度拍、为什么要从这个角度拍。方案从场景里长出来，不是在维度表里排列组合。

⛔ 如果发现好几种方案其实是"同一张照片换了不同后期滤镜"——回退重来。方案间的差异必须首先是前期差异（角度/焦点/景别/光线利用），其次才是后期。

## 🧰 第二步：从场景出发选工具

以下工具不是必选清单——是灵感参考。从第一步的答案出发，需要哪个用哪个，不需要就跳过。

### 通用变化维度

**角度三要素**（相机高度 × 拍摄方向 × 人物体位——三选二就有天然变化）：
- 相机高度：高机位俯拍（人脸尖/背景地面）/ 平视（对话感）/ 低机位仰拍（人显高/天空背景）
- 拍摄方向：正面 / 侧面45°（最显瘦）/ 正侧90°（轮廓）/ 背面 / 回头（抓拍感）
- 人物体位：站/坐/靠/蹲/趴/躺 → 每换一种体位自然就要换机位

**视觉焦点**（这张拍什么——9张不能全拍同一张脸）：
- 人→环境（退远拍空间关系）/ 整体→细节（只拍手/眼/衣领）/ 正面→背影/侧面
- 静态→动态（抓动作瞬间）/ 实物→光影（拍影子/反光/光斑）/ 色彩→纹理（拍材质对比）

⛔ 有人的场景至少1张焦点不在脸上。纯景场景在纹理/光影/空间上轮换。

{scene_template}

### 风格翻译（从风格知识提取前期操作）

从上面的「风格知识」中提取标注了"前期拍法""🎯"的参数，翻译成方案指令：
- 光线/构图/空间要求 → shooter/enhance（前期执行动作）
- 元素/姿势选择 → subject（前期执行动作）
- 色彩调色 → quick_edit（后期修图）
⛔ 禁止：风格知识写了"找光斑"但方案只写"后期加柔光"——前期能做的绝不放后期。

### 多张节奏（≥4张时启用，≤3张不套）

**景别分散**：远景开场→中景叙事→近景亲密→1张创意高点→远景收束。弹性框架。
**首尾呼应（≥5张）**：第1张和最后1张有呼应——景别/色彩/构图/主题四选一。
**情绪起伏**：不是每张都安静或都大笑——至少1张情绪不同于其他。
**色彩统一**：所有方案共享同一色温方向和主色调。选1个强调色在2-3张中复现做「韵脚」。
⛔ 场景支持3种拍法就3张——不凑"开场→发展→收束"
⛔ 9张不能全中景——覆盖≥4种景别
⛔ 破格方案放中间（5-7张），不放开头或结尾

{series_rhythm}

## 每套方案字段
① name: 能记住的方案名——最好含素材元素+视角暗示，如"树缝光斑里的回眸""水洼倒影双世界"
② prep: 准备什么（≤50字）
③ subject: 被拍摄者——给"做一件事"的自然指令。引用锚点。2-3句。
   ✅ "侧身倚靠粗浮木，右手搭膝上，头转向海面，像在等船来"
   ❌ "摆一个自然的姿势，眼神放松看远方"
④ shooter: 摄影师——站哪/多远/高度/角度/取景范围。必须基于系统A的视角描述。2-3句。
   ✅ "蹲在长条枯木后方，手机举到与眼睛齐平，透过枯木缝隙拍——天空占画面上半，人物在右下1/3处"
   ❌ "找个好角度拍"
⑤ gear: 设备调试——焦段/对焦/曝光。不需要就写"全自动"。1-2句。
⑥ enhance: 拍摄时现场增色技巧——光线利用/前景制造/道具调整。只写按快门前能操作的。
   例："侧硬光让人物右肩锐利阴影落在浮木上""找一片叶子挡镜头前5cm虚化成前景绿雾""斑驳树影碎光斑对准球衣队徽位置"
   ❌ 不混入后期操作（调色/滤镜/颗粒 → 这些是 quick_edit 的事）
⑦ result: 拍出来——画面视觉预览。必须基于系统B的焦点来描述。2-3句。
   ✅ "侧光在球衣褶皱上切出利落阴影，海面在背景化成淡蓝色块，她的轮廓在逆光里镶了金边"
   ❌ "发朋友圈肯定被赞爆"
⑧ why: 为什么好看——摄影原理。2-3句。
⑨ annotations: 视觉标注（最多3个）
   - subject: {{"type":"subject","x":0.35,"y":0.72,"label":"站这","color":"#4ade80"}}
   - shooter: {{"type":"shooter","from":{{"x":0.05,"y":0.85}},"to":{{"x":0.4,"y":0.5}},"angle":"蹲下·45°仰拍","color":"#4ade80"}}
   - frame/crop 可选。color: #4ade80(绿)/#f59e0b(金)/#a78bfa(紫)
⑩ perspective: 换个思路（可选）——同风格不同维度的替代方案。有真正不同才写。
⑪ shot_size: 景别（远景/全景/中景/近景/特写）
⑫ angle: 角度（平视/俯拍/仰拍/侧面/背面）——必须与系统A视角一致
⑬ quick_edit: 手机修图傻瓜引导。只放后期操作（调色/裁剪/颗粒/柔光），不混入前期技法。
    格式：{{"app":"醒图","goal":"一句话说清楚修完什么效果","steps":["第1步（括号写为什么）","第2步","第3步"]}}
    原则：只写用户能点到的位置。每步括号里写效果。3-5步。
⑭ img_gen_prompt: 图生图提示词（≤250汉字）——豆包Seedream图生图格式

    结构：
    - 开头固定：「参考上传的照片，保持人物面部特征和场景环境不变。修改如下：」
    - 第一段：人物动作表情变化（基于 subject 字段，写最终视觉结果）
    - 第二段：光线氛围变化（基于 enhance，只写跟原片不同的光影变化）
    - 第三段：色调质感变化（基于 quick_edit 效果，用自然语言描述调色结果）
    - 结尾固定：「自然肤质，真实摄影感，无文字水印。」

    ❌ 禁止重新描述整个场景——原片已经提供了
    ❌ 禁止用列表/符号/拍摄参数
    ✅ 只写跟原片不同的部分，一段流畅中文

⑮ ai_tips: AI 可单独优化的小建议（2-3条简短字符串数组）
    例：["面部光影重塑——让侧光过渡更柔和","天空色调微调——灰蓝更干净通透"]
⑯ combo_label: "🧪实验性"（所有方案统一标记）

## 方案质量自检（生成后逐条检查）
☐ 每条方案引用了素材清单中的 ≥1 个具体元素？
☐ subject 给了"做一件事"的自然指令（不是"摆造型""自然一点"）？
☐ subject 里有没有"笑一个""看镜头""自然点"等废指令？（有→改成系统E3的具体话术）
☐ shooter 指名了具体站位+锚点+视角类型（不是"换个角度"）？
☐ enhance 全是前期操作（没有混入调色/滤镜等后期内容）？
☐ quick_edit 全是后期操作（没有混入站位/构图等前期内容）？
☐ 方案之间确实拍了不同的东西（不同视角/不同焦点/不同景别/不同道具互动）？
☐ 有道具时——道具是创造了新的视觉焦点，还是只是拿在手里当摆设？
☐ 有没有方案是在"套后期风格"而非"改前期拍法"？（有→重写）
☐ img_gen_prompt 是图生图格式（参考上传照片...）？
☐ quick_edit 步骤是用户能照着点的？

## 约束
- 口吻：朋友分享 ✅"你"视角 ❌摄影术语 ❌"我"
- result ✅"侧光从左侧打来，半张脸在光里半张在暗里，球衣红色刚好在亮面"
- 长度：prep≤50字 subject/shooter 2-3句 gear 1-2句 result/why 2-3句
- 🚨 前期优先：enhance 里出现"后期""滤镜""调色""加颗粒""柔焦" = 放错位置 → 移到 quick_edit
- 🚨 不强凑：场景给不出就少给——有意义的3套 > 灌水的9套
- 🚨 不套壳：不能9套方案是同一张原图换9个后期滤镜——每套的 shooter/subject 必须有实质变化
- 🚨 不说废话：subject 里出现"摆一个自然的姿势""微笑看镜头""放松一点" = 废指令 → 改成系统E3的具体场景动作

## 输出格式

严格JSON，只输出 plans 数组。不要markdown包裹。

{{
  "plans": [
    {{
      "name": "", "prep": "", "subject": "", "shooter": "", "gear": "",
      "enhance": "", "result": "", "why": "", "annotations": [], "perspective": "",
      "shot_size": "", "angle": "",
      "quick_edit": {{"app":"","goal":"","steps":["","",""]}},
      "img_gen_prompt": "",
      "ai_tips": ["",""],
      "combo_label": "🧪实验性"
    }}
  ]
}}"""


# ============================================================
# 天气 + 地名 + 光照时段（Open-Meteo 免费 API）
# ============================================================

# WMO Weather Code → 中文 + emoji
WMO_CODES = {
    0:  ("☀️", "晴"),
    1:  ("🌤", "大部晴"),
    2:  ("⛅", "多云"),
    3:  ("☁️", "阴"),
    45: ("🌫", "有雾"),
    48: ("🌫", "霜雾"),
    51: ("🌦", "小毛毛雨"),
    53: ("🌦", "毛毛雨"),
    55: ("🌦", "大毛毛雨"),
    56: ("🌧", "冻毛毛雨"),
    57: ("🌧", "冻毛毛雨"),
    61: ("🌦", "小雨"),
    63: ("🌧", "中雨"),
    65: ("🌧", "大雨"),
    66: ("🌧", "冻雨"),
    67: ("🌧", "冻雨"),
    71: ("🌨", "小雪"),
    73: ("🌨", "中雪"),
    75: ("❄️", "大雪"),
    77: ("🌨", "雪粒"),
    80: ("🌦", "阵雨"),
    81: ("🌧", "中阵雨"),
    82: ("🌧", "大阵雨"),
    85: ("🌨", "小阵雪"),
    86: ("🌨", "大阵雪"),
    95: ("⛈", "雷阵雨"),
    96: ("⛈", "冰雹雷雨"),
    99: ("⛈", "大冰雹雷雨"),
}

# 光照时段标签
LIGHT_PERIODS = [
    # (start_minutes_before_sunrise, end_minutes_after_sunrise, label, emoji, desc)
    # 从日出前开始排
    (-60, -40, "天文晨光", "🌌", "天刚蒙蒙亮"),
    (-40, -20, "蓝调时刻", "💙", "天空纯蓝，最佳氛围光"),
    (-20, 0,   "黄金时刻", "🌟", "日出金光，所有方向都好看"),
    (0,   60,  "黄金时刻", "🌟", "日出后暖光，立体感最强"),
    (60,  180, "上午光", "☀️", "光线通透，适合顺光拍摄"),
    (180, 360, "正午光", "☀️", "顶光较强，找阴影或漫射"),
    (360, 480, "下午光", "☀️", "光线开始变暖"),
    (480, 560, "黄金时刻", "🌅", "日落前暖光，拉长阴影"),
    (560, 580, "蓝调时刻", "💙", "日落后天空变蓝"),
    (580, 620, "天文暮光", "🌌", "天色渐暗，适合夜景"),
]

# 日出日落本地计算（不需要网络，精度 ±2 分钟）
def _calc_sun_times(lat, lon, date_dt):
    """返回 (sunrise_dt, sunset_dt)，本地时间"""
    # Julian day
    def to_jd(dt):
        a = (14 - dt.month) // 12
        y = dt.year + 4800 - a
        m = dt.month + 12 * a - 3
        jdn = dt.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
        return jdn + (dt.hour - 12) / 24 + dt.minute / 1440 + dt.second / 86400

    jd = to_jd(date_dt)
    n = jd - 2451545.0 - 0.0009

    # Solar mean anomaly
    M = (357.5291 + 0.98560028 * n) % 360
    M_rad = math.radians(M)

    # Equation of center
    C = 1.9148 * math.sin(M_rad) + 0.02 * math.sin(2 * M_rad) + 0.0003 * math.sin(3 * M_rad)

    # Ecliptic longitude
    lam = (M + C + 180 + 102.9372) % 360
    lam_rad = math.radians(lam)

    # Solar declination
    sin_dec = math.sin(math.radians(23.44)) * math.sin(lam_rad)
    cos_dec = math.sqrt(1 - sin_dec * sin_dec)
    dec_rad = math.asin(sin_dec)

    # Hour angle
    lat_rad = math.radians(lat)
    cos_ha = (math.sin(math.radians(-0.833)) - math.sin(lat_rad) * sin_dec) / (math.cos(lat_rad) * cos_dec)
    cos_ha = max(-1, min(1, cos_ha))
    ha_rad = math.acos(cos_ha)
    ha_deg = math.degrees(ha_rad)

    # Solar transit (noon)
    jd_noon = 2451545.0 + 0.0009 + n - lon / 360
    jd_noon = round(jd_noon) + (jd_noon - round(jd_noon))

    # Sunrise / Sunset
    jd_rise = jd_noon - ha_deg / 360
    jd_set = jd_noon + ha_deg / 360

    def jd_to_dt(jd_val):
        jd_val += 0.5
        z = int(jd_val)
        f = jd_val - z
        if f < 0:
            f += 1
            z -= 1
        if z >= 2299161:
            a = int((z - 1867216.25) / 36524.25)
            z += 1 + a - a // 4
        b = z + 1524
        c = int((b - 122.1) / 365.25)
        d = int(365.25 * c)
        e = int((b - d) / 30.6001)
        day = b - d - int(30.6001 * e)
        month = e - 1 if e < 14 else e - 13
        year = c - 4716 if month > 2 else c - 4715
        frac = f * 24
        hour = int(frac)
        minute = int((frac - hour) * 60)
        second = int(((frac - hour) * 60 - minute) * 60)
        return datetime(year, month, day, hour, minute, second)

    return jd_to_dt(jd_rise), jd_to_dt(jd_set)


def _classify_light_period(photo_dt, lat, lon):
    """根据拍摄时间和本地日出日落，判断光照时段"""
    date_dt = photo_dt.replace(hour=12, minute=0, second=0, microsecond=0)
    try:
        sunrise_utc, sunset_utc = _calc_sun_times(lat, lon, date_dt)
    except Exception:
        return None, None, None

    # _calc_sun_times 返回 UTC 时间，需转换为本地时间
    # 用经度估算时区偏移（每 15° 一小时）
    tz_offset_hours = round(lon / 15)
    sunrise = sunrise_utc + timedelta(hours=tz_offset_hours)
    sunset = sunset_utc + timedelta(hours=tz_offset_hours)

    # 以日出/日落为参考，计算拍摄时刻的偏移（分钟）
    mins_from_sunrise = (photo_dt - sunrise).total_seconds() / 60
    mins_from_sunset = (photo_dt - sunset).total_seconds() / 60

    # 先用相对日出判断
    period_label = None
    period_emoji = None
    period_desc = None

    for start_m, end_m, label, emoji, desc in LIGHT_PERIODS:
        if start_m <= mins_from_sunrise < end_m:
            period_label = label
            period_emoji = emoji
            period_desc = desc
            break

    # 如果日出侧没匹配到（可能在日落侧），用日落判断
    if period_label is None:
        sunset_offsets = [
            (-60, -40, "日落黄金", "🌅", "日落前暖光，拉长阴影"),
            (-40, -20, "日落蓝调", "💙", "日落后天空纯蓝"),
            (-20, 0,   "日落黄金", "🌅", "最后一道金光"),
            (0,   20,  "日落蓝调", "💙", "天空变蓝，城市灯亮"),
            (20,  60,  "天文暮光", "🌌", "天色渐暗"),
        ]
        for start_m, end_m, label, emoji, desc in sunset_offsets:
            if start_m <= mins_from_sunset < end_m:
                period_label = label
                period_emoji = emoji
                period_desc = desc
                break

    if period_label is None:
        # 夜间（日出前>60min 或 日落后>60min）
        if mins_from_sunrise < -60 or mins_from_sunset > 60:
            period_label = "夜间"
            period_emoji = "🌙"
            period_desc = "夜间拍摄"
        else:
            period_label = "白天"
            period_emoji = "☀️"
            period_desc = ""

    return sunrise, sunset, {
        "label": period_label,
        "emoji": period_emoji,
        "desc": period_desc,
        "sunrise": sunrise.strftime("%H:%M"),
        "sunset": sunset.strftime("%H:%M"),
    }


def _get_place_name(lat, lon):
    """OpenStreetMap Nominatim 逆地理编码 → 中文地名"""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?"
            f"format=json&lat={lat}&lon={lon}&zoom=12&addressdetails=1&accept-language=zh"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "GuidePic/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        addr = data.get("address", {})
        # 构建层级地名：国家·省·市·区·具体地点
        parts = []
        for key in ["country", "state", "city", "town", "village", "county", "suburb", "hamlet"]:
            v = addr.get(key, "")
            if v and v not in parts:
                parts.append(v)
        # 加上显示名称中的具体地点名
        display = data.get("display_name", "").split(",")[0].strip()
        if display and display not in parts:
            parts.append(display)
        # 知名地标（山、湖、公园等）
        named = data.get("name", "")
        if named and named != display and named not in parts:
            parts.append(named)

        return " · ".join(parts[-4:]) if len(parts) > 4 else " · ".join(parts) if parts else None
    except Exception as e:
        print(f"[Weather] Nominatim reverse geocode failed: {e}", file=sys.stderr, flush=True)
        return None


def _get_weather(lat, lon, photo_dt):
    """Open-Meteo：历史天气 + 预报（完全免费）"""
    date_str = photo_dt.strftime("%Y-%m-%d")
    now = datetime.now()
    hours_ago = (now - photo_dt).total_seconds() / 3600

    result = {
        "historical": None,   # {emoji, desc, temp, cloud, wind, precip}
        "forecast": None,     # {next_hours: [{time, emoji, desc, temp, precip_prob, cloud}]}
        "sun_times": None,    # {sunrise, sunset, period_label, period_emoji, period_desc}
    }

    # ── 计算光照时段 ──
    sunrise, sunset, period = _classify_light_period(photo_dt, lat, lon)
    result["sun_times"] = period if period else {"label": "未知", "emoji": "", "desc": "", "sunrise": "", "sunset": ""}

    # ── 历史天气（拍摄时的气象站记录）──
    try:
        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": "temperature_2m,weather_code,cloud_cover,wind_speed_10m,precipitation",
            "timezone": "Asia/Shanghai",
        })
        url = f"https://archive-api.open-meteo.com/v1/archive?{params}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if times:
            # 找最接近拍摄时刻的小时
            target_hour = photo_dt.strftime("%Y-%m-%dT%H:00")
            idx = None
            for i, t in enumerate(times):
                if t == target_hour:
                    idx = i
                    break
            if idx is None and times:
                idx = min(range(len(times)), key=lambda i: abs(i - photo_dt.hour))

            if idx is not None:
                wmo = hourly.get("weather_code", [0] * len(times))[idx]
                emoji, desc = WMO_CODES.get(wmo, ("☁️", "未知"))
                temp = hourly.get("temperature_2m", [None])[idx]
                cloud = hourly.get("cloud_cover", [None])[idx]
                wind = hourly.get("wind_speed_10m", [None])[idx]
                precip = hourly.get("precipitation", [None])[idx]

                result["historical"] = {
                    "emoji": emoji,
                    "desc": desc,
                    "temp": round(temp, 1) if temp is not None else None,
                    "cloud": round(cloud) if cloud is not None else None,
                    "wind": round(wind, 1) if wind is not None else None,
                    "precip": round(precip, 1) if precip is not None else None,
                }
    except Exception as e:
        print(f"[Weather] Historical fetch failed: {e}", file=sys.stderr, flush=True)

    # ── 预报（仅最近 48 小时内的照片有意义）──
    if hours_ago < 48:
        try:
            params = urllib.parse.urlencode({
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,precipitation_probability,weather_code,cloud_cover,wind_speed_10m",
                "timezone": "Asia/Shanghai",
                "forecast_hours": 6,
            })
            url = f"https://api.open-meteo.com/v1/forecast?{params}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            if times:
                forecast_items = []
                for i, t in enumerate(times[:6]):
                    wmo = hourly.get("weather_code", [0] * len(times))[i]
                    emoji, desc = WMO_CODES.get(wmo, ("☁️", "未知"))
                    forecast_items.append({
                        "time": t.split("T")[1][:5] if "T" in t else t,
                        "emoji": emoji,
                        "desc": desc,
                        "temp": hourly.get("temperature_2m", [None])[i],
                        "precip_prob": hourly.get("precipitation_probability", [None])[i],
                        "cloud": hourly.get("cloud_cover", [None])[i],
                    })
                result["forecast"] = forecast_items
        except Exception as e:
            print(f"[Weather] Forecast fetch failed: {e}", file=sys.stderr, flush=True)

    return result


def get_location_weather(exif_result):
    """从 EXIF 结果提取 GPS+时间，获取完整天气/地名/光照信息"""
    if not isinstance(exif_result, dict) or 'error' in exif_result:
        return None

    gps = exif_result.get('gps')
    dt_str = exif_result.get('datetime')

    if not gps or not dt_str:
        return None

    lat = gps.get('lat')
    lon = gps.get('lon')
    if lat is None or lon is None:
        return None

    # 解析时间
    try:
        photo_dt = datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None

    result = {
        "gps": {"lat": round(lat, 4), "lon": round(lon, 4)},
    }

    # 地名（异步不阻塞——有就有没有就跳过）
    place = _get_place_name(lat, lon)
    if place:
        result["place"] = place

    # 天气 + 光照时段
    weather = _get_weather(lat, lon, photo_dt)
    result.update(weather)

    return result


# ============================================================
# Session 管理
# ============================================================

def create_session(vision_json, exif_summary, device_key, device_context, directions, scene_tier, client_ip=None, env_context="", fold_details=None, scene_category="", session_id=None):
    """创建分析会话"""
    if session_id is None:
        session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        'vision_json': vision_json,
        'exif_summary': exif_summary,
        'device_key': device_key,
        'device_context': device_context,
        'directions': directions,
        'scene_tier': scene_tier,
        'plan_cache': {},   # key: f"{direction_id}:{device_key}"
        'created_at': time.time(),
        'client_ip': client_ip,
        'env_context': env_context,
        'fold_details': fold_details or {},
        'scene_category': scene_category
    }
    _cleanup_old_sessions()
    _save_session(session_id)
    return session_id


def get_session(session_id):
    """获取会话，自动清理过期，内存缺失时尝试从磁盘恢复"""
    sess = _sessions.get(session_id)
    if not sess:
        # 部署重启后内存清空，尝试从磁盘恢复
        sess = _load_session_from_disk(session_id)
        if not sess:
            return None
    if time.time() - sess['created_at'] > SESSION_TTL:
        del _sessions[session_id]
        try: os.remove(_session_path(session_id))
        except: pass
        try: os.remove(_img_path(session_id))
        except: pass
        return None
    return sess


def _cleanup_old_sessions():
    """清理过期会话"""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s['created_at'] > SESSION_TTL]
    for sid in expired:
        del _sessions[sid]
        try: os.remove(_session_path(sid))
        except: pass
        try: os.remove(_img_path(sid))
        except: pass


# ============================================================
# 辅助函数
# ============================================================

def extract_exif(image_path):
    """提取 EXIF 数据"""
    try:
        result = subprocess.run(
            [sys.executable, EXIF_SCRIPT, image_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"error": result.stderr}
    except Exception as e:
        return {"error": str(e)}


def call_doubao(messages, max_tokens=2000, call_type='unknown', session_id=None, model=None):
    """调用豆包 API，自动记录调用日志。model=None 则用默认 DOUBAO_MODEL"""
    import time as time_mod
    t0 = time_mod.time()
    usage = {}
    success = 1
    result = None
    if model is None:
        model = DOUBAO_MODEL
    try:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens
        }
        req = urllib.request.Request(
            DOUBAO_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DOUBAO_API_KEY}"
            }
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
        content = result['choices'][0]['message']['content'].strip()
        usage = result.get('usage', {})
    except Exception as e:
        success = 0
        duration_ms = int((time_mod.time() - t0) * 1000)
        # 记录失败调用
        try:
            log_api_call(session_id or '', call_type, model,
                        0, 0, 0, duration_ms, 0)
        except:
            pass
        raise

    duration_ms = int((time_mod.time() - t0) * 1000)

    # 记录成功调用
    try:
        log_api_call(
            session_id=session_id or '',
            call_type=call_type,
            model=DOUBAO_MODEL,
            prompt_tokens=usage.get('prompt_tokens', 0),
            completion_tokens=usage.get('completion_tokens', 0),
            total_tokens=usage.get('total_tokens', 0),
            duration_ms=duration_ms,
            success=1
        )
    except Exception:
        pass  # 日志记录失败不影响主流程

    # ── 健壮的 JSON 提取 ──
    # 策略 1: 提取 ```json ... ``` 或 ``` ... ``` 之间的内容
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if m:
        content = m.group(1).strip()
    elif content.startswith('```'):
        lines = content.split('\n')
        content = '\n'.join(lines[1:])
        if content.endswith('```'):
            content = content[:-3].strip()

    # 策略 2: 如果仍不是有效 JSON，尝试提取第一个 { 到最后一个 }
    try:
        json.loads(content)
    except (json.JSONDecodeError, ValueError):
        start = content.find('{')
        end = content.rfind('}')
        if start >= 0 and end > start:
            extracted = content[start:end+1]
            try:
                json.loads(extracted)
                content = extracted
            except (json.JSONDecodeError, ValueError):
                pass

    return content, usage


def normalize_creative_output(data):
    """修复输出格式：v2 object → v3 array，处理各种边缘情况"""
    if not isinstance(data, dict):
        return data

    directions = data.get('directions')
    if directions is None:
        if data.get('parse_error'):
            return data
        data['directions'] = []
        data['_format_warning'] = 'directions 字段缺失，已重置为空数组'
        return data

    # 已经是 array 格式
    if isinstance(directions, list):
        data.setdefault('scene_tier', '🥈')
        for d in directions:
            if not isinstance(d, dict):
                continue
            d.setdefault('emoji', '')
            d.setdefault('label', '')
            d.setdefault('style', '')
            d.setdefault('reason', '')
            d.setdefault('how', '')
            d.setdefault('source_note', '')
            d.setdefault('plans', [])
            d.setdefault('subtitle', '')
            d.setdefault('style_promise', '')
            d.setdefault('fit_rationale', '')
            d.setdefault('light_annotation', '')
            d.setdefault('device_annotation', '')
            d.setdefault('source_type', '')
            d.setdefault('name_source', '')
            d.setdefault('style_brief', {})
            for p in d.get('plans', []):
                if isinstance(p, dict):
                    p.setdefault('subject', '')
                    p.setdefault('shooter', '')
                    p.setdefault('gear', '')
                    p.setdefault('enhance', '')
                    p.setdefault('annotations', [])
                    p.setdefault('perspective', '')
                    p.setdefault('img_gen_prompt', '')
        return data

    # v2 object 格式 → 转换为 array
    if isinstance(directions, dict):
        dir_ids = {'now': {'emoji': '🟢', 'label': '现在就拍', 'subtitle': '零门槛，站在这就能拍'},
                    'best': {'emoji': '🔥', 'label': '最出片', 'subtitle': '发出去会被赞的那种'},
                    'creative': {'emoji': '✨', 'label': '脑洞大开', 'subtitle': '不像游客照的视角'}}
        array_dirs = []
        for key, defaults in dir_ids.items():
            d = directions.get(key, {})
            if isinstance(d, dict):
                d['id'] = key
                for k, v in defaults.items():
                    d.setdefault(k, v)
                d.setdefault('style', '')
                d.setdefault('style_promise', '')
                d.setdefault('reason', '')
                d.setdefault('how', '')
                d.setdefault('source_note', '')
                d.setdefault('plans', [])
                d.setdefault('fit_rationale', '')
                d.setdefault('light_annotation', '')
                d.setdefault('device_annotation', '')
                d.setdefault('source_type', '')
                d.setdefault('name_source', '')
                for p in d.get('plans', []):
                    if isinstance(p, dict):
                        p.setdefault('posture', '')
                        p.setdefault('annotations', [])
                array_dirs.append(d)
        if array_dirs:
            data['directions'] = array_dirs
            return data
        # v2 dict 但没有任何可识别的 key
        array_dirs = []
        for key, d in directions.items():
            if isinstance(d, dict):
                d.setdefault('id', str(key))
                d.setdefault('emoji', '')
                d.setdefault('label', str(key))
                d.setdefault('subtitle', '')
                d.setdefault('style', '')
                d.setdefault('style_promise', '')
                d.setdefault('reason', '')
                d.setdefault('how', '')
                d.setdefault('source_note', '')
                d.setdefault('plans', [])
                d.setdefault('fit_rationale', '')
                d.setdefault('light_annotation', '')
                d.setdefault('device_annotation', '')
                d.setdefault('source_type', '')
                d.setdefault('name_source', '')
                for p in d.get('plans', []):
                    if isinstance(p, dict):
                        p.setdefault('posture', '')
                        p.setdefault('annotations', [])
                array_dirs.append(d)
        if array_dirs:
            data['directions'] = array_dirs
            return data

    # 无法识别的 directions 格式
    direction_type = type(directions).__name__
    data['_format_warning'] = f'directions 格式异常（类型: {direction_type}），已重置为空数组'
    data['directions'] = []
    return data


def repair_json(text):
    """本地修复常见 JSON 语法错误 + 截断恢复"""
    stripped = text.rstrip()

    # 0. 截断恢复
    needs_closure = False
    if stripped and stripped[-1] not in ('}', ']', '"') and not stripped[-1].isdigit():
        last_comma = stripped.rfind(',')
        if last_comma > len(stripped) * 0.5:
            truncated = stripped[:last_comma]
            needs_closure = True
        else:
            last_brace = stripped.rfind('}')
            if last_brace > len(stripped) * 0.5:
                truncated = stripped[:last_brace + 1]
                needs_closure = True
            else:
                truncated = stripped

        if needs_closure:
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            truncated += '\n' + ']' * open_brackets + '}' * open_braces
            text = truncated

    # 1. 移除 trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # 1.5 修复缺失的字符串开头引号：`"key": 中文内容"` → `"key": "中文内容"`
    # 模式：冒号后空格跟中文，但缺少开头引号，结尾有引号
    text = re.sub(r'":\s+([^"{}\[\],\s][^"]*?)"(\s*[,}\]])', r'": "\1"\2', text)

    # 2. 修复字符串中未转义的控制字符
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            result.append(ch)
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch == '\n':
            result.append('\\n')
            continue
        if in_string and ch == '\r':
            result.append('\\r')
            continue
        if in_string and ch == '\t':
            result.append('\\t')
            continue
        result.append(ch)
    text = ''.join(result)

    return text


def parse_json_safe(content, retry_prompt=None, original_prompt=None):
    """安全解析 JSON。先尝试直接解析，失败后本地修复，再失败才 API retry。

    original_prompt: 如果提供，retry 时会作为上下文附上，防止 LLM 丢失场景信息胡编。"""

    parse_errors = []

    # ── 尝试 1: 直接解析 ──
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        parse_errors.append(f"直接解析失败: {e}")

    # ── 尝试 2: 本地修复后解析 ──
    repaired = repair_json(content)
    try:
        data = json.loads(repaired)
        print(f"[JSON] Repaired locally (was {len(content)} chars)", file=sys.stderr, flush=True)
        return data, None
    except json.JSONDecodeError as e:
        parse_errors.append(f"本地修复后仍失败: {e}")

    # ── 尝试 3: 重新提取 JSON 边界 ──
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                extracted = content[start:i+1]
                extracted_repaired = repair_json(extracted)
                try:
                    data = json.loads(extracted_repaired)
                    print(f"[JSON] Extracted from braces (was {len(content)} chars, extracted {len(extracted)} chars)", file=sys.stderr, flush=True)
                    return data, None
                except json.JSONDecodeError as e:
                    parse_errors.append(f"括号提取后仍失败: {e}")
                break

    # ── 尝试 4: API retry ──
    if retry_prompt:
        print(f"[JSON] Parse failed after 3 attempts: {'; '.join(parse_errors)}", file=sys.stderr, flush=True)
        print(f"[JSON] Raw start: {content[:200]}", file=sys.stderr, flush=True)

        full_retry = f"""{retry_prompt}

原始输出的JSON解析错误：{parse_errors[-1]}
请务必输出完整JSON，包含所有字段。特别是 directions 必须是数组格式。"""
        if original_prompt:
            full_retry = f"""以下是原始拍摄任务的全部信息，你需要基于这些信息重新输出JSON：

{original_prompt}

---
{full_retry}"""
        try:
            retry_content, _ = call_doubao([
                {"role": "user", "content": full_retry}
            ], max_tokens=4000, call_type='vision')
            retry_content = repair_json(retry_content)
            try:
                data = json.loads(retry_content)
                print(f"[JSON] Retry succeeded: {len(retry_content)} chars", file=sys.stderr, flush=True)
                return data, None
            except json.JSONDecodeError as e:
                parse_errors.append(f"API retry 仍失败: {e}")
        except Exception as e:
            parse_errors.append(f"API retry 异常: {e}")

    print(f"[JSON] All attempts failed: {'; '.join(parse_errors)}", file=sys.stderr, flush=True)
    return {"raw": content[:500], "parse_error": True, "errors": parse_errors}, parse_errors[-1]


def build_device_context(device_key, lens_key=None):
    """构建设备上下文字符串"""
    ctx = DEVICE_CONTEXTS.get(device_key, DEVICE_CONTEXTS["unknown"])
    text = f"""当前设备：{ctx['name']}
可用焦段：{ctx['lenses']}
设备优势：{ctx['strengths']}
设备限制：{ctx['limits']}
能力边界：{ctx['capability']}"""

    if device_key == 'dslr-mirrorless' and lens_key:
        lens_text = get_lens_context(lens_key)
        if lens_text:
            text += f"\n{lens_text}"

    return text, ctx


def build_device_constraints(device_key, lens_key=None):
    """生成设备约束文本（用于 PLANS_PROMPT）"""
    ctx = DEVICE_CONTEXTS.get(device_key, DEVICE_CONTEXTS["unknown"])
    lines = [
        f"你正在为 **{ctx['name']}** 设计拍摄方案。",
        f"可用焦段：{ctx['lenses']}",
        f"设备优势：{ctx['strengths']}",
        f"设备限制：{ctx['limits']}",
    ]

    if device_key == 'dslr-mirrorless' and lens_key:
        lens = LENSES.get(lens_key, {})
        if lens:
            lines.append(f"当前镜头：{lens.get('name', '未知')}（{lens.get('focal_range', '未知')}, {lens.get('aperture', '未知')}）")
            if 'prime' in lens.get('type', ''):
                lines.append("⚠️ 这是定焦镜头——所有方案必须用同一个焦段思考，靠走位变化而非变焦。")

    lines.append("在写 where/do 时必须逐一检查上述焦段和能力边界。方案应该发挥优势、规避限制。")
    return '\n'.join(lines)


def get_tier_constraint(scene_tier):
    """根据场景等级返回方案数量约束文本"""
    tiers = {
        '🥉': ('1', '3', '1-3'),
        '🥈': ('3', '6', '3-6'),
        '🥇': ('6', '9', '6-9'),
    }
    min_n, max_n, range_n = tiers.get(scene_tier, ('3', '6', '3-6'))
    return f"当前场景等级 {scene_tier}：必须生成 {range_n} 套方案。上限 {max_n} 套——不准超过。场景给不出那么多就诚实少给（最少 {min_n} 套）。"


def build_scene_template(vision_json, scene_category):
    """根据场景类型和是否有人物，返回场景专属拍摄模板。
    模板不是必选清单——是'这个场景通常能拍什么'的灵感提示。"""

    people_count = 0
    if vision_json and isinstance(vision_json, dict):
        people_str = vision_json.get('people', '')
        if people_str:
            import re
            nums = re.findall(r'\d+', str(people_str))
            if nums:
                people_count = int(nums[0])

    parts = []

    # ── 有人物时注入人像模板 ──
    if people_count >= 1:
        parts.append("""### 👤 人像拍摄思路

这个场景有人物——以下是最常用的出片角度（选2-3个真正适合现场的，不全用）：

**角度 × 景别快选**：
- 远景 + 低机位仰拍 → 天空做背景，人全身，腿显长
- 中景 + 侧面45°平视 → 最显瘦，拍半身不呆板
- 近景 + 略高30°俯拍 → 下巴尖、眼睛大、背景虚化
- 特写 + 平视 → 不拍脸——拍手/头发/衣领/配饰细节

**姿态引导（不说废话）**：
- 让她做一个具体动作：回头看远方 / 手插口袋往前走 / 把头发撩到耳后 / 蹲下来看地上的东西
- 不说"自然一点"——说"像在等一个迟到的朋友""像刚听到一个只有你知道的笑话"
- 不说"笑一个"——说"给我一个'你也太夸张了吧'的表情"
- 不说"看镜头"——说"看远处那棵歪脖子树""看玻璃里自己的倒影"

**手边道具利用**（有就用，没有不硬塞）：
- 帽子：压低帽檐阴影遮眼 / 摘下来拿手里转 / 反戴显俏皮
- 墨镜：戴着看远方 / 摘一半露一只眼看镜头 / 墨镜反射出对面风景
- 伞：撑开透过伞面形成柔焦 / 收拢当手杖 / 伞放肩上回头
- 手机：假装自拍 / 拿手里看屏幕的光映在脸上 / 举起来拍天空
- 咖啡杯：双手捧着暖手 / 放旁边拍人和杯的关系
- 花/叶子：举到耳边 / 低头闻 / 挡在一只眼前

⛔ 有道具时——道具是创造新视觉焦点的支点，不是拍照道具。围绕道具设计角度和景别。""")

    # ── 环境专属模板 ──
    env_templates = {
        "park_nature": """### 🌿 公园/自然场景思路
- 前景层次：找花丛/草地/落叶做前景虚化——手机贴地穿过草拍人物
- 尺度参照：远景拍「人小天地大」——人在画面中占1/10，让树冠/山峦/花海做主角
- 自然光利用：找树叶缝隙的光斑落在人物身上——逆光让头发和草叶边缘发亮
- 动态抓拍：让她在草地上走/跑/转圈——连拍抓裙摆飘起或头发飞起的瞬间""",

        "waterside": """### 🌊 水边场景思路
- 水平线：横平竖直——海平线/湖岸线必须水平，这是水边照片的及格线
- 倒影拍摄：蹲低拍水面倒影——下半是倒影上半是真人，虚实双世界。雨后地面水洼也能用
- 天空比例：水+天=画面主体——人在下方1/3处，天空和水面各占一半。黄金时刻逆光拍剪影极佳
- 风的利用：水边通常有风——让头发/裙摆/围巾被风吹起来，动态比静态有生命力""",

        "urban_street": """### 🏙️ 街拍/城市思路
- 几何构图：找建筑的直线/拱门/楼梯/走廊——这些几何结构天然就是构图框架
- 等待时机：找一面有意思的墙或一扇好看的门——让人物走过去，抓「恰好经过」的瞬间
- 光影追逐：城市里的光是有形状的——大楼间隙的光带/遮阳棚下的条纹阴影/玻璃幕墙的反光。让人物走进光里
- 路人关系：不需要路人消失——等一个路人恰好形成呼应（同色衣服/相反方向/相似姿态）""",

        "f_and_b": """### ☕ 咖啡厅/餐厅思路
- 窗光优先：找靠窗的位置——窗光是室内最好的光源。侧窗光打在脸上有自然的明暗过渡
- 桌面层次：杯子/盘子/花/菜单都是天然前景——手机放在桌面上穿过这些物品拍人物
- 空间纵深：咖啡厅通常有纵深——利用吧台/走廊/门框制造空间层次
- 氛围细节：不拍吃——拍搅拌咖啡的手/翻书页的指尖/窗外看进来的视角""",

        "cultural_site": """### 🏛️ 文化场所/建筑思路
- 框中框：园林的花窗/寺庙的门洞/博物馆的拱廊——退后穿过这些天然画框拍人物
- 对称构图：中式建筑最讲究对称——站正中间拍，人物在画面中轴线上
- 人与建筑比例：大建筑+小人物=崇高感——人在台阶上/门洞下/走廊尽头，占画面5-10%
- 光影时间：老建筑的光影在上午9-11点或下午3-5点最美——斜阳让雕花/窗格投下图案阴影""",

        "residential": """### 🏠 居家/室内思路
- 窗光：拉一半窗帘——让光在墙上形成明暗分界线，人物坐在明暗交界处
- 生活感：不收拾——沙发上的毯子/桌上的杯子/床边的书都是生活痕迹，比样板间好看
- 私密视角：透过门缝/窗帘/镜子拍——像偷看到的日常瞬间
- 逆光窗拍：人物站在窗前背对镜头——窗外光在人物轮廓上形成光边（手机点按人脸对焦后下拉曝光补偿-0.3）""",

        "night_scene": """### 🌃 夜景思路
- 光源利用：霓虹灯/路灯/橱窗——让人物站在光源附近，脸被暖光照亮
- 剪影：在亮背景前拍人物剪影——手机对焦在亮处，人物自然变暗形成轮廓
- 色彩：夜景的色彩来自灯光——找冷暖对比（暖黄路灯 vs 冷蓝霓虹）
- 稳定：夜景快门慢——手肘靠在固定物上，或让人物保持静止1秒""",

        "commercial": """### 🏬 商场/商业空间思路
- 几何线条：扶梯/走廊/玻璃栏杆——利用建筑本身的线条做构图引导
- 色彩块面：商场通常有大面积纯色墙面——找一面干净的背景拍人物
- 空间透视：长走廊/中庭——利用纵深制造空间感，人物在透视消失点附近""",

        "sports_venue": """### ⚽ 运动场思路
- 动态抓拍：运动中的瞬间——低机位仰拍让跳跃/奔跑更有力量感
- 线条引导：跑道/球场的白线天然有引导视线作用——让人物站在线条的延伸方向
- 低角度：蹲下仰拍——天空做背景，地面杂物消失""",

        "transit_station": """### 🚉 交通枢纽思路
- 对称构图：地铁站/火车站通常有对称结构——站中间拍
- 动态与静止：利用人流——人物静止（等车/看手机），周围人流虚化移动
- 线条透视：站台/铁轨的线条天然有透视——人物站在透视消失方向""",

        "industrial_ruins": """### 🏚️ 废墟/工业思路
- 质感对比：粗粝墙面+柔软衣物 / 锈迹金属+皮肤——材质冲突制造视觉张力
- 破败美感：利用残破窗口/裂缝/杂草——不是拍破败，是拍「被时间打磨过的质感」
- 负空间：大面积空白墙面+角落的人物——留白制造孤独感""",

        "campus": """### 🎒 校园思路
- 操场/跑道：低机位仰拍跑道人像——白线做引导线，天空做背景
- 教学楼走廊：长走廊的纵深透视——人物在走廊中间或尽头
- 教室窗光：靠窗座位——侧窗光是最自然的肖像光源""",
    }

    # 匹配场景模板
    if scene_category and scene_category in env_templates:
        parts.append(env_templates[scene_category])
    elif scene_category == "outdoor_generic" or (scene_category == "" and "室外" in str(vision_json.get('scene_type', ''))):
        parts.append("""### 🌤 户外通用思路
- 找光：先看光线方向——顺光色彩饱和/侧光有立体感/逆光有氛围。让人物面朝光源方向或站在明暗交界处
- 简化背景：手机拍照背景容易乱——移动位置让背景变成纯色（天空/草地/墙面），或走近让人物填满画面
- 空间层次：前景+中景+背景三层——前景找一片叶子/花丛虚化，中景是人物，背景是环境""")
    elif scene_category == "indoor_generic" or (scene_category == "" and "室内" in str(vision_json.get('scene_type', ''))):
        parts.append("""### 🏠 室内通用思路
- 窗光优先：找最近的窗户——侧窗光是最好的室内光源。离窗1-2米，让光从侧面打在人物脸上
- 减法：室内杂物多——拍之前挪开背景里最乱的三样东西。走近拍半身或特写，自然避开地面杂物
- 前景制造：桌面/沙发扶手/门框都可以做前景——手机凑近前景物体，对焦在人物脸上""")

    return '\n'.join(parts) if parts else ""


def build_material_inventory(vision_json):
    """从 Vision 分析结果构建素材清单——所有可用于技巧设计的视觉原材料。

    Stage 2 的技巧设计必须引用这些素材，确保每条建议与这张照片强绑定，不模板化。
    """
    if not isinstance(vision_json, dict):
        return "（视觉分析数据不可用）"

    lines = ["## 📦 素材清单（每条方案必须引用 ≥1 个素材，禁止通用空话）\n"]

    # ── 人物素材 ──
    people = vision_json.get('people', '')
    if people and '无' not in str(people):
        lines.append(f"### 🧑 人物状态\n{people}\n")

    # ── 服饰素材（从 distinctive_traits 提取可用于物品调整的）──
    traits = vision_json.get('distinctive_traits', '')
    if traits and '无' not in str(traits):
        traits_clean = traits.replace('，', ',').replace(',', '、')
        lines.append(f"### 👗 服饰道具\n{traits_clean}")
        lines.append("> 可调整：摘/戴/卷起/反戴/脱掉/披上——每个物品都是设计变量\n")

    # ── 空间锚点 ──
    space = vision_json.get('space', {})
    if isinstance(space, dict):
        anchors = space.get('anchors', '')
        if anchors:
            lines.append(f"### 📍 场景锚点（用于空间化指令）\n{anchors}")
            lines.append("> 站位/坐位/靠位必须指名具体锚点：'站粗浮木右侧''坐长条枯木上'\n")
        depth = space.get('depth', '')
        foreground = space.get('foreground', '')
        midground = space.get('midground', '')
        background = space.get('background', '')
        if any([foreground, midground, background]):
            lines.append(f"### 📐 空间层次（用于景深/对焦决策）")
            if depth:
                lines.append(f"- 纵深：{depth}")
            if foreground:
                lines.append(f"- 前景：{foreground}")
            if midground:
                lines.append(f"- 中景：{midground}")
            if background:
                lines.append(f"- 背景：{background}")
            lines.append("")

    # ── 光线 ──
    light = vision_json.get('light', {})
    if isinstance(light, dict):
        lines.append("### 💡 光线条件（用于光线利用/避让决策）")
        for key in ['direction', 'quality', 'color_temp', 'special', 'level']:
            val = light.get(key, '')
            if val:
                labels = {'direction': '方向', 'quality': '质感', 'color_temp': '色温',
                          'special': '特殊光', 'level': '亮度'}
                lines.append(f"- {labels.get(key, key)}：{val}")
        lines.append("")

    # ── 色彩 ──
    color = vision_json.get('color', {})
    if isinstance(color, dict):
        lines.append("### 🎨 色彩信息（用于配色/调色决策）")
        for key in ['primary', 'secondary', 'accent']:
            val = color.get(key, '')
            if val:
                labels = {'primary': '主色', 'secondary': '次要色', 'accent': '强调色'}
                lines.append(f"- {labels.get(key, key)}：{val}")
        lines.append("")

    # ── 构图 ──
    composition = vision_json.get('composition', '')
    if composition:
        lines.append(f"### 🖼️ 构图元素\n{composition}\n")

    return "\n".join(lines)


def build_forbidden_constraints(device_key, lens_key=None, scene_mode=None):
    """生成禁止型约束——直接排除不可实现的建议"""
    lines = ["## 🚫 禁止型约束（以下建议一律不可出现）\n"]

    # ── 设备相关禁止 ──
    ctx = DEVICE_CONTEXTS.get(device_key, DEVICE_CONTEXTS.get("unknown", {}))
    if ctx:
        device_name = ctx.get('name', '此设备')
        if '手机' in device_name or 'iPhone' in device_name or 'android' in device_key:
            lines.append("### 设备限制")
            lines.append("- ❌ 禁止提'打反光板''离机闪''布灯'——用户没有专业灯光设备")
            lines.append("- ❌ 禁止提具体光圈值（f/1.4/f/2.8等）——手机光圈不可调")
            lines.append("- ❌ 禁止提'70-200mm''超广角镜头'——可提'人像模式''2×变焦''0.5×超广角'")
            lines.append("- ❌ 禁止提'RAW后期''Lightroom精修'——可提'相册编辑''醒图''VSCO'")
        elif '相机' in device_name or '富士' in device_name or '理光' in device_name or 'Canon' in device_name or 'Sony' in device_name:
            lines.append("### 设备限制（相机）")
            lines.append("- ❌ 禁止提'计算摄影''AI人像模式''夜景模式'——相机没有这些")
            lines.append("- ✅ 可提具体光圈/快门/ISO/焦段——相机用户能操作这些")
            if lens_key and 'prime' in LENSES.get(lens_key, {}).get('type', ''):
                lines.append("- ⚠️ 定焦镜头——所有方案用同一焦段，靠走位代替变焦")

    # ── 安全相关禁止 ──
    lines.append("\n### 安全限制")
    lines.append("- ❌ 禁止提'跳起抓拍''连续跳跃'——普通人拍10次9次废，且可能受伤")
    lines.append("- ❌ 禁止提'躺水边让浪花打湿'——不卫生且有安全风险")
    lines.append("- ❌ 禁止提'爬树''攀岩''站礁石尖端''坐悬崖边缘'——安全风险")

    # ── 社交/操作限制 ──
    lines.append("\n### 操作限制")
    lines.append("- ❌ 禁止提'让路人帮忙''找摄影师''约模特'——用户只有手机/相机+同行人")
    lines.append("- ❌ 禁止提'等一小时后的光线''明天再来'——除非用户真的在场景里")
    lines.append("- ❌ 禁止提'去私人领地/酒店''进收费区'——不可控")

    # ── 通用审美禁忌 ──
    lines.append("\n### 审美禁忌（来自小红书/摄影社区踩坑帖）")
    lines.append("- ❌ 顶光+平视正脸 → 眼窝/鼻下/下巴三重阴影")
    lines.append("- ❌ 全身照+俯拍 → 头大身小Q版比例")
    lines.append("- ❌ 绿草地+正红衣服（未褪色处理）→ 红绿补色直接碰撞=土")
    lines.append("- ❌ 闪光灯直打+油性皮肤 → 面部油光反光=灾难")
    lines.append("- ❌ 逆光+深色背景+无补光 → 主体全黑剪影（除非这是目的）")

    # ── 场景特有禁止项 ──
    if scene_mode and scene_mode in SCENE_KNOWLEDGE_REGISTRY:
        scene_forbidden = SCENE_KNOWLEDGE_REGISTRY[scene_mode].get("forbidden_constraints", "")
        if scene_forbidden:
            lines.append(scene_forbidden)

    return "\n".join(lines) + "\n"


# ============================================================
# 流式分析生成器（：渐进式——EXIF→场景→方向，方案按需）
# ============================================================

def analyze_photo_stream(image_path, device_override=None, lens_key=None, client_ip=None):
    """流式照片分析——SSE 事件生成器
    阶段：EXIF → 视觉分析 → 方向卡片（不含方案）
    方案由 /analyze/plans 按需生成
    """
    global _processing
    t0 = time.time()
    trace_id = uuid.uuid4().hex[:12]  # 提前生成，用于全链路 API 调用埋点

    def emit(event, data):
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def emit_progress(phase, text):
        return emit("progress", {"phase": phase, "text": text})

    try:
        # ── Phase 0: 图片载入 ──
        print("[SSE] Starting analysis...", file=sys.stderr, flush=True)
        yield emit_progress("exif", "正在读取照片信息...")

        ext = os.path.splitext(image_path)[1].lower()
        try:
            img = Image.open(image_path)
            img = ImageOps.exif_transpose(img)  # 应用 EXIF 旋转方向——防止找回会话时图片方向错误
            if img.mode in ('RGBA', 'P', 'LA'):
                img = img.convert('RGB')
            w, h = img.size
            max_dim = max(w, h)

            # ── 主图：2048px 用于展示/EXIF ──
            main_img = img
            if max_dim > MAX_IMAGE_DIM:
                ratio = MAX_IMAGE_DIM / max_dim
                main_img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            main_buf = io.BytesIO()
            main_img.save(main_buf, format='JPEG', quality=85)
            img_b64 = base64.b64encode(main_buf.getvalue()).decode()

            # ── 视觉图：1024px 给豆包 API——场景分析不需要高分辨率，省一半时间 ──
            vision_img = img
            if max_dim > VISION_IMAGE_DIM:
                ratio_v = VISION_IMAGE_DIM / max_dim
                vision_img = img.resize((int(w * ratio_v), int(h * ratio_v)), Image.LANCZOS)
            vision_buf = io.BytesIO()
            vision_img.save(vision_buf, format='JPEG', quality=80)
            vision_b64 = base64.b64encode(vision_buf.getvalue()).decode()

            mime_type = "image/jpeg"
            print(f"[SSE] Image loaded: main={main_img.size} ({len(img_b64)}b64), vision={vision_img.size} ({len(vision_b64)}b64)", file=sys.stderr, flush=True)
        except Exception as imgerr:
            print(f"[SSE] Image open error: {imgerr}", file=sys.stderr, flush=True)
            yield emit("error", {"message": f"无法读取照片: {str(imgerr)}"})
            _processing = False
            return

        # ── Phase 1: 先读 EXIF（~1s），立刻发给前端，不等 Vision ──
        exif_result = {"error": "未执行"}
        vision_result = {"error": "未执行"}

        def do_exif():
            nonlocal exif_result
            try:
                exif_result = extract_exif(image_path)
            except Exception as e:
                exif_result = {"error": str(e)}

        def do_vision():
            nonlocal vision_result
            try:
                print("[SSE] Vision API starting...", file=sys.stderr, flush=True)
                result, usage = call_doubao([
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{vision_b64}"}},
                        {"type": "text", "text": VISION_PROMPT}
                    ]}
                ], max_tokens=2000, call_type='vision', session_id=trace_id)
                print(f"[SSE] Vision API done: {usage.get('total_tokens','?')} tokens", file=sys.stderr, flush=True)
                vision_result = {"content": result, "usage": usage}
            except Exception as e:
                vision_result = {"error": str(e)}
                print(f"[SSE] Vision thread error: {e}", file=sys.stderr, flush=True)

        # 1) EXIF 先跑（~1s），Vision 同时启动但不等待
        t_exif = threading.Thread(target=do_exif)
        t_vision = threading.Thread(target=do_vision)
        t_exif.start()
        t_vision.start()
        t_exif.join()  # 只等 EXIF，不等 Vision

        # ── 设备自动检测（EXIF 数据已有）──
        exif_summary = "无EXIF数据"
        detected_device_key = None
        detected_device_name = None
        is_camera = False

        if isinstance(exif_result, dict) and 'error' not in exif_result:
            exif_summary = json.dumps(exif_result, ensure_ascii=False)
            detected_device_key, detected_device_name, is_camera = detect_device_from_exif(exif_result)

        # 清理 EXIF 设备名（去掉 "Apple " 等多余前缀）
        if detected_device_name:
            detected_device_name = detected_device_name.replace("Apple ", "").strip()

        if device_override:
            final_device_key = device_override
            device_source = "manual"
        elif detected_device_key:
            final_device_key = detected_device_key
            device_source = "exif"
        else:
            final_device_key = "unknown"
            device_source = "none"

        device_text, device_ctx = build_device_context(final_device_key, lens_key)

        # ── 🔥 立刻发送 EXIF + 设备信息给前端（不等 Vision！）──
        exif_display = {}
        if isinstance(exif_result, dict) and 'error' not in exif_result:
            # 顶层字段
            for key in ['device', 'datetime', 'dimensions', 'orientation']:
                val = exif_result.get(key, '')
                if val:
                    exif_display[key] = val
            # shooting_params 嵌套字段
            sp = exif_result.get('shooting_params', {})
            if isinstance(sp, dict):
                for key in ['focal_length_35mm', 'iso', 'exposure_time', 'aperture',
                             'white_balance', 'exposure_program', 'metering_mode',
                             'image_orientation', 'brightness', 'lens_model',
                             'exposure_compensation']:
                    val = sp.get(key, '')
                    if val or (isinstance(val, (int, float)) and val == 0):
                        exif_display[key] = val
                # 闪光灯特殊处理
                flash = sp.get('flash', {})
                if isinstance(flash, dict) and flash.get('fired'):
                    exif_display['flash'] = '已触发 ⚡'
                elif isinstance(flash, dict):
                    exif_display['flash'] = '未触发'
                # 分析备注（低光/慢快门等信号）
                notes = sp.get('_analysis_notes', [])
                if notes:
                    exif_display['_notes'] = notes

        print(f"[SSE] EXIF ready, sending immediately (Vision still running)", file=sys.stderr, flush=True)

        # ── 🌤 天气 + 地名 + 光照时段（GPS 有才调）──
        location_weather = get_location_weather(exif_result)
        if location_weather:
            print(f"[SSE] Location+Weather fetched: place={location_weather.get('place','?')}, period={location_weather.get('sun_times',{}).get('label','?')}", file=sys.stderr, flush=True)

        yield emit("exif_ready", {
            "exif": exif_display,
            "exif_raw": exif_summary,
            "device_key": final_device_key,
            "device_name": device_ctx['name'],
            "device_lenses": device_ctx['lenses'],
            "device_strengths": device_ctx['strengths'],
            "device_limits": device_ctx['limits'],
            "exif_device": detected_device_name or "",
            "is_camera": is_camera,
            "source": device_source,
            "lens_options": list(LENSES.keys()) if is_camera else None,
            "location_weather": location_weather  # 🆕 天气/地名/光照时段
        })

        # ── Phase 2: 等 Vision API 完成 ──
        yield emit_progress("vision", "正在分析画面内容...")
        t_vision.join()
        print("[SSE] Vision thread joined", file=sys.stderr, flush=True)

        # ── 处理视觉结果 ──
        vision_content = vision_result.get("content", "")
        vision_usage = vision_result.get("usage", {})
        vision_error_msg = vision_result.get("error", "")

        if vision_error_msg:
            yield emit("error", {"message": f"视觉分析失败: {vision_error_msg}"})
            _processing = False
            return

        if not vision_content:
            yield emit("error", {"message": "视觉分析返回空结果，请换张照片重试"})
            _processing = False
            return

        vision_json, vision_error = parse_json_safe(vision_content)
        if vision_error or (isinstance(vision_json, dict) and vision_json.get('parse_error')):
            yield emit("error", {"message": "视觉分析结果解析失败，请换张照片重试"})
            _processing = False
            return

        print("[SSE] Vision parsed OK", file=sys.stderr, flush=True)

        # ── 发送场景分析给前端展示 ──
        yield emit("vision_ready", {
            "scene_type": vision_json.get('scene_type', ''),
            "people": vision_json.get('people', ''),
            "light": vision_json.get('light', {}),
            "color": vision_json.get('color', {}),
            "space": vision_json.get('space', {}),
            "composition": vision_json.get('composition', '')
        })

        # ── Phase 2: 方向生成（不含方案）──
        yield emit_progress("directions", "正在搜索社区灵感 + 生成风格方向...")

        # 风格积累上下文
        scene_type = vision_json.get('scene_type', '')
        location_clues = vision_json.get('location_clues', '')
        scene_category = extract_scene_category(scene_type, location_clues)

        # ── 🎯 自动场景模式检测（融入统一流程，不创建平行路径）──
        scene_mode = detect_scene_mode(scene_type, vision_json)
        if scene_mode:
            print(f"[SSE] 🎯 Auto-detected scene mode: {scene_mode}", file=sys.stderr, flush=True)

        # ── EXIF 交叉验证 ──
        exif_cross_check = ""
        if isinstance(exif_result, dict) and 'error' not in exif_result:
            sp = exif_result.get('shooting_params', {})
            checks = []
            iso = sp.get('iso', 0)
            shutter = sp.get('exposure_time', '')
            flash = sp.get('flash', {})
            brightness = sp.get('brightness', None)

            # ISO 交叉验证
            if isinstance(iso, (int, float)) and iso >= 800:
                light_quality = vision_json.get('light', {}).get('quality', '')
                if '硬' in str(light_quality) or '明亮' in str(vision_json.get('light', {})):
                    checks.append(f"⚠️ EXIF交叉验证：ISO={iso}（低光环境的硬证据），但视觉分析判断光线充足——采信EXIF。此场景实际光线偏暗，需注意噪点和稳定性。")

            # 闪光灯修正
            if isinstance(flash, dict) and flash.get('fired'):
                checks.append("⚠️ 闪光灯已触发！视觉分析中的'自然光'判断需修正——实际拍摄有人工补光。光质分析需考虑闪光灯影响。")

            # 快门稳定性
            if isinstance(shutter, str) and '/' in shutter:
                try:
                    num, den = shutter.split('/')
                    speed = float(num) / float(den)
                    if speed < 1/60 and speed > 0:
                        checks.append(f"💡 EXIF：快门={shutter}（慢于1/60s），建议稳定支撑或利用防抖。")
                except (ValueError, ZeroDivisionError):
                    pass

            # 白平衡
            wb = sp.get('white_balance', '')
            if wb and 'Manual' in str(wb):
                checks.append("💡 白平衡设为手动——用户在主动控制色彩，可推荐更进阶的风格方向。")

            if checks:
                exif_cross_check = "## 🚨 EXIF 交叉验证\n" + "\n".join(checks) + "\n"

        # ── 知识库注入（作为参考，不限制 LLM 创作）──
        people_info = vision_json.get('people', '') if isinstance(vision_json, dict) else ''
        light_data = vision_json.get('light', {}) if isinstance(vision_json, dict) else {}

        knowledge_context = get_all_knowledge_for_prompt(
            scene_type=scene_type,
            device_key=final_device_key,
            light_condition=json.dumps(light_data, ensure_ascii=False),
            fallback_level="medium"  # 固定权重——AI自由创作，KB作为参考
        )
        print(f"[SSE] Knowledge context: {len(knowledge_context)} chars", file=sys.stderr, flush=True)

        # ── 场景知识注入（融入统一 knowledge_context，不替换 Prompt）──
        if scene_mode and scene_mode in SCENE_KNOWLEDGE_REGISTRY:
            scene_kb = SCENE_KNOWLEDGE_REGISTRY[scene_mode].get("knowledge_text", "")
            if scene_kb:
                knowledge_context = knowledge_context + "\n\n" + scene_kb
                print(f"[SSE] Injected {scene_mode} knowledge: +{len(scene_kb)} chars", file=sys.stderr, flush=True)

        # ── 快速路径判断 ──
        fast_path_note = ""
        if not location_weather:
            fast_path_note += "- 无GPS数据 → 跳过了位置/天气/光照时段分析\n"
        indoor_keywords = ["室内", "地铁", "商场", "咖啡", "餐厅", "家", "卧室", "客厅", "办公室"]
        if any(kw in scene_type for kw in indoor_keywords):
            fast_path_note += "- 室内场景 → 天气策略不适用，聚焦室内光线利用\n"
        if "无" in str(people_info) or "无人" in str(people_info):
            fast_path_note += "- 无人物 → 跳过姿势引导，聚焦空间/静物/氛围\n"
        if fast_path_note:
            fast_path_note = "## ⚡ 快速路径（本次跳过的分析）\n" + fast_path_note + "\n"

        # 不再触发搜索——风格由 AI 从视觉数据自由创作，KB 作为参考验证

        # ── 🌤 环境上下文（注入方向+方案 prompt，让推荐更智能）──
        env_context = ""
        if location_weather:
            st = location_weather.get('sun_times', {})
            if st:
                env_context += f"- 光照时段：{st.get('emoji','')} {st.get('label','')}（{st.get('desc','')}）\n"
                env_context += f"- 日出 {st.get('sunrise','?')} / 日落 {st.get('sunset','?')}\n"
                # 日落倒计时
                if st.get('sunset'):
                    try:
                        from datetime import datetime
                        sunset_t = datetime.strptime(st['sunset'], '%H:%M').time()
                        now_t = datetime.now().time()
                        mins_left = (sunset_t.hour * 60 + sunset_t.minute) - (now_t.hour * 60 + now_t.minute)
                        if 0 < mins_left < 120:
                            env_context += f"- ⚠️ 距日落约{mins_left}分钟——时间窗口有限\n"
                    except:
                        pass
            # 光线评估（豆包 AI）
            light_level = vision_json.get('light', {}).get('level', '')
            if light_level:
                env_context += f"- AI亮度评估：{light_level}\n"
            # 识别地点
            loc_clues = vision_json.get('location_clues', '')
            if loc_clues and loc_clues != '无法识别':
                env_context += f"- 画面识别地点：{loc_clues}\n"
            elif location_weather.get('place'):
                env_context += f"- GPS地点：{location_weather['place']}\n"
            # 天气预报摘要
            fc = location_weather.get('forecast', [])
            if fc:
                fc_parts = []
                for f_item in fc[:6]:
                    part = f"{f_item.get('time','')} {f_item.get('emoji','')}"
                    if f_item.get('temp') is not None:
                        part += f" {int(f_item['temp'])}°"
                    if f_item.get('precip_prob', 0) >= 30:
                        part += f" 🌧{f_item['precip_prob']}%"
                    fc_parts.append(part)
                env_context += f"- 未来天气：{' · '.join(fc_parts)}\n"
                # 雨警
                rain_items = [f for f in fc if f.get('precip_prob', 0) >= 30]
                if rain_items:
                    env_context += "- ⚠️ 未来有降雨概率——风格推荐需考虑天气变化\n"
        if env_context:
            env_context = "## 🌤 拍摄环境上下文\n" + env_context
        else:
            env_context = "（无可用环境数据）\n"

        # ── 统一 Prompt（场景知识已注入 knowledge_context，无需分支）──
        directions_prompt = DIRECTIONS_PROMPT.format(
            vision_json=json.dumps(vision_json, ensure_ascii=False, indent=2),
            exif_summary=exif_summary,
            exif_cross_check=exif_cross_check,
            device_context=device_text,
            knowledge_context=knowledge_context,
            fast_path_note=fast_path_note,
            env_context=env_context
        )
        print(f"[SSE] Directions prompt: {len(directions_prompt)} chars", file=sys.stderr, flush=True)
        directions_content, directions_usage = call_doubao([
            {"role": "user", "content": directions_prompt}
        ], max_tokens=2500, call_type='directions', session_id=trace_id)  # 方向输出通常<1500 tokens
        print(f"[SSE] Directions API done: {directions_usage.get('total_tokens','?')} tokens", file=sys.stderr, flush=True)

        # 解析方向输出
        directions_json, directions_error = parse_json_safe(
            directions_content,
            retry_prompt="你上次的输出不是有效JSON。请重新输出，只输出纯JSON对象，不要markdown包裹，不要任何额外文字。directions 必须是数组 []。",
            original_prompt=directions_prompt
        )
        directions_json = normalize_creative_output(directions_json)

        # 验证 directions 格式
        if isinstance(directions_json, dict):
            dirs = directions_json.get('directions')
            if not isinstance(dirs, list):
                dir_type = type(dirs).__name__
                print(f"[SSE] WARNING: directions is {dir_type}, not list. Resetting.", file=sys.stderr, flush=True)
                directions_json['directions'] = []
                if not directions_json.get('_format_warning'):
                    directions_json['_format_warning'] = f'directions 格式异常（{dir_type}），已重置为空数组'

        # 提取元数据
        insight = directions_json.get('insight', '')
        scene_tier = directions_json.get('scene_tier', '🥈')
        directions = directions_json.get('directions', [])
        fold_details = directions_json.get('fold_details', {})

        # ── KB 查证：风格来源标注（结合 AI 的 kb_status 和服务端查询）──
        discovery_note = directions_json.get('discovery_note', '')
        if discovery_note:
            print(f"[KB] 🆕 AI 发现备注: {discovery_note[:120]}", file=sys.stderr, flush=True)

        source_tags = {}
        for d in directions:
            style_name = d.get('style', '')
            ai_kb_status = d.get('kb_status', '')  # AI 自己标注的 📚已有记录 / 🆕新发现
            if not style_name:
                source_tags[d['id']] = '🤖 AI 探索'
                continue
            try:
                kb_detail = get_style_detail(style_name)
                in_kb = kb_detail and ('来源：知识库' in kb_detail or '跨媒介' in kb_detail)

                if in_kb:
                    source_tags[d['id']] = '📚 有据可查'
                    print(f"[KB] ✅ {style_name} → KB 已有",
                          file=sys.stderr, flush=True)
                elif '🆕' in ai_kb_status:
                    source_tags[d['id']] = '🆕 AI 新发现'
                    print(f"[KB] 🆕 {style_name} → AI 自由探索新风格！",
                          file=sys.stderr, flush=True)
                else:
                    source_tags[d['id']] = '🤖 AI 探索'
                    print(f"[KB] 🤖 {style_name} → 新风格，AI 自由创作",
                          file=sys.stderr, flush=True)
            except Exception as e:
                source_tags[d['id']] = '🤖 AI 探索'
                print(f"[KB] 查证异常 {style_name}: {e}", file=sys.stderr, flush=True)

        # ── v4.0: 风格探索日志（记录 AI 选取的风格及理由）──
        for d in directions:
            style_name = (d.get('style') or '').strip()
            if not style_name:
                continue
            reason = (d.get('fit_rationale') or d.get('reason') or '').strip()
            src_tag = source_tags.get(d['id'], '🤖 AI 探索')
            full_reason = f"{src_tag} | {reason}" if reason else src_tag
            try:
                log_style_exploration(
                    session_id=trace_id,
                    style_name=style_name,
                    decision='selected',
                    reason=full_reason
                )
            except Exception:
                pass  # 日志失败不阻塞主流程

        # ── 创建 session（后续方案生成使用）──
        session_id = create_session(
            session_id=trace_id,
            vision_json=vision_json,
            exif_summary=exif_summary,
            device_key=final_device_key,
            device_context=device_text,
            directions=directions,
            scene_tier=scene_tier,
            client_ip=client_ip,
            env_context=env_context,
            fold_details=fold_details,
            scene_category=scene_category
        )

        # ── 记录使用统计 ──
        try:
            save_usage_session(
                session_id=session_id,
                ip_address=client_ip,
                device_key=final_device_key,
                device_name=device_ctx.get('name', '') if device_ctx else '',
                scene_type=scene_type,
                scene_tier=scene_tier,
                direction_count=len(directions)
            )
        except Exception as e:
            print(f"[Stats] Save usage session error: {e}", file=sys.stderr, flush=True)

        # ── 风格积累 ──
        try:
            accumulate(scene_type, [], [],
                      scene_category=scene_category,
                      authenticity='ai_generated')
        except Exception as e:
            print(f"[StyleCache] Accumulate error: {e}", file=sys.stderr, flush=True)

        # ── 发送方向结果给前端 ──
        yield emit("directions_ready", {
            "insight": insight,
            "scene_tier": scene_tier,
            "directions": directions,
            "fold_details": fold_details,
            "source_tags": source_tags,
            "session_id": session_id
        })

        # ── 保存恢复数据到 session（用户误关后可找回）──
        sess = _sessions.get(session_id)
        if sess:
            sess['img_b64'] = img_b64
            sess['exif_data'] = exif_display
            sess['insight'] = insight
            sess['fold_details'] = fold_details
            sess['scene_mode'] = scene_mode  # 记住场景模式，方案生成时复用
            _save_session(session_id)  # 立即持久化到磁盘，防止重启丢图片

        # ── 📋 本地分析留存：每次分析完保存视觉数据，方便代码改动后对比 ──
        try:
            os.makedirs(_RECENT_DIR, exist_ok=True)
            recent = {
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "scene_category": scene_category,
                "scene_mode": scene_mode,
                "scene_tier": scene_tier,
                "scene_type": scene_type,
                "insight": insight,
                "device_key": final_device_key,
                "vision_json": vision_json,
                "exif_summary": exif_summary,
                "directions": [{
                    "id": d.get("id"),
                    "style": d.get("style"),
                    "kb_status": d.get("kb_status"),
                    "style_promise": d.get("style_promise"),
                    "style_brief": d.get("style_brief"),
                    "photo_guide": d.get("photo_guide"),
                } for d in directions],
            }
            recent_path = os.path.join(_RECENT_DIR, f"{session_id}.json")
            with open(recent_path, "w", encoding="utf-8") as f:
                json.dump(recent, f, ensure_ascii=False, indent=2)
            # 更新索引
            index_path = os.path.join(_RECENT_DIR, "_index.json")
            index_entries = []
            if os.path.exists(index_path):
                try:
                    with open(index_path) as f:
                        index_entries = json.load(f)
                except:
                    pass
            index_entries.insert(0, {
                "session_id": session_id,
                "timestamp": recent["timestamp"],
                "scene_category": scene_category,
                "scene_mode": scene_mode,
                "scene_tier": scene_tier,
                "scene_type": scene_type[:80],
                "styles": [d.get("style", "") for d in directions],
            })
            # 只保留最近 50 条
            index_entries = index_entries[:50]
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index_entries, f, ensure_ascii=False, indent=2)
            print(f"[Recent] Saved analysis: {recent_path}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[Recent] Save failed: {e}", file=sys.stderr, flush=True)

        # ── 完成 ──
        total_time = round(time.time() - t0, 1)
        total_tokens = (vision_usage.get('total_tokens', 0) +
                        directions_usage.get('total_tokens', 0))

        print(f"[SSE] Complete! {total_time}s, {total_tokens} tokens, session={session_id}", file=sys.stderr, flush=True)
        yield emit("complete", {
            "success": True,
            "elapsed": total_time,
            "tokens": total_tokens,
            "session_id": session_id
        })

    except Exception as e:
        import traceback
        print(f"[SSE] ERROR: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        yield emit("error", {"message": str(e)})
    finally:
        _processing = False
        print("[SSE] Generator finished", file=sys.stderr, flush=True)


# ============================================================
# 方案按需生成（用户选方向后调用）
# ============================================================

def generate_plans_for_direction(session_id, direction_id, device_override=None, lens_key=None, scene_mode=None):
    """为指定方向生成方案，支持缓存"""
    session = get_session(session_id)
    if not session:
        return None, "会话已过期，请重新上传照片"

    # 确定设备
    if device_override:
        device_key = device_override
    else:
        device_key = session['device_key']

    # 查找方向
    direction = None
    for d in session['directions']:
        if d.get('id') == direction_id:
            direction = d
            break
    if not direction:
        return None, f"未找到方向 {direction_id}"

    # 构建缓存 key（设备切换会导致缓存失效）
    cache_key = f"{direction_id}:{device_key}"
    if lens_key:
        cache_key += f":{lens_key}"

    # 检查缓存
    if cache_key in session['plan_cache']:
        print(f"[Plans] Cache hit: {cache_key}", file=sys.stderr, flush=True)
        plans = session['plan_cache'][cache_key]
        # v5: 增强图由前端 Canvas 标注渲染（不再服务端生图）
        return plans, None

    # ── 防止重复 LLM 调用（retry/poll 并发时同一 key 只生成一次）──
    global_key = f"{session_id}:{cache_key}"
    with _plan_generating_lock:
        # 清理 stale entries（超过 5 分钟的标记视为无效，可能 worker 被 kill）
        now = time.time()
        stale = [k for k, t in _plan_generating.items() if now - t > 300]
        for k in stale:
            _plan_generating.pop(k, None)
        if stale:
            print(f"[Plans] Cleaned {len(stale)} stale generating entries", file=sys.stderr, flush=True)

        if global_key in _plan_generating:
            is_generating = True
        else:
            is_generating = False
            _plan_generating[global_key] = time.time()

    if is_generating:
        # 另一个请求正在生成中，等待它完成（在锁外等待，不阻塞其他请求）
        waited = 0
        while waited < 60:
            time.sleep(1.5)
            waited += 1.5
            # 每 3 秒检查一次缓存
            if waited % 3 < 0.5:
                sess = get_session(session_id)
                if sess and cache_key in sess.get('plan_cache', {}):
                    print(f"[Plans] Waited {waited:.0f}s for in-progress generation, cache now ready", file=sys.stderr, flush=True)
                    return sess['plan_cache'][cache_key], None
            # 检查生成标记是否已清除（生成失败或完成）
            with _plan_generating_lock:
                if global_key not in _plan_generating:
                    sess = get_session(session_id)
                    if sess and cache_key in sess.get('plan_cache', {}):
                        return sess['plan_cache'][cache_key], None
                    # 生成失败且无缓存 → 重新标记并触发生成
                    _plan_generating[global_key] = time.time()
                    break

        # 等待超时（>60s）— 原请求可能还在跑但特别慢，不触发生成避免重复
        if waited >= 60:
            print(f"[Plans] Timed out waiting for existing generation ({global_key})", file=sys.stderr, flush=True)
            return None, "方案生成时间较长，请稍后重试"

    # 构建设备上下文
    device_text, _ = build_device_context(device_key, lens_key)
    device_constraints = build_device_constraints(device_key, lens_key)
    tier_constraint = get_tier_constraint(session['scene_tier'])

    # ── 组图节奏知识注入（仅 🥇 丰富场景启用）──
    scene_tier = session.get('scene_tier', '🥈')
    if scene_tier == '🥇':
        series_rhythm = load_series_rhythm()
        print(f"[Plans] Series rhythm injected: {len(series_rhythm)} chars for 🥇 scene", file=sys.stderr, flush=True)
    else:
        series_rhythm = ""

    # 构建 prompt
    style_knowledge = get_style_detail(direction.get('style', '')) or ""
    device_knowledge = get_device_adaptation(device_key) or ""

    # ── 查询数据库历史验证技法，注入方案生成 ──
    scene_type = session.get('vision_json', {}).get('scene_type', '')
    scene_category = session.get('scene_category', '')
    db_techniques = query_scene_techniques_for_plans(scene_type, category=scene_category)
    if db_techniques:
        print(f"[Plans] DB techniques: {len(db_techniques)} chars for cat={scene_category}", file=sys.stderr, flush=True)

    # 🆕 Stage 2 输入
    material_inventory = build_material_inventory(session.get('vision_json', {}))
    forbidden_constraints = build_forbidden_constraints(device_key, lens_key, scene_mode=scene_mode or session.get('scene_mode'))
    scene_template = build_scene_template(session.get('vision_json', {}), scene_category)
    scene_execution_context = build_scene_execution_context(scene_mode or session.get('scene_mode'))

    # 从 fold_details 获取方向详情
    fold_details = session.get('fold_details', {})
    direction_detail = fold_details.get(direction_id, '')

    # ── 🆕 photo_guide：新风格专属摄影翻译（已有记录的风格为空）──
    photo_guide_raw = direction.get('photo_guide', '') or ''
    if photo_guide_raw.strip():
        photo_guide = f"## 🎯 摄影翻译（🆕新风格专属——由方向阶段 AI 翻译）\n{photo_guide_raw.strip()}"
        print(f"[Plans] photo_guide injected: {len(photo_guide)} chars for new style", file=sys.stderr, flush=True)
    else:
        photo_guide = ""

    # 构建 style_brief 文本
    sb = direction.get('style_brief', {}) or {}
    if sb and isinstance(sb, dict):
        style_brief_lines = []
        if sb.get('essence'): style_brief_lines.append(f"核心：{sb['essence']}")
        if sb.get('color'): style_brief_lines.append(f"色彩：{sb['color']}")
        if sb.get('composition'): style_brief_lines.append(f"构图：{sb['composition']}")
        if sb.get('light'): style_brief_lines.append(f"光线：{sb['light']}")
        if sb.get('mood'): style_brief_lines.append(f"情绪：{sb['mood']}")
        style_brief_text = '\n'.join(style_brief_lines) if style_brief_lines else '（无特殊视觉约束，基于场景数据自由发挥）'
    else:
        style_brief_text = '（无特殊视觉约束，基于场景数据自由发挥）'

    plans_prompt = PLANS_PROMPT.format(
        vision_json=json.dumps(session['vision_json'], ensure_ascii=False, indent=2),
        material_inventory=material_inventory,
        device_context=device_text,
        style_knowledge=style_knowledge,
        device_knowledge=device_knowledge,
        emoji=direction.get('emoji', ''),
        label=direction.get('label', ''),
        style=direction.get('style', ''),
        style_promise=direction.get('style_promise', ''),
        style_brief=style_brief_text,
        reason=direction.get('reason', ''),
        direction_detail=direction_detail if direction_detail else direction.get('reason', ''),
        photo_guide=photo_guide,
        scene_tier=session['scene_tier'],
        tier_constraint=tier_constraint,
        device_constraints=device_constraints,
        env_context=session.get('env_context', ''),
        forbidden_constraints=forbidden_constraints,
        scene_template=scene_template,
        scene_execution_context=scene_execution_context,
        series_rhythm=series_rhythm,
    )

    print(f"[Plans] Prompt: {len(plans_prompt)} chars, direction={direction_id}, device={device_key}, mode={scene_mode or session.get('scene_mode', 'general')}", file=sys.stderr, flush=True)

    try:
        plans_content, plans_usage = call_doubao([
            {"role": "user", "content": plans_prompt}
        ], max_tokens=8000, call_type='plans', session_id=session_id)  # 方案输出较长，需要充足 token

        plans_json, plans_error = parse_json_safe(
            plans_content,
            retry_prompt="你上次输出的拍摄方案JSON格式有误。请重新输出，只输出包含 plans 数组的纯JSON对象。注意：这是摄影拍摄方案，不是旅行攻略。每条方案包含 name/prep/subject/shooter/gear/enhance/result/why/shot_size/angle/quick_edit/img_gen_prompt/ai_tips/combo_label 字段。",
            original_prompt=plans_prompt  # 重试时带上完整场景上下文，防止胡编
        )

        if plans_error or not isinstance(plans_json, dict):
            return None, f"方案生成解析失败: {plans_error}"

        plans = plans_json.get('plans', [])
        if not isinstance(plans, list):
            plans = []

        # 补齐字段
        for p in plans:
            if isinstance(p, dict):
                p.setdefault('subject', '')
                p.setdefault('shooter', '')
                p.setdefault('gear', '')
                p.setdefault('enhance', '')
                p.setdefault('annotations', [])
                p.setdefault('perspective', '')
                p.setdefault('shot_size', '')
                p.setdefault('angle', '')
                p.setdefault('img_gen_prompt', '')
                p.setdefault('quick_edit', {})
                p.setdefault('ai_tips', [])

        # 缓存（内存 + 磁盘持久化）
        session['plan_cache'][cache_key] = plans
        _save_session(session_id)

        # ── 更新使用统计 ──
        try:
            duration = round(time.time() - session['created_at'], 1)
            update_usage_session(
                session_id=session_id,
                direction_id=direction_id,
                direction_label=direction.get('label', ''),
                style=direction.get('style', ''),
                plan_count=len(plans),
                duration_seconds=duration,
                completed=1
            )
        except Exception as e:
            print(f"[Stats] Update usage session error: {e}", file=sys.stderr, flush=True)

        return plans, None

    except Exception as e:
        print(f"[Plans] Error: {e}", file=sys.stderr, flush=True)
        return None, str(e)
    finally:
        # 清理“生成中”标记
        with _plan_generating_lock:
            _plan_generating.pop(global_key, None)


# ============================================================
# Flask 路由
# ============================================================

@app.route('/')
def index():
    """移动端主页"""
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    """流式分析上传的照片（SSE）—— 渐进式 EXIF→场景→方向"""
    global _processing

    if not DOUBAO_API_KEY:
        return jsonify({"success": False, "error": "API Key 未配置"}), 500

    # 提取客户端 IP
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '127.0.0.1'

    # ── 每日使用限制检查 ──
    allowed, used, limit = check_and_increment_usage(client_ip, DAILY_LIMIT)
    if not allowed:
        return jsonify({
            "success": False,
            "error": "limit_reached",
            "used": used,
            "limit": limit,
            "message": f"今日免费次数已用完（{used}/{limit}），可以申请更多次数"
        }), 429

    if _processing:
        # 正在处理中——返回排队信息
        elapsed = time.time() - getattr(analyze, '_start_time', time.time())
        estimated = max(30, 120 - int(elapsed))
        return jsonify({
            "success": False,
            "error": "queue",
            "message": "前面有人在用，请稍候...",
            "estimated_wait_seconds": estimated
        }), 429

    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "未收到照片"}), 400

    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 检查文件大小
    photo.seek(0, 2)
    size = photo.tell()
    photo.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"success": False, "error": f"照片太大（{size//1024//1024}MB），限制 {MAX_FILE_SIZE//1024//1024}MB"}), 400

    # 保存临时文件
    fext = os.path.splitext(photo.filename)[1] or '.jpg'
    tmp_path = f"/tmp/daipai_{int(time.time())}_{os.getpid()}{fext}"
    photo.save(tmp_path)

    # 读取设备参数
    device_override = request.form.get('device', None) or None
    lens_key = request.form.get('lens', None) or None

    _processing = True
    analyze._start_time = time.time()  # 记录开始时间供排队估算

    def cleanup_and_generate():
        try:
            yield from analyze_photo_stream(tmp_path, device_override, lens_key, client_ip)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return Response(
        stream_with_context(cleanup_and_generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/analyze/plans', methods=['POST'])
def analyze_plans():
    """按需生成方案——用户选方向后调用。

    支持 poll 模式：参数 poll=true 时只检查缓存，不触发 LLM 生成。
    用于解决移动网络 NAT 空闲超时断开连接的问题（首次请求失败后前端轮询缓存）。
    """
    data = request.get_json() or {}
    session_id = data.get('session_id', '')
    direction_id = data.get('direction_id', '')
    device_override = data.get('device', None) or None
    lens_key = data.get('lens', None) or None
    poll_only = data.get('poll', False)

    if not session_id or not direction_id:
        return jsonify({"success": False, "error": "缺少 session_id 或 direction_id"}), 400

    # 确定缓存 key
    session = get_session(session_id)
    if not session:
        return jsonify({"success": False, "error": "会话已过期，请重新上传照片"}), 404

    # 从 session 获取场景模式（通用 / 街拍）
    scene_mode = session.get('scene_mode', None)

    cache_key = f"{direction_id}:{device_override or session['device_key']}"
    if lens_key:
        cache_key += f":{lens_key}"

    # 检查缓存
    if cache_key in session.get('plan_cache', {}):
        return jsonify({
            "success": True,
            "plans": session['plan_cache'][cache_key],
            "direction_id": direction_id,
            "cached": True
        })

    # poll 模式：检查是否真的有生成在进行中
    if poll_only:
        global_key = f"{session_id}:{cache_key}"
        with _plan_generating_lock:
            is_generating = global_key in _plan_generating
        if is_generating:
            return jsonify({"success": True, "generating": True})
        else:
            # 没有生成在进行中（首次请求可能根本没到服务器）
            # → 降级为正常模式，触发生成
            print(f"[Plans] Poll found no in-progress generation, falling back to full generation", file=sys.stderr, flush=True)

    # prewarm 模式：后台异步生成，立即返回（前端预热用）
    prewarm = data.get('prewarm', False)
    if prewarm:
        global_key = f"{session_id}:{cache_key}"
        # 检查是否已有生成在进行中（generate_plans_for_direction 会自行管理锁）
        with _plan_generating_lock:
            already_running = global_key in _plan_generating
        if already_running:
            return jsonify({"success": True, "prewarm": "already_running"})

        def _prewarm():
            try:
                plans, err = generate_plans_for_direction(session_id, direction_id, device_override, lens_key, scene_mode=scene_mode)
                if err:
                    print(f"[Prewarm] Failed for {global_key}: {err}", file=sys.stderr, flush=True)
                else:
                    print(f"[Prewarm] Completed {global_key}: {len(plans) if plans else 0} plans", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Prewarm] Error for {global_key}: {e}", file=sys.stderr, flush=True)

        import threading as _prewarm_threading
        _prewarm_threading.Thread(target=_prewarm, daemon=True).start()
        print(f"[Prewarm] Started background generation for {global_key}", file=sys.stderr, flush=True)
        return jsonify({"success": True, "prewarm": "started", "direction_id": direction_id})

    # 正常模式：触发 LLM 生成（可能耗时 30-90 秒，移动网络 NAT 可能断开）
    plans, error = generate_plans_for_direction(session_id, direction_id, device_override, lens_key, scene_mode=scene_mode)

    if error:
        return jsonify({"success": False, "error": error}), 500

    return jsonify({
        "success": True,
        "plans": plans,
        "direction_id": direction_id,
        "device": device_override or session['device_key']
    })


@app.route('/deploy', methods=['POST'])
def deploy_webhook():
    """
    GitHub Webhook 端点——代码 push 后自动部署。
    在 GitHub 仓库 Settings → Webhooks → Payload URL = https://guidepic.cn/deploy
    Content type: application/json
    Secret: 与 .env 中的 DEPLOY_SECRET 匹配
    """
    import hmac
    import hashlib

    secret = os.environ.get("DEPLOY_SECRET", "")
    if secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), request.data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return jsonify({"success": False, "error": "签名验证失败"}), 403

    # 异步执行部署（不阻塞 webhook 响应）
    def do_deploy():
        import subprocess
        deploy_script = os.path.join(os.path.dirname(__file__), "deploy.sh")
        if os.path.exists(deploy_script):
            try:
                subprocess.run(["bash", deploy_script, "--auto"], timeout=120)
            except Exception as e:
                print(f"[Deploy] Error: {e}", file=sys.stderr, flush=True)

    t = threading.Thread(target=do_deploy)
    t.start()

    return jsonify({"success": True, "message": "部署已触发"}), 200


@app.route('/sync', methods=['GET', 'POST'])
def sync_knowledge():
    """
    Claude ↔ 服务器知识同步端点。
    POST: 接收 Claude 端导出的知识数据
    GET: 导出服务器端积累的数据供 Claude 端读取
    """
    if request.method == 'POST':
        data = request.get_json() or {}
        direction = data.get('direction', 'import')  # 'import' or 'export'

        if direction == 'import':
            count = import_from_claude(data.get('data', {}))
            applied = apply_pending_sync()
            return jsonify({"success": True, "imported": count, "applied": applied})
        else:
            exported = export_for_claude()
            return jsonify({"success": True, "data": exported})

    # GET
    exported = export_for_claude()
    return jsonify({"success": True, "data": exported})


@app.route('/health')
def health():
    """健康检查"""
    try:
        stats = get_db_stats()
    except Exception:
        stats = {}
    return jsonify({
        "status": "ok",
        "api_key_configured": bool(DOUBAO_API_KEY),
        "exif_script_exists": os.path.exists(EXIF_SCRIPT),
        "db_stats": stats,
        "sessions_active": len(_sessions),
        "processing": _processing
    })


# ── 处理中状态查询（前端排队轮询）──
@app.route('/processing-status')
def processing_status():
    """查询是否正在处理中"""
    global _processing
    elapsed = 0
    if _processing:
        start = getattr(analyze, '_start_time', time.time())
        elapsed = int(time.time() - start)
    return jsonify({
        "processing": _processing,
        "elapsed_seconds": elapsed,
        "estimated_wait_seconds": max(0, 120 - elapsed) if _processing else 0
    })


# ── 方案反馈 ──
@app.route('/feedback', methods=['POST'])
def submit_feedback():
    """记录方案反馈（like/dislike）"""
    data = request.get_json() or {}
    session_id = data.get('session_id', '')
    direction_id = data.get('direction_id', '')
    plan_index = data.get('plan_index')
    rating = data.get('rating', '')
    reason = data.get('reason', '')
    reason_text = data.get('reason_text', '')

    if not session_id or not direction_id or plan_index is None:
        return jsonify({"success": False, "error": "缺少必填字段"}), 400
    if rating not in ('like', 'dislike', 'none'):
        return jsonify({"success": False, "error": "无效的 rating"}), 400
    if rating == 'dislike' and not reason:
        return jsonify({"success": False, "error": "请选择不满意原因"}), 400

    # 从 session 提取上下文
    sess = get_session(session_id)
    scene_type = ''
    style = ''
    device_key = ''
    if sess:
        scene_type = sess.get('vision_json', {}).get('scene_type', '')
        device_key = sess.get('device_key', '')
        direction = next((d for d in sess.get('directions', []) if d.get('id') == direction_id), None)
        if direction:
            style = direction.get('style', '')

    try:
        save_feedback(session_id, direction_id, plan_index, rating,
                      reason=reason, reason_text=reason_text,
                      scene_type=scene_type, style=style, device_key=device_key)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 配额申请 ──
@app.route('/request-quota', methods=['POST'])
def request_quota():
    """申请更多使用次数"""
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '127.0.0.1'
    ok, msg = submit_quota_request(client_ip)
    return jsonify({"success": ok, "message": msg})


# ── 管理面板（密码保护）──

def login_required(f):
    """装饰器：要求管理员登录。页面路由重定向到登录页，API 路由返回 401"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            # API 路由（/admin/approve, /admin/stats）返回 JSON 401
            if request.path.startswith('/admin/') and request.path != '/admin':
                return jsonify({"error": "未登录", "redirect": "/admin/login"}), 401
            # 页面路由重定向到登录页
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """管理员登录"""
    error = ''
    if request.method == 'POST':
        pw = (request.form.get('password') or '').strip()
        if pw == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        error = '密码错误'
        # 避免暴力破解：延迟一下
        time.sleep(1)
    # 已登录就直接进面板
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    return render_template('login.html', error=error)


@app.route('/admin')
@login_required
def admin_panel():
    """管理面板——查看反馈统计 + 审批配额申请"""
    return render_template('admin.html')


@app.route('/admin/approve', methods=['POST'])
@login_required
def admin_approve():
    """管理员审批配额申请"""
    data = request.get_json() or {}
    request_id = data.get('request_id')
    action = data.get('action', '')
    amount = data.get('amount', 5)

    if not request_id or action not in ('approve', 'reject'):
        return jsonify({"success": False, "error": "参数错误"}), 400

    ok, msg = approve_quota_request(request_id, action, amount)
    return jsonify({"success": ok, "message": msg})


@app.route('/admin/stats')
@login_required
def admin_stats():
    """管理面板数据 API"""
    try:
        db_stats = get_db_stats()
        feedback_stats = get_feedback_stats()
        # ── 自动刷新反馈报告 Markdown ──
        try:
            md = export_feedback_markdown()
            report_path = os.path.join(os.path.dirname(__file__), "feedback_report.md")
            with open(report_path, 'w') as f:
                f.write(md)
        except Exception:
            pass
    except Exception:
        db_stats = {}
        feedback_stats = {}
    # ── 新增监控数据 ──
    try:
        api_stats = get_api_call_stats()
    except Exception:
        api_stats = {}
    try:
        style_exploration = get_style_exploration_stats()
    except Exception:
        style_exploration = {}
    try:
        style_panel = get_style_technique_panel()
    except Exception:
        style_panel = {}
    try:
        knowledge_quality = get_source_quality_map()
    except Exception:
        knowledge_quality = {}

    return jsonify({
        "db": db_stats,
        "feedback": feedback_stats,
        "pending_requests": get_pending_quota_requests(),
        "dislike_reasons": DISLIKE_REASONS,
        "daily_limit": DAILY_LIMIT,
        "active_sessions": len(_sessions),
        "processing": _processing,
        "api_stats": api_stats,
        "style_exploration": style_exploration,
        "style_panel": style_panel,
        "knowledge_quality": knowledge_quality
    })


# ── AI 风格探索日志 ──
@app.route('/api/log-style-exploration', methods=['POST'])
def api_log_style_exploration():
    """记录 AI 自由探索风格名的选取/舍弃决定"""
    try:
        data = request.get_json(force=True)
        style_name = (data.get('style_name') or '').strip()
        decision = (data.get('decision') or '').strip()
        reason = (data.get('reason') or '').strip()
        session_id = (data.get('session_id') or request.remote_addr or '')

        if not style_name:
            return jsonify({"success": False, "error": "style_name 不能为空"}), 400
        if decision not in ('selected', 'rejected'):
            return jsonify({"success": False, "error": "decision 必须是 selected 或 rejected"}), 400

        log_style_exploration(session_id, style_name, decision, reason)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 搜索发现审核（已废弃——搜索已移除）──
@app.route('/admin/promote-exploration', methods=['POST'])
@login_required
def admin_promote_exploration():
    """将 AI 探索到的风格入库为正式风格"""
    data = request.get_json() or {}
    exploration_id = data.get('exploration_id')
    if not exploration_id:
        return jsonify({"success": False, "error": "exploration_id 不能为空"}), 400
    result = promote_exploration_to_style(int(exploration_id))
    return jsonify(result)


@app.route('/admin/delete-exploration', methods=['POST'])
@login_required
def admin_delete_exploration():
    """删除一条 AI 风格探索记录"""
    data = request.get_json() or {}
    exploration_id = data.get('exploration_id')
    if not exploration_id:
        return jsonify({"success": False, "error": "exploration_id 不能为空"}), 400
    ok = delete_exploration(int(exploration_id))
    return jsonify({"success": ok})


# ── 以下为已废弃的搜索发现审核端点（保留兼容性）──
@app.route('/admin/discoveries')
@login_required
def admin_discoveries():
    """获取待审核的搜索发现列表（搜索已移除，返回空）"""
    return jsonify({"discoveries": []})


@app.route('/admin/promote-discovery', methods=['POST'])
@login_required
def admin_promote_discovery():
    """搜索已移除——此端点保留兼容性"""
    return jsonify({"error": "搜索功能已移除，请使用知识库管理"}), 410


@app.route('/admin/delete-discovery', methods=['POST'])
@login_required
def admin_delete_discovery():
    """搜索已移除——此端点保留兼容性"""
    return jsonify({"error": "搜索功能已移除"}), 410


# ── 🆕 新风格入库（AI 发现的风格 → 知识库）──
@app.route('/admin/add-style-to-kb', methods=['POST'])
@login_required
def admin_add_style_to_kb():
    """将 AI 新发现的风格加入知识库。

    POST body: {"session_id": "...", "direction_id": "now|best|creative", "apply": false}
    - 从 session 中提取风格的 photo_guide
    - 在 cross-media-styles/ 下创建 .md 文件
    - 返回 markdown 内容 + knowledge_base.py 代码片段
    - apply=true 时自动追加到 knowledge_base.py
    """
    import re as _re
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    direction_id = data.get('direction_id', '').strip()
    apply_kb = data.get('apply', False)

    if not session_id or not direction_id:
        return jsonify({"error": "缺少 session_id 或 direction_id"}), 400

    # 加载 session
    session = get_session(session_id)
    if not session:
        return jsonify({"error": f"Session 未找到: {session_id}"}), 404

    # 查找方向
    direction = None
    for d in session.get('directions', []):
        if d.get('id') == direction_id:
            direction = d
            break
    if not direction:
        return jsonify({"error": f"未找到方向 {direction_id}"}), 404

    style_name = (direction.get('style') or '').strip()
    kb_status = (direction.get('kb_status') or '').strip()
    photo_guide = (direction.get('photo_guide') or '').strip()
    style_brief = direction.get('style_brief', {}) or {}
    style_promise = (direction.get('style_promise') or '').strip()

    if not style_name:
        return jsonify({"error": "方向中无 style 字段"}), 400
    if '已有记录' in kb_status:
        return jsonify({"error": f"风格「{style_name}」已标记为 {kb_status}——不需要入库"}), 400
    if not photo_guide:
        return jsonify({"error": f"风格「{style_name}」无 photo_guide——方向阶段 AI 未生成摄影翻译"}), 400

    # 生成 slug
    slug = _re.sub(r'[^\w\s-]', '', style_name.lower().replace(' ', '-'))
    slug = _re.sub(r'[-\s]+', '-', slug).strip('-') or f"style-{date.today().isoformat()}"

    # 构建 one_liner
    sb_parts = []
    if style_brief.get('essence'):
        sb_parts.append(style_brief['essence'])
    if style_promise:
        sb_parts.append(style_promise)
    one_liner = '。'.join(sb_parts) if sb_parts else style_name

    # 生成 markdown
    today = date.today().isoformat()
    md_content = f"""---
id: KB-CMS-AUTO-{today}
domain: cross-media-styles
tags: [{style_name}, AI发现, 待验证]
level: basic
status: ai_discovered
source: [AI 自由探索发现, guidepic.cn session={session_id}]
---

# {style_name}

## 媒介源头

**AI 自由探索发现。** {style_brief.get('essence', style_promise)}

## 一句话识别

{one_liner}

## 色彩

{style_brief.get('color', '（从 photo_guide 提取）')}

## 光线

{style_brief.get('light', '（从 photo_guide 提取）')}

## 构图

{style_brief.get('composition', '（从方案实践中提取）')}

## 前期可操作技法（AI 翻译——待验证）

{photo_guide}

## 情绪氛围

{style_brief.get('mood', '（待补充）')}

---
> 采集日期：{today} | via AI 自由探索 · guidepic.cn
> 状态：待验证——管理员审核后可提升为 mvp
"""

    # 写入文件
    cms_dir = os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', 'daipai', 'knowledge', 'cross-media-styles')
    cms_dir = os.path.abspath(cms_dir)
    os.makedirs(cms_dir, exist_ok=True)
    md_path = os.path.join(cms_dir, f"{slug}.md")

    file_action = 'created'
    if os.path.exists(md_path):
        file_action = 'overwritten'

    with open(md_path, 'w') as f:
        f.write(md_content)

    # 生成 knowledge_base.py 代码片段
    one_liner_entry = f'    "{style_name}": "{one_liner}",'
    pg_escaped = photo_guide.replace('"""', '\\"\\"\\"')
    photo_params_entry = f'''    "{style_name}": """**{style_name} · 摄影可执行参数**
{pg_escaped}
📎 技法锚点：（人工审核后补充）""",'''

    kb_snippet = f"""
# === 添加到 CROSS_MEDIA_STYLE_ONE_LINERS（"老钱静奢" 之后）===
{one_liner_entry}

# === 添加到 CROSS_MEDIA_PHOTO_PARAMS（"奶油风" 条目之后）===
{photo_params_entry}
"""

    # 可选：自动应用到 knowledge_base.py
    kb_updated = False
    if apply_kb:
        kb_py = os.path.join(os.path.dirname(__file__), 'knowledge_base.py')
        if os.path.exists(kb_py):
            with open(kb_py, 'r') as f:
                kb_content = f.read()

            # 追加 one_liner
            marker = '"老钱静奢":'
            if marker in kb_content and style_name not in kb_content[:kb_content.find('CROSS_MEDIA_PHOTO_PARAMS')]:
                lines = kb_content.split('\n')
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if marker in line:
                        new_lines.append(f'    "{style_name}": "{one_liner}",')
                kb_content = '\n'.join(new_lines)

            # 追加 PHOTO_PARAMS
            marker2 = '📎 技法锚点：日系清新（米白奶咖+柔和到无阴影+高明度低对比）"""'
            if marker2 in kb_content:
                insert_pos = kb_content.find(marker2) + len(marker2) + 4  # after """,
                kb_content = kb_content[:insert_pos] + '\n' + photo_params_entry.replace('}}', '') + kb_content[insert_pos:]
                kb_updated = True

            if kb_updated:
                with open(kb_py, 'w') as f:
                    f.write(kb_content)

    return jsonify({
        "success": True,
        "style_name": style_name,
        "slug": slug,
        "md_path": md_path,
        "file_action": file_action,
        "md_content": md_content,
        "kb_snippet": kb_snippet,
        "kb_updated": kb_updated,
        "next_steps": [
            f"1. 审核 {md_path} 的内容",
            "2. 手动补充「构图」「穿搭」等章节",
            "3. 将 kb_snippet 中的代码添加到 knowledge_base.py（如未自动应用）",
            "4. git commit + push 部署"
        ]
    })


# ── 数据导入（本地 → 生产同步）──
@app.route('/admin/import-data', methods=['POST'])
@login_required
def admin_import_data():
    """导入风格和技法数据（用于本地→生产数据同步）"""
    import sqlite3
    data = request.get_json() or {}
    styles = data.get('styles', [])
    techniques = data.get('techniques', [])
    imported_styles = 0
    imported_techniques = 0

    try:
        db = sqlite3.connect(DB_PATH)
        for s in styles:
            db.execute('''INSERT OR REPLACE INTO styles (name, one_liner, source_type, fit_rationale, created_at, updated_at, verify_count)
                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                       (s['name'], s.get('one_liner'), s.get('source_type', 'inference'),
                        s.get('fit_rationale'), s.get('created_at'), s.get('updated_at'), s.get('verify_count', 1)))
            imported_styles += 1
        for t in techniques:
            db.execute('''INSERT OR REPLACE INTO techniques (name, source_type, description, created_at, updated_at, verify_count)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (t['name'], t.get('source_type', 'tutorial'),
                        t.get('description'), t.get('created_at'), t.get('updated_at'), t.get('verify_count', 1)))
            imported_techniques += 1
        db.commit()
        db.close()
        return jsonify({"success": True, "imported_styles": imported_styles, "imported_techniques": imported_techniques})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin/knowledge-files')
@login_required
def admin_knowledge_files():
    """返回指定质量分类的知识库文件详情，支持下钻审核"""
    quality = request.args.get('quality', '')
    valid = {'verified', 'real_world', 'ai_inferred', 'ai_generated'}
    qf = quality if quality in valid else None
    files = get_knowledge_files_by_quality(qf)
    dist = {"verified": 0, "real_world": 0, "ai_inferred": 0, "ai_generated": 0}
    for f in files:
        dist[f["quality"]] = dist.get(f["quality"], 0) + 1
    return jsonify({"files": files, "distribution": dist, "filter": quality or "all"})


@app.route('/admin/export-data')
@login_required
def admin_export_data():
    """导出风格和技法数据（JSON）"""
    import sqlite3
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        styles = [dict(r) for r in db.execute('SELECT name, one_liner, source_type, fit_rationale, created_at, updated_at, verify_count FROM styles').fetchall()]
        techniques = [dict(r) for r in db.execute('SELECT name, source_type, description, created_at, updated_at, verify_count FROM techniques').fetchall()]
        db.close()
        return jsonify({"styles": styles, "techniques": techniques})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 配额状态查询 ──
@app.route('/quota-status')
def quota_status():
    """查询当前 IP 的用量和申请状态"""
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '127.0.0.1'
    usage = get_daily_usage(client_ip)
    req_status = get_quota_request_status(client_ip)
    return jsonify({
        "used": usage['used'],
        "extra": usage['extra'],
        "limit": DAILY_LIMIT,
        "effective_limit": DAILY_LIMIT + usage['extra'],
        "request_status": req_status
    })


@app.route('/api/restore/<session_id>')
def restore_session(session_id):
    """精简恢复——返回 session 中已有的分析结果"""
    sess = get_session(session_id)
    if not sess:
        return jsonify({"ok": False, "error": "会话已过期"}), 404
    # 重新计算 source_tags（KB 查证）
    source_tags = {}
    for d in sess.get('directions', []):
        style_name = d.get('style', '')
        if style_name:
            try:
                kb_detail = get_style_detail(style_name)
                if kb_detail and '来源：知识库' in kb_detail:
                    source_tags[d['id']] = '📚 有据可查'
                elif kb_detail and '跨媒介' in kb_detail:
                    source_tags[d['id']] = '📚 跨媒介参考'
                else:
                    source_tags[d['id']] = '🤖 AI 探索'
            except Exception:
                source_tags[d['id']] = '🤖 AI 探索'
        else:
            source_tags[d.get('id', '')] = '🤖 AI 探索'

    return jsonify({"ok": True, "data": {
        "img_b64": sess.get('img_b64', ''),
        "exif_data": sess.get('exif_data', {}),
        "vision_json": sess.get('vision_json', {}),
        "insight": sess.get('insight', ''),
        "scene_tier": sess.get('scene_tier', '🥈'),
        "directions": sess.get('directions', []),
        "fold_details": sess.get('fold_details', {}),
        "source_tags": source_tags,
        "techniques_used": sess.get('techniques_used', []),
        "search_quality": sess.get('search_quality'),
        "device_key": sess.get('device_key', ''),
        "device_context": sess.get('device_context', {}),
        "plan_cache": sess.get('plan_cache', {}),
        "scene_mode": sess.get('scene_mode', "")
    }})


if __name__ == '__main__':
    import socket

    # ── 启动时自动迁移 JSON→SQLite + 应用 Claude 端同步数据 ──
    try:
        json_path = os.path.join(os.path.dirname(__file__), "style_cache.json")
        if os.path.exists(json_path) and not os.path.exists(DB_PATH):
            print("[Init] Migrating style_cache.json → SQLite...", file=sys.stderr, flush=True)
            migrate_from_json(json_path)
        applied = apply_pending_sync()
        if applied:
            print(f"[Init] Applied {applied} pending sync items from Claude", file=sys.stderr, flush=True)
        # 知识库种子数据（首次启动写入 styles/techniques 表）
        seeded = seed_from_knowledge_base()
        if seeded:
            print(f"[Init] Seeded {seeded} styles/techniques from knowledge_base", file=sys.stderr, flush=True)
        # 实战技法种子（社交媒体验证的高频场景技法）
        practical_seeded = seed_practical_techniques()
        if practical_seeded:
            print(f"[Init] Seeded {practical_seeded} practical techniques from social media patterns", file=sys.stderr, flush=True)
        # 拍照姿势技法种子（Valenzuela/Barnbaum 教材）
        posing_seeded = seed_posing_techniques()
        if posing_seeded:
            print(f"[Init] Seeded {posing_seeded} posing techniques from textbooks", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[Init] Migration/sync error (non-fatal): {e}", file=sys.stderr, flush=True)

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    print(f"""
╔══════════════════════════════════════════╗
║       带拍 · 移动端测试工具 ║
║                                          ║
║  手机浏览器访问:                          ║
║  → http://{local_ip}:8888          ║
║                                          ║
║  确保手机和电脑在同一 WiFi 网络            ║
║  按 Ctrl+C 停止服务器                     ║
║                                          ║
║  方案重构 + 图生图 + 环境感知 + 监控 ║
╚══════════════════════════════════════════╝
    """)

    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
