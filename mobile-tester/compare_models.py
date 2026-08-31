#!/usr/bin/env python3
"""四模型效率+质量对比：网球场案例（IMG_7004 网球中心观景平台）

对比 DeepSeek V4 Pro / V4 Flash vs 豆包 Seed 2.0 Pro / Lite
固定输入 = 网球场案例的视觉识别 JSON + EXIF + 设备 + 知识库 + 环境上下文。
每个模型跑「方向生成 directions」→「方案生成 plans(best方向)」两阶段，
记录 wall-time / tokens / reasoning tokens / JSON 解析是否成功。

用法：
  DEEPSEEK_API_KEY=sk-xxx python3 compare_models.py [--out docs/xxx.md]
"""
import sys, os, json, time, re, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import server  # 复用全部模板与构建函数

# ───────────────────────── 密钥 ─────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
if not DOUBAO_API_KEY:
    for line in open(os.path.join(SCRIPT_DIR, ".env")):
        if line.startswith("DOUBAO_API_KEY="):
            DOUBAO_API_KEY = line.strip().split("=", 1)[1]

DS_URL = "https://api.deepseek.com/chat/completions"
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"

# 四模型 + DeepSeek 关思考附加变体
MODELS = [
    ("deepseek-pro",     "deepseek-v4-pro",     DS_URL,    DEEPSEEK_API_KEY, {}),
    ("deepseek-flash",   "deepseek-v4-flash",   DS_URL,    DEEPSEEK_API_KEY, {}),
    ("doubao-pro",       "doubao-seed-2.0-pro", DOUBAO_URL, DOUBAO_API_KEY,  {}),
    ("doubao-lite",      "doubao-seed-2.0-lite",DOUBAO_URL, DOUBAO_API_KEY,  {}),
    ("deepseek-flash-no-think", "deepseek-v4-flash", DS_URL, DEEPSEEK_API_KEY,
     {"thinking": {"type": "disabled"}}),  # 附加参考：关思考
]

# ───────────────────────── 固定输入：网球场案例 ─────────────────────────
VISION_JSON = {
    "scene_type": "室外—网球公开赛场馆户外观景平台",
    "people": "1名女性, 棕色羽绒服+浅蓝牛仔裤",
    "light": {"direction": "侧光", "quality": "硬光", "color_temp": "冷约5600K"},
    "color": {"primary": "冷灰色", "secondary": "浅蓝色", "accent": "棕色",
              "mood": "明亮清爽轻松明快"},
}
EXIF_JSON = {
    "device_model": "iPhone 17",
    "shooting_params": {
        "iso": 50, "exposure_time": "1/4065", "brightness": 9.8,
        "flash": {"fired": False}, "white_balance": "Auto",
    },
}
DEVICE_KEY = "iphone-17"
SCENE_TIER = "🥈"
EXIF_SUMMARY = json.dumps(EXIF_JSON, ensure_ascii=False)
EXIF_CROSS_CHECK = ""  # ISO 50 / 1/4065s / 无闪光 / 自动白平衡 → 无交叉验证警告
ENV_CONTEXT = (
    "## 🌤 拍摄环境上下文\n"
    "- 光照时段：🌅 黄金时刻前（太阳 229° 西方，19° 低角——低角度侧暖光，轮廓与氛围感强）\n"
    "- 地点：北京国家网球中心（观景平台）\n"
)
FAST_PATH_NOTE = ""

def build_directions_prompt():
    scene_type = VISION_JSON["scene_type"]
    knowledge_context = server.get_all_knowledge_for_prompt(
        scene_type=scene_type,
        device_key=DEVICE_KEY,
        light_condition=json.dumps(VISION_JSON["light"], ensure_ascii=False),
        fallback_level="medium",
    )
    device_text, _ = server.build_device_context(DEVICE_KEY, None)
    return server.DIRECTIONS_PROMPT.format(
        vision_json=json.dumps(VISION_JSON, ensure_ascii=False, indent=2),
        exif_summary=EXIF_SUMMARY,
        exif_cross_check=EXIF_CROSS_CHECK,
        device_context=device_text,
        knowledge_context=knowledge_context,
        fast_path_note=FAST_PATH_NOTE,
        env_context=ENV_CONTEXT,
    )

def build_plans_prompt(direction):
    scene_type = VISION_JSON["scene_type"]
    scene_category = server.extract_scene_category(scene_type, "") if hasattr(server, "extract_scene_category") else ""
    device_text, _ = server.build_device_context(DEVICE_KEY, None)
    device_constraints = server.build_device_constraints(DEVICE_KEY, None)
    tier_constraint = server.get_tier_constraint(SCENE_TIER)
    style_knowledge = server.get_style_detail(direction.get("style", "")) or ""
    device_knowledge = server.get_device_adaptation(DEVICE_KEY) or ""
    material_inventory = server.build_material_inventory(VISION_JSON)
    forbidden_constraints = server.build_forbidden_constraints(DEVICE_KEY, None, scene_mode=None)
    scene_template = server.build_scene_template(VISION_JSON, scene_category)
    scene_execution_context = ""  # 网球场不命中 street/pet/home
    selfie_context = ""
    series_rhythm = ""  # 🥈 不启用组图节奏

    photo_guide_raw = direction.get("photo_guide", "") or ""
    photo_guide = f"## 🎯 摄影翻译（🆕新风格专属——由方向阶段 AI 翻译）\n{photo_guide_raw.strip()}" if photo_guide_raw.strip() else ""

    sb = direction.get("style_brief", {}) or {}
    style_brief_lines = []
    if sb.get("essence"): style_brief_lines.append(f"核心：{sb['essence']}")
    if sb.get("color"): style_brief_lines.append(f"色彩：{sb['color']}")
    if sb.get("composition"): style_brief_lines.append(f"构图：{sb['composition']}")
    if sb.get("light"): style_brief_lines.append(f"光线：{sb['light']}")
    if sb.get("mood"): style_brief_lines.append(f"情绪：{sb['mood']}")
    style_brief_text = "\n".join(style_brief_lines) if style_brief_lines else "（无特殊视觉约束，基于场景数据自由发挥）"

    return server.PLANS_PROMPT.format(
        vision_json=json.dumps(VISION_JSON, ensure_ascii=False, indent=2),
        material_inventory=material_inventory,
        device_context=device_text,
        style_knowledge=style_knowledge,
        device_knowledge=device_knowledge,
        emoji=direction.get("emoji", ""),
        label=direction.get("label", ""),
        style=direction.get("style", ""),
        style_promise=direction.get("style_promise", ""),
        style_brief=style_brief_text,
        reason=direction.get("reason", ""),
        photo_guide=photo_guide,
        scene_tier=SCENE_TIER,
        tier_constraint=tier_constraint,
        device_constraints=device_constraints,
        env_context=ENV_CONTEXT,
        forbidden_constraints=forbidden_constraints,
        scene_template=scene_template,
        selfie_context=selfie_context,
        scene_execution_context=scene_execution_context,
        series_rhythm=series_rhythm,
    )

# ───────────────────────── 网络调用 ─────────────────────────
def call_api(model_cfg, messages, max_tokens, label):
    name, model, url, key, extra = model_cfg
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    payload.update(extra)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        return {"label": label, "error": str(e)[:300], "duration_s": round(time.time() - t0, 2)}
    dur = round(time.time() - t0, 2)
    msg = d["choices"][0]["message"]
    content = msg.get("content") or ""
    usage = d.get("usage", {})
    reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    return {
        "label": label, "model": model, "duration_s": dur, "content": content,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "reasoning_tokens": reasoning,
    }

def parse_json_content(content):
    """纯解析，不触发任何 API 重试。"""
    if not content:
        return None, "空响应"
    text = content.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text), None
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1]), None
            except (json.JSONDecodeError, ValueError):
                pass
    return None, "JSON解析失败"

def pick_best_direction(parsed):
    if not isinstance(parsed, dict):
        return None
    dirs = parsed.get("directions") or []
    if not isinstance(dirs, list):
        return None
    for d in dirs:
        if isinstance(d, dict) and d.get("id") == "best" and d.get("style"):
            return d
    for d in dirs:
        if isinstance(d, dict) and d.get("style"):
            return d
    return None

# ───────────────────────── 主流程 ─────────────────────────
def main():
    if not DEEPSEEK_API_KEY:
        print("❌ 未设置 DEEPSEEK_API_KEY 环境变量")
        return
    dir_prompt = build_directions_prompt()
    print(f"[directions prompt] {len(dir_prompt)} chars")

    results = []
    for cfg in MODELS:
        name = cfg[0]
        print(f"\n===== {name} — 方向生成 =====")
        r = call_api(cfg, [{"role": "user", "content": dir_prompt}], 4000, "directions")
        if "error" in r:
            r["name"] = name; r["directions_ok"] = False
            results.append(r)
            print(f"  ❌ {r['error']}")
            continue
        parsed, err = parse_json_content(r["content"])
        r["name"] = name
        r["directions_ok"] = parsed is not None
        r["directions_parse_err"] = err
        best = pick_best_direction(parsed)
        r["best_style"] = best.get("style") if best else None
        print(f"  耗时 {r['duration_s']}s | tokens {r['total_tokens']} (推理 {r['reasoning_tokens']}) | 解析{'✅' if parsed else '❌'} | best={r['best_style']}")
        if best:
            plans_prompt = build_plans_prompt(best)
            print(f"  [plans prompt] {len(plans_prompt)} chars — {name}")
            pr = call_api(cfg, [{"role": "user", "content": plans_prompt}], 8000, "plans")
            if "error" in pr:
                r["plans_error"] = pr["error"]
                print(f"  ❌ plans: {pr['error']}")
            else:
                pparsed, perr = parse_json_content(pr["content"])
                r["plans_duration_s"] = pr["duration_s"]
                r["plans_tokens"] = pr["total_tokens"]
                r["plans_reasoning"] = pr["reasoning_tokens"]
                r["plans_ok"] = pparsed is not None
                r["plans_parse_err"] = perr
                r["plans_count"] = len(pparsed.get("plans", [])) if isinstance(pparsed, dict) else 0
                print(f"  方案耗时 {pr['duration_s']}s | tokens {pr['total_tokens']} (推理 {pr['reasoning_tokens']}) | 解析{'✅' if pparsed else '❌'} | {r['plans_count']}套")
                r["plans_output"] = pr["content"]
        r["directions_output"] = r["content"]
        results.append(r)

    # ── 报告输出 ──
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "model_compare_report.md")
    report = render_report(results)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 报告已写入: {out_path}")
    print(report)

def render_report(results):
    L = []
    L.append("# 四模型效率+质量对比 — 网球场案例（IMG_7004）\n")
    L.append(f"固定输入：视觉识别JSON + EXIF(ISO50/1/4065s) + iPhone 17 + 知识库 + 环境上下文\n")
    L.append("| 模型 | 方向耗时 | 方向tokens(推理) | 方向解析 | 方案耗时 | 方案tokens(推理) | 方案解析 | 方案数 | Best方向 |")
    L.append("|------|---------|-----------------|---------|---------|-----------------|---------|--------|---------|")
    for r in results:
        if "error" in r:
            L.append(f"| {r['name']} | ❌ {r['error'][:40]} | | | | | | | |")
            continue
        dir_dur = f"{r['duration_s']}s"
        dir_tok = f"{r['total_tokens']}({r['reasoning_tokens']})"
        dir_ok = "✅" if r.get("directions_ok") else f"❌{r.get('directions_parse_err','')[:20]}"
        pl_dur = f"{r.get('plans_duration_s','-')}s"
        pl_tok = f"{r.get('plans_tokens','-')}({r.get('plans_reasoning','-')})"
        pl_ok = "✅" if r.get("plans_ok") else (f"❌{r.get('plans_error','')[:20]}" if r.get("plans_error") else "-")
        pl_cnt = r.get("plans_count", "-")
        best = r.get("best_style") or "-"
        L.append(f"| {r['name']} | {dir_dur} | {dir_tok} | {dir_ok} | {pl_dur} | {pl_tok} | {pl_ok} | {pl_cnt} | {best} |")
    L.append("")
    for r in results:
        if "error" in r:
            continue
        L.append(f"---\n## {r['name']} — 方向输出\n")
        L.append(f"耗时 {r['duration_s']}s | tokens {r['total_tokens']} (推理 {r['reasoning_tokens']})")
        try:
            parsed = json.loads(parse_json_content(r["directions_output"])[0]) if False else None
        except Exception:
            parsed = None
        L.append("```json")
        L.append(r["directions_output"][:2500])
        L.append("```")
        if r.get("plans_output"):
            L.append(f"\n## {r['name']} — 方案输出（best方向）\n")
            L.append(f"耗时 {r.get('plans_duration_s')}s | tokens {r.get('plans_tokens')} (推理 {r.get('plans_reasoning')})")
            L.append("```json")
            L.append(r["plans_output"][:2500])
            L.append("```")
    return "\n".join(L)

if __name__ == "__main__":
    main()
