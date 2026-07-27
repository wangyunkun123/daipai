"""
带拍 · Web 搜索模块 v1.0
为风格推荐提供社区验证——搜索真实的小红书/摄影教程/Instagram 内容。
非阻塞设计：搜索在后台运行，不影响主流程。有结果就注入，没有就跳过。
"""

import json
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 搜索超时
SEARCH_TIMEOUT = 8  # 秒

def _search_ddg(query, max_results=5):
    """
    DuckDuckGo 搜索（免费，无需 API key）。
    返回 [{"title": "", "url": "", "snippet": ""}] 或空列表。
    """
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", r.get("href", "")),
                    "snippet": r.get("body", r.get("content", "")),
                })
        return results
    except Exception as e:
        print(f"[Search] DDG error: {e}", file=sys.stderr, flush=True)
        return []


def _search_one(query, max_results=5):
    """单次搜索，带超时保护"""
    result = []
    def _run():
        nonlocal result
        result = _search_ddg(query, max_results)

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=SEARCH_TIMEOUT)

    if t.is_alive():
        print(f"[Search] Timeout: {query[:50]}...", file=sys.stderr, flush=True)
        return []

    return result


def search_style_inspiration(scene_type, people_info=""):
    """
    搜索风格灵感——基于场景类型搜索社区推荐。

    返回格式化的搜索摘要文本，可直接注入 prompt。
    搜索策略：
    1. "{场景摘要} 拍照 风格 摄影" — 通用风格搜索
    2. "{场景摘要} 拍照技巧 构图" — 技法搜索
    """
    # 从 scene_type 提取简短查询词
    # scene_type 格式如："[观察]室外 — [推测]城市居民小区公共草坪绿地..."
    scene_short = scene_type
    # 提取 [推测] 或 [观察] 后的简短描述
    for marker in ["推测]", "观察]"]:
        if marker in scene_type:
            parts = scene_type.split(marker, 1)
            if len(parts) > 1:
                scene_short = parts[1].strip()
                break

    # 截取前30字作为搜索关键词
    scene_short = scene_short[:60].split("，")[0].split("。")[0].split("依据")[0].strip()
    if not scene_short or len(scene_short) < 3:
        scene_short = scene_type[:60]

    queries = [
        f"{scene_short} 拍照 风格 摄影",
        f"{scene_short} 拍照技巧 构图 姿势",
    ]

    # 有人物时加搜人像技巧
    if people_info and "无" not in people_info:
        queries.append(f"{scene_short} 人像拍照 姿势 引导")

    all_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_search_one, q, 3): q for q in queries}
        for future in as_completed(futures, timeout=SEARCH_TIMEOUT * 2):
            query = futures[future]
            try:
                results = future.result()
                if results:
                    all_results.append((query, results))
                    print(f"[Search] Found {len(results)} results for: {query[:50]}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Search] Failed: {query[:50]} - {e}", file=sys.stderr, flush=True)

    if not all_results:
        return "", "🔴", {}

    # 格式化搜索摘要
    summary_lines = ["## 🌐 社区搜索发现\n"]
    sources = {}

    for query, results in all_results:
        summary_lines.append(f"### 搜索：「{query}」")
        for i, r in enumerate(results[:3], 1):
            snippet = r["snippet"][:150].strip()
            title = r["title"][:80].strip()
            summary_lines.append(f"{i}. **{title}** — {snippet}")
            # 记录来源类型
            domain = urllib.parse.urlparse(r["url"]).netloc
            if any(d in domain for d in ["xiaohongshu", "xhscdn", "red"]):
                src_type = "community"
            elif any(d in domain for d in ["instagram", "flickr", "500px", "unsplash"]):
                src_type = "portfolio"
            elif any(d in domain for d in ["youtube", "bilibili", "zhihu", "douyin"]):
                src_type = "tutorial"
            else:
                src_type = "community"  # default to community
            if src_type not in sources:
                sources[src_type] = 0
            sources[src_type] += 1
        summary_lines.append("")

    overall = "🟢" if len(all_results) >= 2 else "🟡"
    summary_text = "\n".join(summary_lines)

    # 构建 honest_note
    honest_note = ""
    if overall == "🟡":
        honest_note = "社区搜索结果有限——以下风格推荐主要基于摄影原理推理，非社区验证。"

    return summary_text, overall, {"sources": sources, "honest_note": honest_note}


def search_location_intel(place_name, scene_type=""):
    """
    搜索位置摄影情报——如果 GPS 能识别出地名。

    返回格式化的位置上下文，可直接注入 prompt。
    """
    if not place_name or len(place_name) < 3:
        return "", "🔴"

    # 提取简短地名
    place_short = place_name.split("·")[-1].strip() if "·" in place_name else place_name.strip()
    if not place_short or len(place_short) < 2:
        place_short = place_name[:30]

    queries = [
        f"{place_short} 拍照 最佳机位",
        f"{place_short} 摄影 推荐 打卡",
    ]

    all_results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_search_one, q, 3): q for q in queries}
        for future in as_completed(futures, timeout=SEARCH_TIMEOUT * 2):
            try:
                results = future.result()
                if results:
                    all_results.append(results)
            except Exception:
                pass

    if not all_results:
        return "", "🔴"

    summary_lines = [f"## 📍 位置情报：「{place_short}」\n"]
    for results in all_results:
        for r in results[:3]:
            snippet = r["snippet"][:120].strip()
            title = r["title"][:60].strip()
            summary_lines.append(f"- **{title}**：{snippet}")

    summary_lines.append("")
    overview = "🟢" if len(all_results) >= 2 else "🟡"
    return "\n".join(summary_lines), overview


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    text, overall, meta = search_style_inspiration(
        "室外公园草地，人物和小狗",
        "1人女性+1小狗"
    )
    print(f"质量: {overall}")
    print(f"长度: {len(text)} 字符")
    print(text[:500])
    if meta.get("honest_note"):
        print(f"诚实告知: {meta['honest_note']}")
