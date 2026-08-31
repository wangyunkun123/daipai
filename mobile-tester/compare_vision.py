#!/usr/bin/env python3
"""视觉识别模型对比：豆包 Pro vs Lite（同一批图片，处理参数与线上完全一致）

验证：
  1. doubao-seed-2.0-lite 是否支持视觉输入
  2. Lite 视觉耗时 vs Pro
  3. JSON 字段质量差异（6 字段完整度 + 关键字段深度）

用法：python3 compare_vision.py <img1> [img2 ...]
"""
import sys, os, json, time, io, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
from PIL import Image

URL = server.DOUBAO_URL
KEY = server.DOUBAO_API_KEY
PRO = server.DOUBAO_MODEL          # doubao-seed-2.0-pro
LITE = server.DOUBAO_FAST_MODEL    # doubao-seed-2.0-lite

def prep(img_path):
    """与 server.analyze_photo_stream 完全一致的视觉预处理：1024px + JPEG q80"""
    img = Image.open(img_path)
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
    w, h = img.size
    max_dim = max(w, h)
    if max_dim > server.VISION_IMAGE_DIM:
        r = server.VISION_IMAGE_DIM / max_dim
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return base64.b64encode(buf.getvalue()).decode(), img.size

def call(model, b64):
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": server.VISION_PROMPT}
    ]}]
    payload = {"model": model, "messages": messages, "max_tokens": 2000}
    client = server._get_httpx_client()
    t0 = time.time()
    resp = client.post(URL, json=payload,
                       headers={"Authorization": f"Bearer {KEY}"}, timeout=300)
    dur = round(time.time() - t0, 2)
    resp.raise_for_status()
    d = resp.json()
    content = d['choices'][0]['message']['content'].strip()
    usage = d.get('usage', {})
    return content, dur, usage

def assess(content):
    """评估视觉 JSON 的质量。返回 (parsed, stats, err)。"""
    try:
        parsed = json.loads(content)
    except Exception:
        # 尝试提取 ```json ... ``` 或首个 { 到末尾 }
        m = __import__('re').search(r'```(?:json)?\s*\n?(.*?)\n?```', content, __import__('re').DOTALL)
        s = m.group(1) if m else content
        try:
            parsed = json.loads(s)
        except Exception as e:
            return None, None, f"JSON错误: {str(e)[:80]}"
    if not isinstance(parsed, dict):
        return None, None, "非对象"
    space = parsed.get('space') or {}
    anchors = space.get('anchors') if isinstance(space, dict) else None
    anchors_n = len(anchors) if isinstance(anchors, list) else (1 if anchors else 0)
    dt = str(parsed.get('distinctive_traits', ''))
    stats = {
        "fields6": all(k in parsed for k in ['scene_type','primary_subject','people','light','color','space','composition','location_clues','specific_location','distinctive_traits']),
        "scene_len": len(str(parsed.get('scene_type', ''))),
        "subject": str(parsed.get('primary_subject', ''))[:40],
        "people": str(parsed.get('people', ''))[:30],
        "anchors": anchors_n,
        "light_has": isinstance(parsed.get('light'), dict) and 'direction' in parsed['light'] and 'quality' in parsed['light'],
        "dt_traits": dt[:20],
        "dt_is_none": '无' in dt,
        "loc": str(parsed.get('location_clues', ''))[:30],
        "loc_unknown": '无法识别' in str(parsed.get('location_clues', '')),
    }
    return parsed, stats, None

def main():
    paths = sys.argv[1:] if len(sys.argv) > 1 else ['/tmp/vtest_person.jpg']
    print(f"图片: {[os.path.basename(p) for p in paths]}")
    print(f"Pro={PRO}  Lite={LITE}\n")

    # Lite 是否支持视觉（首跑探活）
    b64s = []
    for p in paths:
        b64, size = prep(p)
        b64s.append((p, b64, size))
        print(f"[预处理] {os.path.basename(p)} -> vision {size} ({len(b64)//1024}KB b64)")

    results = []
    for p, b64, size in b64s:
        for model, label, n in [(PRO, 'pro', 1), (LITE, 'lite', 2)]:
            for i in range(n):
                try:
                    content, dur, usage = call(model, b64)
                    parsed, stats, err = assess(content)
                    flag = '✅' if parsed is not None else '❌'
                    extra = ''
                    if stats:
                        extra = (f"subject={stats['subject'][:18]} | anchors={stats['anchors']} | "
                                 f"dt={stats['dt_traits'][:12]} | loc={stats['loc'][:14]}")
                    elif err:
                        extra = err
                    print(f"[{label} #{i+1}] {flag} {dur}s  tok={usage.get('total_tokens','?')}"
                          f"(提示{usage.get('prompt_tokens','?')}) {extra}")
                    results.append({"model": label, "dur": dur, "usage": usage,
                                    "ok": parsed is not None, "stats": stats,
                                    "err": err, "content": content})
                except Exception as e:
                    print(f"[{label} #{i+1}] 💥 {str(e)[:120]}")
                    results.append({"model": label, "dur": 0, "usage": {}, "ok": False, "err": str(e)[:120], "content": ""})
                time.sleep(0.5)

    # 汇总
    print("\n===== 汇总 =====")
    for label in ['pro', 'lite']:
        rs = [r for r in results if r['model'] == label]
        if not rs: continue
        ok = sum(1 for r in rs if r['ok'])
        avg = sum(r['dur'] for r in rs) / len(rs)
        avg_tok = sum((r['usage'].get('total_tokens') or 0) for r in rs) / len(rs)
        print(f"{label}: 成功率 {ok}/{len(rs)} | 平均 {avg:.1f}s | 平均tok {avg_tok:.0f}")

    # 保存完整输出供人工对比
    with open('/tmp/vision_compare_out.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n完整 JSON 输出已存: /tmp/vision_compare_out.json")

if __name__ == "__main__":
    main()
