#!/usr/bin/env python3
"""
带拍 · 移动端测试工具 v3.6
在电脑上启动后，手机浏览器访问 http://<电脑IP>:8888
拍照上传 → 渐进式展示（EXIF→场景→方向→方案按需生成）→ Canvas 标注 → 生图提示词
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
from knowledge_base import get_all_knowledge_for_prompt, get_style_detail, get_device_adaptation
from search_web import search_style_inspiration, search_location_intel
from database import accumulate, query_scene_context, get_db_stats, migrate_from_json, export_for_claude, import_from_claude, apply_pending_sync, check_and_increment_usage, get_daily_usage, submit_quota_request, get_quota_request_status, get_pending_quota_requests, approve_quota_request, save_usage_session, update_usage_session, save_feedback, get_feedback_stats, export_feedback_markdown, DISLIKE_REASONS, DB_PATH, log_api_call, log_search, get_api_call_stats, get_search_stats, get_style_technique_panel

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ============================================================
# 配置
# ============================================================
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "daipai2026")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
EXIF_SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude/skills/daipai/scripts/exif-extract.py")
STYLE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "style_cache.json")
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "10"))  # 每人每天免费次数
MAX_IMAGE_DIM = 2048  # 上传前压缩到最长边2048px，加快上传
VISION_IMAGE_DIM = 1024  # 给豆包视觉用的更小尺寸——场景分析不需要高分辨率，省一半时间
REQUEST_TIMEOUT = 300  # 含大图上传时间
SESSION_TTL = 1800  # 30分钟

# 并发控制
_processing_lock = threading.Lock()
_processing = False

# 方案生成并发控制——防止重复 LLM 调用（retry/poll 同时来时只生成一次）
_plan_generating: dict[str, float] = {}  # key: global_cache_key → started_at_timestamp
_plan_generating_lock = threading.Lock()

# Session 存储
_sessions: dict[str, dict] = {}

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
  "location_clues": "从画面识别位置线索。检查：招牌文字、建筑风格/颜色、地标轮廓、植被类型、山形地貌、室内装修风格、菜单/包装/标识。能推断具体场所就写场所名（如'太舞滑雪场山顶餐厅后方观景台'），只能到城区级就写级别，完全无法识别写'无法识别'"
}

只输出JSON，不要任何额外文字。不要markdown代码块包裹。"""

# ============================================================
# 方向生成 Prompt（不含方案，方案按需另行生成）
# ============================================================
DIRECTIONS_PROMPT = """你是带拍的摄影知识引擎。用户是普通人，想要"发朋友圈好看"的照片。

## 视觉分析
{vision_json}

## EXIF数据
{exif_summary}

{exif_cross_check}
## 设备信息
{device_context}

{style_context}

## 📚 带拍专业知识库
{knowledge_context}

{search_context}

{fast_path_note}

{env_context}

## 工作流程

### Step 0: 环境约束感知
根据环境上下文调整风格策略：
- 黄金时刻剩<30分钟 → 🔥最出片优先推荐立刻可拍的风格，标注时间窗口
- 未来有降雨 → 自动避开需阳光直射的硬光风格，标注"建议30分钟内完成"
- 夜间 → 自动推荐夜景/灯光/闪光可用风格
- 即将蓝调时刻 → ✨脑洞大开可推荐"等蓝调时刻拍"的方案
- AI亮度评估=不足 → 推荐暗光风格，标注稳定需求；❌不要给需快速快门的方案
- AI亮度评估=充足或一般 → 正常推荐，不瞎报"光线弱"
- 识别到具体场所 → 风格推荐中融入场所特异性
	- 运动场地（球场/跑道/泳池/冰场/健身房）→ 风格选择必须考虑运动属性：
	  动态抓拍、动作瞬间、场地线条构图、运动装备色彩点缀。
	  ❌不要推静态摆拍风格（如"安静真实""日系清新"纯摆拍变体）
	  ✅动感纪实、运动人像、广角冲击力、高速连拍选片思路

### Step 1: 场景观察 + 等级评估

读视觉分析，沉浸进去。找画面里最具体的一个细节说出来——
可以是一束光、一个眼神、一个颜色、一个意外发现。

insight: 1-2句话，像小红书发照片时的配文：
  - 具体——有能指出的东西（"树叶的影子刚好落在她肩膀上"）
  - 像说话——用"你看""刚好""其实"这类自然语气
  - 不评价——不说"好看""动人""完美""太美了"
  - 不强凑——一句话说清楚就不用硬写两句
  - 可以承认意外——"拍完才发现..."

  ❌ 空洞： "午后阳光营造出温暖慵懒的氛围，构图的平衡与光线的层次相得益彰"
  ✅ 好的： "刚好有一束光从窗帘缝里漏进来，在桌上画了一道线"
           "你看她的影子——比真人还好看"
           "拍完才发现那只猫一直在画面角落盯着镜头"

scene_tier: 🥉一般 / 🥈不错 / 🥇丰富（内部使用，控制方案数量，不展示给用户）

场景等级判定：
🥉 一般场景（普通客厅/随手拍/信息量少/光线平淡/空间浅）
🥈 不错场景（有光线/构图/情绪亮点/空间层次中）
🥇 丰富场景（空间深/光线有戏剧性/人物状态好/元素密集）

### Step 2: 风格发现
基于光线（软/硬/方向）×题材（人像/环境/静物）×情绪（从场景色彩和人物状态推断），匹配最佳风格方向。从摄影风格知识中选择匹配度最高的，诚实标注光线和设备可执行性。

每个风格标注：
- fit_rationale: 为什么适合
- light_annotation: 🟢完美/🟡可模拟/🔴需等待
- device_annotation: 🟢直接拍/🟡微调/🟠替代方案
- source_type: community/tutorial/portfolio/inference

### Step 3: 方向卡片

三个方向：
🟢 现在就拍 — 零门槛，站在这就能拍。每个场景必有
🔥 最出片 — 高辨识度，社交验证加分。有才出
✨ 脑洞大开 — 摄影的可能性，最酷的视角。有才出

## 🚨 重要：本次只生成方向卡片
每个方向的 plans 必须是空数组 []。具体方案将在用户选择方向后另行生成。
reason 字段应该足够详细，让用户理解为什么推荐这个方向（80-120字）。

## 🚨 两道追问（每个方向生成后立刻自问）
□ 叙事完整性：这个方向有清晰的视觉叙事吗？
□ 调性统一度：色调/影调/质感在风格框架内吗？
不通过 → 修正后再输出。

## 🚨 约束
- EXIF交叉：ISO≥800但视觉说"明亮"→采信EXIF；闪光灯触发→修正光质；快门<1/60→标注稳定支撑
- 口吻：朋友分享观察，❌摄影术语 ❌"我"第一人称 ✅"你"视角
- 风格翻译：style必须使用中文风格名（如"安静真实""日系清新""胶片复古"），style_promise翻译为效果语言（"干净透亮，像日剧里的画面"）。禁止英文风格名如"casual_pet_daily""minimal_warm"。
- style_promise 必须是视觉效果描述——画面里能看到的东西。❌禁止社交验证话术（如"发出去会被问在哪拍的""朋友圈会被赞""小红书爆款""让人羡慕"）。✅好的例子："暖黄光从侧面打过来，头发丝是金色的""逆光下整个人像在发光，背景化成一片模糊的绿""干净得像刚下过雨，空气都是透明的"。
- name_source 诚实标注风格名的来源：
  · discovered = 中文名来自以下任一来源，不需要翻译：
    a) 搜索结果中直接获得
    b) 💡 知识库已有风格名（日系清新/电影感/胶片复古/极简高级/纪实粗粝/杂志时尚/梦幻柔美/Lofi直闪/县城记忆/安静真实/Grunge脏感/微观微距/便利店美学/港风复古/森系/法式慵懒/新中式）——这些是中文摄影圈的成熟词汇，属于discovered
    c) 摄影师风格名（如滨田英明风/川内伦子风/Saul Leiter风/Crewdson式）
  · translated = 搜索到的英文风格名（如"Moody Landscape""Golden Hour Portrait"），由AI翻译为中文
  · generated = 不属于以上两类——搜索结果为空且不是知识库已有风格名，AI完全基于摄影原理自创的中文风格名（如"清冷森系""暗调都市叙事"这类从没在摄影圈出现过的名字）
- 长度：insight≤60字 reason≤120字 how≤50字

## 输出格式

严格JSON，不要markdown包裹。directions 必须是 ARRAY 不是 OBJECT：

{{
  "insight": "1-2句话，小红书配文风格",
  "scene_tier": "🥉/🥈/🥇",
  "directions": [
    {{
      "id": "now", "emoji": "🟢", "label": "现在就拍", "subtitle": "零门槛，站在这就能拍",
      "style": "内部风格名", "style_promise": "效果语言翻译",
      "reason": "推荐理由（80-120字，说明为什么匹配这个场景和设备）",
      "how": "一句话操作概述",
      "source_note": "来源标注",
      "fit_rationale": "为什么适合这个场景",
      "light_annotation": "🟢/🟡/🔴",
      "device_annotation": "🟢直接拍/🟡微调/🟠替代方案",
      "source_type": "community/tutorial/portfolio/inference",
      "name_source": "discovered/translated/generated",
      "plans": []
    }},
    {{
      "id": "best", "emoji": "🔥", "label": "最出片", "subtitle": "发出去会被赞的那种",
      "style": "", "style_promise": "", "reason": "", "how": "", "source_note": "",
      "fit_rationale": "", "light_annotation": "", "device_annotation": "", "source_type": "", "name_source": "",
      "plans": []
    }},
    {{
      "id": "creative", "emoji": "✨", "label": "脑洞大开", "subtitle": "不像游客照的视角",
      "style": "", "style_promise": "", "reason": "", "how": "", "source_note": "",
      "fit_rationale": "", "light_annotation": "", "device_annotation": "", "source_type": "", "name_source": "",
      "plans": []
    }}
  ],
  "search_quality": {{"overall": "🟢/🟡/🔴", "honest_note": ""}},
  "discovered_styles": [{{"name":"","source_type":"","fit_rationale":"","light_annotation":"","device_annotation":""}}],
  "techniques_used": [{{"name":"","source_type":"","description":""}}]
}}

🔥和✨没有实质内容时，除id/emoji/label/subtitle外全为null，plans为空数组。至少一个有实质内容。
directions 必须是数组 []，不是对象 {{}}——v2 OBJECT格式会崩溃！"""


# ============================================================
# 方案生成 Prompt（按需调用，用户选完方向后）
# ============================================================
PLANS_PROMPT = """你是带拍的摄影知识工程师。为已选定的风格方向生成具体拍摄方案。

## 场景信息
{vision_json}

## 设备信息
{device_context}

## 📚 风格知识参考
{style_knowledge}

## 📚 设备适配参考
{device_knowledge}

## 已选方向
{emoji} {label}
风格：{style}
效果承诺：{style_promise}
推荐理由：{reason}
操作概述：{how}

## 场景等级：{scene_tier}

## 方案数量硬约束（严格执行，不准超过）
{tier_constraint}

## 方案差异变化层次
- 2-3套：必须用不同的主要变化手段（姿态变化 / 景别变化 / 角度变化）
- 4+套：主要+次要（构图变化 / 光线利用变化）组合使用
- 不强凑——场景给不出那么多就诚实少给

## 🚨 场景锚定（最高优先级——与设备约束同级）
场景信息中的每个细节都是方案的素材。每套方案必须严格锚定场景：
- subject 的位置/动作必须引用 space.anchors 的具体物体——"站网球网右侧""靠在窗边沙发左扶手"
- shooter 的位置必须引用 space.anchors——"退到对面底线铁网后""蹲在门口盆栽旁边"
- 如果在运动场地（球场/跑道/泳池/冰场等）→ 方案必须融入该运动的典型动作或场地特有构图
  （挥拍瞬间、发球姿态、球网作前景虚化、底线低角度仰拍、利用场地线条引导视线）
- 如果在特定场所（咖啡馆/书店/地铁/展馆）→ 利用该场所的设计元素做构图
- 至少1个方案必须有"只有这个场景才有的专属元素"——换了地方这个方案就不成立

## 🚨 设备约束（最高优先级——每套方案的 where/do 必须遵守）
{device_constraints}

## 🌤 环境上下文（辅助约束）
{env_context}

在写 shooter 和 gear 时，必须逐一检查：
- 如果设备没有长焦镜头 → 不能写"用长焦压缩空间""拉近拍"
- 如果设备没有超广角 → 不能写"超广角低角度仰拍"
- 如果设备是定焦 → 所有方案用同一焦段思考，靠走位变化
- iPhone 人像模式可用时 → 可以写"用人像模式虚化背景"，但要标注
- 发挥设备优势，规避设备限制——这才是真正可执行的方案

## 每套方案的字段

① name: 方案名——能让人记住的，"让阳光给你打光"不是"方案1"
② prep: 要准备什么——"什么都不用准备，站过去就行"
③ subject: 被拍摄者——有人物必写，无人物为空
   给"做一件事"的指令，不说"摆造型""摆姿势"
   包含：站/坐的具体位置（引用 anchors）、身体重心、手部任务、
         眼神方向、表情触发（不说"笑"，给动作触发）
   2-3句话，纯动作语言
④ shooter: 摄影师——每套必写
   包含：站哪个位置（引用 space.anchors 的具体元素）、
         离多远、什么高度（平视/蹲下/高处俯拍）、什么角度
   必须考虑设备焦段限制
   2-3句话
⑤ gear: 设备调试——每套必写
   包含：用哪个焦段、对焦点在哪、曝光补偿怎么调、
         是否用人像模式/闪光灯
   基于当前设备的实际能力，不需要特别操作就写"全自动就行"
   1-2句话
⑥ enhance: 增色技巧——可选，有真正能增色的想法才写
   包含：打光建议、现场道具利用、服装/发型调整、
         滤镜方向、后期思路、AI处理想法
   不强凑，没有就诚实不写
   1-3句话
⑦ result: 拍出来——效果预览，用效果语言
⑧ why: 为什么好看——摄影原理，2-3句
⑨ annotations: 视觉标注——只标注文字说不精确的，1-2个，最多3个：
   - subject: 被摄者位置 {{"type":"subject","x":0.35,"y":0.72,"label":"站这","color":"#4ade80"}}
   - shooter: 拍摄者站位 {{"type":"shooter","from":{{"x":0.05,"y":0.85}},"to":{{"x":0.4,"y":0.5}},"angle":"蹲下·45°仰拍","color":"#4ade80"}}
   - frame: 取景范围，加w/h字段
   - crop: 裁剪建议，加w/h字段
   - color: #4ade80(绿)/#f59e0b(金)/#a78bfa(紫)
⑩ perspective: 换个思路——有真正差异才写，可选
⑪ img_gen_prompt: 豆包图生图提示词——每套必写（⚠️ 图生图模式）

   这是图生图提示词——用户会上传原图作为参考图，豆包需要基于原图生成调整后的画面。

   🚨 图生图核心原则：
   - 开头必写"参考上传的照片，保持[人物特征]和[场景环境]不变"
   - 然后写"做以下调整："逐项列出姿势、机位、光线的变化
   - 风格用视觉特征描述，不堆砌风格标签
   - 禁止写相机品牌型号参数（Canon/85mm/f1.4/iPhone）——用视觉语言描述透视和景别
   - ≤300 汉字，中文完整句式，禁止否定描述
   - 末尾统一加：无文字、无水印、无签名、自然肤质、真实摄影感

   图生图模板：
   ```
   参考上传的照片，保持人物的面部特征、发型、[从vision分析提取的服装描述]不变，
   保持[从vision分析提取的场景关键元素]不变。

   做以下调整：
   - 人物：[subject字段内容——新姿势/表情/眼神]
   - 机位：[shooter字段内容——拍摄位置/高度/角度，用视觉语言写]
   - 光线：[光线方向+光质+特殊光影效果，用视觉语言写]
     [如有enhance字段的打光建议，融入光线描述]

   画面风格：[风格名]——[具体视觉特征：色调/影调/质感/颗粒感，2-3个可感知的视觉属性]
   景别与空间：[用视觉语言描述距离感和空间关系，不写焦段数字]

   无文字、无水印、无签名、自然肤质、真实摄影感
   ```

   参考示例：
   "参考上传的照片，保持人物的面部特征、发型、白色卫衣和牛仔裤不变，
    保持客厅灰色沙发和落地窗的场景环境不变。

    做以下调整：
    - 人物：站起来走到落地窗边，侧身靠窗框，右手拿马克杯垂在腰旁，
      脸转向窗外看外面的树，嘴唇自然闭合
    - 机位：退到电视柜旁边，蹲下到胸口高度，低角度往窗户方向仰拍
    - 光线：午后阳光从左侧窗外斜照进来，在头发边缘形成金色轮廓光，
      窗边白墙作为天然反光板给脸部补柔光

    画面风格：日系清新——明亮通透，低饱和度，阴影偏蓝，柔和高光过渡
    景别与空间：中景构图，人物占据画面三分之二，背景窗外虚化成绿色光斑

    无文字、无水印、无签名、自然肤质、真实摄影感"

## 🚨 两道追问（每套方案生成后立刻自问——不通过不输出）
□ 叙事完整性：这套方案有清晰的视觉叙事吗？→ 不是机械指令
□ 调性统一度：色调/影调/质感在风格框架内吗？→ 森系不能配高反差黑白
不通过 → 修正后再输出。修不了 → 诚实跳过这套。

## 🚨 约束
- 场景锚点：subject/shooter 必须引用视觉分析 space.anchors 中的具体元素，不得使用通用描述
- 口吻：朋友分享观察，❌摄影术语 ❌"我"第一人称 ✅"你"视角
- result 必须是画面视觉预览——拍出来能看到什么。❌禁止社交验证话术（"发朋友圈会被赞""小红书同款""让人羡慕""被问在哪拍的"）。✅好的例子："整个人被暖光包住，头发丝是金色的，背景化成一片奶油色的模糊"
- 长度：prep≤50字 subject 2-3句 shooter 2-3句 gear 1-2句 enhance 1-3句 result 2-3句 why 2-3句

## 输出格式

严格JSON，只输出 plans 数组。不要markdown包裹。

{{
  "plans": [
    {{
      "name": "", "prep": "", "subject": "", "shooter": "", "gear": "",
      "enhance": "", "result": "", "why": "", "annotations": [], "perspective": "",
      "img_gen_prompt": ""
    }}
  ]
}}"""


# ============================================================
# 风格缓存（本地 JSON 积累，越用越聪明）
# ============================================================

def load_style_cache():
    """加载风格积累缓存"""
    if os.path.exists(STYLE_CACHE_FILE):
        try:
            with open(STYLE_CACHE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_style_cache(cache):
    """保存风格积累缓存"""
    try:
        with open(STYLE_CACHE_FILE, 'w') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[StyleCache] Save failed: {e}", file=sys.stderr, flush=True)


def accumulate_styles(scene_type, discovered_styles, techniques_used):
    """积累发现的风格和技法到本地缓存"""
    if not scene_type:
        return

    cache = load_style_cache()
    if scene_type not in cache:
        cache[scene_type] = {'styles': [], 'techniques': [], 'count': 0}

    entry = cache[scene_type]

    for s in (discovered_styles or []):
        name = s.get('name', '').strip()
        if not name:
            continue
        existing = next((x for x in entry['styles'] if x['name'] == name), None)
        if existing:
            existing['count'] = existing.get('count', 1) + 1
            existing['source_type'] = s.get('source_type', existing.get('source_type', ''))
        else:
            entry['styles'].append({
                'name': name,
                'source_type': s.get('source_type', ''),
                'fit_rationale': s.get('fit_rationale', '')[:200],
                'count': 1
            })

    for t in (techniques_used or []):
        name = t.get('name', '').strip()
        if not name:
            continue
        existing = next((x for x in entry['techniques'] if x['name'] == name), None)
        if existing:
            existing['count'] = existing.get('count', 1) + 1
            existing['source_type'] = t.get('source_type', existing.get('source_type', ''))
        else:
            entry['techniques'].append({
                'name': name,
                'source_type': t.get('source_type', ''),
                'description': t.get('description', '')[:200],
                'count': 1
            })

    entry['count'] += 1
    save_style_cache(cache)
    print(f"[StyleCache] Accumulated to '{scene_type}': {len(entry['styles'])} styles, {len(entry['techniques'])} techniques (total {entry['count']} sessions)",
          file=sys.stderr, flush=True)


def get_style_context(scene_type):
    """获取同类型场景的历史积累，注入 prompt"""
    if not scene_type:
        return ""

    cache = load_style_cache()
    # 模糊匹配：找最相似的 scene_type
    best_key = None
    for key in cache:
        # 简单关键词重叠匹配
        if scene_type in key or key in scene_type:
            best_key = key
            break
    if not best_key:
        # 尝试匹配第一个词（如 "室外" 匹配 "室外公园"）
        first_word = scene_type.split('·')[0].split('—')[0].strip()
        for key in cache:
            if first_word and first_word in key:
                best_key = key
                break

    if not best_key:
        return ""

    entry = cache[best_key]
    top_styles = sorted(entry['styles'], key=lambda x: x['count'], reverse=True)[:5]
    top_techniques = sorted(entry['techniques'], key=lambda x: x['count'], reverse=True)[:5]

    if not top_styles and not top_techniques:
        return ""

    ctx = f"\n## 📚 历史积累（同类型场景「{best_key}」的风格发现，共{entry['count']}次分析）\n"
    if top_styles:
        ctx += "### 过往匹配的风格\n"
        for s in top_styles:
            ctx += f"- {s['name']}（{s['source_type']}, 使用{s['count']}次）\n"
    if top_techniques:
        ctx += "### 过往使用的技法\n"
        for t in top_techniques:
            ctx += f"- {t['name']}（{t['source_type']}, 使用{t['count']}次）\n"
    ctx += "\n可以参考以上积累，但不强制使用。如果场景特征不匹配，忽略即可。\n"

    return ctx


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

def create_session(vision_json, exif_summary, device_key, device_context, directions, scene_tier, client_ip=None, env_context="", session_id=None):
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
        'env_context': env_context
    }
    _cleanup_old_sessions()
    return session_id


def get_session(session_id):
    """获取会话，自动清理过期"""
    sess = _sessions.get(session_id)
    if not sess:
        return None
    if time.time() - sess['created_at'] > SESSION_TTL:
        del _sessions[session_id]
        return None
    return sess


def _cleanup_old_sessions():
    """清理过期会话"""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s['created_at'] > SESSION_TTL]
    for sid in expired:
        del _sessions[sid]


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


def call_doubao(messages, max_tokens=2000, call_type='unknown', session_id=None):
    """调用豆包 API，自动记录调用日志"""
    import time as time_mod
    t0 = time_mod.time()
    usage = {}
    success = 1
    result = None
    try:
        payload = {
            "model": DOUBAO_MODEL,
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
            log_api_call(session_id or '', call_type, DOUBAO_MODEL,
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


def parse_json_safe(content, retry_prompt=None):
    """安全解析 JSON。先尝试直接解析，失败后本地修复，再失败才 API retry"""
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


# ============================================================
# 流式分析生成器（v3.5：渐进式——EXIF→场景→方向，方案按需）
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
        style_context = query_scene_context(scene_type)

        # ── EXIF 交叉验证（v4.0）──
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

        # ── 知识库注入（v4.0 统一知识源）──
        knowledge_context = get_all_knowledge_for_prompt(
            scene_type=scene_type,
            device_key=final_device_key,
            light_condition=json.dumps(vision_json.get('light', {}), ensure_ascii=False)
        )
        print(f"[SSE] Knowledge context: {len(knowledge_context)} chars", file=sys.stderr, flush=True)

        # ── 🌐 Web 搜索（社区验证，v4.0）──
        search_context = ""
        search_quality_web = "🔴"
        people_info = vision_json.get('people', '')
        try:
            # 风格搜索（最多 6 秒）
            t_search = time.time()
            search_text, search_quality_web, search_meta = search_style_inspiration(
                scene_type, people_info
            )
            search_duration = int((time.time() - t_search) * 1000)
            if search_text:
                search_context = search_text
                print(f"[Search] Style search: {len(search_text)} chars, quality={search_quality_web}", file=sys.stderr, flush=True)
            # 记录搜索日志
            try:
                source_types_str = ','.join(f"{k}:{v}" for k, v in search_meta.get('sources', {}).items())
                log_search(trace_id, 'style', scene_type[:200],
                          search_meta.get('total_results', 0) if isinstance(search_meta, dict) else 0,
                          search_quality_web, source_types_str, search_duration,
                          results_summary=search_text[:500] if search_text else None)
            except Exception:
                pass
        except Exception as e:
            print(f"[Search] Style search failed: {e}", file=sys.stderr, flush=True)
            try:
                log_search(trace_id, 'style', scene_type[:200], 0, '🔴', '', 0)
            except Exception:
                pass

        # 位置搜索（优先用豆包识别的具体场所，fallback Nominatim 城市名）
        loc_clues = vision_json.get('location_clues', '') if isinstance(vision_json, dict) else ''
        search_place = None
        if loc_clues and loc_clues != '无法识别' and len(loc_clues) >= 3:
            search_place = loc_clues
            print(f"[Search] Using vision location_clues: {loc_clues}", file=sys.stderr, flush=True)
        elif location_weather and location_weather.get('place'):
            search_place = location_weather['place']

        if search_place:
            try:
                t_loc = time.time()
                loc_text, loc_quality = search_location_intel(
                    search_place, scene_type
                )
                loc_duration = int((time.time() - t_loc) * 1000)
                if loc_text:
                    search_context += "\n" + loc_text
                    print(f"[Search] Location search: {len(loc_text)} chars, quality={loc_quality}, place={search_place[:60]}", file=sys.stderr, flush=True)
                # 记录搜索日志
                try:
                    log_search(trace_id, 'location', search_place[:200],
                              len(loc_text.split('\n')) if loc_text else 0,
                              loc_quality, '', loc_duration,
                              results_summary=loc_text[:500] if loc_text else None)
                except Exception:
                    pass
            except Exception as e:
                print(f"[Search] Location search failed: {e}", file=sys.stderr, flush=True)
                try:
                    log_search(trace_id, 'location', search_place[:200], 0, '🔴', '', 0)
                except Exception:
                    pass

        # ── 快速路径判断（v4.0）──
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

        if not search_context:
            search_context = "（本次未触发社区搜索——场景匹配主要基于专业知识库推理。）\n"

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

        directions_prompt = DIRECTIONS_PROMPT.format(
            vision_json=json.dumps(vision_json, ensure_ascii=False, indent=2),
            exif_summary=exif_summary,
            exif_cross_check=exif_cross_check,
            device_context=device_text,
            style_context=style_context,
            knowledge_context=knowledge_context,
            search_context=search_context,
            fast_path_note=fast_path_note,
            env_context=env_context
        )
        print(f"[SSE] Directions prompt: {len(directions_prompt)} chars", file=sys.stderr, flush=True)
        directions_content, directions_usage = call_doubao([
            {"role": "user", "content": directions_prompt}
        ], max_tokens=4000, call_type='directions', session_id=trace_id)
        print(f"[SSE] Directions API done: {directions_usage.get('total_tokens','?')} tokens", file=sys.stderr, flush=True)

        # 解析方向输出
        directions_json, directions_error = parse_json_safe(
            directions_content,
            retry_prompt="你上次的输出不是有效JSON。请重新输出，只输出纯JSON对象，不要markdown包裹，不要任何额外文字。directions 必须是数组 []。"
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
        discovered_styles = directions_json.get('discovered_styles', [])
        techniques_used = directions_json.get('techniques_used', [])
        search_quality = directions_json.get('search_quality', {})

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
            env_context=env_context
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

        # ── 风格积累（异步不影响响应）──
        try:
            accumulate(scene_type, discovered_styles, techniques_used)
        except Exception as e:
            print(f"[StyleCache] Accumulate error: {e}", file=sys.stderr, flush=True)

        # ── 发送方向结果给前端 ──
        yield emit("directions_ready", {
            "insight": insight,
            "scene_tier": scene_tier,
            "directions": directions,
            "search_quality": search_quality,
            "discovered_styles": discovered_styles,
            "techniques_used": techniques_used,
            "session_id": session_id
        })

        # ── 保存恢复数据到 session（用户误关后可找回）──
        sess = _sessions.get(session_id)
        if sess:
            sess['img_b64'] = img_b64
            sess['exif_data'] = exif_display
            sess['insight'] = insight
            sess['discovered_styles'] = discovered_styles
            sess['techniques_used'] = techniques_used
            sess['search_quality'] = search_quality

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

def generate_plans_for_direction(session_id, direction_id, device_override=None, lens_key=None):
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
        return session['plan_cache'][cache_key], None

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

    # 构建 prompt
    style_knowledge = get_style_detail(direction.get('style', '')) or ""
    device_knowledge = get_device_adaptation(device_key) or ""

    plans_prompt = PLANS_PROMPT.format(
        vision_json=json.dumps(session['vision_json'], ensure_ascii=False, indent=2),
        device_context=device_text,
        style_knowledge=style_knowledge,
        device_knowledge=device_knowledge,
        emoji=direction.get('emoji', ''),
        label=direction.get('label', ''),
        style=direction.get('style', ''),
        style_promise=direction.get('style_promise', ''),
        reason=direction.get('reason', ''),
        how=direction.get('how', ''),
        scene_tier=session['scene_tier'],
        tier_constraint=tier_constraint,
        device_constraints=device_constraints,
        env_context=session.get('env_context', '')
    )

    print(f"[Plans] Prompt: {len(plans_prompt)} chars, direction={direction_id}, device={device_key}", file=sys.stderr, flush=True)

    try:
        plans_content, plans_usage = call_doubao([
            {"role": "user", "content": plans_prompt}
        ], max_tokens=4000, call_type='plans', session_id=session_id)  # v4.1: 6000→4000，实际输出很少超4000

        plans_json, plans_error = parse_json_safe(
            plans_content,
            retry_prompt="你上次的输出不是有效JSON。请重新输出，只输出包含 plans 数组的纯JSON对象。"
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
                p.setdefault('img_gen_prompt', '')

        # 缓存
        session['plan_cache'][cache_key] = plans
        print(f"[Plans] Generated {len(plans)} plans, cached as {cache_key}", file=sys.stderr, flush=True)

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
    """流式分析上传的照片（SSE）—— v3.5: 渐进式 EXIF→场景→方向"""
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

    # 正常模式：触发 LLM 生成（可能耗时 30-90 秒，移动网络 NAT 可能断开）
    plans, error = generate_plans_for_direction(session_id, direction_id, device_override, lens_key)

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


# ── v3.5: 处理中状态查询（前端排队轮询）──
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


# ── v3.5: 方案反馈 ──
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


# ── v3.5: 配额申请 ──
@app.route('/request-quota', methods=['POST'])
def request_quota():
    """申请更多使用次数"""
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '127.0.0.1'
    ok, msg = submit_quota_request(client_ip)
    return jsonify({"success": ok, "message": msg})


# ── v3.5: 管理面板（v3.6: 密码保护）──

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
    # ── v3.6 新增监控数据 ──
    try:
        api_stats = get_api_call_stats()
    except Exception:
        api_stats = {}
    try:
        search_stats = get_search_stats()
    except Exception:
        search_stats = {}
    try:
        style_panel = get_style_technique_panel()
    except Exception:
        style_panel = {}

    return jsonify({
        "db": db_stats,
        "feedback": feedback_stats,
        "pending_requests": get_pending_quota_requests(),
        "dislike_reasons": DISLIKE_REASONS,
        "daily_limit": DAILY_LIMIT,
        "active_sessions": len(_sessions),
        "processing": _processing,
        "api_stats": api_stats,
        "search_stats": search_stats,
        "style_panel": style_panel
    })


# ── v3.6: 数据导入（本地 → 生产同步）──
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


# ── v3.5: 配额状态查询 ──
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
    return jsonify({"ok": True, "data": {
        "img_b64": sess.get('img_b64', ''),
        "exif_data": sess.get('exif_data', {}),
        "vision_json": sess.get('vision_json', {}),
        "insight": sess.get('insight', ''),
        "scene_tier": sess.get('scene_tier', '🥈'),
        "directions": sess.get('directions', []),
        "discovered_styles": sess.get('discovered_styles', []),
        "techniques_used": sess.get('techniques_used', []),
        "search_quality": sess.get('search_quality'),
        "device_key": sess.get('device_key', ''),
        "device_context": sess.get('device_context', {}),
        "plan_cache": sess.get('plan_cache', {})
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
    except Exception as e:
        print(f"[Init] Migration/sync error (non-fatal): {e}", file=sys.stderr, flush=True)

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    print(f"""
╔══════════════════════════════════════════╗
║       带拍 · 移动端测试工具 v3.6      ║
║                                          ║
║  手机浏览器访问:                          ║
║  → http://{local_ip}:8888          ║
║                                          ║
║  确保手机和电脑在同一 WiFi 网络            ║
║  按 Ctrl+C 停止服务器                     ║
║                                          ║
║  v3.6: 方案重构 + 图生图 + 环境感知 + 监控 ║
╚══════════════════════════════════════════╝
    """)

    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
