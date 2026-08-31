#!/usr/bin/env python3
"""DeepSeek 补充测试：加大 max_tokens + 关思考模式 + 模拟线上 JSON 重试兜底。

首轮结果：deepseek-flash 默认模式 max_tokens=4000 被推理吃光返回空；
deepseek-flash 关思考快但 JSON 有一个字符错。本轮验证：
  1) max_tokens 加大后 flash 默认模式能否出结果
  2) pro/flash 关思考的质量与速度
  3) JSON 解析失败时「重试一次提示修复」能否自救（模拟线上 parse_json_safe 兜底）
"""
import sys, os, json, time, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
from compare_models import build_directions_prompt, build_plans_prompt, parse_json_content, pick_best_direction

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_URL = "https://api.deepseek.com/chat/completions"

VARIANTS = [
    ("ds-pro-8k",     "deepseek-v4-pro",   {}),
    ("ds-flash-8k",   "deepseek-v4-flash", {}),
    ("ds-pro-nothink","deepseek-v4-pro",   {"thinking": {"type": "disabled"}}),
    ("ds-flash-nothink", "deepseek-v4-flash", {"thinking": {"type": "disabled"}}),
]

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
    return {"content": content, "dur": dur, "tok": usage.get("total_tokens", 0),
            "reasoning": reasoning, "prompt_tok": usage.get("prompt_tokens", 0)}

def call_with_retry(model, extra, messages, max_tokens):
    """一次调用 + 失败时一次重试（带修复提示），模拟线上 parse_json_safe 兜底。"""
    r1 = call(model, extra, messages, max_tokens)
    parsed, err = parse_json_content(r1["content"])
    if parsed is not None:
        r1["retried"] = False
        return r1, parsed, None
    retry_msg = f"你上次的输出不是有效JSON。请重新输出，只输出纯JSON对象，不要markdown包裹，不要任何额外文字。\n\n上次输出(节选):\n{r1['content'][:300]}"
    try:
        r2 = call(model, extra, messages + [{"role": "user", "content": retry_msg}], max_tokens)
        parsed2, err2 = parse_json_content(r2["content"])
        r1["retried"] = True
        r1["retry_dur"] = r2["dur"]
        r1["retry_tok"] = r2["tok"]
        r1["retry_reasoning"] = r2["reasoning"]
        r1["total_dur"] = round(r1["dur"] + r2["dur"], 2)
        return r1, parsed2, err2
    except Exception as e:
        r1["retried"] = True
        r1["retry_err"] = str(e)[:200]
        return r1, None, "retry_failed"

def main():
    if not DEEPSEEK_API_KEY:
        print("❌ 未设置 DEEPSEEK_API_KEY"); return
    dir_prompt = build_directions_prompt()
    print(f"[directions prompt] {len(dir_prompt)} chars\n")
    report = []
    report.append("# DeepSeek 补充测试：max_tokens + 关思考 + 重试兜底\n")
    report.append("| 变体 | 方向耗时(s) | 方向tok(推理) | 方向解析 | 方案耗时(s) | 方案tok(推理) | 方案解析 | 方案数 |")
    report.append("|------|-----------|--------------|---------|-----------|--------------|---------|--------|")
    for name, model, extra in VARIANTS:
        print(f"===== {name} 方向 =====")
        # 方向：max_tokens 8000（默认思考模式推理吃 token）
        mt = 4000 if extra else 8000
        r, parsed, err = call_with_retry(model, extra, [{"role": "user", "content": dir_prompt}], mt)
        if err or parsed is None:
            print(f"  ❌ 方向失败 dur={r['dur']}s tok={r['tok']}(推理{r['reasoning']}) err={err}")
            report.append(f"| {name} | {r['dur']}(+{r.get('retry_dur','-')}) | {r['tok']}({r['reasoning']}) | ❌ | - | - | - | - |")
            continue
        best = pick_best_direction(parsed)
        print(f"  ✅ dur={r['dur']}s{'+(重试'+str(r['retry_dur'])+'s)' if r.get('retried') else ''} tok={r['tok']}(推理{r['reasoning']}) best={best.get('style') if best else None}")
        r["name"] = name; r["best"] = best.get("style") if best else None
        r["dir_parsed"] = parsed
        r["dir_retry"] = r.get("retried")
        # 方案
        if best:
            plans_prompt = build_plans_prompt(best)
            pr = call(model, extra, [{"role": "user", "content": plans_prompt}], 8000)
            pparsed, perr = parse_json_content(pr["content"])
            pcount = len(pparsed.get("plans", [])) if isinstance(pparsed, dict) else 0
            print(f"  [方案] dur={pr['dur']}s tok={pr['tok']}(推理{pr['reasoning']}) 解析{'✅' if pparsed else '❌'} {pcount}套")
            r["plans_dur"] = pr["dur"]; r["plans_tok"] = pr["tok"]; r["plans_reasoning"] = pr["reasoning"]
            r["plans_ok"] = pparsed is not None; r["plans_count"] = pcount
            r["plans_output"] = pr["content"]
            report.append(f"| {name} | {r['dur']}(+{r.get('retry_dur','-')}) | {r['tok']}({r['reasoning']}) | ✅ | {pr['dur']} | {pr['tok']}({pr['reasoning']}) | {'✅' if pparsed else '❌'} | {pcount} |")
        else:
            report.append(f"| {name} | {r['dur']} | {r['tok']}({r['reasoning']}) | ✅(无best) | - | - | - | - |")
        # 保存方向输出
        r["dir_output"] = r["content"]
    # 详细输出
    report.append("")
    for v in [r for r in [] ]:
        pass
    out = "\n".join(report)
    with open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds_followup_report.md"), "w", encoding="utf-8") as f:
        f.write(out)
    print("\n" + out)

if __name__ == "__main__":
    main()
