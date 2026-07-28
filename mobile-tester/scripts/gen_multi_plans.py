"""
生成多景别/多角度的干净方案标注图。
每一张图一个方案，标注自适应景别：
- 远景：水平线 + 主体区域 + 引导线 + 光线
- 全景：网格 + 定位圈 + 光线
- 中景：网格 + 精确定位圈 + 光线质感
- 近景：仅光线质感（网格无用）
"""
import math
import os, sys
sys.path.insert(0, '/Users/rabbit/Claude code/Photography/mobile-tester')
from PIL import Image, ImageDraw, ImageFont

SRC = "/tmp/test_7971.jpg"
OUT_DIR = "/Users/rabbit/Claude code/Photography/mobile-tester/static"
MOBILE_W = 1290

# ── Fonts ───────────────────────────────────────────
def load_font(size):
    for fp in ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        try: return ImageFont.truetype(fp, size)
        except: pass
    return ImageFont.load_default()

FONT_TITLE = load_font(32)
FONT_SMALL = load_font(24)

# ── Helpers ─────────────────────────────────────────
def draw_light_gradient(draw, W, H, direction='upper-left', warmth='warm'):
    """Light direction as semi-transparent radial gradient."""
    if warmth == 'warm':
        base = (255, 200, 120)
    else:
        base = (200, 210, 255)

    positions = {
        'upper-left':  (0.20, 0.15),
        'upper-right': (0.80, 0.12),
        'back':        (0.50, 0.50),  # backlight from center
        'side-left':   (0.05, 0.40),
    }
    cx_r, cy_r = positions.get(direction, (0.20, 0.15))
    cx, cy = int(W * cx_r), int(H * cy_r)

    for i in range(30):
        alpha = int(25 * (1 - i / 30))
        r = int(W * 0.35 * (i + 1) / 30)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*base, alpha))

def draw_grid(draw, W, H):
    """Rule of thirds grid, subtle."""
    color = (255, 255, 255, 38)
    for i in [1, 2]:
        x = int(W * i / 3)
        draw.line([(x, 0), (x, H)], fill=color, width=2)
        y = int(H * i / 3)
        draw.line([(0, y), (W, y)], fill=color, width=2)

def draw_subject_circle(draw, W, H, cx_r, cy_r, r_r, label, color=(245,158,11)):
    """Draw a subject positioning circle with label pill."""
    cx, cy = int(W * cx_r), int(H * cy_r)
    r = int(W * r_r)

    # Glow
    for i in range(3):
        gr = r + 5 + i * 3
        draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
                     outline=(*color, 70 - i * 20), width=2)
    # Main ring
    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                 outline=(*color, 170), width=3)
    # Corner dots
    dot_r = 3
    for angle in [0, 90, 180, 270]:
        rad = math.radians(angle)
        dx = int(r * 0.7 * math.cos(rad))
        dy = int(r * 0.7 * math.sin(rad))
        draw.ellipse([cx + dx - dot_r, cy + dy - dot_r,
                      cx + dx + dot_r, cy + dy + dot_r], fill=(*color, 200))

    # Label pill
    tw = 60; th = 28
    lx = cx + r + 14; ly = cy - th // 2
    draw.rounded_rectangle([lx, ly, lx + tw, ly + th], radius=8, fill=(8,8,12,210))
    draw.text((lx + 8, ly + 4), label, fill=(*color, 255), font=FONT_TITLE)

def draw_horizon_line(draw, W, H, y_r, color=(255,255,255,50)):
    """Horizontal reference line."""
    y = int(H * y_r)
    draw.line([(0, y), (W, y)], fill=color, width=2)
    # Small tick marks at ends
    tick = 20
    draw.line([(tick, y - 6), (tick, y + 6)], fill=color, width=2)
    draw.line([(W - tick, y - 6), (W - tick, y + 6)], fill=color, width=2)

def draw_leading_line(draw, W, H, points, color=(255,255,255,50)):
    """Highlight an existing leading line in the photo."""
    pts = [(int(W * x), int(H * y)) for x, y in points]
    for i in range(3):  # glow layers
        draw.line(pts, fill=(*color[:3], color[3] // 3), width=4 + i * 2)

def draw_crop_mask(draw, W, H, keep_region, label=""):
    """Darken areas outside keep_region (left_r, top_r, right_r, bottom_r)."""
    l, t, r, b = keep_region
    lx, tx = int(W * l), int(H * t)
    rx, bx = int(W * r), int(H * b)
    # Top bar
    if tx > 0: draw.rectangle([(0, 0), (W, tx)], fill=(0,0,0,60))
    # Bottom bar
    if bx < H: draw.rectangle([(0, bx), (W, H)], fill=(0,0,0,60))
    # Left bar
    if lx > 0: draw.rectangle([(0, tx), (lx, bx)], fill=(0,0,0,60))
    # Right bar
    if rx < W: draw.rectangle([(rx, tx), (W, bx)], fill=(0,0,0,60))

def draw_bottom_bar(draw, W, H, plan_num, plan_name, color=(245,158,11)):
    """Bottom status bar on image."""
    bar_h = 56
    y0 = H - bar_h
    draw.rectangle([(0, y0), (W, H)], fill=(0,0,0,140))
    draw.text((20, y0 + 14), f"📷 方案 {plan_num}", fill=(200,200,200,255), font=FONT_TITLE)
    tw = FONT_TITLE.getbbox(plan_name)[2] if hasattr(FONT_TITLE, 'getbbox') else len(plan_name) * 18
    draw.text((W - tw - 30, y0 + 14), plan_name, fill=color, font=FONT_TITLE)

def vignette(draw, W, H, strength=40):
    """Darken edges for vignette effect."""
    for i in range(20):
        alpha = int(strength * (1 - i / 20))
        m = int(min(W, H) * 0.02 * i)
        draw.rectangle([m, m, W - m, H - m], outline=(0,0,0,alpha),
                       width=int(min(W, H) * 0.04))

# ── Plan Definitions ─────────────────────────────────
PLANS = [
    {
        "id": "plan1",
        "name": "中景互动",
        "num": "1/4",
        "color": (245, 158, 11),
        "light_dir": "upper-left",
        "light_warmth": "warm",
        "annotations": ["grid", "subjects", "light", "vignette"],
        "subjects": [
            {"xy": (0.32, 0.48), "r": 0.07, "label": "人物", "color": (245,158,11)},
            {"xy": (0.63, 0.73), "r": 0.05, "label": "宠物", "color": (245,158,11)},
        ],
        "crop": None,
        "horizon": None,
        "leading_lines": None,
    },
    {
        "id": "plan2",
        "name": "全景氛围",
        "num": "2/4",
        "color": (34, 211, 238),
        "light_dir": "upper-left",
        "light_warmth": "warm",
        "annotations": ["grid", "subjects", "light", "vignette", "horizon", "leading_lines"],
        "subjects": [
            {"xy": (0.28, 0.55), "r": 0.04, "label": "人宠", "color": (34,211,238)},
        ],
        "horizon": 0.52,
        "leading_lines": [[(0.05, 0.95), (0.30, 0.65), (0.50, 0.52)]],
        "crop": None,
    },
    {
        "id": "plan3",
        "name": "近景特写",
        "num": "3/4",
        "color": (167, 139, 250),
        "light_dir": "side-left",
        "light_warmth": "warm",
        "annotations": ["subjects", "light", "vignette"],
        "subjects": [
            {"xy": (0.35, 0.42), "r": 0.10, "label": "人物", "color": (167,139,250)},
            {"xy": (0.60, 0.68), "r": 0.06, "label": "狗", "color": (167,139,250)},
        ],
        "crop": (0.02, 0.08, 0.98, 0.82),
        "horizon": None,
        "leading_lines": None,
    },
    {
        "id": "plan4",
        "name": "侧面角度",
        "num": "4/4",
        "color": (74, 222, 128),
        "light_dir": "upper-right",
        "light_warmth": "warm",
        "annotations": ["grid", "subjects", "light", "vignette", "horizon"],
        "subjects": [
            {"xy": (0.45, 0.50), "r": 0.06, "label": "人物", "color": (74,222,128)},
            {"xy": (0.70, 0.72), "r": 0.05, "label": "宠物", "color": (74,222,128)},
        ],
        "horizon": 0.48,
        "crop": None,
        "leading_lines": None,
    },
]

# ── Render ───────────────────────────────────────────
img = Image.open(SRC).convert("RGB")
w, h = img.size
scale = MOBILE_W / w
new_h = int(h * scale)
img = img.resize((MOBILE_W, new_h), Image.LANCZOS)
W, H = img.size
print(f"Canvas: {W}x{H}")

for plan in PLANS:
    base = img.copy().convert("RGBA")

    # Layer stack
    light_layer = Image.new("RGBA", (W, H), (0,0,0,0))
    ldr = ImageDraw.Draw(light_layer)
    grid_layer = Image.new("RGBA", (W, H), (0,0,0,0))
    gdr = ImageDraw.Draw(grid_layer)
    subj_layer = Image.new("RGBA", (W, H), (0,0,0,0))
    sdr = ImageDraw.Draw(subj_layer)
    vign_layer = Image.new("RGBA", (W, H), (0,0,0,0))
    vdr = ImageDraw.Draw(vign_layer)

    annotations = plan["annotations"]

    if "light" in annotations:
        draw_light_gradient(ldr, W, H, plan["light_dir"], plan.get("light_warmth", "warm"))
    if "grid" in annotations:
        draw_grid(gdr, W, H)
    if "subjects" in annotations:
        for subj in plan["subjects"]:
            draw_subject_circle(sdr, W, H, subj["xy"][0], subj["xy"][1],
                               subj["r"], subj["label"], subj["color"])
    if "vignette" in annotations:
        vignette(vdr, W, H)
    if "horizon" in annotations and plan.get("horizon"):
        draw_horizon_line(sdr, W, H, plan["horizon"])
    if "leading_lines" in annotations and plan.get("leading_lines"):
        for pts in plan["leading_lines"]:
            draw_leading_line(sdr, W, H, pts)
    if "crop" in annotations and plan.get("crop"):
        draw_crop_mask(sdr, W, H, plan["crop"])

    # Bottom bar
    bar = Image.new("RGBA", (W, H), (0,0,0,0))
    bdr = ImageDraw.Draw(bar)
    draw_bottom_bar(bdr, W, H, plan["num"], plan["name"], plan["color"])

    # Composite
    result = base
    result = Image.alpha_composite(result, light_layer)
    result = Image.alpha_composite(result, grid_layer)
    result = Image.alpha_composite(result, subj_layer)
    result = Image.alpha_composite(result, vign_layer)
    result = Image.alpha_composite(result, bar)

    out_path = os.path.join(OUT_DIR, f"plan_v4_{plan['id']}.jpg")
    result.convert("RGB").save(out_path, "JPEG", quality=90)
    print(f"  → {out_path} ({result.size})")

print("Done! 4 plans generated.")
