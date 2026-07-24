#!/usr/bin/env python3
"""保存每张照片的完整视觉 JSON 到独立文件"""
import base64, json, os, sys, time, urllib.request

PHOTO_DIR = "/Users/rabbit/Downloads/直出相机测试"
OUT_DIR = "/Users/rabbit/Downloads/直出相机测试/vision_results"
API_KEY = os.environ.get("DOUBAO_API_KEY", "")
API_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
MODEL = "doubao-seed-2.0-pro"

PROMPT = """请详细分析这张照片，输出严格的结构化JSON。必须包含以下8个字段，缺一不可。

## 核心原则：区分[观察]与[推测]

- [观察]：照片中能直接看到的视觉事实（如"天空灰白色""地面无清晰阴影""人物身着米白衬衫"）
- [推测]：从视觉线索推断的结论（如"可能为多云天气""可能为午后"）
- 禁止输出纯感受描述（如"空旷清幽""治愈松弛"）——那是下游AI的工作。你只负责报告视觉事实和合理推测。

每个字段的值中，请用[观察]或[推测]标注每条信息的性质。不确定的字段用[推测]并说明依据。

{
  "scene_type": "[观察]室外/室内/半室外 — [推测]具体场景类型及依据",
  "people": "人物数量、每人位置/衣着/动作/表情/姿态。如果没有人，写'无人物'。衣着用[观察]标注具体颜色和款式，表情用[观察]标注可见的面部状态",
  "light": {
    "direction": "[推测]顺光/侧光/逆光/顶光/漫射 — 判断依据（阴影方向/高光位置）",
    "quality": "[推测]硬光/软光/混合 — 判断依据（阴影边缘是锐利还是柔和）",
    "color_temp": "[推测]暖/中/冷 — 估算色温K值及依据",
    "special": "[观察]遮阳阴影区/斑驳树影/窗边漫射/混合色温/无特殊 — 具体描述",
    "uncertainty": "如果对某个子字段（direction/quality/color_temp）的判断不够确定，在这里标注字段名。确定就写'none'"
  },
  "color": {
    "primary": "[观察]最主导的颜色及在画面中的位置",
    "secondary": "[观察]次要色及在画面中的位置",
    "accent": "[观察]强调色及在画面中的位置",
    "mood_axes": {
      "_note": "三个轴的数值范围都是0.0到1.0。基于色彩组合的客观属性估值，不要基于主观感受。",
      "warmth": "0.0=全冷色(蓝/青/紫), 0.5=中性(白/灰/绿), 1.0=全暖色(红/橙/黄)。给一位小数。",
      "energy": "0.0=全低饱和暗沉(死寂), 0.5=中等饱和明度, 1.0=全高饱和高明度(爆裂)。给一位小数。",
      "complexity": "0.0=单色或近乎单色, 0.5=2-3个主要色系, 1.0=4个以上色系混杂。给一位小数。"
    }
  },
  "space": {
    "foreground": "[观察]前景有什么具体物体或元素",
    "midground": "[观察]中景有什么具体物体或元素",
    "background": "[观察]背景有什么具体物体或元素",
    "depth": "[观察]浅/中/深 — 判断依据（各层次之间的空间距离感）"
  },
  "composition": "[观察]当前构图方式（三分法/中心/引导线/框架/对称等） + [观察]画面中可利用的构图元素（具体物体/线条/空隙/光影区域）",
  "perspective": "[观察]拍摄视角（平视/俯视/仰视/鸟瞰/低角度）+ [推测]机位高度及判断依据",
  "weather_env": "[推测]天气状况及判断依据（云层/阴影/反光/植被状态等） + [观察]环境中可见的具体细节（植被种类/地面材质/建筑特征等）"
}

只输出JSON，不要任何额外文字。不要markdown代码块包裹。"""

os.makedirs(OUT_DIR, exist_ok=True)

photos = sorted([f for f in os.listdir(PHOTO_DIR) if f.lower().endswith(('.heic', '.heif', '.jpg', '.jpeg', '.png'))])

for i, photo in enumerate(photos, 1):
    out_path = os.path.join(OUT_DIR, f"{os.path.splitext(photo)[0]}_vision.json")

    # Skip if already exists
    if os.path.exists(out_path):
        print(f"[{i}/10] {photo} → 已存在，跳过")
        continue

    image_path = os.path.join(PHOTO_DIR, photo)
    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "image/heic" if ext in ('.heic', '.heif') else "image/jpeg"

    t0 = time.time()
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}},
                {"type": "text", "text": PROMPT}
            ]
        }],
        "max_tokens": 2000
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())

    elapsed = time.time() - t0
    usage = result.get('usage', {})

    content = result['choices'][0]['message']['content'].strip()
    if content.startswith('```'):
        lines = content.split('\n')
        content = '\n'.join(lines[1:])
        if content.endswith('```'):
            content = content[:-3]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"raw": content, "parse_error": "JSON解析失败"}

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            "filename": photo,
            "model": MODEL,
            "elapsed_s": round(elapsed, 2),
            "tokens": usage,
            "vision_result": parsed
        }, f, ensure_ascii=False, indent=2)

    print(f"[{i}/10] {photo} → ✅ {elapsed:.1f}s | tokens={usage.get('total_tokens', '?')} | {out_path}")
    time.sleep(1)

print("\n全部完成！")
