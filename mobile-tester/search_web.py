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


def search_style_inspiration(scene_type, people_info="", primary_subject=""):
    """
    搜索风格灵感——基于场景类型搜索社区推荐。

    返回格式化的搜索摘要文本，可直接注入 prompt。
    搜索策略：
    1. 如果有 primary_subject（猫/车/建筑等），优先搜 "{primary_subject} 拍照 技巧"
    2. "{场景摘要} 拍照 风格 摄影" — 通用风格搜索
    3. "{场景摘要} 拍照技巧 构图" — 技法搜索
    """
    # 从 scene_type 提取简短查询词
    scene_short = scene_type
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

    queries = []

    # 如果有明确拍摄主体，优先搜主体相关技巧
    if primary_subject and primary_subject not in ("无", "无法识别", "无明确主体") and len(primary_subject) >= 1:
        # 去掉 [观察][推测] 等标记
        subj = primary_subject.replace("[观察]", "").replace("[推测]", "").strip()
        if len(subj) >= 1:
            queries.append(f"{subj} 拍照 技巧 摄影")
            queries.append(f"{subj} 摄影 构图 光线")

    queries.extend([
        f"{scene_short} 拍照 风格 摄影",
        f"{scene_short} 拍照技巧 构图 姿势",
    ])

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

    # v3.8: 真实性判定 & 有用数据分类
    community_count = sources.get("community", 0)
    portfolio_count = sources.get("portfolio", 0)
    tutorial_count = sources.get("tutorial", 0)

    if community_count >= 3:
        authenticity = "real_community"
    elif community_count + portfolio_count >= 3:
        authenticity = "mixed"
    elif tutorial_count >= 2:
        authenticity = "mixed"
    else:
        authenticity = "unknown"

    # 有用数据标签
    useful_tags = []
    all_snippets = " ".join(r["snippet"][:100] for _, results in all_results for r in results[:2])
    if any(kw in all_snippets for kw in ["姿势", "pose", "站", "动作", "表情"]):
        useful_tags.append("pose_guides")
    if any(kw in all_snippets for kw in ["风格", "色调", "滤镜", "调色", "氛围", "style"]):
        useful_tags.append("style_names")
    if any(kw in all_snippets for kw in ["构图", "角度", "机位", "光线", "光", "视角"]):
        useful_tags.append("techniques")
    if any(kw in all_snippets for kw in ["打卡", "机位", "拍照点", "最佳"]):
        useful_tags.append("location_tips")
    useful_data = ",".join(useful_tags) if useful_tags else "general"

    # 实际搜索关键词
    keywords_used = [q for q, _ in all_results]

    return summary_text, overall, {
        "sources": sources,
        "honest_note": honest_note,
        "keywords": keywords_used,
        "authenticity": authenticity,
        "useful_data": useful_data,
        "total_results": sum(len(results) for _, results in all_results),
    }


def _is_notable_place(place_name):
    """判断地名是否为值得搜索摄影技巧的场所（非随机街道/住宅区）"""
    if not place_name:
        return False
    notable_keywords = [
        # 景区/自然
        "公园", "花园", "植物园", "动物园", "景区", "风景", "山", "峰", "岭", "崖", "峡谷", "瀑布",
        "湖", "河", "海", "沙滩", "海岸", "滨", "湾", "滩", "湿地", "森林", "草原", "沙漠",
        "岛", "温泉", "溶洞", "冰川", "雪山",
        # 城市地标
        "广场", "步行街", "古镇", "老街", "胡同", "里弄", "遗址", "城墙", "宫殿", "园林",
        "塔", "桥", "钟楼", "鼓楼", "大厦", "中心", "剧院", "音乐厅", "艺术",
        # 文博场馆
        "博物馆", "美术馆", "展览", "图书馆", "书店", "教堂", "寺庙", "清真寺", "道观",
        # 商业/娱乐
        "商场", "购物中心", "美食街", "夜市", "酒吧街", "文创园", "创意园", "产业园",
        "体育场", "体育馆", "游泳馆", "滑雪场", "滑冰场", "游乐场", "主题乐园", "乐园",
        "酒店", "度假", "民宿", "咖啡馆", "餐厅",
        # 校园
        "大学", "学院", "校园", "校区",
        # 交通枢纽（有建筑特色）
        "机场", "火车站", "地铁站",
        # 国际
        "park", "beach", "temple", "museum", "gallery", "square", "market",
        "mountain", "lake", "river", "garden", "castle", "palace", "cathedral",
        "stadium", "university", "campus", "resort",
    ]
    # 排除：纯街道地址、小区名、道路名
    exclude_patterns = [
        "路", "街", "巷", "弄", "道", "号", "楼", "单元", "小区", "花园小区",
        "公寓", "座", "层", "室", "栋", "幢", "区", "县", "镇", "乡", "村",
        "派出", "办事", "政府", "居委会", "收费站",
        "road", "street", "ave", "avenue", "lane", "district",
    ]
    # 如果地名只有街道级信息，不搜索
    place_clean = place_name.replace(" ", "").strip()
    # 检车是否为纯地址（如 "XX路XX号"）
    is_address = any(p in place_clean for p in ["路", "街", "巷", "道"])
    if is_address and len(place_clean) <= 10:
        return False
    # 检查是否包含值得拍摄的地标关键词
    has_notable = any(kw in place_clean for kw in notable_keywords)
    if not has_notable:
        return False
    return True


def search_location_intel(place_name, scene_type=""):
    """
    搜索位置摄影情报——如果 GPS 能识别出地名。
    仅在 place_name 为知名景点/地标时搜索，普通街道跳过。

    返回格式化的位置上下文，可直接注入 prompt。
    """
    if not place_name or len(place_name) < 3:
        return "", "🔴"

    # 只搜索值得拍照的场所
    if not _is_notable_place(place_name):
        print(f"[Search] Location skipped (not notable): {place_name[:60]}", file=sys.stderr, flush=True)
        return "", "🔴"

    # 提取简短地名
    place_short = place_name.split("·")[-1].strip() if "·" in place_name else place_name.strip()
    if not place_short or len(place_short) < 2:
        place_short = place_name[:30]

    # 排除旅游攻略类关键词，只搜摄影相关
    travel_blocklist = [
        "旅游", "攻略", "行程", "几日游", "天游", "旅行社", "酒店", "住宿",
        "门票", "美食", "小吃", "购物", "特产", "交通指南", "包车", "导游",
        "跟团", "自由行", "周边游", "一日游", "两日游", "三日游", "周末游",
        "度假", "温泉", "民宿推荐", "必去景点", "十大", "排名",
    ]
    travel_exclude = " ".join(f"-{kw}" for kw in travel_blocklist)

    queries = [
        f"{place_short} 拍照 最佳机位 {travel_exclude}",
        f"{place_short} 摄影 构图 技巧 {travel_exclude}",
    ]

    # 旅游内容二次过滤关键词
    TRAVEL_PATTERNS = [
        "日游", "天游", "行程", "攻略", "旅行社", "酒店", "住宿", "门票",
        "美食推荐", "必吃", "小吃街", "购物", "包车", "导游", "跟团",
        "自由行", "周边游", "度假", "温泉", "民宿", "必去景点",
    ]

    def _is_travel_guide(title, snippet):
        """判断搜索结果是否为旅游攻略而非摄影内容"""
        text = f"{title} {snippet}"
        # 如果标题/摘要主要是旅游攻略关键词，排除
        travel_score = sum(1 for p in TRAVEL_PATTERNS if p in text)
        photo_score = sum(1 for p in ["拍照", "摄影", "机位", "构图", "光线", "打卡", "出片", "pose", "相机", "镜头", "焦段"] if p in text)
        # 旅游关键词多且摄影关键词少 → 判定为旅游攻略
        return travel_score > photo_score

    all_results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_search_one, q, 3): q for q in queries}
        for future in as_completed(futures, timeout=SEARCH_TIMEOUT * 2):
            try:
                results = future.result()
                if results:
                    # 过滤旅游攻略类结果
                    filtered = [r for r in results if not _is_travel_guide(r.get("title",""), r.get("snippet",""))]
                    if filtered:
                        all_results.append(filtered)
                    else:
                        print(f"[Search] Location: all results filtered as travel guides, dropped", file=sys.stderr, flush=True)
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
