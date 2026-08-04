#!/usr/bin/env python3
"""
审美过滤模块 v1.0 —— 程序化筛除明显审美冲突的方向。

设计原则：
- 只筛除程序可确定判断的"不应该"（审美冲突），不处理"做不到"（技术限制）
- 筛除后始终替换，不减少方向数量
- 风格无配置 → 不筛除（保守策略）
- 场景特征缺失 → 只用最确定的约束（保守策略）
- 纯函数、无副作用、线程安全
"""

# ============================================================
# 风格审美约束配置
# ============================================================
# 仅配置有明显且可程序化检测的审美约束的风格。
# 通用风格（日系清新/安静真实/胶片复古/电影感/法式慵懒/Lofi直闪等）
# 不在此配置——它们在几乎所有场景都安全，不应被程序化筛除。

_STYLE_PROFILES = {
    # ── 需要干净/开阔空间的风格 ──
    "极简高级": {
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "f_and_b", "industrial_ruins",
        ],
        "requires_open_space": True,
    },

    # ── 需要自然风景的风格 ──
    "水彩风景感": {
        "forbidden_categories": [
            "commercial", "urban_street", "industrial_ruins",
            "night_scene", "transit_station", "residential",
        ],
        "required_categories": ["park_nature", "waterside", "cultural_site"],
        "requires_light_quality": "soft",
    },

    "森系": {
        "required_categories": ["park_nature", "waterside"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "transit_station", "industrial_ruins", "residential",
        ],
        "requires_open_space": True,
    },

    "田园生活": {
        "required_categories": ["park_nature", "waterside"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "industrial_ruins", "transit_station",
        ],
    },

    "中国水墨": {
        "required_categories": ["park_nature", "waterside", "cultural_site"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "industrial_ruins", "transit_station", "residential",
        ],
        "requires_light_quality": "soft",
        "requires_open_space": True,
    },

    "宫崎骏吉卜力": {
        "required_categories": ["park_nature", "waterside"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "industrial_ruins", "transit_station", "residential",
        ],
        "requires_open_space": True,
        "requires_sky_visible": True,
    },

    "新海诚天空": {
        "forbidden_categories": [
            "industrial_ruins", "residential", "transit_station",
        ],
        "requires_sky_visible": True,
    },

    # ── 需要城市/人造环境的风格 ──
    "赛博朋克": {
        "required_categories": ["night_scene", "urban_street", "commercial"],
        "forbidden_categories": [
            "park_nature", "waterside", "residential", "cultural_site",
        ],
    },

    "港风复古": {
        "required_categories": ["night_scene", "urban_street", "commercial"],
        "forbidden_categories": [
            "park_nature", "waterside", "residential",
            "cultural_site", "industrial_ruins",
        ],
    },

    "便利店美学": {
        "required_categories": ["f_and_b", "commercial", "night_scene"],
        "forbidden_categories": [
            "park_nature", "waterside", "industrial_ruins",
        ],
    },

    "县城记忆": {
        "required_categories": ["urban_street", "industrial_ruins"],
        "forbidden_categories": [
            "commercial", "residential", "park_nature",
            "waterside", "cultural_site",
        ],
    },

    # ── 需要文化/建筑场景的风格 ──
    "新中式": {
        "required_categories": ["cultural_site", "park_nature"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "industrial_ruins", "transit_station",
        ],
    },

    "韦斯安德森": {
        "forbidden_categories": [
            "industrial_ruins", "park_nature", "waterside",
        ],
        # 韦斯安德森需要建筑对称性，自然场景难以满足
    },

    "暗调学院": {
        "forbidden_categories": [
            "park_nature", "waterside", "sports_venue",
        ],
        # 需要室内/建筑环境的深色木质调
    },

    # ── 光质敏感的风格 ──
    "梦幻柔美": {
        "forbidden_light_qualities": ["hard"],
        "forbidden_categories": [
            "industrial_ruins", "night_scene", "transit_station",
        ],
    },

    "莫兰迪色系": {
        "requires_light_quality": "soft",
        "forbidden_categories": [
            "night_scene", "industrial_ruins",
        ],
    },

    "奶油风": {
        "requires_light_quality": "soft",
        "forbidden_light_qualities": ["hard"],
        "forbidden_categories": [
            "night_scene", "industrial_ruins",
        ],
    },

    # ── 需要受控环境的风格 ──
    "杂志时尚": {
        "forbidden_categories": [
            "industrial_ruins", "park_nature",
        ],
        # 公园/废墟缺乏控光条件
    },

    "纪实粗粝": {
        "forbidden_categories": ["residential"],
        # 纪实粗粝的粗颗粒/高对比不适合温馨居家
    },

    "浮世绘": {
        "forbidden_categories": ["industrial_ruins", "residential"],
    },

    # ── 需要特定人物的风格 ──
    "霍普式孤独": {
        "requires_indoor": True,
        "forbidden_categories": [
            "park_nature", "waterside", "sports_venue",
        ],
        # 霍普式孤独=窗边单人+室内光+长影子，户外自然场景完全无法表达
    },

    "伦勃朗光": {
        "forbidden_categories": [
            "park_nature", "waterside",
        ],
        # 需要方向性窗光或可控光源，户外自然光难以实现三角光斑
    },

    "宋画山水": {
        "required_categories": ["park_nature", "waterside", "cultural_site"],
        "forbidden_categories": [
            "commercial", "urban_street", "night_scene",
            "industrial_ruins", "transit_station", "residential",
        ],
        "requires_open_space": True,
    },

    "中式梦核": {
        "forbidden_categories": [
            "park_nature", "waterside", "sports_venue",
        ],
        # 中式梦核=2000年代室内/建筑，需要人造空间
    },

    "阈限空间": {
        "forbidden_categories": [
            "park_nature", "waterside",
        ],
        # 阈限空间=空荡走廊/建筑内部，自然场景无法表达
    },
}

# ============================================================
# 场景类别 → 安全替代风格
# ============================================================

# ── 共享 style_brief 模板，避免重复定义 ──
_BRIEF_安静真实 = {
    "essence": "生活刚好被看见", "color": "中性偏暖",
    "composition": "自然视角", "light": "场景自然光", "mood": "安静日常",
}
_BRIEF_日系清新 = {
    "essence": "空气感的画面", "color": "低饱和蓝绿偏移",
    "composition": "留白+自然视角", "light": "柔光过曝倾向", "mood": "清新治愈",
}
_BRIEF_胶片复古 = {
    "essence": "有温度的旧照片", "color": "暖色偏移+褪色",
    "composition": "自然抓拍", "light": "场景光+暖调", "mood": "怀旧温暖",
}
_BRIEF_纪实粗粝 = {
    "essence": "真实的力量", "color": "黑白倾向+高对比",
    "composition": "直接正面", "light": "硬光+深阴影", "mood": "粗粝真实",
}
_BRIEF_电影感 = {
    "essence": "电影里的一帧", "color": "色彩分级冷暖对比",
    "composition": "宽画幅叙事构图", "light": "方向性光+暗部", "mood": "故事感张力",
}
_BRIEF_极简高级 = {
    "essence": "少即是多", "color": "低饱和克制",
    "composition": "几何秩序+留白", "light": "均匀柔光", "mood": "冷静高级",
}

_FALLBACK_BY_CATEGORY = {
    # 格式：primary（首选）+ secondary（去重碰撞时备用）
    # v1.1: 每个分类有二级兜底，避免方向被清空
    "commercial": {
        "primary": {
            "style": "胶片复古",
            "style_promise": "给商业空间一点旧时光的温度",
            "fit_rationale": "胶片复古的暖色调让商业空间少一点冷峻，多一点人情味——任何商业场景的安全选择",
            "style_brief": _BRIEF_胶片复古,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "如实记录这个空间的氛围",
            "fit_rationale": "安静真实不加修饰——让商业空间自身的氛围说话",
            "style_brief": _BRIEF_安静真实,
        },
    },
    # v1.1: urban_street 从"安静真实"改为"纪实粗粝"——街头摄影天然是纪实
    "urban_street": {
        "primary": {
            "style": "纪实粗粝",
            "style_promise": "捕捉街头真实的瞬间",
            "fit_rationale": "纪实粗粝的高对比+真实感是街头摄影的经典语言——街头的纹理和光影就是最好的素材",
            "style_brief": _BRIEF_纪实粗粝,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "如实记录街头这一刻的样子",
            "fit_rationale": "安静真实是街头摄影的安全选择——不改变场景，只如实呈现街头的生活感",
            "style_brief": _BRIEF_安静真实,
        },
    },
    "park_nature": {
        "primary": {
            "style": "日系清新",
            "style_promise": "让自然的光和空气充满画面",
            "fit_rationale": "日系清新的高调+低饱和天然适合户外自然场景——光线和绿色就是最好的素材",
            "style_brief": _BRIEF_日系清新,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "让自然自己说话",
            "fit_rationale": "安静真实不加滤镜——自然场景本身的光影和色彩已经足够好",
            "style_brief": _BRIEF_安静真实,
        },
    },
    "waterside": {
        "primary": {
            "style": "日系清新",
            "style_promise": "让水面和天空一起呼吸",
            "fit_rationale": "水边的开阔+天空+自然光天然匹配日系清新的空气感——拍出来干净通透",
            "style_brief": _BRIEF_日系清新,
        },
        "secondary": {
            "style": "极简高级",
            "style_promise": "让水面成为纯粹的画布",
            "fit_rationale": "水面的开阔+水平线天然适合极简高级——用几何秩序组织水天一色",
            "style_brief": _BRIEF_极简高级,
        },
    },
    "night_scene": {
        "primary": {
            "style": "电影感",
            "style_promise": "让夜晚的灯光讲一个故事",
            "fit_rationale": "电影感的叙事性+色彩分级天然适合夜景——每一盏灯都是一个故事的开头",
            "style_brief": _BRIEF_电影感,
        },
        "secondary": {
            "style": "纪实粗粝",
            "style_promise": "捕捉夜晚的真实质感",
            "fit_rationale": "纪实粗粝的高对比黑白在夜景中反而纯粹——去掉色彩干扰，只留光影结构",
            "style_brief": _BRIEF_纪实粗粝,
        },
    },
    "f_and_b": {
        "primary": {
            "style": "胶片复古",
            "style_promise": "给这个空间一点胶片温度",
            "fit_rationale": "咖啡厅/餐厅的暖光+木质+食物天然适合胶片复古的暖调——像旧照片里的美好日常",
            "style_brief": _BRIEF_胶片复古,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "记录这个空间的日常氛围",
            "fit_rationale": "安静真实让咖啡厅/餐厅的氛围自己说话——不添加多余修饰",
            "style_brief": _BRIEF_安静真实,
        },
    },
    "industrial_ruins": {
        "primary": {
            "style": "纪实粗粝",
            "style_promise": "让废墟的纹理自己说话",
            "fit_rationale": "纪实粗粝的高对比+粗颗粒天然适合废墟/工厂——纹理和光影就是最好的素材",
            "style_brief": _BRIEF_纪实粗粝,
        },
        "secondary": {
            "style": "电影感",
            "style_promise": "把废墟变成电影场景",
            "fit_rationale": "电影感的叙事构图+色彩分级可以把废墟拍成末世电影里的一个画面",
            "style_brief": _BRIEF_电影感,
        },
    },
    # v1.1: cultural_site 从"安静真实"改为"极简高级"——文化遗产的建筑秩序需要克制的视觉语言
    "cultural_site": {
        "primary": {
            "style": "极简高级",
            "style_promise": "让建筑和光影安静地对话",
            "fit_rationale": "极简高级的几何秩序+克制色彩最配文化遗产的建筑美学——不抢镜，只呈现",
            "style_brief": _BRIEF_极简高级,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "让文化遗产自己讲述历史",
            "fit_rationale": "安静真实不添加多余的风格滤镜——让文化遗产用自己的光影和纹理说话",
            "style_brief": _BRIEF_安静真实,
        },
    },
    "residential": {
        "primary": {
            "style": "安静真实",
            "style_promise": "让家的样子就是家的样子",
            "fit_rationale": "安静真实天然适合居家场景——不需要摆拍，家的日常就是最好的素材",
            "style_brief": _BRIEF_安静真实,
        },
        "secondary": {
            "style": "胶片复古",
            "style_promise": "给家的日常一点胶片温度",
            "fit_rationale": "胶片复古的暖调让居家日常更有温度——像家庭相册里的老照片",
            "style_brief": _BRIEF_胶片复古,
        },
    },
    "transit_station": {
        "primary": {
            "style": "纪实粗粝",
            "style_promise": "捕捉流动人群中的静止瞬间",
            "fit_rationale": "交通枢纽的人流+建筑结构天然适合纪实粗粝——在混乱中找到秩序",
            "style_brief": _BRIEF_纪实粗粝,
        },
        "secondary": {
            "style": "电影感",
            "style_promise": "把通勤变成电影开场",
            "fit_rationale": "电影感的宽画幅+色彩分级让交通枢纽变成都市电影的场景——人流就是最好的演员",
            "style_brief": _BRIEF_电影感,
        },
    },
    "campus": {
        "primary": {
            "style": "日系清新",
            "style_promise": "让校园的光和青春感充满画面",
            "fit_rationale": "校园的开阔+绿化+建筑天然适合日系清新的明亮调性——像青春电影里的一帧",
            "style_brief": _BRIEF_日系清新,
        },
        "secondary": {
            "style": "胶片复古",
            "style_promise": "给校园时光一点怀旧温度",
            "fit_rationale": "胶片复古的褪色暖调天然适合校园——像毕业很多年后翻看的老照片",
            "style_brief": _BRIEF_胶片复古,
        },
    },
    "sports_venue": {
        "primary": {
            "style": "纪实粗粝",
            "style_promise": "捕捉运动中的力量感和瞬间",
            "fit_rationale": "运动场景的动态+张力天然适合纪实粗粝——高对比让动作更有力量",
            "style_brief": _BRIEF_纪实粗粝,
        },
        "secondary": {
            "style": "电影感",
            "style_promise": "把运动拍成热血电影",
            "fit_rationale": "电影感的叙事构图+色彩分级让运动瞬间更有戏剧张力",
            "style_brief": _BRIEF_电影感,
        },
    },
    "outdoor_generic": {
        "primary": {
            "style": "日系清新",
            "style_promise": "让户外的光和空气充满画面",
            "fit_rationale": "户外场景的开阔+自然光天然适合日系清新的明亮通透——不容易出错",
            "style_brief": _BRIEF_日系清新,
        },
        "secondary": {
            "style": "安静真实",
            "style_promise": "如实记录户外的这一刻",
            "fit_rationale": "安静真实在户外同样适用——不加修饰，只呈现户外的光和空间",
            "style_brief": _BRIEF_安静真实,
        },
    },
    "indoor_generic": {
        "primary": {
            "style": "安静真实",
            "style_promise": "如实记录室内的这一刻",
            "fit_rationale": "室内场景天然适合安静真实——不改变光线和布局，只如实呈现",
            "style_brief": _BRIEF_安静真实,
        },
        "secondary": {
            "style": "胶片复古",
            "style_promise": "给室内空间一点胶片温度",
            "fit_rationale": "胶片复古的暖调让任何室内空间多一层怀旧氛围",
            "style_brief": _BRIEF_胶片复古,
        },
    },
    "_default": {
        "primary": {
            "style": "安静真实",
            "style_promise": "如实记录眼前的这一刻",
            "fit_rationale": "安静真实是万能的安全选择——不改变场景，只如实呈现。任何场景都能拍",
            "style_brief": _BRIEF_安静真实,
        },
        "secondary": {
            "style": "日系清新",
            "style_promise": "让画面明亮通透",
            "fit_rationale": "日系清新的明亮调性是不确定场景的通用安全牌——画面干净不容易出错",
            "style_brief": _BRIEF_日系清新,
        },
    },
}


# ============================================================
# 场景特征提取
# ============================================================

def _classify_light_quality(light_dict):
    """从 vision_json.light 中提取光质分类。"""
    if not isinstance(light_dict, dict):
        return "unknown"

    quality = light_dict.get("quality", "")
    level = light_dict.get("level", "")
    direction = light_dict.get("direction", "")
    text = f"{quality} {level} {direction}".lower()

    # 漫射光/阴天——最明确的信号
    if any(w in text for w in ["漫射", "diffuse", "阴", "多云", "overcast", "cloudy"]):
        return "diffuse"
    # 软光
    if any(w in text for w in ["软", "soft", "柔", "柔光"]):
        return "soft"
    # 硬光
    if any(w in text for w in ["硬", "hard", "强光", "直射", "harsh"]):
        return "hard"

    # 从光比推断
    ratio = light_dict.get("ratio", "")
    if isinstance(ratio, str):
        try:
            # 尝试解析 "1:4" 格式
            parts = ratio.replace("≤", "").replace("≥", "").split(":")
            if len(parts) == 2:
                r = float(parts[0]) / float(parts[1])
                if r >= 0.25:  # 1:4 及以上 = 软光
                    return "soft"
                else:
                    return "hard"
        except (ValueError, ZeroDivisionError):
            pass

    return "unknown"


def _detect_sky(vision_json):
    """检测画面中是否有可见天空。"""
    if not isinstance(vision_json, dict):
        return False

    space = vision_json.get("space", {})
    if isinstance(space, dict):
        bg = space.get("background", "")
        if any(w in bg for w in ["天空", "sky", "云天"]):
            return True

    composition = vision_json.get("composition", "")
    if any(w in composition for w in ["天空", "sky", "云天"]):
        return True

    scene_type = vision_json.get("scene_type", "")
    if any(w in scene_type for w in ["蓝天", "天空", "晴天", "户外", "室外"]) and "室内" not in scene_type:
        return True

    return False


def _detect_open_space(vision_json, scene_category):
    """检测场景是否为开阔空间。"""
    if not isinstance(vision_json, dict):
        return False

    open_categories = {"park_nature", "waterside", "sports_venue", "campus"}
    confined_categories = {"commercial", "urban_street", "residential", "transit_station",
                           "f_and_b", "night_scene", "indoor_generic"}

    space = vision_json.get("space", {})
    if isinstance(space, dict):
        depth = space.get("depth", "")
        if "深" in depth and scene_category in open_categories:
            return True
        if "浅" in depth and scene_category in confined_categories:
            return False

    scene_type = vision_json.get("scene_type", "")
    if any(w in scene_type for w in ["开阔", "一望无际", "广袤", "空旷"]):
        return True
    if any(w in scene_type for w in ["拥挤", "狭窄", "巷弄", "室内"]):
        return False

    # 按类别推断
    if scene_category in open_categories:
        return True
    if scene_category in confined_categories:
        return False

    return False


def _detect_crowded(vision_json, scene_category):
    """检测场景是否拥挤。"""
    if not isinstance(vision_json, dict):
        return False

    scene_type = vision_json.get("scene_type", "")
    # 明确拥挤信号
    if any(w in scene_type for w in ["拥挤", "人山人海", "热闹", "人群", "游客", "游人"]):
        return True

    # 商业街默认有一定人流
    if scene_category == "commercial":
        space = vision_json.get("space", {})
        if isinstance(space, dict):
            midground = space.get("midground", "")
            if any(w in midground for w in ["人", "游客", "行人", "商铺"]):
                return True

    return False


def _detect_people(people_str):
    """检测画面中是否有人物。"""
    if not people_str:
        return False
    if any(w in str(people_str) for w in ["无人", "无人物", "没有人", "none", "no people"]):
        return False
    return True


def _extract_scene_features(vision_json, scene_category):
    """从 vision_json 提取场景特征 dict。"""
    if not isinstance(vision_json, dict):
        vision_json = {}

    scene_type = vision_json.get("scene_type", "")
    light_dict = vision_json.get("light", {})

    features = {
        "category": scene_category or "",
        "light_quality": _classify_light_quality(light_dict),
        "is_indoor": "室内" in str(scene_type),
        "sky_visible": _detect_sky(vision_json),
        "is_open_space": _detect_open_space(vision_json, scene_category),
        "is_crowded": _detect_crowded(vision_json, scene_category),
        "has_people": _detect_people(vision_json.get("people", "")),
    }
    return features


# ============================================================
# 冲突检测
# ============================================================

def _check_rule1_insight_conflict(profile, style_name, features):
    """Rule 1 - 洞察冲突：场景类别/空间/天空约束。"""
    cat = features["category"]

    # 场景类别禁止
    forbidden = profile.get("forbidden_categories", [])
    if forbidden and cat and cat in forbidden:
        reason = (
            f"场景类别 '{cat}' 与 '{style_name}' 审美冲突"
            f"（该风格在此类场景中失去核心表达力）"
        )
        return True, reason

    # 场景类别必需
    required = profile.get("required_categories", [])
    if required and cat and cat not in required:
        reason = (
            f"场景类别 '{cat}' 缺少 '{style_name}' 所需的环境条件"
            f"（该风格需要 {'/'.join(required)} 类场景）"
        )
        return True, reason

    # 开阔空间
    if profile.get("requires_open_space") and not features["is_open_space"]:
        # 仅在明确判断为非开阔空间时才筛除
        if features["category"] in {
            "commercial", "urban_street", "residential",
            "transit_station", "f_and_b", "indoor_generic",
        }:
            reason = f"'{style_name}' 需要开阔空间，当前场景空间条件不足"
            return True, reason

    # 天空可见
    if profile.get("requires_sky_visible") and not features["sky_visible"]:
        reason = f"'{style_name}' 需要可见天空，当前场景天空不可见或不可确认"
        return True, reason

    # 室内必需
    if profile.get("requires_indoor") and not features["is_indoor"]:
        reason = f"'{style_name}' 需要室内环境，当前为室外场景"
        return True, reason

    return False, None


def _check_rule2_unity_destruction(profile, style_name, features):
    """Rule 2 - 统一性破坏：光质冲突。"""
    lq = features["light_quality"]
    if lq == "unknown":
        return False, None  # 保守：不知道光质就不筛

    # 禁止特定光质
    forbidden_lq = profile.get("forbidden_light_qualities", [])
    if forbidden_lq and lq in forbidden_lq:
        reason = (
            f"'{style_name}' 与 {lq} 光质冲突"
            f"（该风格在此光质下会破坏原有的审美统一感）"
        )
        return True, reason

    # 必需特定光质（仅 "soft" 类——硬光下柔美风格确实不可行）
    required_lq = profile.get("requires_light_quality")
    if required_lq and lq != required_lq:
        # 如果要求软光但当前是硬光→筛除
        if required_lq == "soft" and lq == "hard":
            reason = f"'{style_name}' 需要软光/漫射光，当前为硬光——风格核心质感无法实现"
            return True, reason
        # 如果要求软光但当前是 diffuse→保留（diffuse 可替代 soft）
        # 如果要求特定光质但当前是其他→保守保留（不确定时不做筛除）

    return False, None


def _check_rule3_device_waste(profile, style_name, device_key):
    """Rule 3 - 设备浪费：保留为空。v1 不做设备过滤。"""
    # 设备约束已由 LLM 在 device_annotation 中处理。
    # 设备限制是"做不到"而非"不应该"——属于方向选择器范畴。
    return False, None


def _evaluate_direction(style_name, features, device_key):
    """评估单个方向，返回 (conflict_type, reason) 或 (None, None)。"""
    profile = _STYLE_PROFILES.get(style_name)
    if profile is None:
        return None, None  # 无配置 = 不筛除

    # Rule 1: 洞察冲突
    conflict, reason = _check_rule1_insight_conflict(profile, style_name, features)
    if conflict:
        return "insight_conflict", reason

    # Rule 2: 统一性破坏
    conflict, reason = _check_rule2_unity_destruction(profile, style_name, features)
    if conflict:
        return "unity_destruction", reason

    # Rule 3: 设备浪费（reserved）
    conflict, reason = _check_rule3_device_waste(profile, style_name, device_key)
    if conflict:
        return "device_waste", reason

    return None, None


# ============================================================
# 替代策略
# ============================================================

def _get_fallback_style(scene_category, device_key=None, tier="primary"):
    """按场景类别返回安全替代风格。
    tier: "primary" 首选, "secondary" 备用（去重碰撞时使用）。
    """
    cat = scene_category or ""
    config = _FALLBACK_BY_CATEGORY.get(cat, _FALLBACK_BY_CATEGORY["_default"])
    # v1.1: 支持二级兜底；若未配置 secondary 则回退到 primary
    entry = config.get(tier) if isinstance(config.get(tier), dict) else config.get("primary", config)
    return dict(entry)  # 返回副本


def _apply_fallback(direction, fallback_config):
    """将 fallback 配置写入 direction（原地修改）。"""
    direction["style"] = fallback_config["style"]
    direction["style_promise"] = fallback_config["style_promise"]
    direction["reason"] = fallback_config["fit_rationale"]
    direction["fit_rationale"] = fallback_config["fit_rationale"]
    direction["kb_status"] = "📚 已有记录"
    direction["style_brief"] = fallback_config.get("style_brief", {})
    direction["photo_guide"] = ""


def _replace_or_clear_direction(direction, features, device_key, used_styles):
    """
    替换被筛除方向的风格内容。先试 primary fallback，碰撞或冲突时试 secondary，
    都不行才清空。

    Returns:
        (old_style, was_cleared)
    """
    old_style = direction.get("style", "").strip()
    cat = features.get("category", "")

    # 尝试顺序：primary → secondary → 清空
    for tier in ("primary", "secondary"):
        fallback = _get_fallback_style(cat, device_key, tier=tier)
        fb_name = fallback["style"]

        # 去重检查
        if fb_name in used_styles:
            continue

        # v1.1: 兜底验证——确保 fallback 自身不会与场景冲突
        conflict, _ = _evaluate_direction(fb_name, features, device_key)
        if conflict:
            continue

        # 通过：应用 fallback
        _apply_fallback(direction, fallback)
        used_styles.add(fb_name)
        return old_style, False

    # 两级兜底都失败——清空方向
    direction["style"] = ""
    direction["kb_status"] = ""
    direction["style_promise"] = ""
    direction["reason"] = ""
    direction["fit_rationale"] = ""
    direction["style_brief"] = {}
    direction["photo_guide"] = ""
    return old_style, True


# ============================================================
# 主入口
# ============================================================

def filter_directions(directions, vision_json, scene_category, device_key):
    """
    程序化筛除审美冲突的方向。优先替换为安全替代风格（primary→secondary 两级兜底），
    两级都不可用时清空。

    Returns:
        (filtered_directions, report_lines, filtered_entries)
        - filtered_directions: 修改后的 directions 列表
        - report_lines: 人类可读的过滤日志（仅 stderr，不发给用户）
        - filtered_entries: [(old_style, filter_reason), ...] 用于 DB 日志
    """
    if not isinstance(directions, list) or not isinstance(vision_json, dict):
        return list(directions or []), [], []

    features = _extract_scene_features(vision_json, scene_category)
    report = []
    filtered_entries = []
    modified = [dict(d) for d in directions]  # 浅拷贝每个方向

    # 先收集未被筛除的风格名（用于去重）
    used_styles = set()
    for d in modified:
        sn = (d.get("style") or "").strip()
        if sn:
            conflict_type, _ = _evaluate_direction(sn, features, device_key)
            if not conflict_type:
                used_styles.add(sn)  # 正常通过的方向，标记为已用

    # 筛除审美冲突的方向
    for i, d in enumerate(modified):
        style_name = (d.get("style") or "").strip()
        if not style_name:
            continue  # 空风格（✨ 槽位常空）——跳过

        conflict_type, reason = _evaluate_direction(style_name, features, device_key)
        if conflict_type:
            old_style, was_cleared = _replace_or_clear_direction(
                d, features, device_key, used_styles
            )
            filtered_entries.append((old_style, reason))

            if was_cleared:
                report.append(
                    f"CLEARED [{d['id']}] '{style_name}' ({conflict_type}): "
                    f"两级兜底均已被占用或冲突，清空此槽位"
                )
            else:
                new_style = d.get("style", "")
                report.append(
                    f"REPLACED [{d['id']}] '{style_name}' -> '{new_style}' "
                    f"({conflict_type})"
                )

    # 兜底：如果所有方向都为空（极端情况），在 🟢 槽位注入安全风格
    non_empty = [d for d in modified if (d.get("style") or "").strip()]
    if not non_empty and modified:
        fallback = _get_fallback_style(scene_category, device_key, tier="primary")
        # 找到 🟢 槽位（通常是 index 1，id="now"）
        now_idx = next((i for i, d in enumerate(modified) if d.get("id") == "now"), 1)
        _apply_fallback(modified[now_idx], fallback)
        report.append("SAFETY: 所有方向被过滤或清空，注入默认安全风格到🟢槽位")

    return modified, report, filtered_entries
