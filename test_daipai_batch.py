#!/usr/bin/env python3
"""
带拍 · 批量测试脚本
对 10 张照片逐一执行：
  阶段 0A: EXIF 提取
  阶段 1A: 豆包视觉 API 识别
记录每张照片的耗时、token 用量、成功/失败状态，最后计算平均值。
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

# ============================================================
# 配置
# ============================================================
PHOTO_DIR = "/Users/rabbit/Downloads/带拍测试"
EXIF_SCRIPT = "/Users/rabbit/Claude code/Photography/.claude/skills/daipai/scripts/exif-extract.py"

# 豆包 API 配置
API_KEY = os.environ.get("DOUBAO_API_KEY", "")
API_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
MODEL = "doubao-seed-2.0-pro"

# 视觉识别 Prompt（与 doubao-vision.py 一致）
VISION_PROMPT = """请详细分析这张照片，输出严格的结构化JSON。必须包含以下8个字段，缺一不可。

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


# ============================================================
# 工具函数
# ============================================================

def run_exif(image_path):
    """阶段 0A：EXIF 提取"""
    t0 = time.time()
    try:
        result = subprocess.run(
            ["python3", EXIF_SCRIPT, image_path],
            capture_output=True, text=True, timeout=15
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {"success": True, "data": data, "elapsed": elapsed, "error": None}
        else:
            return {"success": False, "data": None, "elapsed": elapsed, "error": result.stderr.strip()}
    except Exception as e:
        elapsed = time.time() - t0
        return {"success": False, "data": None, "elapsed": elapsed, "error": str(e)}


def run_vision(image_path):
    """阶段 1A：豆包视觉 API 识别"""
    t0 = time.time()
    try:
        # 读取图片并 Base64 编码
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()

        # 判断文件扩展名
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = "image/heic" if ext in ('.heic', '.heif') else "image/jpeg"

        payload = {
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}},
                    {"type": "text", "text": VISION_PROMPT}
                ]
            }],
            "max_tokens": 2000
        }

        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}"
            }
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())

        elapsed = time.time() - t0

        # 提取 token 用量
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)

        # 提取响应内容
        content = result['choices'][0]['message']['content']
        content = content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:])
            if content.endswith('```'):
                content = content[:-3]

        try:
            parsed = json.loads(content)
            parse_success = True
        except json.JSONDecodeError as je:
            parsed = {"raw": content, "parse_error": str(je)}
            parse_success = False

        return {
            "success": True,
            "parse_success": parse_success,
            "data": parsed,
            "elapsed": elapsed,
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens
            },
            "error": None
        }

    except Exception as e:
        elapsed = time.time() - t0
        return {
            "success": False,
            "parse_success": False,
            "data": None,
            "elapsed": elapsed,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "error": str(e)
        }


def summarize_exif(exif_data):
    """提取 EXIF 关键信息摘要"""
    if not exif_data:
        return "无 EXIF 数据"
    parts = []
    device = exif_data.get('device', '未知')
    parts.append(f"设备: {device}")
    if exif_data.get('has_gps'):
        gps = exif_data['gps']
        parts.append(f"GPS: {gps['lat']:.4f}, {gps['lon']:.4f}")
    dt = exif_data.get('datetime', '')
    if dt:
        parts.append(f"时间: {dt[:16]}")
    sp = exif_data.get('shooting_params', {})
    if sp:
        fl = sp.get('focal_length_35mm', '')
        iso = sp.get('iso', '')
        et = sp.get('exposure_time', '')
        ap = sp.get('aperture', '')
        params = []
        if fl: params.append(f"焦距={fl}mm")
        if iso: params.append(f"ISO={iso}")
        if et: params.append(f"快门={et}")
        if ap: params.append(f"光圈=f/{ap}")
        if params:
            parts.append(" | ".join(params))
    return " | ".join(parts)


def summarize_vision(vision_data):
    """提取视觉识别关键信息摘要"""
    if not vision_data:
        return "无视觉数据"
    parts = []
    parts.append(f"场景: {vision_data.get('scene_type', '?')}")
    people = vision_data.get('people', '')
    parts.append(f"人物: {people[:60]}..." if len(str(people)) > 60 else f"人物: {people}")
    light = vision_data.get('light', {})
    parts.append(f"光线: {light.get('direction', '?')} / {light.get('quality', '?')} / {light.get('color_temp', '?')}")
    color = vision_data.get('color', {})
    parts.append(f"主色: {color.get('primary', '?')}")
    return " | ".join(parts)


# ============================================================
# 主流程
# ============================================================

def main():
    # 获取所有照片文件
    photos = sorted([
        f for f in os.listdir(PHOTO_DIR)
        if f.lower().endswith(('.heic', '.heif', '.jpg', '.jpeg', '.png'))
    ])

    if not photos:
        print("❌ 未找到照片文件")
        sys.exit(1)

    print(f"{'='*80}")
    print(f"带拍 · 批量测试")
    print(f"{'='*80}")
    print(f"照片目录: {PHOTO_DIR}")
    print(f"照片数量: {len(photos)}")
    print(f"视觉模型: {MODEL}")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

    results = []
    total_start = time.time()

    for i, photo in enumerate(photos, 1):
        image_path = os.path.join(PHOTO_DIR, photo)
        file_size = os.path.getsize(image_path) / (1024 * 1024)

        print(f"{'─'*80}")
        print(f"[{i}/{len(photos)}] {photo} ({file_size:.1f} MB)")
        print(f"{'─'*80}")

        # ---- 阶段 0A：EXIF 提取 ----
        print(f"  📋 阶段 0A: EXIF 提取...", end=" ", flush=True)
        exif_result = run_exif(image_path)
        if exif_result['success']:
            print(f"✅ ({exif_result['elapsed']:.2f}s)")
            print(f"      {summarize_exif(exif_result['data'])}")
        else:
            print(f"❌ ({exif_result['elapsed']:.2f}s) - {exif_result['error'][:100]}")

        # ---- 阶段 1A：豆包视觉识别 ----
        print(f"  🚨 阶段 1A: 豆包视觉识别...", end=" ", flush=True)
        vision_result = run_vision(image_path)
        if vision_result['success']:
            status = "✅" if vision_result['parse_success'] else "⚠️ (JSON解析失败)"
            print(f"{status} ({vision_result['elapsed']:.2f}s)")
            t = vision_result['tokens']
            print(f"      Tokens: prompt={t['prompt']}, completion={t['completion']}, total={t['total']}")
            if vision_result['parse_success']:
                print(f"      {summarize_vision(vision_result['data'])}")
            else:
                print(f"      原始响应(前200字): {str(vision_result['data'].get('raw', ''))[:200]}")
        else:
            print(f"❌ ({vision_result['elapsed']:.2f}s) - {vision_result['error'][:200]}")

        results.append({
            "index": i,
            "filename": photo,
            "size_mb": round(file_size, 1),
            "exif": exif_result,
            "vision": vision_result
        })

        # 短暂间隔，避免 API 限流
        if i < len(photos):
            time.sleep(1)

    total_elapsed = time.time() - total_start

    # ============================================================
    # 统计报告
    # ============================================================
    print(f"\n{'='*80}")
    print(f"统计报告")
    print(f"{'='*80}")

    # 成功计数
    exif_ok = sum(1 for r in results if r['exif']['success'])
    vision_ok = sum(1 for r in results if r['vision']['success'])
    vision_parse_ok = sum(1 for r in results if r['vision']['success'] and r['vision']['parse_success'])

    print(f"\n📊 成功率:")
    print(f"  EXIF 提取:     {exif_ok}/{len(results)} ({exif_ok/len(results)*100:.0f}%)")
    print(f"  豆包视觉识别:  {vision_ok}/{len(results)} ({vision_ok/len(results)*100:.0f}%)")
    print(f"  JSON 解析成功: {vision_parse_ok}/{len(results)} ({vision_parse_ok/len(results)*100:.0f}%)")

    # 耗时统计
    exif_times = [r['exif']['elapsed'] for r in results if r['exif']['success']]
    vision_times = [r['vision']['elapsed'] for r in results if r['vision']['success']]

    print(f"\n⏱️ 耗时统计:")
    if exif_times:
        print(f"  EXIF 提取:")
        print(f"    平均: {sum(exif_times)/len(exif_times):.2f}s")
        print(f"    最快: {min(exif_times):.2f}s")
        print(f"    最慢: {max(exif_times):.2f}s")
    if vision_times:
        print(f"  豆包视觉识别:")
        print(f"    平均: {sum(vision_times)/len(vision_times):.2f}s")
        print(f"    最快: {min(vision_times):.2f}s")
        print(f"    最慢: {max(vision_times):.2f}s")
    print(f"  总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f} 分钟)")

    # Token 统计
    prompt_tokens_list = [r['vision']['tokens']['prompt'] for r in results if r['vision']['success']]
    completion_tokens_list = [r['vision']['tokens']['completion'] for r in results if r['vision']['success']]
    total_tokens_list = [r['vision']['tokens']['total'] for r in results if r['vision']['success']]

    if total_tokens_list:
        print(f"\n🔢 Token 用量统计 (豆包视觉 API):")
        print(f"  Prompt Tokens:")
        print(f"    平均: {sum(prompt_tokens_list)/len(prompt_tokens_list):.0f}")
        print(f"    最少: {min(prompt_tokens_list)}")
        print(f"    最多: {max(prompt_tokens_list)}")
        print(f"  Completion Tokens:")
        print(f"    平均: {sum(completion_tokens_list)/len(completion_tokens_list):.0f}")
        print(f"    最少: {min(completion_tokens_list)}")
        print(f"    最多: {max(completion_tokens_list)}")
        print(f"  Total Tokens:")
        print(f"    平均: {sum(total_tokens_list)/len(total_tokens_list):.0f}")
        print(f"    最少: {min(total_tokens_list)}")
        print(f"    最多: {max(total_tokens_list)}")
        print(f"    总计: {sum(total_tokens_list)}")

    # 逐张汇总表
    print(f"\n📋 逐张汇总:")
    print(f"  {'#':<3} {'文件名':<25} {'大小':<7} {'EXIF':<6} {'视觉':<6} {'视觉耗时':<9} {'Tokens':<7} {'摘要'}")
    print(f"  {'─'*3} {'─'*25} {'─'*7} {'─'*6} {'─'*6} {'─'*9} {'─'*7} {'─'*40}")
    for r in results:
        exif_icon = "✅" if r['exif']['success'] else "❌"
        vis_icon = "✅" if r['vision']['success'] else "❌"
        vis_time = f"{r['vision']['elapsed']:.1f}s" if r['vision']['success'] else "N/A"
        tokens = r['vision']['tokens']['total'] if r['vision']['success'] else 0
        summary = ""
        if r['vision']['success'] and r['vision']['parse_success']:
            d = r['vision']['data']
            summary = f"{d.get('scene_type', '?')[:30]} | {d.get('light', {}).get('direction', '?')}"
        elif not r['vision']['success']:
            summary = f"错误: {str(r['vision'].get('error', ''))[:40]}"
        print(f"  {r['index']:<3} {r['filename']:<25} {r['size_mb']:<6.1f}MB {exif_icon:<6} {vis_icon:<6} {vis_time:<9} {tokens:<7} {summary[:50]}")

    # 保存详细结果到 JSON
    output_path = os.path.join(PHOTO_DIR, "test_results.json")

    # 构建可序列化的结果（去掉 raw data 中的大字段）
    serializable = []
    for r in results:
        sr = {
            "index": r['index'],
            "filename": r['filename'],
            "size_mb": r['size_mb'],
            "exif": {
                "success": r['exif']['success'],
                "elapsed": round(r['exif']['elapsed'], 3),
                "summary": summarize_exif(r['exif']['data']) if r['exif']['success'] else None,
                "error": r['exif']['error']
            },
            "vision": {
                "success": r['vision']['success'],
                "parse_success": r['vision']['parse_success'],
                "elapsed": round(r['vision']['elapsed'], 3),
                "tokens": r['vision']['tokens'],
                "summary": summarize_vision(r['vision']['data']) if r['vision']['success'] and r['vision']['parse_success'] else None,
                "error": r['vision']['error']
            }
        }
        serializable.append(sr)

    report = {
        "test_time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "total_photos": len(results),
        "total_elapsed_s": round(total_elapsed, 1),
        "model": MODEL,
        "success_rates": {
            "exif": f"{exif_ok}/{len(results)}",
            "vision": f"{vision_ok}/{len(results)}",
            "vision_parse": f"{vision_parse_ok}/{len(results)}"
        },
        "averages": {
            "exif_time_s": round(sum(exif_times)/len(exif_times), 2) if exif_times else None,
            "vision_time_s": round(sum(vision_times)/len(vision_times), 2) if vision_times else None,
            "vision_prompt_tokens": round(sum(prompt_tokens_list)/len(prompt_tokens_list)) if prompt_tokens_list else None,
            "vision_completion_tokens": round(sum(completion_tokens_list)/len(completion_tokens_list)) if completion_tokens_list else None,
            "vision_total_tokens": round(sum(total_tokens_list)/len(total_tokens_list)) if total_tokens_list else None,
            "vision_total_tokens_sum": sum(total_tokens_list) if total_tokens_list else None
        },
        "results": serializable
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📝 详细结果已保存到: {output_path}")
    print(f"\n{'='*80}")
    print(f"测试完成！")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
