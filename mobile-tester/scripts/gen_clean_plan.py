"""
生成 "仅 Layer 1 标注" 的干净方案图。
标注：九宫格 + 主体定位圈 + 光线方向渐变 + 底部状态栏
不在照片上写任何文字标注、箭头、地面标记。
"""
import os, sys
sys.path.insert(0, '/Users/rabbit/Claude code/Photography/mobile-tester')
from dotenv import load_dotenv
load_dotenv()

import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Config ──────────────────────────────────────────
SRC = "/tmp/test_7971.jpg"  # HEIC converted via sips
OUT = "/Users/rabbit/Claude code/Photography/mobile-tester/static/plan_v4_clean.jpg"
MOBILE_W = 1290  # 3x mobile screen width (390*3 for retina clarity)

# Subject positions (based on scene analysis)
# Person: left third, dog: right third
SUBJECTS = [
    {"label": "人物", "xy": (0.30, 0.45), "r": 0.08, "color": (245, 158, 11)},   # gold
    {"label": "宠物", "xy": (0.65, 0.72), "r": 0.06, "color": (245, 158, 11)},   # gold
]

# ── Load & resize ───────────────────────────────────
img = Image.open(SRC).convert("RGB")
w, h = img.size
scale = MOBILE_W / w
new_h = int(h * scale)
img = img.resize((MOBILE_W, new_h), Image.LANCZOS)
W, H = img.size
print(f"Canvas: {W}x{H}")

# ── Font setup ──────────────────────────────────────
font_paths = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
title_font = None
for fp in font_paths:
    try:
        title_font = ImageFont.truetype(fp, 32)
        break
    except:
        continue
if title_font is None:
    title_font = ImageFont.load_default()

# ── Layer 1: Light direction gradient ───────────────
# Warm light from upper-left (based on scene analysis: soft side lighting)
light = Image.new("RGBA", (W, H), (0, 0, 0, 0))
light_draw = ImageDraw.Draw(light)

# Radial gradient from upper-left: warm golden glow
for i in range(30):
    alpha = int(25 * (1 - i / 30))  # fade from 25 to 0
    r = int(W * 0.3 * (i + 1) / 30)
    cx, cy = int(W * 0.2), int(H * 0.15)
    light_draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(255, 200, 120, alpha),
    )

# Vignette: darken edges slightly
vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
v_draw = ImageDraw.Draw(vignette)
for i in range(20):
    alpha = int(40 * (1 - i / 20))
    margin = int(min(W, H) * 0.02 * i)
    v_draw.rectangle(
        [margin, margin, W - margin, H - margin],
        outline=(0, 0, 0, alpha),
        width=int(min(W, H) * 0.04),
    )

# ── Layer 2: Composition grid (rule of thirds) ──────
grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
g_draw = ImageDraw.Draw(grid)
GRID_COLOR = (255, 255, 255, 40)  # white, 15% opacity
GRID_LINE = 2

# Vertical thirds
for i in [1, 2]:
    x = int(W * i / 3)
    g_draw.line([(x, 0), (x, H)], fill=GRID_COLOR, width=GRID_LINE)

# Horizontal thirds
for i in [1, 2]:
    y = int(H * i / 3)
    g_draw.line([(0, y), (W, y)], fill=GRID_COLOR, width=GRID_LINE)

# ── Layer 3: Subject positioning circles ────────────
subjects = Image.new("RGBA", (W, H), (0, 0, 0, 0))
s_draw = ImageDraw.Draw(subjects)

for subj in SUBJECTS:
    cx = int(subj["xy"][0] * W)
    cy = int(subj["xy"][1] * H)
    r = int(subj["r"] * W)
    color = subj["color"]
    label = subj["label"]

    # Outer glow ring
    for i in range(4):
        glow_r = r + 6 + i * 3
        glow_alpha = 80 - i * 20
        s_draw.ellipse(
            [cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
            outline=(*color, glow_alpha),
            width=2,
        )

    # Main circle
    s_draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=(*color, 180),
        width=3,
    )

    # Dashed inner ring effect: crosshair dots at 4 corners
    dot_r = 3
    for angle in [0, 90, 180, 270]:
        rad = math.radians(angle)
        dx = int(r * 0.7 * math.cos(rad))
        dy = int(r * 0.7 * math.sin(rad))
        s_draw.ellipse(
            [cx + dx - dot_r, cy + dy - dot_r, cx + dx + dot_r, cy + dy + dot_r],
            fill=(*color, 200),
        )

    # Label with pill background
    label_w = 60
    label_h = 28
    label_x = cx + r + 14
    label_y = cy - label_h // 2
    # Semi-transparent dark pill
    s_draw.rounded_rectangle(
        [label_x, label_y, label_x + label_w, label_y + label_h],
        radius=8,
        fill=(8, 8, 12, 210),
    )
    # Text
    s_draw.text(
        (label_x + 8, label_y + 4),
        label,
        fill=(*color, 255),
        font=title_font,
    )

# ── Layer 4: Bottom status bar ──────────────────────
bar_h = 56
bar = Image.new("RGBA", (W, bar_h), (0, 0, 0, 0))
b_draw = ImageDraw.Draw(bar)

# Gradient dark bar at bottom
b_draw.rectangle([(0, 0), (W, bar_h)], fill=(0, 0, 0, 140))

# Left: scheme indicator
b_draw.text((20, 14), "📷 方案 1/2", fill=(200, 200, 200, 255), font=title_font)

# Right: scheme name
b_draw.text((W - 200, 14), "人宠互动特写", fill=(245, 158, 11, 255), font=title_font)

# ── Composite ───────────────────────────────────────
result = img.copy()
result = Image.alpha_composite(result.convert("RGBA"), light)
result = Image.alpha_composite(result, vignette)
result = Image.alpha_composite(result, grid)
result = Image.alpha_composite(result, subjects)

# Paste bottom bar
result.paste(bar, (0, H - bar_h), bar)

# Convert back to RGB for JPEG
result = result.convert("RGB")
result.save(OUT, "JPEG", quality=92)
print(f"Saved: {OUT}")
print(f"Size: {result.size}")
