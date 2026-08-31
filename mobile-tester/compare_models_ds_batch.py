#!/usr/bin/env python3
"""DS Flash关思考 vs Pro 批量统计：出错率 + 质量差异（网球场固定输入，方向阶段）

flash 关思考 × N 次 / pro × M 次，统计：
  - JSON 解析成功率
  - 字段完整性（insight / directions 数 / style_brief / photo_guide 长度 / fold_details）
  - 耗时、tokens、推理 tokens
  - 每次的方向质量摘要（供人工对比）
"""
import sys, os, json, time, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
from compare_models import build_directions_prompt, build_plans_prompt, parse_json_content, pick_best_direction

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_URL = "https://api.deepseek.com/chat/completions"

def call(model, extra, messages, max_tokens):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    payload.update(extra)
    req = urllib.request.Request(DS_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    dur = round(time.time() - t0, 2)
    msg = d["choices"][0]["message"]
    content = msg.get("content") or ""
    usage = d.get("usage", {})
    reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    cached = usage.get("prompt_cache_hit_tokens", 0)
    return {"content": content, "dur": dur, "tok": usage.get("total_tokens", 0),
            "reasoning": reasoning, "cached": cached,
            "prompt_tok": usage.get("prompt_tokens", 0)}

def assess(parsed):
    """评估方向输出的字段完整性/质量指标。"""
    if not isinstance(parsed, dict):
        return None
    dirs = parsed.get("directions") or []
    best = pick_best_direction(parsed)
    stats = {
        "n_dirs": len(dirs) if isinstance(dirs, list) else 0,
        "has_insight": bool(parsed.get("insight")),
        "best_style": best.get("style") if best else None,
        "best_kb": best.get("kb_status") if best else None,
        "photo_guide_len": len((best.get("photo_guide") or "")) if best else 0,
        "style_brief_fields": sum(1 for v in ((best.get("style_brief") or {}).values() if best else []) if v),
        "has_fold_details": bool(parsed.get("fold_details")),
        "insight_len": len(parsed.get("insight") or ""),
    }
    return stats

def main():
    if not DEEPSEEK_API_KEY:
        print("❌ no key"); return
    dir_prompt = build_directions_prompt()
    FLASH = 6   # flash 关思考次数
    PRO = 3     # pro 参照次数
    print(f"[directions prompt] {len(dir_prompt)} chars\n")

    rows = []   # {model, round, dur, tok, reasoning, cached, ok, err, stats}
    for model, extra, label, n in [
        ("deepseek-v4-flash", {"thinking": {"type": "disabled"}}, "flash-nothink", FLASH),
        ("deepseek-v4-pro",   {"thinking": {"type": "disabled"}}, "pro-nothink", PRO),
        ("deepseek-v4-pro",   {}, "pro-default", PRO),
    ]:
        for i in range(n):
            r = call(model, extra, [{"role": "user", "content": dir_prompt}], 4000)
            parsed, err = parse_json_content(r["content"])
            st = assess(parsed)
            row = {"model": label, "round": i + 1, "dur": r["dur"], "tok": r["tok"],
                   "reasoning": r["reasoning"], "cached": r["cached"],
                   "ok": parsed is not None, "err": (err or "")[:60], "stats": st,
                   "content": r["content"]}
            rows.append(row)
            flag = "✅" if parsed is not None else "❌"
            print(f"[{label} #{i+1}] {flag} dur={r['dur']}s tok={r['tok']}(推理{r['reasoning']},缓存{r['cached']}) "
                  f"dirs={st['n_dirs'] if st else '-'} best={st['best_style'] if st else '-'} "
                  f"photo_guide={st['photo_guide_len'] if st else 0}chars" + (f" err={err[:50]}" if parsed is None else ""))
            time.sleep(1)  # 避免并发触发限流

    # 汇总
    print("\n===== 汇总 =====")
    for label in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == label]
        ok = sum(1 for r in rs if r["ok"])
        avg_dur = sum(r["dur"] for r in rs) / len(rs)
        avg_tok = sum(r["tok"] for r in rs) / len(rs)
        avg_reason = sum(r["reasoning"] for r in rs) / len(rs)
        avg_pg = sum((r["stats"]["photo_guide_len"] if r["stats"] else 0) for r in rs) / len(rs)
        avg_dir = sum((r["stats"]["n_dirs"] if r["stats"] else 0) for r in rs) / len(rs)
        print(f"{label}: 成功率 {ok}/{len(rs)} | 平均耗时 {avg_dur:.1f}s | 平均tok {avg_tok:.0f}(推理{avg_reason:.0f}) | 平均方向数 {avg_dir:.1f} | 平均photo_guide {avg_pg:.0f}chars")

    # 保存详细到文件
    out = [json.dumps(r, ensure_ascii=False) for r in rows]
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds_batch_raw.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\n原始数据已存: {path}")

if __name__ == "__main__":
    main()
