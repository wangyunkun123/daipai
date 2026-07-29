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
from PIL import Image, ImageOps, ImageDraw, ImageFont
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, session, redirect, url_for
from knowledge_base import get_all_knowledge_for_prompt, get_style_detail, get_device_adaptation, get_source_quality_map, get_knowledge_files_by_quality
from search_web import search_style_inspiration, search_location_intel
from database import accumulate, query_scene_context, query_scene_techniques_for_plans, get_db_stats, migrate_from_json, export_for_claude, import_from_claude, apply_pending_sync, check_and_increment_usage, get_daily_usage, submit_quota_request, get_quota_request_status, get_pending_quota_requests, approve_quota_request, save_usage_session, update_usage_session, save_feedback, get_feedback_stats, export_feedback_markdown, DISLIKE_REASONS, DB_PATH, log_api_call, log_search, get_api_call_stats, get_search_stats, get_style_technique_panel, extract_scene_category, seed_from_knowledge_base, seed_practical_techniques, seed_posing_techniques, get_pending_discoveries, promote_search_to_technique

# ═══════════════════════════════════════════════════════════
# v5: 增强方案图生成（PIL）
# ═══════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


def _get_plan_img_dir():
    d = os.path.join(os.path.dirname(__file__), "static", "plan_images")
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass
    return d

def _load_font(size):
    for fp in ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/PingFang.ttc",
               "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        try: return ImageFont.truetype(fp, size)
        except: pass
    return ImageFont.load_default()

def generate_plan_image(photo_path, plan, plan_index, output_key):
    """Generate an enhanced plan image with visual overlays.
    Returns the URL path relative to /static/, or None on failure."""
    try:
        img = Image.open(photo_path).convert("RGB")
    except Exception:
        return None

    W, H = img.size
    # Resize for mobile: width = 750 (2x of 375px, fits 390-430px screens)
    MOBILE_W = 750
    scale = MOBILE_W / W
    img = img.resize((MOBILE_W, int(H * scale)), Image.LANCZOS)
    W, H = img.size

    font_lg = _load_font(26)
    font_md = _load_font(20)
    font_sm = _load_font(16)

    color = (245, 158, 11)  # gold default
    name = plan.get('name', f'方案{plan_index+1}')
    shot_size = plan.get('shot_size', '')
    angle = plan.get('angle', '')
    annotations = plan.get('annotations', [])
    color_map = {'#4ade80': (74,222,128), '#f59e0b': (245,158,11), '#a78bfa': (167,139,250)}

    base = img.copy().convert("RGBA")
    light_l = Image.new("RGBA", (W, H), (0,0,0,0))
    grid_l  = Image.new("RGBA", (W, H), (0,0,0,0))
    subj_l  = Image.new("RGBA", (W, H), (0,0,0,0))
    vign_l  = Image.new("RGBA", (W, H), (0,0,0,0))
    frame_l = Image.new("RGBA", (W, H), (0,0,0,0))
    badge_l = Image.new("RGBA", (W, H), (0,0,0,0))
    bar_l   = Image.new("RGBA", (W, H), (0,0,0,0))

    ld = ImageDraw.Draw(light_l)
    gd = ImageDraw.Draw(grid_l)
    sd = ImageDraw.Draw(subj_l)
    vd = ImageDraw.Draw(vign_l)
    fd = ImageDraw.Draw(frame_l)
    bd = ImageDraw.Draw(badge_l)
    bad = ImageDraw.Draw(bar_l)

    # ── Light gradient ──
    cx_l, cy_l = int(W*0.2), int(H*0.15)
    for i in range(30):
        a = int(22*(1-i/30))
        r = int(W*0.35*(i+1)/30)
        ld.ellipse([cx_l-r, cy_l-r, cx_l+r, cy_l+r], fill=(255,200,120,a))

    # ── Grid ──
    gc = (255,255,255,55)
    for i in [1,2]:
        x = int(W*i/3); gd.line([(x,0),(x,H)], fill=gc, width=2)
        y = int(H*i/3); gd.line([(0,y),(W,y)], fill=gc, width=2)

    # ── Vignette ──
    for i in range(20):
        a = int(38*(1-i/20)); m = int(min(W,H)*0.02*i)
        vd.rectangle([m,m,W-m,H-m], outline=(0,0,0,a), width=int(min(W,H)*0.04))

    # ── Subjects ──
    bar_h = 36  # bottom bar height, used for clamping subject labels
    for ann in annotations:
        if ann.get('type') == 'subject':
            c = color_map.get(ann.get('color',''), color)
            cx = int(W * ann.get('x', 0.5))
            cy = int(H * ann.get('y', 0.5))
            r  = int(W * ann.get('r', 0.06))
            label = ann.get('label', '')
            for i in range(3):
                gr = r+5+i*3; sd.ellipse([cx-gr,cy-gr,cx+gr,cy+gr], outline=(*c,80-i*20), width=2)
            sd.ellipse([cx-r,cy-r,cx+r,cy+r], outline=(*c,210), width=4)
            for a_deg in [0,90,180,270]:
                rad = math.radians(a_deg); dx=int(r*0.7*math.cos(rad)); dy=int(r*0.7*math.sin(rad))
                sd.ellipse([cx+dx-4,cy+dy-4,cx+dx+4,cy+dy+4], fill=(*c,220))
            if label:
                try:
                    bb = sd.textbbox((0,0), label, font=font_md); tw=bb[2]-bb[0]; th=bb[3]-bb[1]
                except: tw=len(label)*18; th=22
                px,py=14,8; lw=tw+px; lh=th+py
                lx=cx+r+10; ly=cy-lh//2
                if lx+lw>W-16: lx=cx-r-lw-10
                bar_top=H-bar_h
                if ly+lh>bar_top-8: ly=bar_top-lh-8
                if ly<8: ly=8
                sd.rounded_rectangle([lx,ly,lx+lw,ly+lh], radius=7, fill=(8,8,12,225))
                sd.text((lx+px//2,ly+py//2), label, fill=(*c,255), font=font_md)

    # ── Shot frame ──
    frame_ann = next((a for a in annotations if a.get('type')=='frame'), None)
    if frame_ann:
        l = int(W*frame_ann.get('l',0.05)); t=int(H*frame_ann.get('t',0.05))
        r = int(W*frame_ann.get('r',0.95)); b=int(H*frame_ann.get('b',0.85))
        dark=(0,0,0,55)
        if t>0: fd.rectangle([(0,0),(W,t)], fill=dark)
        if b<H: fd.rectangle([(0,b),(W,H)], fill=dark)
        if l>0: fd.rectangle([(0,t),(l,b)], fill=dark)
        if r<W: fd.rectangle([(r,t),(W,b)], fill=dark)
        fc=(*color,110); fd.rectangle([(l,t),(r,b)], outline=fc, width=3)
        bk=36; bkc=(*color,200)
        fd.line([(l,t),(l+bk,t)], fill=bkc, width=4)
        fd.line([(l,t),(l,t+bk)], fill=bkc, width=4)
        fd.line([(r-bk,t),(r,t)], fill=bkc, width=4)
        fd.line([(r,t),(r,t+bk)], fill=bkc, width=4)
        fd.line([(l,b-bk),(l,b)], fill=bkc, width=4)
        fd.line([(l,b),(l+bk,b)], fill=bkc, width=4)
        fd.line([(r-bk,b),(r,b)], fill=bkc, width=4)
        fd.line([(r,b-bk),(r,b)], fill=bkc, width=4)
        flabel = shot_size if shot_size else '取景'
        try: fb=fd.textbbox((0,0),flabel,font=font_md); fw=fb[2]-fb[0]; fh=fb[3]-fb[1]
        except: fw=len(flabel)*18; fh=22
        fp=16; flw=fw+fp; flh=fh+10
        flx=l+(r-l)//2-flw//2; fly=t+10
        fd.rounded_rectangle([flx,fly,flx+flw,fly+flh], radius=8, fill=(*color,160))
        fd.text((flx+fp//2,fly+5), flabel, fill=(0,0,0,255), font=font_md)

    # ── Badges ──
    badges = []
    if shot_size: badges.append((shot_size, color))
    if angle: badges.append((angle, (180,180,190)))
    bx0, by0 = 16, 16
    for btext, bclr in badges:
        try: bb=bd.textbbox((0,0),btext,font=font_sm); bw=bb[2]-bb[0]; bh=bb[3]-bb[1]
        except: bw=len(btext)*16; bh=18
        bpad=16; btw=bw+bpad; bth=bh+10
        bd.rounded_rectangle([bx0,by0,bx0+btw,by0+bth], radius=7, fill=(8,8,12,210))
        bd.text((bx0+bpad//2,by0+5), btext, fill=(*bclr,255), font=font_sm)
        bx0 += btw+8

    # ── Camera position diagram (when angle suggests position change) ──
    angle_l = Image.new("RGBA", (W, H), (0,0,0,0))
    ad = ImageDraw.Draw(angle_l)
    has_angle_change = angle and any(kw in angle for kw in ['仰','俯','侧','低','高','蹲','移','绕','转','背'])
    if has_angle_change:
        box_w, box_h = 160, 100
        bx = W - box_w - 20
        by = H - bar_h - box_h - 16
        ad.rounded_rectangle([bx, by, bx+box_w, by+box_h], radius=10, fill=(8,8,12,200))
        title = "📷 机位移动"
        try:
            tb = ad.textbbox((0,0), title, font=font_sm)
            tw_l = tb[2]-tb[0]
        except: tw_l = len(title)*12
        ad.text((bx + (box_w-tw_l)//2, by+6), title, fill=(200,200,200,255), font=font_sm)
        # Current position (left)
        cur_cx, cur_cy = bx+30, by+55
        ad.ellipse([cur_cx-12, cur_cy-12, cur_cx+12, cur_cy+12], fill=(100,100,110,200))
        ad.text((cur_cx-6, cur_cy-8), "📷", fill=(180,180,180,255), font=font_sm)
        cur_label = "现在"
        try:
            cb2 = ad.textbbox((0,0), cur_label, font=font_sm)
            cw = cb2[2]-cb2[0]
        except: cw = len(cur_label)*12
        ad.text((cur_cx-cw//2, cur_cy+16), cur_label, fill=(120,120,130,255), font=font_sm)
        # Target position (right)
        tgt_cx, tgt_cy = bx+130, by+55
        ad.ellipse([tgt_cx-14, tgt_cy-14, tgt_cx+14, tgt_cy+14], fill=(*color,180))
        ad.text((tgt_cx-6, tgt_cy-8), "📷", fill=(255,255,255,255), font=font_sm)
        tgt_label = angle[:6] if len(angle)>6 else angle
        try:
            tb3 = ad.textbbox((0,0), tgt_label, font=font_sm)
            tw3 = tb3[2]-tb3[0]
        except: tw3 = len(tgt_label)*12
        ad.text((tgt_cx-tw3//2, tgt_cy+16), tgt_label, fill=(*color,255), font=font_sm)
        # Arrow
        arrow_y = cur_cy
        ad.line([(cur_cx+14, arrow_y), (tgt_cx-16, arrow_y)], fill=(*color,150), width=2)
        ax_h = tgt_cx-16
        ad.polygon([(ax_h, arrow_y), (ax_h-8, arrow_y-5), (ax_h-8, arrow_y+5)], fill=(*color,150))

    # ── Bottom bar ──
    y0 = H - bar_h
    bad.rectangle([(0,y0),(W,H)], fill=(0,0,0,140))
    bad.text((20,y0+12), f"📷 {plan_index+1}/{4}", fill=(200,200,200,255), font=font_lg)
    try: bb=bad.textbbox((0,0),name,font=font_lg); nw=bb[2]-bb[0]
    except: nw=len(name)*20
    bad.text((W-nw-24,y0+12), name, fill=color, font=font_lg)

    # ── Composite ──
    result = base
    for layer in [light_l, grid_l, subj_l, vign_l, frame_l, badge_l, angle_l, bar_l]:
        result = Image.alpha_composite(result, layer)
    result = result.convert("RGB")

    out_path = os.path.join(_get_plan_img_dir(), f"{output_key}.jpg")
    if os.path.exists(out_path):
        return f"/static/plan_images/{output_key}.jpg"
    result.save(out_path, "JPEG", quality=88)
    return f"/static/plan_images/{output_key}.jpg"


# ============================================================
# 配置
# ============================================================
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "daipai2026")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
DOUBAO_FAST_MODEL = "doubao-seed-2.0-lite"  # 方案生成用快速模型——结构化JSON不需要最强推理
EXIF_SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude/skills/daipai/scripts/exif-extract.py")
STYLE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "style_cache.json")  # v4.3: 已弃用，保留变量以防旧引用
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "10"))  # 每人每天免费次数
MAX_IMAGE_DIM = 2048  # 上传前压缩到最长边2048px，加快上传
PLAN_IMG_VERSION = 3   # v3: 修复示意图版本不匹配——强制重新生成所有增强图
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

## 📚 专业知识库
{knowledge_context}

{search_context}

{fast_path_note}

{env_context}

## 工作流程

### Step 0: 环境约束
- 黄金时刻剩<30分钟 → 🔥优先推荐立刻可拍的风格
- 有降雨/夜间/AI亮度不足 → 自动调整风格策略，标注注意事项
- 运动场地 → 推动态抓拍/场地线条构图，不推静态摆拍风格
- 识别到具体场所 → 融入场所特异性

### Step 1: 场景观察 + 等级评估
insight: 1-2句话，像小红书配文——具体有画面感、像说话、不空洞评价。
✅"刚好有一束光从窗帘缝里漏进来" ❌"午后阳光营造温暖慵懒的氛围"
scene_tier: 🥉一般/🥈不错/🥇丰富（控制方案数量，不展示给用户）

### Step 2: 方向卡片
三个方向（诚实优先，没想法就跳过🔥和✨）：
🟢 现在就拍 — 零门槛，每个场景必有
🔥 最出片 — 高辨识度，有才出
✨ 脑洞大开 — 最酷视角，有才出

风格标注：fit_rationale, light_annotation(🟢/🟡/🔴), device_annotation(🟢/🟡/🟠), source_type, name_source
三个方向必须不同风格名。无实质内容时除id/emoji/label/subtitle外全null。plans=[]。
reason: 80-120字，让用户理解为什么推荐。insight≤60字 reason≤120字 how≤50字。

### Step 3: 知识收获
discovered_styles: 从搜索中提取新中文风格名（❌已有风格名 ❌英文名），标注source_type/fit_rationale。无→[]
techniques_used: 从搜索中提取可操作技法（不是通用构图法则），标注source_type/description。无→[]

## 约束
- EXIF交叉：ISO≥800但视觉说"明亮"→采信EXIF；闪光灯→修正光质；快门<1/60→标注稳定
- 口吻：朋友分享观察 ✅"你"视角 ❌摄影术语 ❌"我"
- style用中文名，style_promise用视觉描述（❌社交验证话术如"发朋友圈被赞"）
- style_promise ✅"暖黄光从侧面打过来，头发丝是金色的" ❌"小红书爆款"
- name_source: discovered(知识库已有/搜索到/摄影师名)/translated(英文翻译)/generated(AI自创)
- 宁可空数组，不填低质量通用概念

## 输出格式
严格JSON，不要markdown包裹。directions 必须是 ARRAY：

{{
  "insight": "1-2句话，小红书配文风格",
  "scene_tier": "🥉/🥈/🥇",
  "directions": [
    {{
      "id": "now", "emoji": "🟢", "label": "现在就拍", "subtitle": "零门槛，站在这就能拍",
      "style": "风格名", "style_promise": "效果语言翻译",
      "reason": "推荐理由（80-120字）", "how": "一句话操作概述",
      "fit_rationale": "", "light_annotation": "🟢/🟡/🔴",
      "device_annotation": "🟢直接拍/🟡微调/🟠替代方案",
      "source_type": "community/tutorial/portfolio/inference",
      "name_source": "discovered/translated/generated",
      "plans": []
    }},
    {{"id":"best","emoji":"🔥","label":"最出片","subtitle":"发出去会被赞的那种","style":"","style_promise":"","reason":"","how":"","fit_rationale":"","light_annotation":"","device_annotation":"","source_type":"","name_source":"","plans":[]}},
    {{"id":"creative","emoji":"✨","label":"脑洞大开","subtitle":"不像游客照的视角","style":"","style_promise":"","reason":"","how":"","fit_rationale":"","light_annotation":"","device_annotation":"","source_type":"","name_source":"","plans":[]}}
  ],
  "search_quality": {{"overall": "🟢/🟡/🔴", "honest_note": ""}},
  "discovered_styles": [{{"name":"","source_type":"","fit_rationale":"","light_annotation":"","device_annotation":""}}],
  "techniques_used": [{{"name":"","source_type":"","description":""}}]
}}

🔥和✨无实质内容时除id/emoji/label/subtitle外全null。至少一个方向有实质内容。
directions 必须是数组 []，不是对象 {{}}！"""


# ============================================================
# 方案生成 Prompt（按需调用，用户选完方向后）
# ============================================================
PLANS_PROMPT = """你是摄影指导——输出"怎么拍"的拍摄指令。❌不是旅行规划师/活动策划/游记作者。每一句话都必须是拍摄指令。

## 场景信息
{vision_json}

## 🌐 社区搜索参考
{search_context}

## 📚 历史验证技法
{db_techniques}

## 设备信息
{device_context}

## 风格知识
{style_knowledge}

## 设备适配
{device_knowledge}

## 已选方向
{emoji} {label} — 风格：{style}
效果承诺：{style_promise} | 推荐理由：{reason} | 操作概述：{how}

## 场景等级：{scene_tier}
## 方案数量约束：{tier_constraint}

## 🚨 场景锚定（最高优先级）
- subject/shooter 的位置必须引用 space.anchors 的具体物体——"站网球网右侧""蹲在门口盆栽旁"
- 运动场地→融入典型动作和场地构图。特定场所→利用场所设计元素
- 至少1个方案有"只有这个场景才有的专属元素"
- 社区搜索中有真实技法→至少引用1个

## 🚨 设备约束（最高优先级）
{device_constraints}
{env_context}
- 无长焦→不写压缩空间/拉近；无超广角→不写超广角仰拍；定焦→靠走位
- 发挥设备优势，规避限制——这才可执行

## 每套方案字段
① name: 能记住的方案名
② prep: 准备什么（≤50字）
③ subject: 被拍摄者——给"做一件事"的指令（引用anchors，不说"摆造型"），2-3句
④ shooter: 摄影师——站哪/多远/什么高度/角度（考虑设备限制），2-3句
⑤ gear: 设备调试——焦段/对焦/曝光/人像模式（不需要就写全自动），1-2句
⑥ enhance: 增色技巧（可选）——打光/道具/服装/AI处理，1-3句
⑦ result: 拍出来——画面视觉预览（❌社交验证话术），2-3句
⑧ why: 为什么好看——摄影原理，2-3句
⑨ annotations: 视觉标注（最多3个）
   - subject: {{"type":"subject","x":0.35,"y":0.72,"label":"站这","color":"#4ade80"}}
   - shooter: {{"type":"shooter","from":{{"x":0.05,"y":0.85}},"to":{{"x":0.4,"y":0.5}},"angle":"蹲下·45°仰拍","color":"#4ade80"}}
   - frame/crop 可选。color: #4ade80(绿)/#f59e0b(金)/#a78bfa(紫)
⑩ perspective: 换个思路（可选）
⑪ shot_size: 景别（远景/全景/中景/近景/特写）
⑫ angle: 角度（平视/俯拍/仰拍/侧面/背面）
⑬ post_process: 后期建议（1-3项）——先决定后期再写生图提示词！
   每项：{{"cat":"color|fx|ai","label":"调色|特效|AI处理","text":"具体描述"}}
⑭ img_gen_prompt: 图生图提示词（≤300汉字）——豆包Seedream自然语言格式！
   ❌禁止用列表/符号/拍摄术语（"机位""焦段""光圈"）
   ✅用一段流畅中文描述画面变化。公式：变化动作（修改/调整/改为）+变化对象+变化后视觉特征
   
   参考上传的照片，保持人物面部特征和场景环境不变。修改如下：
   · 人物动作表情：[subject的动作姿态+表情+眼神方向+身体朝向，写视觉结果]
     例："侧身倚靠栏杆回头微笑，眼神自然看向镜头，身体略微前倾"
   · 景别与镜头：[shot_size的画面范围+angle的视觉效果，用"镜头从…""画面中人物在…"]
     例："中景画面，低角度仰拍使人物挺拔，人物在画面左侧三分线上"
   · 光线氛围：[enhance的光质+方向+特效，写可见的光影画面效果]
     例："暖金色侧光从左侧斜照，发丝边缘泛起轮廓金光，面部呈现柔和立体过渡"
   · 色调后期：[逐一融入post_process每项的text，写视觉调色结果]
     例："电影感青橙调色，阴影偏冷青灰，高光带暖橙色，叠加轻胶片颗粒"
   画面整体[风格名]氛围，自然肤质，真实摄影感，无文字水印。

## 约束
- 口吻：朋友分享观察 ✅"你"视角 ❌摄影术语 ❌"我"
- result ✅"整个人被暖光包住，头发丝是金色的，背景化成奶油色模糊"
- 长度：prep≤50字 subject/shooter 2-3句 gear 1-2句 result/why 2-3句
- 方案间用不同变化手段（姿态/景别/角度/构图/光线），不强凑

## 输出格式

严格JSON，只输出 plans 数组。不要markdown包裹。

{{
  "plans": [
    {{
      "name": "", "prep": "", "subject": "", "shooter": "", "gear": "",
      "enhance": "", "result": "", "why": "", "annotations": [], "perspective": "",
      "shot_size": "", "angle": "", "post_process": [], "img_gen_prompt": ""
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

def create_session(vision_json, exif_summary, device_key, device_context, directions, scene_tier, client_ip=None, env_context="", search_context="", scene_category="", session_id=None):
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
        'search_context': search_context,
        'scene_category': scene_category
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
        location_clues = vision_json.get('location_clues', '')
        scene_category = extract_scene_category(scene_type, location_clues)
        style_context = query_scene_context(scene_type, category=scene_category)

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

        # ── 🌐 Web 搜索（并行：风格 + 位置，v4.6）──
        search_context = ""
        search_quality_web = "🔴"
        people_info = vision_json.get('people', '')
        loc_clues = vision_json.get('location_clues', '') if isinstance(vision_json, dict) else ''

        # 确定位置搜索词
        search_place = None
        if loc_clues and loc_clues != '无法识别' and len(loc_clues) >= 3:
            search_place = loc_clues
        elif location_weather and location_weather.get('place'):
            search_place = location_weather['place']

        # 并行跑风格搜索 + 位置搜索
        from concurrent.futures import ThreadPoolExecutor as _SearchExecutor
        search_futures = {}
        with _SearchExecutor(max_workers=2) as _search_ex:
            # 风格搜索
            search_futures['style'] = _search_ex.submit(
                search_style_inspiration, scene_type, people_info,
                vision_json.get('primary_subject', '')
            )
            # 位置搜索
            if search_place:
                search_futures['location'] = _search_ex.submit(
                    search_location_intel, search_place, scene_type
                )

        # 收集风格搜索结果
        try:
            t_search = time.time()
            search_text, search_quality_web, search_meta = search_futures['style'].result()
            search_duration = int((time.time() - t_search) * 1000)
            if search_text:
                search_context = search_text
                print(f"[Search] Style search: {len(search_text)} chars, quality={search_quality_web}", file=sys.stderr, flush=True)
            try:
                source_types_str = ','.join(f"{k}:{v}" for k, v in search_meta.get('sources', {}).items())
                log_search(trace_id, 'style', scene_type[:200],
                          search_meta.get('total_results', 0) if isinstance(search_meta, dict) else 0,
                          search_quality_web, source_types_str, search_duration,
                          results_summary=search_text[:500] if search_text else None,
                          keywords_used=','.join(search_meta.get('keywords', [])) if isinstance(search_meta, dict) else '',
                          useful_data=search_meta.get('useful_data', '') if isinstance(search_meta, dict) else '',
                          authenticity=search_meta.get('authenticity', 'unknown') if isinstance(search_meta, dict) else 'unknown')
            except Exception:
                pass
        except Exception as e:
            print(f"[Search] Style search failed: {e}", file=sys.stderr, flush=True)
            try:
                log_search(trace_id, 'style', scene_type[:200], 0, '🔴', '', 0)
            except Exception:
                pass

        # 收集位置搜索结果
        if 'location' in search_futures:
            try:
                loc_text, loc_quality = search_futures['location'].result()
                if loc_text:
                    search_context += "\n" + loc_text
                    print(f"[Search] Location search: {len(loc_text)} chars, quality={loc_quality}, place={search_place[:60]}", file=sys.stderr, flush=True)
                try:
                    log_search(trace_id, 'location', search_place[:200],
                              len(loc_text.split('\n')) if loc_text else 0,
                              loc_quality, '', 0,
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

        # ── 🚨 安全网：过滤搜索上下文中的旅游攻略污染（v4.4）──
        _travel_pollution_kw = [
            "日游", "天游", "行程安排", "旅游攻略", "旅行计划", "住宿推荐",
            "美食推荐", "必吃", "必去景点", "交通指南", "包车", "导游",
            "跟团", "自由行", "周边游", "一日游", "两日游", "三日游",
            "度假村", "温泉酒店", "民宿推荐", "购物指南", "休闲游",
        ]
        _cleaned = search_context
        for _kw in _travel_pollution_kw:
            if _kw in _cleaned:
                _cleaned = "\n".join(
                    line for line in _cleaned.split("\n")
                    if _kw not in line
                )
        if _cleaned != search_context:
            print(f"[Sanitize] Stripped travel pollution from search_context", file=sys.stderr, flush=True)
            search_context = _cleaned

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
        ], max_tokens=2500, call_type='directions', session_id=trace_id)  # 方向输出通常<1500 tokens
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
            env_context=env_context,
            search_context=search_context,
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

        # ── 风格积累（v4.3: 传入搜索真实性，社区验证来源自动加分）──
        try:
            accumulate(scene_type, discovered_styles, techniques_used,
                      scene_category=scene_category,
                      authenticity=search_meta.get('authenticity', 'unknown') if search_meta else 'unknown')
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
        plans = session['plan_cache'][cache_key]
        # v5: 补生成缺失的增强图
        photo_path = session.get('photo_path', '')
        if photo_path and os.path.exists(photo_path):
            for i, p in enumerate(plans):
                if isinstance(p, dict) and p.get('annotations'):
                    cur_img = p.get('plan_image', '')
                    if not cur_img or f'_v{PLAN_IMG_VERSION}_' not in cur_img:
                        img_key = f"{cache_key}_v{PLAN_IMG_VERSION}_{i}"
                        img_url = generate_plan_image(photo_path, p, i, img_key)
                        if img_url:
                            p['plan_image'] = img_url
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

    # 构建 prompt
    style_knowledge = get_style_detail(direction.get('style', '')) or ""
    device_knowledge = get_device_adaptation(device_key) or ""

    # ── v4.2: 查询数据库历史验证技法，注入方案生成 ──
    scene_type = session.get('vision_json', {}).get('scene_type', '')
    scene_category = session.get('scene_category', '')
    db_techniques = query_scene_techniques_for_plans(scene_type, category=scene_category)
    if db_techniques:
        print(f"[Plans] DB techniques: {len(db_techniques)} chars for cat={scene_category}", file=sys.stderr, flush=True)
    else:
        db_techniques = "（同类场景暂无历史验证技法——方案将主要基于知识库推理和社区搜索。）\n"

    plans_prompt = PLANS_PROMPT.format(
        vision_json=json.dumps(session['vision_json'], ensure_ascii=False, indent=2),
        search_context=session.get('search_context', '（无社区搜索数据）'),
        db_techniques=db_techniques,
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
        ], max_tokens=3000, call_type='plans', session_id=session_id, model=DOUBAO_FAST_MODEL)  # 快速模型——结构化方案不需要最强推理

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
                p.setdefault('shot_size', '')
                p.setdefault('angle', '')
                p.setdefault('img_gen_prompt', '')
                p.setdefault('post_process', [])

        # 缓存
        session['plan_cache'][cache_key] = plans
        print(f"[Plans] Generated {len(plans)} plans, cached as {cache_key}", file=sys.stderr, flush=True)

        # ── v5: 生成增强方案图 ──
        photo_path = session.get('photo_path', '')
        if photo_path and os.path.exists(photo_path):
            for i, p in enumerate(plans):
                if isinstance(p, dict) and p.get('annotations'):
                    cur_img = p.get('plan_image', '')
                    if not cur_img or f'_v{PLAN_IMG_VERSION}_' not in cur_img:
                        img_key = f"{cache_key}_v{PLAN_IMG_VERSION}_{i}"
                        img_url = generate_plan_image(photo_path, p, i, img_key)
                        if img_url:
                            p['plan_image'] = img_url
                        print(f"[Plans] Image generated: {img_url}", file=sys.stderr, flush=True)

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

    # prewarm 模式：后台异步生成，立即返回（前端预热用）
    prewarm = data.get('prewarm', False)
    if prewarm:
        global_key = f"{session_id}:{cache_key}"
        with _plan_generating_lock:
            if global_key in _plan_generating:
                return jsonify({"success": True, "prewarm": "already_running"})
            _plan_generating[global_key] = time.time()

        def _prewarm():
            try:
                plans, err = generate_plans_for_direction(session_id, direction_id, device_override, lens_key)
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
        "search_stats": search_stats,
        "style_panel": style_panel,
        "knowledge_quality": knowledge_quality
    })


# ── v4.3: 搜索发现审核 ──
@app.route('/admin/discoveries')
@login_required
def admin_discoveries():
    """获取待审核的搜索发现列表"""
    try:
        discoveries = get_pending_discoveries()
        return jsonify({"discoveries": discoveries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/promote-discovery', methods=['POST'])
@login_required
def admin_promote_discovery():
    """审批通过一个搜索发现，提升为正式技法。支持 auto 模式——从搜索数据自动提取名称和描述。"""
    try:
        data = request.get_json() or {}
        search_log_id = data.get('search_log_id')
        technique_name = data.get('technique_name', '').strip()
        description = data.get('description', '').strip()
        scene_category = data.get('scene_category', '')
        auto_mode = data.get('auto', False)

        if not search_log_id:
            return jsonify({"error": "缺少 search_log_id"}), 400

        # Auto 模式：从搜索数据中自动提取技法和场景分类
        if auto_mode:
            import sqlite3
            db = sqlite3.connect(DB_PATH)
            row = db.execute(
                "SELECT query_text, keywords_used, results_summary, useful_data FROM search_log WHERE id=?",
                (search_log_id,)
            ).fetchone()
            db.close()
            if not row:
                return jsonify({"error": "搜索记录不存在"}), 404

            query_text = row[0] or ''
            keywords = row[1] or ''
            summary = row[2] or ''
            useful = row[3] or ''

            # 自动提取技法名称：从 keywords 中取第一个有意义的词
            if not technique_name:
                kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
                for kw in kw_list:
                    # 跳过场景描述词，取拍摄相关词
                    if any(w in kw for w in ['拍照', '摄影', '技巧', '构图', '姿势', 'pose', '风格']):
                        # 提取主语部分
                        name = kw.replace('拍照','').replace('摄影','').replace('技巧','').replace('构图','').replace('姿势','').strip()
                        if len(name) >= 2 and len(name) <= 30:
                            technique_name = name
                            break
                if not technique_name:
                    # Fallback: 从 query_text 提取
                    technique_name = query_text[:30].split(' ')[0] if query_text else '未命名技法'

            # 自动提取描述：从 summary 取前 120 字
            if not description and summary:
                # 取第一个有意义的结果
                for line in summary.split('\n'):
                    line = line.strip()
                    if line.startswith('- **') or line.startswith('1. **'):
                        # 去掉 markdown 标记
                        desc = line.lstrip('- 0123456789.*# ').strip()
                        if len(desc) >= 10:
                            description = desc[:200]
                            break
                if not description:
                    description = summary[:200]

            # 自动推断场景分类
            if not scene_category:
                q = (query_text + ' ' + keywords).lower()
                mapping = [
                    ('park_nature', ['公园','花园','植物','树','花','草','森林','湖','河','海','山','自然','户外','野外','天空','日落','日出','阳光','风景']),
                    ('urban_street', ['街','路','城市','建筑','楼','广场','桥','巷','弄','市区','马路','交通','车']),
                    ('cultural_site', ['博物馆','美术馆','展览','寺庙','教堂','历史','文化','遗址','古城','古镇','园林','宫殿','塔','钟楼']),
                    ('f_and_b', ['餐厅','咖啡','美食','酒吧','食物','饮料','餐桌','吃饭','奶茶','甜品','饭店','食堂']),
                    ('commercial', ['商场','购物','商店','超市','店铺','零售','品牌','室内','工作室']),
                    ('indoor_home', ['家','客厅','卧室','房间','室内','窗边','阳台','家居','家具','公寓','宿舍']),
                    ('night', ['夜景','夜晚','灯光','霓虹','夜晚','晚上','暗光','夜景']),
                    ('portrait', ['人像','人物','自拍','合影','闺蜜','情侣','朋友','小孩','宠物','猫','狗','动物']),
                ]
                for cat, kws in mapping:
                    if any(kw in q for kw in kws):
                        scene_category = cat
                        break
                if not scene_category:
                    scene_category = 'urban_street'

        if not technique_name:
            return jsonify({"error": "无法自动提取技法名称，请手动输入"}), 400

        ok = promote_search_to_technique(
            search_log_id, technique_name, description,
            source_type='community', scene_category=scene_category, verify_count=3
        )
        return jsonify({"success": ok, "name": technique_name, "category": scene_category})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/delete-discovery', methods=['POST'])
@login_required
def admin_delete_discovery():
    """删除一条搜索发现（不需要的不入库）"""
    try:
        data = request.get_json() or {}
        search_log_id = data.get('search_log_id')
        if not search_log_id:
            return jsonify({"error": "缺少 search_log_id"}), 400
        import sqlite3
        db = sqlite3.connect(DB_PATH)
        db.execute("DELETE FROM search_log WHERE id=?", (search_log_id,))
        db.commit()
        db.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        # v3.8: 知识库种子数据（首次启动写入 styles/techniques 表）
        seeded = seed_from_knowledge_base()
        if seeded:
            print(f"[Init] Seeded {seeded} styles/techniques from knowledge_base", file=sys.stderr, flush=True)
        # v4.2: 实战技法种子（社交媒体验证的高频场景技法）
        practical_seeded = seed_practical_techniques()
        if practical_seeded:
            print(f"[Init] Seeded {practical_seeded} practical techniques from social media patterns", file=sys.stderr, flush=True)
        # v4.3: 拍照姿势技法种子（Valenzuela/Barnbaum 教材）
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
