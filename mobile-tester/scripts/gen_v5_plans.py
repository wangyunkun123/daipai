"""
v5 方案图生成：增加景别框 + 角度指示 + 后期栏 + 生图提示词栏
- 景别框: 白色取景框叠加，框外压暗，框内是目标构图范围
- 角度变化: 画面角落加小型的"相机位置示意"（当前→目标）
- 标签: 左上角景别+角度 badge
"""
import math, os, sys
sys.path.insert(0, '/Users/rabbit/Claude code/Photography/mobile-tester')
from PIL import Image, ImageDraw, ImageFont

SRC = "/tmp/test_7971.jpg"
OUT_DIR = "/Users/rabbit/Claude code/Photography/mobile-tester/static"
MOBILE_W = 1290

# ── Fonts ──
def load_font(size):
    for fp in ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        try: return ImageFont.truetype(fp, size)
        except: pass
    return ImageFont.load_default()

FONT_LG = load_font(34)
FONT_MD = load_font(28)
FONT_SM = load_font(22)
FONT_XS = load_font(18)

# ═══════════════════════════════════════════════════════════
# Drawing helpers
# ═══════════════════════════════════════════════════════════

def draw_light(draw, W, H, direction='upper-left'):
    """Warm light radial gradient."""
    pos = {'upper-left': (0.20,0.15), 'upper-right': (0.80,0.12),
           'side-left': (0.05,0.40)}
    cx_r, cy_r = pos.get(direction, (0.20, 0.15))
    cx, cy = int(W * cx_r), int(H * cy_r)
    for i in range(30):
        alpha = int(22 * (1 - i / 30))
        r = int(W * 0.35 * (i + 1) / 30)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255,200,120, alpha))

def draw_grid(draw, W, H):
    """Rule of thirds grid."""
    c = (255,255,255,35)
    for i in [1,2]:
        x = int(W * i/3); draw.line([(x,0),(x,H)], fill=c, width=2)
        y = int(H * i/3); draw.line([(0,y),(W,y)], fill=c, width=2)

def draw_subject(draw, W, H, cx_r, cy_r, r_r, label, color=(245,158,11)):
    """Subject positioning circle + label pill."""
    cx, cy = int(W * cx_r), int(H * cy_r)
    r = int(W * r_r)
    # Glow
    for i in range(3):
        gr = r + 5 + i*3
        draw.ellipse([cx-gr, cy-gr, cx+gr, cy+gr], outline=(*color, 65-i*18), width=2)
    # Ring
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(*color, 160), width=3)
    # Corner dots
    for a in [0,90,180,270]:
        rad = math.radians(a)
        dx = int(r*0.7*math.cos(rad)); dy = int(r*0.7*math.sin(rad))
        draw.ellipse([cx+dx-3, cy+dy-3, cx+dx+3, cy+dy+3], fill=(*color, 190))
    # Label pill
    lw, lh = 56, 26
    lx = cx + r + 12
    ly = cy - lh//2
    draw.rounded_rectangle([lx, ly, lx+lw, ly+lh], radius=7, fill=(8,8,12,210))
    draw.text((lx+7, ly+3), label, fill=(*color, 255), font=FONT_MD)

def draw_horizon(draw, W, H, y_r):
    """Horizontal ref line with end ticks."""
    y = int(H * y_r)
    draw.line([(0,y),(W,y)], fill=(255,255,255,45), width=2)
    t = 18
    draw.line([(t,y-5),(t,y+5)], fill=(255,255,255,55), width=2)
    draw.line([(W-t,y-5),(W-t,y+5)], fill=(255,255,255,55), width=2)

def draw_leading(draw, W, H, points):
    """Highlight a leading line path."""
    pts = [(int(W*x), int(H*y)) for x,y in points]
    for i in range(3):
        draw.line(pts, fill=(255,255,255, 15 + i*5), width=3+i*2)

def draw_vignette(draw, W, H):
    """Edge darkening."""
    for i in range(20):
        a = int(38 * (1 - i/20))
        m = int(min(W,H)*0.02*i)
        draw.rectangle([m,m,W-m,H-m], outline=(0,0,0,a), width=int(min(W,H)*0.04))

# ═══════════════════════════════════════════════════════════
# NEW: Shot frame (景别框)
# ═══════════════════════════════════════════════════════════

def draw_shot_frame(draw, W, H, frame, label, color=(255,255,255)):
    """
    Draw a target frame overlay showing the shot size boundary.
    frame = (left_r, top_r, right_r, bottom_r) in 0..1
    Everything outside the frame is darkened slightly.
    Frame edges have corner brackets.
    """
    l, t, r, b = [int(W*x) if i%2==0 else int(H*x) for i,x in enumerate(frame)]

    # Darken outside
    dark = (0,0,0,55)
    if t > 0: draw.rectangle([(0,0),(W,t)], fill=dark)
    if b < H: draw.rectangle([(0,b),(W,H)], fill=dark)
    if l > 0: draw.rectangle([(0,t),(l,b)], fill=dark)
    if r < W: draw.rectangle([(r,t),(W,b)], fill=dark)

    # Frame border (subtle white line)
    border_c = (*color, 70)
    draw.rectangle([(l,t),(r,b)], outline=border_c, width=2)

    # Corner brackets (more visible)
    bracket_c = (*color, 160)
    bracket = 30  # px length
    bw = 3
    # Top-left
    draw.line([(l,t),(l+bracket,t)], fill=bracket_c, width=bw)
    draw.line([(l,t),(l,t+bracket)], fill=bracket_c, width=bw)
    # Top-right
    draw.line([(r-bracket,t),(r,t)], fill=bracket_c, width=bw)
    draw.line([(r,t),(r,t+bracket)], fill=bracket_c, width=bw)
    # Bottom-left
    draw.line([(l,b-bracket),(l,b)], fill=bracket_c, width=bw)
    draw.line([(l,b),(l+bracket,b)], fill=bracket_c, width=bw)
    # Bottom-right
    draw.line([(r-bracket,b),(r,b)], fill=bracket_c, width=bw)
    draw.line([(r,b-bracket),(r,b)], fill=bracket_c, width=bw)

    # Label at top-center of frame
    label_w = len(label) * 18 + 20
    label_h = 30
    lx = l + (r-l)//2 - label_w//2
    ly = t + 10
    draw.rounded_rectangle([lx, ly, lx+label_w, ly+label_h], radius=8, fill=(*color, 160))
    draw.text((lx+10, ly+4), label, fill=(0,0,0,255), font=FONT_MD)

# ═══════════════════════════════════════════════════════════
# NEW: Camera position mini-diagram (角度变化指示)
# ═══════════════════════════════════════════════════════════

def draw_camera_diagram(draw, W, H, target_label, direction='left'):
    """
    Small top-down camera position diagram in bottom-right corner.
    Shows current position → target position with arrow.
    Only called when there's an angle/position change.
    """
    # Diagram box in bottom-right corner, above bottom bar
    box_w, box_h = 160, 100
    bx = W - box_w - 20
    by = H - 56 - box_h - 16  # above bottom bar

    # Background
    draw.rounded_rectangle([bx, by, bx+box_w, by+box_h], radius=10, fill=(8,8,12,200))

    # Title
    draw.text((bx+8, by+6), "📷 机位移动", fill=(200,200,200,255), font=FONT_XS)

    # Current camera (left side, gray)
    cur_cx = bx + 30
    cur_cy = by + 55
    draw.ellipse([cur_cx-12, cur_cy-12, cur_cx+12, cur_cy+12],
                 fill=(100,100,110,200))
    draw.text((cur_cx-5, cur_cy-8), "📷", fill=(180,180,180,255), font=FONT_XS)
    draw.text((cur_cx-14, cur_cy+16), "现在", fill=(120,120,130,255), font=FONT_XS)

    # Target camera (right side, colored)
    tgt_cx = bx + 130
    tgt_cy = by + 55
    tgt_color = (245,158,11)
    draw.ellipse([tgt_cx-14, tgt_cy-14, tgt_cx+14, tgt_cy+14],
                 fill=(*tgt_color, 180))
    draw.text((tgt_cx-5, tgt_cy-8), "📷", fill=(255,255,255,255), font=FONT_XS)
    draw.text((tgt_cx-14, tgt_cy+16), target_label, fill=(*tgt_color, 255), font=FONT_XS)

    # Arrow from current to target
    arrow_y = cur_cy
    draw.line([(cur_cx+14, arrow_y), (tgt_cx-16, arrow_y)],
              fill=(*tgt_color, 150), width=2)
    # Arrowhead
    ax = tgt_cx - 16
    draw.polygon([(ax, arrow_y), (ax-8, arrow_y-5), (ax-8, arrow_y+5)],
                 fill=(*tgt_color, 150))

# ═══════════════════════════════════════════════════════════
# Badge: shot size + angle (top-left corner)
# ═══════════════════════════════════════════════════════════

def draw_badges(draw, W, H, shot_size, angle, color=(245,158,11)):
    """Small badges in top-left corner showing shot size and angle."""
    badges = [
        (shot_size, color),
        (angle, (180,180,190)),
    ]
    x0, y0 = 16, 16
    for text, clr in badges:
        tw = len(text) * 16 + 24
        th = 28
        draw.rounded_rectangle([x0, y0, x0+tw, y0+th], radius=7, fill=(8,8,12,210))
        draw.text((x0+12, y0+4), text, fill=(*clr, 255), font=FONT_SM)
        x0 += tw + 8

# ═══════════════════════════════════════════════════════════
# Bottom bar
# ═══════════════════════════════════════════════════════════

def draw_bottom_bar(draw, W, H, plan_num, plan_name, color):
    bar_h = 56
    y0 = H - bar_h
    draw.rectangle([(0, y0), (W, H)], fill=(0,0,0,140))
    draw.text((20, y0+12), f"📷 {plan_num}", fill=(200,200,200,255), font=FONT_LG)
    draw.text((W-220, y0+12), plan_name, fill=color, font=FONT_LG)

# ═══════════════════════════════════════════════════════════
# Plan Definitions
# ═══════════════════════════════════════════════════════════

PLANS = [
    {
        "id": "plan1",
        "name": "中景互动",
        "num": "1/4",
        "color": (245,158,11),
        "shot_size": "中景",
        "angle": "平视",
        "light_dir": "upper-left",
        "annotations": ["grid", "subjects", "light", "vignette", "frame"],
        "frame": (0.06, 0.10, 0.94, 0.80),  # 中景: 裁掉上下环境
        "frame_label": "📐 中景",
        "frame_color": (245,158,11),
        "subjects": [
            {"xy":(0.32,0.48), "r":0.07, "label":"人物", "color":(245,158,11)},
            {"xy":(0.63,0.73), "r":0.05, "label":"宠物", "color":(245,158,11)},
        ],
        "horizon": None,
        "camera_diagram": None,  # No angle change
    },
    {
        "id": "plan2",
        "name": "全景氛围",
        "num": "2/4",
        "color": (34,211,238),
        "shot_size": "全景",
        "angle": "平视",
        "light_dir": "upper-left",
        "annotations": ["grid", "subjects", "light", "vignette", "frame", "horizon", "leading"],
        "frame": (0.02, 0.03, 0.98, 0.97),  # 全景: 几乎满框
        "frame_label": "📐 全景",
        "frame_color": (34,211,238),
        "subjects": [
            {"xy":(0.28,0.55), "r":0.04, "label":"人宠", "color":(34,211,238)},
        ],
        "horizon": 0.52,
        "leading": [[(0.05,0.95),(0.30,0.65),(0.50,0.52)]],
        "camera_diagram": None,
    },
    {
        "id": "plan3",
        "name": "近景特写",
        "num": "3/4",
        "color": (167,139,250),
        "shot_size": "近景",
        "angle": "低角度",
        "light_dir": "side-left",
        "annotations": ["subjects", "light", "vignette", "frame"],
        "frame": (0.10, 0.08, 0.90, 0.62),  # 近景: 紧凑脸部区域
        "frame_label": "📐 近景",
        "frame_color": (167,139,250),
        "subjects": [
            {"xy":(0.35,0.38), "r":0.10, "label":"人物", "color":(167,139,250)},
            {"xy":(0.60,0.55), "r":0.06, "label":"狗", "color":(167,139,250)},
        ],
        "horizon": None,
        "camera_diagram": None,
    },
    {
        "id": "plan4",
        "name": "侧面角度",
        "num": "4/4",
        "color": (74,222,128),
        "shot_size": "全景",
        "angle": "侧面",
        "light_dir": "upper-right",
        "annotations": ["grid", "subjects", "light", "vignette", "frame", "horizon"],
        "frame": (0.02, 0.03, 0.98, 0.97),
        "frame_label": "📐 全景",
        "frame_color": (74,222,128),
        "subjects": [
            {"xy":(0.45,0.50), "r":0.06, "label":"人物", "color":(74,222,128)},
            {"xy":(0.70,0.72), "r":0.05, "label":"宠物", "color":(74,222,128)},
        ],
        "horizon": 0.48,
        "camera_diagram": {"label": "侧面", "direction": "left"},  # NEW: angle change
    },
]

# ═══════════════════════════════════════════════════════════
# Render Loop
# ═══════════════════════════════════════════════════════════

img = Image.open(SRC).convert("RGB")
w, h = img.size
scale = MOBILE_W / w
img = img.resize((MOBILE_W, int(h*scale)), Image.LANCZOS)
W, H = img.size
print(f"Canvas: {W}x{H}")

for plan in PLANS:
    base = img.copy().convert("RGBA")

    # Layer canvases
    layers = {}
    for name in plan["annotations"]:
        layers[name] = Image.new("RGBA", (W,H), (0,0,0,0))
    # Plus always-present layers
    badge_layer = Image.new("RGBA", (W,H), (0,0,0,0))
    bar_layer = Image.new("RGBA", (W,H), (0,0,0,0))

    # Draw each layer
    if "light" in layers:
        draw_light(ImageDraw.Draw(layers["light"]), W, H, plan["light_dir"])
    if "grid" in layers:
        draw_grid(ImageDraw.Draw(layers["grid"]), W, H)
    if "subjects" in layers:
        sdr = ImageDraw.Draw(layers["subjects"])
        for s in plan["subjects"]:
            draw_subject(sdr, W, H, s["xy"][0], s["xy"][1], s["r"], s["label"], s["color"])
        if plan.get("horizon"):
            draw_horizon(sdr, W, H, plan["horizon"])
        if plan.get("leading"):
            for pts in plan["leading"]:
                draw_leading(sdr, W, H, pts)
    if "vignette" in layers:
        draw_vignette(ImageDraw.Draw(layers["vignette"]), W, H)
    if "frame" in layers:
        draw_shot_frame(ImageDraw.Draw(layers["frame"]), W, H,
                       plan["frame"], plan["frame_label"], plan.get("frame_color", (255,255,255)))

    # Badges
    draw_badges(ImageDraw.Draw(badge_layer), W, H, plan["shot_size"], plan["angle"], plan["color"])

    # Camera diagram (if angle change)
    if plan.get("camera_diagram"):
        draw_camera_diagram(ImageDraw.Draw(badge_layer), W, H,
                          plan["camera_diagram"]["label"], plan["camera_diagram"]["direction"])

    # Bottom bar
    draw_bottom_bar(ImageDraw.Draw(bar_layer), W, H, plan["num"], plan["name"], plan["color"])

    # Composite all
    result = base
    for name in plan["annotations"]:
        result = Image.alpha_composite(result, layers[name])
    result = Image.alpha_composite(result, badge_layer)
    result = Image.alpha_composite(result, bar_layer)

    out = os.path.join(OUT_DIR, f"plan_v5_{plan['id']}.jpg")
    result.convert("RGB").save(out, "JPEG", quality=90)
    print(f"  → {out}")

print("Done! 4 v5 plans with shot frames + angle diagrams.")
