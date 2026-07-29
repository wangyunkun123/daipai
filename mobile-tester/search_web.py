"""
带拍 · Web 搜索模块 精确搜索优先——只在有精确信息（具名地点/独特特征/特殊天气）时搜索社区内容。
搜不到精确信息则跳过搜索，由知识库兜底。不搜泛词。

风格+技巧并行搜索，结构化输出（候选方向/位置机位/姿势参考/技法）
"""

import json
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

SEARCH_TIMEOUT = 8  # 秒


def _search_ddg(query, max_results=5, retries=1):
    """DuckDuckGo 搜索（免费，无需 API key），带重试。"""
    import time as _time
    from ddgs import DDGS
    last_err = None
    for attempt in range(retries + 1):
        try:
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
            last_err = e
            if attempt < retries:
                _time.sleep(0.5 * (attempt + 1))  # 0.5s, 1s backoff
    print(f"[Search] DDG error (after {retries+1} tries): {last_err}", file=sys.stderr, flush=True)
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


def _classify_domain(url):
    """统一域名分类"""
    domain = urllib.parse.urlparse(url).netloc
    if any(d in domain for d in ["instagram"]):
        return "instagram"
    elif any(d in domain for d in ["youtube"]):
        return "youtube"
    elif any(d in domain for d in ["tiktok"]):
        return "tiktok"
    elif any(d in domain for d in ["bilibili"]):
        return "bilibili"
    elif any(d in domain for d in ["xiaohongshu", "xhscdn", "red"]):
        return "xiaohongshu"
    elif any(d in domain for d in ["flickr", "500px", "unsplash"]):
        return "portfolio"
    elif any(d in domain for d in ["zhihu", "douyin"]):
        return "tutorial"
    else:
        return "community"


# ============================================================
# 精确信息判定
# ============================================================

# ── 泛场景类型黑名单：这些是通用类型词，不是具名地点，不触发位置搜索 ──
GENERIC_SCENE_TYPES = {
    "沙滩", "海滩", "海边", "海岸", "海滨", "公园", "咖啡馆", "咖啡厅",
    "室内", "街头", "街边", "森林", "树林", "山顶", "山峰", "草地",
    "草坪", "花园", "花海", "广场", "阳台", "天台", "窗边",
}

# ── 场景典型穿着（KB 已覆盖，不值得搜索）──
TYPICAL_ATTIRE = {
    "海边": ["泳衣", "比基尼", "草帽", "太阳镜", "墨镜", "度假裙", "沙滩裤", "拖鞋", "凉拖", "人字拖", "长裙", "碎花裙", "度假", "沙滩", "比基"],
    "沙滩": ["泳衣", "比基尼", "草帽", "太阳镜", "墨镜", "度假裙", "沙滩裤", "拖鞋", "凉拖", "人字拖", "长裙", "碎花裙"],
    "公园": ["休闲装", "T恤", "牛仔裤", "运动装", "连衣裙", "休闲", "日常", "便装", "卫衣", "运动鞋"],
    "咖啡": ["日常装", "休闲", "便装", "T恤", "衬衫", "针织"],
    "街头": ["日常装", "休闲", "T恤", "牛仔裤", "卫衣", "便装", "街头", "潮牌"],
    "森林": ["休闲装", "运动装", "T恤", "冲锋衣", "登山鞋", "运动鞋", "户外"],
    "草地": ["休闲装", "连衣裙", "T恤", "牛仔裤", "便装"],
    "室内": ["日常装", "家居", "睡衣", "T恤", "休闲", "便装"],
}

# ── 独特特征——这些出现在任何场景都值得搜（非典型穿着/造型）──
SEARCH_WORTHY_TRAITS = {
    # 特殊场合
    "婚纱", "礼服", "毕业服", "典礼", "婚礼", "伴娘", "西装",
    # 文化服饰
    "汉服", "旗袍", "JK", "制服", "洛丽塔", "和服", "民族服饰", "cosplay", "cos",
    # 亚文化风格
    "朋克", "哥特", "嘻哈", "蒸汽朋克", "赛博", "原宿", "视觉系",
    # 特殊道具
    "滑板", "机车", "乐器", "画架", "孕照", "宠物狗", "宠物猫", "猫咪", "狗狗",
    "气球", "泡泡机", "吉他", "自行车", "冲浪", "滑雪",
}

# ============================================================
# 中→英翻译（国际平台搜索用，零延迟规则映射）
# ============================================================

# ── 场景翻译 ──
SCENE_EN_MAP = {
    "海边": "beach", "沙滩": "beach", "海滩": "beach", "海滨": "seaside",
    "街头": "street", "街边": "street", "街道": "street", "马路": "street",
    "咖啡厅": "cafe", "咖啡馆": "cafe", "咖啡店": "cafe", "餐厅": "restaurant",
    "公园": "park", "花园": "garden", "植物园": "botanical garden",
    "森林": "forest", "树林": "woods", "竹林": "bamboo forest",
    "草地": "grassland", "草坪": "lawn", "草原": "grassland",
    "山顶": "mountain top", "山峰": "mountain", "山": "mountain",
    "室内": "indoor", "窗边": "window light", "卧室": "bedroom",
    "夜景": "night", "夜晚": "night", "黄昏": "golden hour", "日落": "sunset",
    "日出": "sunrise", "清晨": "morning light",
    "城市": "urban", "都市": "city", "街头": "street",
    "天台": "rooftop", "阳台": "balcony", "屋顶": "rooftop",
    "花海": "flower field", "花田": "flower field",
    "雪景": "snow", "雪地": "snow", "雪": "snow",
    "沙漠": "desert", "戈壁": "desert",
    "湖边": "lakeside", "湖": "lake", "河边": "riverside", "河": "river",
    "泳池": "pool", "游泳池": "pool",
    "废墟": "abandoned building", "废弃": "abandoned",
    "隧道": "tunnel", "地铁": "subway", "车站": "station",
    "教室": "classroom", "校园": "campus", "学校": "school",
    "健身房": "gym", "体育馆": "stadium",
    "图书馆": "library", "书店": "bookstore",
    "商场": "mall", "购物": "shopping",
}

# ── 服饰/特征翻译 ──
TRAITS_EN_MAP = {
    # 特殊场合
    "婚纱": "wedding dress", "礼服": "formal dress", "西装": "suit",
    "毕业服": "graduation gown", "学士服": "graduation gown",
    # 文化/亚文化服饰
    "汉服": "hanfu", "旗袍": "cheongsam",
    "JK制服": "jk uniform", "JK": "jk uniform",
    "洛丽塔": "lolita fashion", "和服": "kimono",
    "民族服饰": "traditional costume", "cosplay": "cosplay",
    # 运动/街头
    "球衣": "jersey", "队服": "jersey", "足球服": "soccer jersey",
    "运动装": "athletic wear", "运动": "sports",
    "泳衣": "swimsuit", "比基尼": "bikini",
    "滑板": "skateboard", "机车": "motorcycle",
    "冲浪": "surfing", "滑雪": "skiing",
    "骑行": "cycling", "自行车": "bicycle",
    # 道具/配件
    "墨镜": "sunglasses", "棒球帽": "baseball cap",
    "草帽": "straw hat", "贝雷帽": "beret",
    "吉他": "guitar", "乐器": "musical instrument",
    "气球": "balloons", "泡泡机": "bubble machine",
    "宠物": "pet", "狗": "dog", "猫": "cat",
    "花束": "bouquet", "捧花": "bouquet",
    "行李箱": "suitcase", "复古车": "vintage car",
    # 服装款式
    "长裙": "long dress", "碎花裙": "floral dress",
    "连衣裙": "dress", "吊带裙": "slip dress",
    "牛仔": "denim", "皮衣": "leather jacket",
    "风衣": "trench coat", "卫衣": "hoodie",
    "毛衣": "knit sweater", "针织": "knit",
    "衬衫": "shirt", "白衬衫": "white shirt",
    "阔腿裤": "wide leg pants", "短裤": "shorts",
    # 其他
    "纹身": "tattoo", "染发": "colored hair",
    "金发": "blonde", "红发": "red hair",
    "卷发": "curly hair", "短发": "short hair",
    "眼镜": "glasses", "口罩": "face mask",
}


def _translate_for_intl(query_cn, scene_type=""):
    """将中文搜索关键词翻译为英文摄影搜索词。

    只做关键词映射，不调 LLM，零延迟。
    输入：中文搜索词（如 "曼联球衣 海边 拍照"）
    输出：英文搜索词（如 "soccer jersey beach photography ideas poses"）
    """
    en_keywords = []
    seen_en = set()

    # 合并所有来源文本用于匹配
    source_text = f"{query_cn} {scene_type}"

    # 1. 提取特征翻译（最长匹配优先，避免"球衣"→"jersey"匹配到"足球服"之前）
    sorted_traits = sorted(TRAITS_EN_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for cn_term, en_term in sorted_traits:
        if cn_term in source_text and en_term not in seen_en:
            en_keywords.append(en_term)
            seen_en.add(en_term)

    # 2. 提取场景翻译
    sorted_scenes = sorted(SCENE_EN_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for cn_term, en_term in sorted_scenes:
        if cn_term in source_text and en_term not in seen_en:
            en_keywords.append(en_term)
            seen_en.add(en_term)
            break  # 只取一个最匹配的场景

    # 3. 构建英文搜索词
    if en_keywords:
        query = " ".join(en_keywords)
    else:
        # 无匹配 → 用通用搜索词
        query = "portrait"

    # 追加摄影上下文
    if "photography" not in query.lower():
        query += " photography"
    query += " ideas poses"

    return query.strip()


# ── 生成国际平台搜索词（英文）──
def _build_intl_queries(distinctive_traits, scene_type=""):
    """为国际平台（Instagram/YouTube/TikTok）生成英文搜索词。"""
    queries = []
    raw_traits = distinctive_traits.strip() if distinctive_traits else ""

    if raw_traits and raw_traits != "无":
        # 用清洗后的 traits 翻译
        cleaned = _clean_traits_for_search(raw_traits, scene_type)
        if cleaned:
            en = _translate_for_intl(cleaned, scene_type)
            if en and "portrait photography ideas poses" not in en:
                queries.append(en)
            # 追加一个带场景的变体
            scene_en = ""
            for cn_term, en_term in sorted(SCENE_EN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
                if cn_term in scene_type or cn_term in raw_traits:
                    scene_en = en_term
                    break
            if scene_en and scene_en not in en:
                queries.append(f"{en.replace(' photography ideas poses', '')} {scene_en} photography ideas poses")

    # 如果没有 traits 但有场景类型
    if not queries:
        scene_en = ""
        for cn_term, en_term in sorted(SCENE_EN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            if cn_term in scene_type:
                scene_en = en_term
                break
        if scene_en:
            queries.append(f"{scene_en} portrait photography ideas poses")
        else:
            queries.append("portrait photography ideas poses")

    return queries[:2]  # 最多 2 个国际查询


def _has_precise_info(location, distinctive_traits, weather_info, sun_times, scene_type):
    """判断是否有精确信息值得去搜索。"""
    if location and _is_notable_place(location):
        return True, "location"
    if distinctive_traits and distinctive_traits.strip() and "无" not in distinctive_traits:
        if _is_search_worthy_trait(distinctive_traits, scene_type):
            return True, "traits"
    if _get_special_weather_tag(weather_info, sun_times, scene_type):
        return True, "weather"
    return False, ""


def _is_search_worthy_trait(traits, scene_type=""):
    """判定 traits 是否值得搜索——逐条检查，而非整串匹配。

    逻辑：
    1. 搜索价值关键词命中任意一条 → 直接 True
    2. 将 traits 按逗号拆分为独立条目，逐条检查
    3. 如果 ALL traits 条目都是场景典型穿着 → False（KB 已覆盖）
    4. 只要有一条非典型 → True（值得搜索）

    这样"曼联球衣,棒球帽,墨镜,一字凉拖"在海边场景：
    - "曼联球衣"非典型 → True ✅（不会被"墨镜"误杀）
    """
    if not traits or not traits.strip():
        return False
    traits_lower = traits.lower()

    # 1. 快速路径：搜索价值关键词命中
    for kw in SEARCH_WORTHY_TRAITS:
        if kw.lower() in traits_lower:
            return True

    # 2. 逐条检查：拆分为独立 trait 条目
    trait_items = [t.strip() for t in traits.replace("，", ",").split(",") if t.strip()]
    if not trait_items:
        return False

    # 3. 如果不在已知场景中 → 搜一下不亏
    if not scene_type:
        return True

    scene_lower = scene_type.lower()
    for scene_kw, typical_list in TYPICAL_ATTIRE.items():
        if scene_kw in scene_lower:
            # 找到了匹配的场景 → 逐条检查
            all_typical = True
            for item in trait_items:
                item_lower = item.lower()
                is_typical = any(typical.lower() in item_lower for typical in typical_list)
                if not is_typical:
                    all_typical = False
                    break  # 有一个非典型就够了

            if all_typical:
                # 全是典型穿着 → KB 已覆盖，不搜
                return False
            else:
                # 至少有一个非典型 → 值得搜
                return True

    # 不在已知典型场景中 → 搜一下
    return True


def _clean_traits_for_search(traits, scene_type=""):
    """清洗 traits 用于搜索——移除场景典型物品，只保留独特信号。

    例：
    "曼联球衣,棒球帽,海边沙滩,一字凉拖,墨镜" + 海边场景
    → 移除典型(棒球帽/墨镜/一字凉拖) → 返回 "曼联球衣"

    这样搜索词不会被"墨镜""棒球帽"等稀释，搜得更精准。
    """
    if not traits or not traits.strip():
        return ""

    # 拆分
    trait_items = [t.strip() for t in traits.replace("，", ",").split(",") if t.strip()]
    if not trait_items:
        return ""

    # 如果没有场景信息，返回全部
    if not scene_type:
        return " ".join(trait_items)

    scene_lower = scene_type.lower()

    # 找到匹配的典型列表
    typical_keywords = set()
    for scene_kw, typical_list in TYPICAL_ATTIRE.items():
        if scene_kw in scene_lower:
            for t in typical_list:
                typical_keywords.add(t.lower())

    if not typical_keywords:
        # 未匹配到已知场景 → 全部保留
        return " ".join(trait_items)

    # 过滤掉典型物品
    cleaned = []
    for item in trait_items:
        item_lower = item.lower()
        is_typical = any(tk in item_lower for tk in typical_keywords)
        if not is_typical:
            cleaned.append(item)

    if cleaned:
        return " ".join(cleaned)
    # 全部被过滤了 → 返回空（说明 traits 全是典型物品）
    return ""


def _is_notable_place(place_name):
    """判断地名是否为值得搜索摄影技巧的场所。
    排除泛场景类型（沙滩/公园/咖啡馆等），只保留具名地点。"""
    if not place_name or len(place_name) < 3:
        return False

    # 泛场景类型黑名单——"沙滩""公园"等不触发位置搜索
    place_clean = place_name.replace(" ", "").strip()
    for generic in GENERIC_SCENE_TYPES:
        if place_clean == generic or place_clean.startswith(generic) or place_clean.endswith(generic):
            # 纯泛类型或泛类型前后缀（如"XX沙滩""公园XX"）→ 不是具名地点
            # 但有具体名称的（如"三亚太阳湾沙滩"→长度>6）放行
            if len(place_clean) <= 6:
                return False
            # 更长但有具体限定词的放行
            if any(kw in place_clean for kw in ["三亚", "亚庇", "巴厘", "普吉", "马尔代夫", "夏威夷",
                                                   "鼓浪屿", "茶卡", "天空之镜", "洱海", "泸沽湖"]):
                return True
            return False

    notable_keywords = [
        "公园", "花园", "植物园", "动物园", "景区", "风景", "山", "峰", "岭", "崖", "峡谷", "瀑布",
        "湖", "河", "海", "沙滩", "海岸", "滨", "湾", "滩", "湿地", "森林", "草原", "沙漠",
        "岛", "温泉", "溶洞", "冰川", "雪山",
        "广场", "步行街", "古镇", "老街", "胡同", "里弄", "遗址", "城墙", "故宫", "宫殿", "园林",
        "塔", "桥", "钟楼", "鼓楼", "大厦", "中心", "剧院", "音乐厅", "艺术",
        "博物馆", "美术馆", "展览", "图书馆", "书店", "教堂", "寺庙", "清真寺", "道观",
        "商场", "购物中心", "美食街", "夜市", "酒吧街", "文创园", "创意园", "产业园",
        "体育场", "体育馆", "游泳馆", "滑雪场", "滑冰场", "游乐场", "主题乐园", "乐园",
        "酒店", "度假", "民宿", "咖啡馆", "餐厅",
        "大学", "学院", "校园", "校区",
        "机场", "火车站", "地铁站",
        "park", "beach", "temple", "museum", "gallery", "square", "market",
        "mountain", "lake", "river", "garden", "castle", "palace", "cathedral",
        "stadium", "university", "campus", "resort",
    ]
    is_address = any(p in place_clean for p in ["路", "街", "巷", "道"])
    if is_address and len(place_clean) <= 10:
        return False
    return any(kw in place_clean for kw in notable_keywords)


def _get_special_weather_tag(weather_info, sun_times, scene_type):
    """提取特殊天气/光线标签（仅特殊条件，常规晴天不触发）。"""
    if sun_times:
        label = sun_times.get("label", "")
        desc = sun_times.get("desc", "")
        if any(w in label + desc for w in ["日落", "黄金", "黄昏", "傍晚", "晚霞"]):
            return "日落"
        if any(w in label + desc for w in ["日出", "清晨", "黎明"]):
            return "日出"
        if "夜间" in label + desc:
            return "夜景"
    if weather_info:
        fc = weather_info.get("forecast", [])
        for f_item in fc[:3]:
            if f_item.get("precip_prob", 0) >= 50:
                return "雨天"
            if "雪" in str(f_item.get("emoji", "")):
                return "雪景"
    if scene_type:
        clean = scene_type.lower()
        for tag, kw in [("雨天", "雨"), ("雪景", "雪"), ("雾天", "雾"), ("夜景", "夜景")]:
            if kw in clean:
                return tag
    return ""


def _shorten_place(place_name):
    """缩短地名：取最后部分，去掉通用词"""
    if not place_name:
        return ""
    # 分割常见分隔符取最后有意义的部分
    for sep in ["·", "的", "—", "-"]:
        if sep in place_name:
            parts = place_name.split(sep)
            place_name = parts[-1].strip()
            break
    # 去省市区前缀
    for prefix in ["马来西亚", "泰国", "日本", "韩国", "中国", "北京", "上海"]:
        if place_name.startswith(prefix) and len(place_name) > len(prefix) + 1:
            place_name = place_name[len(prefix):]
    return place_name.strip()[:30]


def _get_subject_tag(people_info):
    """从 people_info 提取主体简短标签"""
    if not people_info or "无" in str(people_info):
        return ""
    info = str(people_info)
    if "情侣" in info or "夫妻" in info:
        return "情侣"
    if any(w in info for w in ["孩", "童", "亲子", "宝宝"]):
        return "亲子"
    if any(w in info for w in ["猫", "狗", "宠物"]):
        return "宠物"
    if "闺蜜" in info:
        return "闺蜜"
    if "女" in info:
        return "女生"
    if "男" in info:
        return "男生"
    return ""


def _extract_scene_tag(scene_type):
    """从 scene_type 提取简短场景标签（2-6字）"""
    if not scene_type:
        return ""
    clean = scene_type
    for marker in ["推测]", "观察]"]:
        if marker in clean:
            parts = clean.split(marker, 1)
            if len(parts) > 1:
                clean = parts[1].strip()
                break
    for sep in ["，", "。", "、", ",", ".", ";", "；"]:
        idx = clean.find(sep)
        if idx > 0:
            clean = clean[:idx]
            break
    try:
        from knowledge_base import _SCENE_STYLE_ENTRIES
        best_tag = ""
        best_len = 0
        clean_lower = clean.lower()
        for entry in _SCENE_STYLE_ENTRIES:
            for alias in entry["aliases"]:
                if alias.lower() in clean_lower:
                    if len(alias) > best_len and len(alias) <= 6:
                        best_tag = alias
                        best_len = len(alias)
        if best_tag:
            return best_tag
    except Exception:
        pass
    return clean[:6].strip()


# ============================================================
# 搜索词生成——仅精确信息
# ============================================================

def _build_style_queries(location, distinctive_traits, people_info, scene_type=""):
    """构建风格搜索词——只使用风格信号（地点+清洗后的独特traits）。

    🚫 不搜姿势/技法——那是 Stage 2 技巧设计的事。
    用 _clean_traits_for_search 移除典型物品，避免"墨镜/棒球帽"稀释搜索信号。
    """
    queries = []
    place = _shorten_place(location) if location else ""
    # 清洗 traits：移除场景典型物品，只保留独特信号
    raw_traits = distinctive_traits.strip() if distinctive_traits else ""
    traits = _clean_traits_for_search(raw_traits, scene_type) if raw_traits else ""
    subject = _get_subject_tag(people_info)

    if place and traits:
        q = f"{place} {traits} {subject} 拍照 风格".replace("  ", " ").strip()
        queries.append(q)
    elif place and subject:
        q = f"{place} {subject} 拍照 出片 风格".replace("  ", " ").strip()
        queries.append(q)
    elif place:
        queries.append(f"{place} 拍照 出片 风格".strip())
    elif traits and subject:
        q = f"{traits} {subject} 拍照 风格".replace("  ", " ").strip()
        queries.append(q)
    elif traits:
        queries.append(f"{traits} 拍照 风格".strip())

    return queries


def _build_tech_queries(location, distinctive_traits, people_info, scene_type):
    """构建补充搜索词——用清洗后的风格信号搜构图/机位/光影。

    注意：这里搜的是风格层面的"怎么拍更好看"，不包含具体姿势关键词。
    姿势等内容由 Stage 2 从 visual 素材直接设计。
    搜索结果中若碰巧包含技法片段，会被 _extract_techniques 捕获作为 Stage 2 补充。
    """
    queries = []
    place = _shorten_place(location) if location else ""
    raw_traits = distinctive_traits.strip() if distinctive_traits else ""
    traits = _clean_traits_for_search(raw_traits, scene_type) if raw_traits else ""
    subject = _get_subject_tag(people_info)
    scene = _extract_scene_tag(scene_type) if scene_type else ""

    if place and traits:
        q = f"{place} {traits} 拍照 构图 机位".replace("  ", " ").strip()
        queries.append(q)
    elif place:
        base = f"{place} {subject} 拍照 机位 构图".replace("  ", " ").strip()
        queries.append(base)
        queries.append(f"{place} 拍照 最佳时间 光影".strip())
    elif traits:
        if scene:
            q = f"{traits} {scene} 拍照 姿势 构图".replace("  ", " ").strip()
        else:
            q = f"{traits} 拍照 姿势 构图".replace("  ", " ").strip()
        queries.append(q)

    return queries


def _build_weather_queries(location, distinctive_traits, weather_info, sun_times, scene_type):
    """构建天气/光线搜索词（特殊条件时追加）"""
    queries = []
    tag = _get_special_weather_tag(weather_info, sun_times, scene_type)
    if not tag:
        return queries

    place = _shorten_place(location) if location else ""
    traits = distinctive_traits.strip() if distinctive_traits else ""

    if place:
        queries.append(f"{place} {tag} 拍照".strip())
    elif traits:
        queries.append(f"{traits} {tag} 拍照 氛围".strip())
    else:
        queries.append(f"{tag} 人像 拍照 参数 技巧".strip())

    return queries


# ============================================================
# 高赞信号 & 发现提示提取
# ============================================================

SOCIAL_PROOF_PATTERNS = [
    "万赞", "万收藏", "万点赞", "万播放", "万浏览",
    "爆款", "热门", "火了", "刷屏", "刷爆",
    "10万+", "100万", "千万", "百万",
    "收藏", "点赞过", "赞过",
]


def _detect_social_proof(text):
    """检测高赞信号"""
    signals = [p for p in SOCIAL_PROOF_PATTERNS if p in text]
    return signals, len(signals) >= 2


def _extract_discovery_hint(search_text):
    """从搜索结果提取可读摘要（纯规则，不调 LLM）"""
    parts = []

    style_kw = [
        "日系", "胶片", "电影感", "复古", "清新", "高级", "梦幻",
        "港风", "法式", "森系", "极简", "纪实", "杂志", "Lofi",
        "Grunge", "新中式", "县城", "便利店", "安静", "微观",
        "赛博", "蒸汽波", "莫兰迪", "伦勃朗", "霍普", "宫崎骏",
        "运动风", "酷感", "街头", "度假", "慵懒", "甜酷", "飒",
        "JK", "汉服", "婚纱", "旗袍", "学院", "工装", "牛仔",
    ]
    found = [kw for kw in style_kw if kw in search_text]
    if found:
        parts.append(f"风格: {', '.join(found[:4])}")

    tech_kw = ["构图", "光线", "角度", "机位", "逆光", "侧光", "仰拍", "俯拍", "剪影",
               "连拍", "抓拍", "倒影", "前景", "框架", "对称", "引导线"]
    found_tech = [kw for kw in tech_kw if kw in search_text]
    if found_tech:
        parts.append(f"技法: {', '.join(found_tech[:3])}")

    pose_kw = ["姿势", "pose", "动作", "表情", "站姿", "坐姿", "撩", "回头", "不看镜头"]
    if any(kw in search_text for kw in pose_kw):
        parts.append("含姿势指导")

    loc_kw = ["打卡", "机位", "拍照点", "最佳位置", "出片点"]
    if any(kw in search_text for kw in loc_kw):
        parts.append("含机位情报")

    if not parts:
        clean = search_text.replace("##", "").replace("**", "").replace("###", "").strip()
        parts.append(clean[:80])

    return " | ".join(parts)


# ============================================================
# 搜索结果→结构化输出
# ============================================================

def _structure_results(all_style_results, all_tech_results, all_weather_results, community_results=None):
    """
    将原始搜索结果转换为结构化输出。
    返回 {
        "candidate_styles": [...],
        "location_tips": [...],
        "pose_refs": [...],
        "techniques": [...],
        "search_quality": str,
        "keywords_used": [...],
        "discovery_hint": str,
        "has_social_proof": bool,
        "social_signals": [...],
        "raw_summary": str,
    }
    """
    all_results = all_style_results + all_tech_results + all_weather_results
    keywords_used = []
    if all_style_results:
        keywords_used.extend(q for q, _ in all_style_results)
    if all_tech_results:
        keywords_used.extend(q for q, _ in all_tech_results)
    if all_weather_results:
        keywords_used.extend(q for q, _ in all_weather_results)

    if not all_results:
        return {
            "candidate_styles": [], "location_tips": [], "pose_refs": [],
            "techniques": [], "search_quality": "🔴", "keywords_used": keywords_used,
            "discovery_hint": "", "has_social_proof": False, "social_signals": [],
            "raw_summary": "",
        }

    # 汇总所有文本
    all_text = ""
    all_snippets = []
    sources = {}

    for query_text, results in all_results:
        for r in results[:3]:
            snippet = r["snippet"][:200].strip()
            title = r["title"][:100].strip()
            all_text += f"{title} {snippet} "
            all_snippets.append({"title": title, "snippet": snippet, "url": r["url"]})
            src_type = _classify_domain(r["url"])
            sources[src_type] = sources.get(src_type, 0) + 1

    # 🆕 多平台搜索结果（Instagram/YouTube/TikTok/B站/小红书）
    community_snippets = []
    community_summary = ""
    community_styles = []
    if community_results:
        for r in community_results:
            snippet = r.get("snippet", "")[:200].strip()
            title = r.get("title", "")[:100].strip()
            if snippet or title:
                community_snippets.append({"title": title, "snippet": snippet, "url": r.get("url", ""),
                                           "domain": r.get("domain", ""), "source_type": r.get("source_type", ""),
                                           "platform": r.get("platform", r.get("source_type", "unknown"))})
        community_summary = _format_community_summary(community_results)
        community_styles = _extract_community_styles(community_results)
        # 合并到主文本用于检测 + 按平台统计
        for cs in community_snippets:
            all_text += f"{cs['title']} {cs['snippet']} "
            all_snippets.append(cs)
            p = cs.get("platform", "community")
            sources[p] = sources.get(p, 0) + 1

    # 高赞信号
    social_signals, has_social_proof = _detect_social_proof(all_text)

    # 候选风格方向提取（合并社区搜索结果）
    candidate_styles = _extract_candidate_styles(all_snippets)
    # 合并社区搜索发现的风格
    for cs in community_styles:
        if cs not in candidate_styles:
            candidate_styles.append(cs)

    # 位置机位提取
    location_tips = _extract_location_tips(all_snippets)

    # 姿势参考提取
    pose_refs = _extract_pose_refs(all_snippets)

    # 技法提取
    techniques = _extract_techniques(all_snippets)

    # 质量判定——多平台搜索有好结果可提升评级
    # 统计所有平台来源（instagram/youtube/tiktok/bilibili + 旧 community/portfolio/tutorial）
    PLATFORM_KEYS = {"instagram", "youtube", "tiktok", "bilibili", "xiaohongshu", "community"}
    community_count = sum(sources.get(k, 0) for k in PLATFORM_KEYS)
    portfolio_count = sources.get("portfolio", 0)
    tutorial_count = sources.get("tutorial", 0)
    total_results = len(all_snippets)

    # 垃圾检测——域名黑名单 + 摄影相关性过滤
    GARBAGE_DOMAINS = ["canva.com", "amazon.", "ebay.", "shopify.", "walmart.", "aliexpress.",
                       "pinterest.", "etsy.", "temu.", "target.com", "bestbuy."]
    PHOTO_KEYWORDS = ["拍照", "摄影", "照片", "相机", "镜头", "光圈", "快门", "构图", "光线",
                      "人像", "风景", "photo", "camera", "lens", "shoot", "portrait",
                      "pose", "姿势", "拍摄", "写真", "出片", "调色", "滤镜", "后期","胶片", "数码"]

    def _is_relevant(snippet_obj):
        """检查搜索结果是否与摄影相关"""
        text = (snippet_obj.get("title", "") + " " + snippet_obj.get("snippet", "")).lower()
        return any(kw in text for kw in PHOTO_KEYWORDS)

    garbage_count = 0
    for s in all_snippets:
        url = s.get("url", "").lower()
        is_garbage_domain = any(d in url for d in GARBAGE_DOMAINS)
        is_relevant = _is_relevant(s)
        if is_garbage_domain or not is_relevant:
            garbage_count += 1

    real_results = total_results - garbage_count

    if real_results == 0:
        quality = "🔴"
    elif garbage_count >= total_results * 0.5:
        # 一半以上是垃圾 → 降级
        quality = "🟡"
    elif total_results >= 4 and (community_count >= 2 or has_social_proof):
        quality = "🟢"
    elif real_results >= 1:
        quality = "🟡"
    else:
        quality = "🔴"

    # 发现提示
    discovery_hint = _extract_discovery_hint(all_text)

    # 原始摘要（注入 prompt 用）——合并社区搜索结果
    ddg_summary = _format_raw_summary(all_style_results, all_tech_results, all_weather_results)
    raw_summary = ddg_summary
    if community_summary:
        raw_summary = raw_summary + "\n" + community_summary if raw_summary else community_summary

    # 🆕 技法补充摘要——搜索风格时碰巧发现的技法内容，供 Stage 2 参考
    supplemental_techniques_summary = ""
    if techniques or pose_refs:
        tech_lines = []
        if techniques:
            tech_lines.append("### 搜索中发现的社区技法")
            for t in techniques:
                tech_lines.append(f"- {t['content'][:150]}（来源：{t['source_url']}）")
        if pose_refs:
            tech_lines.append("### 搜索中发现的姿势参考")
            for p in pose_refs:
                tech_lines.append(f"- {p['content'][:150]}（来源：{p['source_url']}）")
        supplemental_techniques_summary = "\n".join(tech_lines)

    return {
        "candidate_styles": candidate_styles,
        "location_tips": location_tips,
        "pose_refs": pose_refs,
        "techniques": techniques,
        "search_quality": quality,
        "keywords_used": keywords_used,
        "discovery_hint": discovery_hint,
        "has_social_proof": has_social_proof,
        "social_signals": social_signals,
        "raw_summary": raw_summary,
        "supplemental_techniques_summary": supplemental_techniques_summary,
        "community_summary": community_summary,
        "community_results_count": len(community_snippets),
    }


# ── 垃圾风格名黑名单（非摄影风格，从搜索噪音中误提取的）──
STYLE_GARBAGE_BLACKLIST = {
    "探花系", "人妖系", "旅游系", "美食系", "游戏系", "音乐系",
    "汽车系", "体育系", "科技系", "财经系", "政治系", "军事系",
    "宠物系", "动漫系", "舞蹈系", "戏曲系", "收藏系", "钓鱼系",
    "手工系", "编程系", "电商系", "房产系", "教育系", "医疗系",
}

def _extract_candidate_styles(snippets):
    """从搜索结果中提取候选风格方向"""
    candidates = []
    style_patterns = [
        # 中文风格名模式
        r'([一-鿿]{2,4})(?:风|感|系|美学|风格)',
    ]
    all_text = " ".join(s["title"] + " " + s["snippet"] for s in snippets)

    seen = set()
    for pattern in style_patterns:
        import re
        for m in re.finditer(pattern, all_text):
            name = m.group(0)
            if name not in seen and len(name) >= 2 and name not in STYLE_GARBAGE_BLACKLIST:
                seen.add(name)
                # 提取上下文
                start = max(0, m.start() - 30)
                end = min(len(all_text), m.end() + 80)
                context = all_text[start:end].strip()
                candidates.append({
                    "style_name": name,
                    "context": context,
                    "source": "search",
                })

    return candidates[:5]


def _extract_location_tips(snippets):
    """从搜索结果提取位置机位情报"""
    tips = []
    loc_keywords = ["机位", "打卡点", "拍照点", "最佳位置", "出片", "拍摄点", "观景台", "码头", "步道"]
    for s in snippets:
        text = s["title"] + " " + s["snippet"]
        for kw in loc_keywords:
            if kw in text:
                tips.append({"content": text[:200], "source_url": s["url"]})
                break
    return tips[:3]


def _extract_pose_refs(snippets):
    """从搜索结果提取姿势/表情参考"""
    refs = []
    pose_keywords = ["姿势", "pose", "动作", "撩", "回头", "甩", "站", "坐", "躺",
                     "不看镜头", "侧脸", "微笑", "抓拍", "连拍"]
    for s in snippets:
        text = s["title"] + " " + s["snippet"]
        hits = sum(1 for kw in pose_keywords if kw in text)
        if hits >= 2:
            refs.append({"content": text[:200], "source_url": s["url"]})
    return refs[:3]


def _extract_techniques(snippets):
    """从搜索结果提取可操作技法"""
    techs = []
    tech_keywords = ["构图", "光线", "角度", "对焦", "曝光", "景深", "快门", "滤镜",
                     "焦段", "白平衡", "ISO", "光圈", "逆光", "补光", "反光板"]
    for s in snippets:
        text = s["title"] + " " + s["snippet"]
        hits = sum(1 for kw in tech_keywords if kw in text)
        if hits >= 1:
            techs.append({"content": text[:200], "source_url": s["url"]})
    return techs[:3]


def _format_raw_summary(all_style_results, all_tech_results, all_weather_results):
    """格式化原始搜索结果摘要（纯文本，注入 prompt 用）"""
    lines = ["## 🌐 社区搜索发现\n"]
    all_results = all_style_results + all_tech_results + all_weather_results

    for query_text, results in all_results:
        source_label = ""
        if query_text in [q for q, _ in all_style_results]:
            source_label = " [风格路]"
        elif query_text in [q for q, _ in all_tech_results]:
            source_label = " [技巧路]"
        lines.append(f"### 搜索：「{query_text}」{source_label}")
        for i, r in enumerate(results[:3], 1):
            snippet = r["snippet"][:180].strip()
            title = r["title"][:80].strip()
            lines.append(f"{i}. **{title}** — {snippet}")
        lines.append("")

    return "\n".join(lines)


def _empty_result():
    return {
        "candidate_styles": [], "location_tips": [], "pose_refs": [],
        "techniques": [], "search_quality": "🔴", "keywords_used": [],
        "discovery_hint": "", "has_social_proof": False, "social_signals": [],
        "raw_summary": "",
    }




# ============================================================
# 主搜索函数
# ============================================================

def search_precise(location=None, distinctive_traits=None, people_info="",
                   weather_info=None, sun_times=None, scene_type=""):
    """
    精确搜索——仅在有精确信息时触发社区搜索。
    无精确信息 → 直接返回空结果，由 KB 兜底。
    风格路 + 技巧路 + 天气路并行执行。

    Args:
        location: 具名地点（如"马来西亚亚庇沙皮岛"）
        distinctive_traits: 独特服装/风格特征（如"球衣酷女孩"）
        people_info: Vision 分析的 people 字段
        weather_info: 天气数据
        sun_times: 光照时段数据
        scene_type: Vision 分析的场景类型

    Returns:
        dict: 结构化搜索结果（参见 _structure_results）
    """
    has_precise, precise_type = _has_precise_info(
        location, distinctive_traits, weather_info, sun_times, scene_type
    )

    if not has_precise:
        print(f"[Search] No precise info — skipping search, KB will handle", file=sys.stderr, flush=True)
        return _empty_result()

    print(f"[Search] Precise info ({precise_type}) — searching", file=sys.stderr, flush=True)

    style_qs = _build_style_queries(location, distinctive_traits, people_info, scene_type)
    tech_qs = _build_tech_queries(location, distinctive_traits, people_info, scene_type)
    weather_qs = _build_weather_queries(location, distinctive_traits, weather_info, sun_times, scene_type)

    all_queries = style_qs + tech_qs + weather_qs
    if not all_queries:
        return _empty_result()

    # 去重（保持顺序）
    seen = set()
    unique_queries = []
    for q in all_queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    style_set = set(style_qs)
    tech_set = set(tech_qs)
    weather_set = set(weather_qs)

    all_style_results = []
    all_tech_results = []
    all_weather_results = []

    print(f"[Search] {len(unique_queries)} queries (style={len(style_qs)}, tech={len(tech_qs)}, weather={len(weather_qs)})",
          file=sys.stderr, flush=True)

    # 🆕 多平台搜索（Instagram/YouTube/TikTok/B站）——直接并行，不嵌套 executor
    # 使用清洗后的 traits 作为搜索词（移除典型物品，保留独特信号）
    community_query = _clean_traits_for_search(distinctive_traits, scene_type) if distinctive_traits else ""
    if not community_query and location:
        community_query = _shorten_place(location)
    community_results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        # 主搜索（DDG 通用）
        ddg_futures = {executor.submit(_search_one, q, 3): ("ddg", q) for q in unique_queries}

        # 多平台搜索——直接作为独立 future 提交（不嵌套）
        if community_query:
            en_queries = _build_intl_queries(community_query, scene_type)
            best_en = en_queries[0] if en_queries else ""
            # 国际平台（英文）
            if best_en:
                for platform_key in INTL_PLATFORMS:
                    domain = INTL_PLATFORMS[platform_key]["domain"]
                    full_q = f"site:{domain} {best_en}"
                    ddg_futures[executor.submit(_search_ddg, full_q, 5, 1)] = (platform_key, best_en)
            # 国内平台（B站 + 抖音，中文 via DDG）
            cn_clean = community_query.replace("拍照", "").replace("风格", "").replace("姿势", "").replace("构图", "").strip()
            if cn_clean:
                for platform_key in CN_PLATFORMS:
                    domain = CN_PLATFORMS[platform_key]["domain"]
                    full_q = f"site:{domain} {cn_clean}"
                    ddg_futures[executor.submit(_search_ddg, full_q, 5, 1)] = (platform_key, cn_clean)

        print(f"[Search] {len(ddg_futures)} total futures (DDG general + multi-platform)",
              file=sys.stderr, flush=True)

        # 收集所有结果
        for future in as_completed(ddg_futures, timeout=SEARCH_TIMEOUT * 3):
            source_type, query_text = ddg_futures[future]
            try:
                results = future.result(timeout=3)
                if not results:
                    continue

                if source_type == "ddg":
                    # DDG 通用搜索结果
                    if query_text in style_set:
                        all_style_results.append((query_text, results))
                    elif query_text in tech_set:
                        all_tech_results.append((query_text, results))
                    else:
                        all_weather_results.append((query_text, results))
                    print(f"[Search] DDG: {len(results)} results for '{query_text[:50]}'",
                          file=sys.stderr, flush=True)
                else:
                    # 多平台搜索结果
                    platform_key = source_type
                    domain = INTL_PLATFORMS.get(platform_key, CN_PLATFORMS.get(platform_key, {})).get("domain", "")
                    for r in results:
                        url = r.get("url", "")
                        if domain and domain in url:
                            community_results.append({
                                "title": r.get("title", "")[:120],
                                "url": url,
                                "snippet": r.get("snippet", "")[:200],
                                "source_type": platform_key,
                                "domain": platform_key,
                                "platform": platform_key,
                            })
                    label = INTL_PLATFORMS.get(platform_key, CN_PLATFORMS.get(platform_key, {"label": "?"})).get("label", "?")
                    print(f"[Search] {label}: {len([r for r in results if domain in r.get('url', '')])} results for '{query_text[:40]}'",
                          file=sys.stderr, flush=True)
            except Exception as e:
                label = INTL_PLATFORMS.get(source_type, {}).get("label", source_type) if source_type != "ddg" else "DDG"
                err = str(e)[:80]
                print(f"[Search] {label} error: {err}", file=sys.stderr, flush=True)

        # 社区结果去重
        seen = set()
        unique_community = []
        for r in community_results:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique_community.append(r)
        community_results = unique_community
        if community_results:
            print(f"[Search] Multi-platform total: {len(community_results)} results",
                  file=sys.stderr, flush=True)

    return _structure_results(all_style_results, all_tech_results, all_weather_results, community_results)


# ============================================================
# 向后兼容接口（server.py 用）
# ============================================================

def search_style_inspiration(scene_type, people_info="", primary_subject="",
                             weather_info=None, light_info=None, sun_times=None):
    """
    向后兼容接口——返回 (summary_text, quality_emoji, meta_dict)。
    此接口不再使用，转为由 server.py 直接调用 search_precise()。
    """
    print("[Search] WARNING: search_style_inspiration is deprecated, use search_precise()",
          file=sys.stderr, flush=True)
    result = search_precise(
        distinctive_traits=primary_subject if primary_subject else None,
        people_info=people_info,
        weather_info=weather_info,
        sun_times=sun_times,
        scene_type=scene_type,
    )
    return result.get("raw_summary", ""), result.get("search_quality", "🔴"), result


def search_location_intel(place_name, scene_type="", people_info="", weather_info=None, sun_times=None):
    """
    向后兼容接口——返回 (summary_text, quality_emoji, meta_dict)。
    并入 search_precise()。
    """
    print("[Search] WARNING: search_location_intel is deprecated, use search_precise()",
          file=sys.stderr, flush=True)
    result = search_precise(
        location=place_name,
        people_info=people_info,
        weather_info=weather_info,
        sun_times=sun_times,
        scene_type=scene_type,
    )
    return result.get("raw_summary", ""), result.get("search_quality", "🔴"), result


# ============================================================
# 多平台搜索——Instagram / YouTube / TikTok / B站
# ============================================================

# ── 平台配置 ──
# 国际平台：英文搜索
INTL_PLATFORMS = {
    "instagram": {"domain": "instagram.com", "label": "Instagram", "lang": "en"},
    "youtube": {"domain": "youtube.com", "label": "YouTube", "lang": "en"},
    "tiktok": {"domain": "tiktok.com", "label": "TikTok", "lang": "en"},
}

# 国内平台：中文搜索（也用 DDG site:，因为部分平台 API geo-blocked）
CN_PLATFORMS = {
    "bilibili": {"domain": "bilibili.com", "label": "B站", "lang": "cn"},
    "douyin": {"domain": "douyin.com", "label": "抖音", "lang": "cn"},
    # "xiaohongshu": {"domain": "xiaohongshu.com", "label": "小红书", "lang": "cn"},  # DDG 搜不到内容，待 xhs 包接入
}


def _search_platform_ddg(platform_key, query, max_results=5):
    """用 DDG site: 搜索指定平台（国内+国际通用）。

    使用 ddgs 库（DDG 内部 API），比 HTML 解析更可靠。
    """
    # 查找平台配置
    domain = None
    for platforms in [INTL_PLATFORMS, CN_PLATFORMS]:
        if platform_key in platforms:
            domain = platforms[platform_key]["domain"]
            break
    if not domain:
        return []

    full_query = f"site:{domain} {query}"
    try:
        raw = _search_ddg(full_query, max_results, retries=1)
        results = []
        for r in raw:
            url = r.get("url", "")
            if domain in url:
                results.append({
                    "title": r.get("title", "")[:120],
                    "url": url,
                    "snippet": r.get("snippet", "")[:200],
                    "source_type": platform_key,
                    "domain": platform_key,
                })
        return results
    except Exception as e:
        print(f"[Search] {platform_key} DDG failed: {e}", file=sys.stderr, flush=True)
        return []


def _search_bilibili_ddg(query, max_results=5):
    """搜索 B站——通过 DDG site:bilibili.com（API geo-blocked，降级为 DDG）。"""
    return _search_platform_ddg("bilibili", query, max_results)


def _search_xiaohongshu_placeholder(query, max_results=5):
    """小红书搜索——占位函数，待 xhs Python 包接入。

    计划:
        from xhs import XhsClient
        client = XhsClient(cookie=os.environ.get("XHS_COOKIE", ""))
        notes = client.search_note(keyword=query, page=1)
        return [{"title": n.title, "url": n.share_link, ...} for n in notes]
    """
    return []


def _search_all_platforms(query_cn, scene_type="", max_results=5):
    """并行搜索所有平台。

    Args:
        query_cn: 中文搜索词
        scene_type: 场景类型（用于中→英翻译）
        max_results: 每平台最大结果数

    Returns:
        dict: {platform_key: [results]}
    """
    import os as _os
    all_results = {}
    en_queries = _build_intl_queries(query_cn, scene_type) if query_cn else []
    # B站用中文原词搜索
    cn_clean = query_cn.replace("拍照", "").replace("风格", "").replace("姿势", "").replace("构图", "").strip() if query_cn else ""

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}

        # ── 国际平台：每个平台只搜一次（用最佳英文查询）──
        best_en = en_queries[0] if en_queries else ""
        if best_en:
            for platform_key in INTL_PLATFORMS:
                future = executor.submit(_search_platform_ddg, platform_key, best_en, max_results)
                futures[future] = (platform_key, best_en)

        # ── B站：中文搜索 via DDG（API geo-blocked）──
        if cn_clean:
            future = executor.submit(_search_bilibili_ddg, cn_clean, max_results)
            futures[future] = ("bilibili", cn_clean)

        # ── 小红书：占位（待 xhs 包接入）──
        xhs_enabled = _os.environ.get("XHS_COOKIE", "")
        if xhs_enabled and cn_clean:
            future = executor.submit(_search_xiaohongshu_placeholder, cn_clean, max_results)
            futures[future] = ("xiaohongshu", cn_clean)

        # ── 收集结果 ──
        for future in as_completed(futures, timeout=SEARCH_TIMEOUT + 5):
            platform_key, q = futures[future]
            try:
                results = future.result(timeout=3)
                if results:
                    if platform_key not in all_results:
                        all_results[platform_key] = []
                    all_results[platform_key].extend(results)
                    label = "?"
                    for p in [INTL_PLATFORMS, CN_PLATFORMS]:
                        if platform_key in p:
                            label = p[platform_key]["label"]
                            break
                    print(f"[Search] {label}: {len(results)} results for '{q[:50]}'",
                          file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Search] {platform_key} timeout/error: {e}", file=sys.stderr, flush=True)

    # 去重（按 URL）
    for platform_key in all_results:
        seen = set()
        unique = []
        for r in all_results[platform_key]:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(r)
        all_results[platform_key] = unique[:max_results]

    return all_results


# ── 向后兼容接口 ──

def _search_community(query, max_results=5):
    """社区搜索——多平台并行搜索的简化接口。

    保留此函数以兼容旧代码（search_precise 中的 comm_future 调用）。
    """
    # 提取场景类型
    scene_type = ""
    results = _search_all_platforms(query, scene_type, max_results)
    # 展平为旧格式的列表
    flat = []
    for platform_results in results.values():
        flat.extend(platform_results)
    return flat


def _extract_community_styles(results):
    """从多平台搜索结果提取风格候选"""
    candidates = []
    all_text = " ".join(r.get("title", "") + " " + r.get("snippet", "") for r in results)
    import re
    style_patterns = [
        r'([一-鿿]{2,4})(?:风|感|系|美学|风格)',
    ]
    seen = set()
    for pattern in style_patterns:
        for m in re.finditer(pattern, all_text):
            name = m.group(0)
            if name not in seen and len(name) >= 2 and name not in STYLE_GARBAGE_BLACKLIST:
                seen.add(name)
                start = max(0, m.start() - 30)
                end = min(len(all_text), m.end() + 80)
                context = all_text[start:end].strip()
                candidates.append({
                    "style_name": name,
                    "context": context,
                    "source": "community_search",
                })
    return candidates[:5]


def _format_community_summary(results):
    """格式化多平台搜索结果摘要"""
    if not results:
        return ""

    lines = ["### 📸 多平台搜索发现\n"]

    # 按平台分组
    platform_groups = {}
    for r in results:
        domain = r.get("domain", r.get("source_type", "other"))
        if domain not in platform_groups:
            platform_groups[domain] = []
        platform_groups[domain].append(r)

    # 平台显示名
    PLATFORM_NAMES = {
        "instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok",
        "bilibili": "B站", "douyin": "抖音", "xiaohongshu": "小红书",
        "zhihu": "知乎", "zcool": "站酷",
    }

    for platform_key, items in platform_groups.items():
        name = PLATFORM_NAMES.get(platform_key, platform_key)
        lines.append(f"**{name}** ({len(items)} 条):")
        for r in items[:3]:
            title = r.get("title", "")[:80]
            snippet = r.get("snippet", "")[:150]
            # B站额外信息（DDG 搜索没有播放量，跳过）
            lines.append(f"- {title} — {snippet}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试 1: 有精确信息（地点 + 特征）
    print("=== 测试 1: 精确信息（沙皮岛 + 球衣酷女孩）===")
    result = search_precise(
        location="马来西亚亚庇沙皮岛",
        distinctive_traits="球衣 时尚 酷女孩",
        people_info="1人女性, 球衣, 海边",
        scene_type="[观察]室外 — [推测]热带滨海沙滩",
    )
    print(f"质量: {result['search_quality']}")
    print(f"关键词: {result['keywords_used']}")
    print(f"候选风格: {[c['style_name'] for c in result['candidate_styles']]}")
    print(f"位置机位: {len(result['location_tips'])}条")
    print(f"姿势参考: {len(result['pose_refs'])}条")
    print(f"技法: {len(result['techniques'])}条")
    print(f"高赞: {result['has_social_proof']}")
    print(f"发现提示: {result['discovery_hint']}")
    if result['raw_summary']:
        print(result['raw_summary'][:500])

    # 测试 2: 无精确信息
    print("\n=== 测试 2: 无精确信息 ===")
    result = search_precise(
        scene_type="[观察]室外 — [推测]居民小区户外绿化",
        people_info="无人物",
    )
    print(f"质量: {result['search_quality']}")
    print(f"关键词: {result['keywords_used']}")
    print("（应返回空结果——跳过搜索，走 KB）")

    # 测试 3: 仅独特特征
    print("\n=== 测试 3: 仅独特特征（JK制服）===")
    result = search_precise(
        distinctive_traits="JK制服 校园风",
        people_info="1人女性, JK制服",
        scene_type="[观察]室外 — [推测]校园操场",
    )
    print(f"质量: {result['search_quality']}")
    print(f"关键词: {result['keywords_used']}")
    print(f"候选风格: {[c['style_name'] for c in result['candidate_styles']]}")
