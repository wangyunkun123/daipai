#!/usr/bin/env python3
"""
带拍 - 风格探索日志脚本 v4.0
从 1C 阶段输出的 JSON 中提取风格探索记录，批量写入 guidepic.com

用法：
  python3 log-exploration.py <1c_output.json> [session_id]

输入 JSON 需包含：
  - discovered_styles: [{name, fit_rationale, ...}, ...]
  - creative_directions: [{name, ...}, ...]  (可选——用于判断选取)
  - exclusion: {decisions: [...], ...}        (可选——用于判断舍弃)

输出：
  每个风格调用一次 POST /api/log-style-exploration
"""
import json, sys, os, urllib.request

API = os.environ.get("GUIDEPIC_API", "https://guidepic.com/api/log-style-exploration")


def main():
    if len(sys.argv) < 2:
        print("用法: python3 log-exploration.py <1c_output.json> [session_id]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    session_id = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SESSION_ID", "cli-" + os.urandom(4).hex())

    discovered = data.get("discovered_styles", [])
    directions = data.get("creative_directions", [])
    exclusion = data.get("exclusion", {})

    # 收集选取的风格名和舍弃信息
    selected_names = set()
    for d in directions:
        # creative_directions 里可能直接有 name，也可能嵌套
        name = d.get("name", "") or d.get("type", "")
        if name:
            selected_names.add(name)

    exclusion_map = {}  # style_name → reason
    for exc in exclusion.get("decisions", []):
        # exclusion decisions 可能是字符串或 dict
        if isinstance(exc, dict):
            for k, v in exc.items():
                exclusion_map[k] = str(v)
        elif isinstance(exc, str):
            # 尝试从字符串中提取风格名
            exclusion_map[exc] = exc

    if not discovered:
        print("[log-exploration] 没有 discovered_styles，跳过", file=sys.stderr)
        return

    count = 0
    for s in discovered:
        name = s.get("name", "")
        if not name:
            continue

        # 判断选取还是舍弃
        is_selected = False
        # 直接匹配风格名
        if name in selected_names:
            is_selected = True
        else:
            # 模糊匹配：风格名是否出现在任何 direction 的 name 中
            for dname in selected_names:
                if name in dname or dname in name:
                    is_selected = True
                    break

        if is_selected:
            decision = "selected"
            reason = s.get("fit_rationale", "") or s.get("visual_effect", "") or ""
        else:
            decision = "rejected"
            # 尝试从 exclusion 中找理由
            reason = exclusion_map.get(name, "")
            if not reason:
                # 回退：用 fit_rationale 做理由，但标注未采用
                reason = s.get("fit_rationale", "") or "未匹配到创作方向"

        # 截断 reason
        reason = reason[:500]

        payload = json.dumps({
            "session_id": session_id,
            "style_name": name[:200],
            "decision": decision,
            "reason": reason
        }).encode("utf-8")

        try:
            req = urllib.request.Request(API, data=payload, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read())
            if result.get("success"):
                count += 1
                print(f"  [{decision}] {name}", file=sys.stderr)
            else:
                print(f"  [FAIL] {name}: {result.get('error','?')}", file=sys.stderr)
        except Exception as e:
            print(f"  [ERR] {name}: {e}", file=sys.stderr)

    print(f"[log-exploration] 已记录 {count}/{len(discovered)} 个风格探索", file=sys.stderr)


if __name__ == "__main__":
    main()
