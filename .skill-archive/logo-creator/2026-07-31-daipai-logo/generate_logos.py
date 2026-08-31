#!/usr/bin/env python3
"""
用豆包 Seedream 文生图生成带拍 Logo
Volcengine ARK 图片生成 API
"""

import os
import sys
import json
import time
import base64
from typing import Optional, Dict, Any
import requests
from pathlib import Path

# Config
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
if not DOUBAO_API_KEY:
    # Try reading from .zshrc
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists():
        for line in zshrc.read_text().splitlines():
            if "DOUBAO_API_KEY" in line:
                DOUBAO_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if not DOUBAO_API_KEY:
    print("❌ 未找到 DOUBAO_API_KEY")
    sys.exit(1)

# Volcengine ARK Plan Image Generation endpoint
IMG_API_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
IMG_MODEL = "doubao-seedream-5.0-lite"  # Plan-compatible model
OUTPUT_DIR = Path(__file__).parent

print(f"🔑 API Key: {DOUBAO_API_KEY[:10]}...{DOUBAO_API_KEY[-4:]}")
print(f"📁 Output: {OUTPUT_DIR}")
print(f"🌐 Endpoint: {IMG_API_URL}")
print()

# ── Logo prompts ──
# Each variant designed for different style directions

VARIANTS = [
    # ── 方向一：极简几何抽象 ──
    {
        "id": "logo-01-geometric-viewfinder",
        "label": "1A · Viewfinder + Guide Trail",
        "prompt": (
            "Minimalist flat design logo for a photography guide app called 'Daipai'. "
            "A rounded square viewfinder frame with a trail of dots leading from top-left to bottom-right, "
            "the final dot being a larger circle with a crosshair inside. "
            "Only the top-left corner of the frame is bold, other corners are thin and subtle. "
            "Warm orange (#F97316) on cream white (#FFF7ED) background. "
            "Clean vector style, simple geometric shapes, modern, no text, no gradients, no shadows. "
            "Suitable for an app icon. Negative space, ultra simple."
        ),
        "size": "2048x2048",
    },
    {
        "id": "logo-02-lens-orbit",
        "label": "1B · Lens Ring + Orbit",
        "prompt": (
            "Minimalist logo mark: three concentric circles forming a camera lens ring, "
            "with a single dot on the outermost orbit path and a dashed curve connecting to it. "
            "Warm orange (#F97316) and dark grey (#1C1917). "
            "Clean flat design, geometric precision, no text, pure symbol. "
            "White background. Modern tech brand logo style. "
            "The composition suggests 'finding the perfect shot'."
        ),
        "size": "2048x2048",
    },

    # ── 方向二：温暖活泼 ──
    {
        "id": "logo-03-warm-app-icon",
        "label": "2B · Warm App Icon (Orange BG)",
        "prompt": (
            "App icon design: Warm orange (#F97316) rounded square background. "
            "In the center, a white circular viewfinder ring with a dashed inner ring. "
            "Inside, a trail of three small gradient dots leading to a larger white dot with a tiny crosshair. "
            "Below the viewfinder, the Chinese text '带拍' in small white rounded sans-serif font. "
            "Friendly, warm, modern. Like a photography app from a friend. "
            "Rounded corners on the outer square. No gradients, flat design."
        ),
        "size": "2048x2048",
    },
    {
        "id": "logo-04-warm-character-mark",
        "label": "2A · 取景框「带」字标",
        "prompt": (
            "Chinese calligraphy-inspired logo design: The Chinese character '带' in warm orange (#F97316) "
            "with the small square radical (口) inside the character replaced by a tiny viewfinder frame "
            "with a dot inside it. Next to it, the character '拍' in dark grey (#1C1917). "
            "Below them, a small subtitle 'AI 拍照灵感指南' in light grey. "
            "Rounded sans-serif font style, warm and friendly. Cream white (#FFF7ED) background. "
            "Modern Chinese brand logo, clean, minimalist, cultural yet contemporary."
        ),
        "size": "2048x2048",
    },

    # ── 方向三：专业克制 ──
    {
        "id": "logo-05-dp-professional",
        "label": "3A · dp 字母标 (Dark BG)",
        "prompt": (
            "Premium minimalist lettermark logo: The letters 'dp' in warm orange (#FB923C) "
            "on a near-black (#1C1917) background. The letters are set in a modern geometric sans-serif font "
            "with tight letter-spacing. A subtle camera lens ring circle surrounds the letters partially. "
            "In the bottom-right corner, a small viewfinder bracket mark. "
            "Elegant, professional, tech-startup vibe. No gradients, clean flat design. "
            "Suitable for a high-end photography guidance app called GuidePic."
        ),
        "size": "2048x2048",
    },
    {
        "id": "logo-06-shutter-abstract",
        "label": "3C · 快门叶片抽象标",
        "prompt": (
            "Abstract geometric logo: hexagonal shutter blade shapes nested concentrically "
            "in warm orange (#F97316) with varying opacity, converging to a solid orange center dot. "
            "The shape suggests a camera aperture. Clean flat design, precise geometry. "
            "White background. No text. Modern photography brand symbol. "
            "Like a tech company logo, minimalist and iconic."
        ),
        "size": "2048x2048",
    },

    # ── 方向四：组合标 ──
    {
        "id": "logo-07-combination-horizontal",
        "label": "4A · 横向组合标",
        "prompt": (
            "Horizontal combination logo: On the left, a small rounded square icon in warm orange "
            "with a white viewfinder ring and guide dot inside. To its right, the Chinese text '带拍' "
            "in warm orange (#F97316) bold rounded font, then 'GuidePic' in dark grey (#1C1917), "
            "and below a small tagline 'AI 拍照灵感指南' in grey (#78716C). "
            "All on a clean white background. Modern brand logo, flat design, "
            "suitable for website header. Clean typography, balanced spacing."
        ),
        "size": "3072x1536",
    },

    # ── 额外：行走者标 ──
    {
        "id": "logo-08-walking-guide",
        "label": "2C · 行走者向导标",
        "prompt": (
            "Minimalist line-art logo: A simple stick figure person walking inside a rounded rectangular "
            "viewfinder frame. The person has one arm extended forward, pointing with a dashed arrow "
            "towards a small target/crosshair circle in the upper right corner. "
            "Single color: warm orange (#F97316) on white background. "
            "Clean lines, geometric simplicity. The illustration tells the story: "
            "'I'll guide you to the perfect photo spot.' No text. Flat design, friendly."
        ),
        "size": "2048x2048",
    },
]


def generate_image(prompt: str, size: str = "2048x2048", retries: int = 2) -> Optional[Dict]:
    """Call Volcengine ARK text-to-image API"""
    payload = {
        "model": IMG_MODEL,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "response_format": "b64_json",
        "watermark": False,
    }

    headers = {
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(IMG_API_URL, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                # Parse response - could be "data" array with b64_json or url
                images = data.get("data", [])
                if images:
                    return images[0]
                else:
                    print(f"  ⚠️ No images in response: {json.dumps(data, ensure_ascii=False)[:300]}")
                    return None
            else:
                print(f"  🔄 HTTP {resp.status_code} (attempt {attempt+1}/{retries+1}): {resp.text[:300]}")
                if resp.status_code == 404:
                    # Maybe wrong endpoint, try alternatives
                    return None
        except Exception as e:
            print(f"  🔄 Error (attempt {attempt+1}/{retries+1}): {e}")

    return None


def generate_image_alt(prompt: str, size: str = "2048x2048") -> Optional[Dict]:
    """Try alternative Volcengine image generation endpoints"""
    alt_endpoints = [
        "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations",
    ]

    # Try different model name formats (plan-compatible)
    alt_models = [
        "doubao-seedream-5.0-lite",
        "doubao-seedream-5-0-lite",
        "doubao-seedream-4.5",
        "doubao-seedream-4-5-251128",
    ]

    for endpoint in alt_endpoints:
        for model in alt_models:
            payload = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "n": 1,
                "response_format": "b64_json",
                "watermark": False,
            }
            headers = {
                "Authorization": f"Bearer {DOUBAO_API_KEY}",
                "Content-Type": "application/json",
            }
            try:
                resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    images = data.get("data", [])
                    if images:
                        print(f"  ✅ Found: {endpoint} / {model}")
                        return images[0]
                elif resp.status_code == 401:
                    print(f"  ❌ Auth failed for {model} — API key may not have image gen access")
                    return None
                # else: try next
            except:
                continue

    return None


def main():
    print(f"🎨 开始生成 {len(VARIANTS)} 个 Logo 变体\n")

    success = 0
    for i, v in enumerate(VARIANTS):
        print(f"[{i+1}/{len(VARIANTS)}] {v['label']}")
        print(f"   📝 Prompt length: {len(v['prompt'])} chars")
        print(f"   📐 Size: {v['size']}")

        # Try primary endpoint first
        result = generate_image(v["prompt"], v["size"])
        if result is None:
            print(f"   🔄 Trying alternative endpoints/models...")
            result = generate_image_alt(v["prompt"], v["size"])

        if result:
            # Save image
            b64_data = result.get("b64_json", "")
            if b64_data:
                output_path = OUTPUT_DIR / f"{v['id']}.png"
                output_path.write_bytes(base64.b64decode(b64_data))
                file_size = output_path.stat().st_size / 1024
                print(f"   ✅ Saved: {output_path.name} ({file_size:.1f} KB)")
                success += 1
            else:
                url = result.get("url", "")
                if url:
                    # Download from URL
                    img_resp = requests.get(url, timeout=60)
                    if img_resp.status_code == 200:
                        output_path = OUTPUT_DIR / f"{v['id']}.png"
                        output_path.write_bytes(img_resp.content)
                        file_size = output_path.stat().st_size / 1024
                        print(f"   ✅ Saved from URL: {output_path.name} ({file_size:.1f} KB)")
                        success += 1
        else:
            print(f"   ⚠️ Failed to generate (all endpoints exhausted)")
            # Save prompt for manual use
            prompt_path = OUTPUT_DIR / f"{v['id']}.prompt.txt"
            prompt_path.write_text(f"Prompt ({v['size']}):\n{v['prompt']}\n")
            print(f"   📝 Prompt saved to {prompt_path.name}")

        if i < len(VARIANTS) - 1:
            time.sleep(1.5)

    print(f"\n{'='*60}")
    print(f"🎉 Done! {success}/{len(VARIANTS)} logos generated")
    print(f"📁 Output: {OUTPUT_DIR}")
    for f in sorted(OUTPUT_DIR.glob("*.png")):
        print(f"   📄 {f.name} ({f.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
