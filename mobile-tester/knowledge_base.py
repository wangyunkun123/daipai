"""
带拍 · 知识库模块 v1.0
统一知识源——Claude 端和服务器端调用同一套知识。
启动时加载压缩知识核心 + 风格配方索引 + 设备适配参考。
"""

import os
import re

# ============================================================
# 知识库路径
# ============================================================
_KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "daipai", "knowledge")

# ============================================================
# 内置紧凑知识（无需文件 I/O 的兜底——部署时知识文件可能不在）
# ============================================================

# ── 风格 one_liner 表（来自 style-recipes/_index.md）──
STYLE_ONE_LINERS = {
    "日系清新": "空气感——像被阳光漂白过的画面。高调、低饱和、蓝绿偏移、大量留白",
    "电影感": "不是照片——是电影里决定性的一帧。叙事、宽画幅、方向性光、色彩分级",
    "胶片复古": "像胶片机拍的旧照片——有温度、有颗粒、有不完美。暖色偏移、褪色、颗粒、漏光",
    "极简高级": "克制的构图 + 疏离的情绪 = 像 MUJI 的产品图。低饱和、大量负空间、几何秩序",
    "纪实粗粝": "真实的力量——像战地记者拍的那样。高对比、硬光、粗颗粒、黑白倾向",
    "杂志时尚": "精致到每一寸——像 VOGUE 的内页。高饱和、控光精准、姿态张力",
    "梦幻柔美": "浪漫得像做了美梦看到的画面。柔焦、逆光、浅景深、粉暖色调",
    "Lofi 直闪": "在场地证明——像2008年傻瓜机拍的派对照。直闪、高噪点、过度曝光、日期戳",
    "县城记忆": "乡愁是可以看见的——像贾樟柯电影里的一帧。灰黄褪色、自然光、中景、静态",
    "安静真实": "不是拍照——是生活刚好被看见。中性偏暖、软光、不调色痕迹",
    "Grunge 脏感": "从1994年地下排练室捡起来的照片。高反差、褪色、粗颗粒、破损边缘",
    "微观微距": "用最近的距离，日常变成了没见过的东西。极近、浅景深、局部神圣化",
    "便利店美学": "世界睡了，便利店的灯还为你亮着。荧光灯绿、暖黄、雨夜反光、孤独温暖",
    "港风复古": "像90年代香港电影截了一帧。霓虹红蓝、柔焦、低快门拖影",
    "森系": "在森林里待久了——身上沾了树叶和泥土的气息。米棕绿、软光、野生松弛、不看镜头",
    "法式慵懒": "我好看是因为我自在，不是因为我努力。暖色、软光、凌乱中的秩序",
    "新中式": "既有东方的骨，又有鲜活的气。低饱和、留白、青绿棕、静中有动",
}

# ── 跨媒介风格 one_liner 表（来自 cross-media-styles/*.md）──
# 导演/画派/互联网原生美学 → 摄影可执行描述
CROSS_MEDIA_STYLE_ONE_LINERS = {
    "宫崎骏吉卜力": "像宫崎骏动画里的一帧——天空的比例、草地的绿色、光穿过树叶的样子，都有一种『这个世界是温柔的』的感觉。",
    "王家卫电影": "霓虹灯在晃动、人物有残影、绿色覆盖了所有阴影——像王家卫电影里一个记不住的瞬间。",
    "韦斯安德森": "画面绝对对称、颜色像马卡龙、所有人都站在正中间——像韦斯·安德森电影里的一帧。",
    "新海诚天空": "蓝天蓝到不真实、光晕大到像在做梦、城市的每一个细节都在发光——像新海诚动画里的壁纸级天空。",
    "张艺谋色彩": "大块的纯红、金黄、翠绿——颜色不是点缀，是主角。像张艺谋电影里的色彩——人不是画面中最重要的东西，色彩才是。",
    "莫奈印象派": "像莫奈画的那样——光被分解成一块一块的颜色，水面不是水面，是一千片碎掉的光。",
    "莫兰迪色系": "所有的颜色都像被蒙了一层灰——粉色不再是粉色，是灰粉；蓝色不再是蓝色，是灰蓝。世界像被温柔地静音了。",
    "霍普式孤独": "窗边一个人、晨光或暮光从窗户斜照进来、很长的影子——你不知道她在想什么，但你觉得你想知道。",
    "赛博朋克": "霓虹紫+蓝+粉、永远在下雨、湿路面反射着全息光——像站在2077年东亚城市的街头。",
    "蒸汽波": "粉紫蓝渐变+希腊石膏像+Windows 95弹窗+棕榈树剪影——像某个已经消失的80年代未来的明信片。",
    "中国水墨": "大面积留白、只有黑白灰、山在远处人在小处——像一幅宋画山水。",
    "中式梦核": "像你小时候做的一个梦——熟悉的场景，但有些不正常的细节。2003年的客厅、老式电视机、窗外的蓝绿色光——你感觉快要醒了，但又没有。",
    "伦勃朗光": "一束光从左侧的窗户照进来，人物的半边脸在光里、半边在暗里——脸颊上有一个小小的三角形光斑。像维米尔画里的人，像伦勃朗画里的光。",
    "暗调学院": "旧图书馆的深棕木桌、羊皮纸色的旧书、深金+深绿+深棕——像在牛津大学某个百年图书馆里、窗外是阴天、只有一盏台灯。",
    "田园生活": "野花、棉麻裙子、手工面包、午后阳光从树叶间洒下来——像逃离城市以后、在乡下过上了最简单但最美的那种生活。",
    "宋画山水": "一座大山占据了画面2/3、山脚下一个人小到几乎看不见——像范宽的《溪山行旅图》——天地巨大，人很渺小，但人在天地中是安定的。",
    "浮世绘": "平面化的构图、清晰的轮廓线、大块的普鲁士蓝——像葛饰北斋的《神奈川冲浪里》——世界被简化成线条和纯色块。",
    "蜘蛛侠漫风": "像漫画书里的一格——有半调网点、有对话框的视觉痕迹、高饱和撞色、动态模糊线——世界被印刷在纸上。",
    "阈限空间": "空荡的走廊、深夜无人加油站、闭店后的商场——这些地方不是恐怖的，但有一种『不应该一个人在这里』的不安。你觉得这个地方你好像来过。",
    "品牌视觉": "最好的品牌已经把摄影语言提炼成了一套可复制的公式。MUJI的照片不需要Logo你就知道是MUJI。这就是品牌摄影语言的力量。",
    "奶油风": "画面里所有颜色都像被加了一勺牛奶——米白、奶咖、浅杏、燕麦，光线柔和到几乎没有阴影。",
    "老钱静奢": "画面里的一切都很『贵』但没有一样东西在喊『我很贵』——中性大地色调、天然材质纹理、人物姿态松弛从容。",
}

def _all_styles():
    """返回所有风格（style-recipes + cross-media）的合并 dict"""
    return {**STYLE_ONE_LINERS, **CROSS_MEDIA_STYLE_ONE_LINERS}

# ── 光线 → 风格匹配矩阵（来自 knowledge-core.md §二）──
LIGHT_STYLE_MATRIX = """
光线→风格匹配规则（诚实标注 🟢🟡🔴）：
- 顺光+硬光+光比≤1:4 → 🟢日系清新/极简高级/安静真实 | 🔴Grunge/纪实粗粝(缺阴影纹理)
- 顺光+软光+光比≤1:4 → 🟢安静真实/日系清新/胶片复古 | 🔴Grunge
- 侧光+硬光+光比≤1:4 → 🟢纪实粗粝/Grunge/杂志时尚 | 🔴梦幻柔美/日系清新
- 侧光+软光+光比≤1:4 → 🟢安静真实/日系清新/极简高级/电影感 | 🔴Grunge
- 逆光+任意+光比≤1:8 → 🟡剪影/梦幻柔美/电影感(需曝光补偿)
- 逆光+软光+通透物 → 🟢微观微距/梦幻柔美(窗边)
- 顶光+硬光 → 🟡何藩式光影几何/Lofi直闪/黑白(需改变站位) | 🔴柔美人像(眼窝阴影)
- 漫射光+无方向+光比≤1:4 → 🟢安静真实/极简高级/日系清新/微观微距 | 🔴Grunge/电影感
- 人物在阴影中+晴天背景 → 🟢安静真实/极简高级/日系清新/电影感(阴影=天然柔光箱) | 🔴Grunge
"""

# ── 场景 → 风格匹配（来自 style-recipes/_index.md §风格选择矩阵）──
SCENE_STYLE_MATRIX = """
场景→风格推荐：
- 海边 → 首选:日系清新/极简高级 | 次选:梦幻柔美/电影感 | 避免:纪实粗粝/县城记忆
- 街拍 → 首选:电影感/纪实粗粝 | 次选:胶片复古/杂志时尚/Lofi直闪 | 避免:梦幻柔美
- 咖啡厅/室内 → 首选:胶片复古/日系清新 | 次选:电影感/极简高级/Lofi直闪 | 避免:纪实粗粝
- 公园/自然 → 首选:日系清新/梦幻柔美 | 次选:胶片复古/极简高级 | 避免:杂志时尚/纪实粗粝
- 夜景 → 首选:电影感/纪实粗粝 | 次选:胶片复古/Lofi直闪 | 避免:日系清新
- 便利店/夜景室内 → 首选:便利店美学/电影感 | 次选:Lofi直闪/胶片复古 | 避免:纪实粗粝/极简高级
- 森林/草地 → 首选:森系/日系清新/梦幻柔美 | 次选:胶片复古/极简高级 | 避免:杂志时尚/纪实粗粝
- 花卉/花树/花园 → 首选:梦幻柔美/森系 | 次选:日系清新/法式慵懒 | 避免:纪实粗粝/Grunge
- 园林/东方场景 → 首选:新中式/极简高级 | 次选:中国水墨 | 避免:日系清新
- 咖啡厅/窗边 → 首选:法式慵懒/胶片复古/日系清新 | 次选:电影感/极简高级 | 避免:纪实粗粝
- 夜景/霓虹街巷 → 首选:港风复古/电影感/纪实粗粝 | 次选:赛博朋克/Lofi直闪/便利店美学 | 避免:日系清新
- 老街/旧区 → 首选:县城记忆/纪实粗粝 | 次选:胶片复古/电影感 | 避免:日系清新/梦幻柔美
- 废墟/工厂 → 首选:县城记忆/纪实粗粝 | 次选:Lofi直闪/极简高级 | 避免:梦幻柔美/日系清新
- 运动/户外活动 → 首选:纪实粗粝/杂志时尚/安静真实 | 次选:电影感/Lofi直闪 | 避免:梦幻柔美/极简高级
- 静物/日常 → 首选:安静真实/微观微距/极简高级 | 次选:胶片复古/日系清新 | 避免:杂志时尚/Grunge
"""

# ── 设备独有优势（来自 device-adaptation/）──
DEVICE_ADVANTAGES = """
设备优势（优势思维——不是"没有长焦所以裁切"，是"手机能做到相机做不到的"）：
- 手机通用优势：最近对焦距离近(微距强)、深景深(环境叙事完整)、不引人注意(抓拍自然)、灵活角度(高举/贴地/侧入)
- iPhone 17 Pro：48MP 全系、5×长焦压缩空间、夜景强、可关闭AI降噪
- iPhone 17：48MP 主摄+2×裁切底气、无长焦需走近
- iPhone Pro(13-16)：三摄完整、ProRAW后期空间大、缺独立中焦
- iPhone 标准版(13-16)：无长焦硬约束、2×裁切像素紧张、主摄素质好
- 安卓旗舰：焦段覆盖最完整、中焦独立光学人像优势 | 短板:AI过度处理
- 相机(APS-C/全画幅)：可换镜头、大光圈浅景深、高感好 | 短板:体积大不便携
- 富士相机：胶片模拟直出色彩不用修图——这是最大的前期优势
- 理光GR：口袋机快拍模式、森山大道高对比黑白——街拍神器
"""

# ── 情绪 → 风格（来自 style-recipes/_index.md §风格与情绪联动）──
MOOD_STYLE_MAP = """
情绪→风格翻译：
- 温暖/亲密 → 日系清新/胶片复古
- 孤独/疏离 → 极简高级/电影感(冷调)
- 自由/松弛 → 日系清新/梦幻柔美/森系
- 浪漫/梦幻 → 梦幻柔美/电影感(暖调)
- 活力/生命力 → 杂志时尚/纪实粗粝
- 怀旧/忧伤 → 胶片复古/电影感(暗调)/县城记忆
- 宁静/治愈 → 日系清新/极简高级/安静真实
- 在场/青春 → Lofi直闪/纪实粗粝
- 乡愁/破碎 → 县城记忆/胶片复古
- 安静/日常 → 安静真实/日系清新
- 叛逆/生猛 → Grunge/纪实粗粝
- 惊奇/发现 → 微观微距/极简高级
- 孤独温暖(都市) → 便利店美学/电影感(夜景)
- 怀旧暧昧(港风) → 港风复古/王家卫风格
- 自信松弛(法式) → 法式慵懒/安静真实
- 静雅(东方) → 新中式/极简高级
"""

# ── 题材审美优先级（来自 knowledge-core.md §一）──
GENRE_PRIORITY = """
题材→审美优先级：
- 人像 → 光线第一 > 情绪第二 > 背景取舍第三
- 风光 → 光线第一 > 空间层次第二 > 色彩第三
- 街拍 → 时机第一 > 构图第二 > 光线第三
- 运动/户外 → 时机第一 > 叙事第二 > 光线第三
- 静物/日常 → 光线第一 > 色彩统一第二 > 质感第三
- 商业/产品 → 质感第一 > 控光第二 > 构图第三
- 活动/记录 → 时机第一 > 叙事第二 > 情绪第三
"""

# ── 用户能力边界（来自 device-adaptation/user-capability.md）──
USER_CAPABILITY = """
用户能力边界：
🟢 零成本(1-5秒)：切焦段/点按对焦曝光/调补偿/锁AE-AF/切换网格/横竖切换
🟡 低成本(10-30秒)：改变机位高度/方向/距离/移动被摄体/清理背景
🟠 中成本(30秒-2分钟)：前景框制造/天然反光利用/光线柔化/等待时机
🔴 高成本(需设备)：额外光源/三脚架/外接镜头/复杂后期
❌ 不可行：改变日光方向/改变光质硬→软(除非等阴天或拉窗帘)/精确光圈控制(手机)
"""


_social_patterns_cache = None
_posing_router_cache = None


def load_social_patterns():
    """加载社交媒体验证拍摄模式（social-media-patterns/ 目录）"""
    global _social_patterns_cache
    if _social_patterns_cache is not None:
        return _social_patterns_cache

    smp_dir = os.path.join(_KNOWLEDGE_DIR, "social-media-patterns")
    if not os.path.isdir(smp_dir):
        _social_patterns_cache = {}
        return _social_patterns_cache

    result = {"scene_techniques": {}, "atmosphere_hacks": []}

    # ── 场景技法提取 ──
    scene_files = {
        "🍜 美食/咖啡厅": "food-cafe.md",
        "💑 情侣互拍": "couple-posing.md",
        "👯 闺蜜/多人合影": "group-photo.md",
        "🧳 单人旅行/打卡": "solo-travel.md",
        "📐 显瘦显高角度": "slimming-angles.md",
    }
    for scene_name, filename in scene_files.items():
        fpath = os.path.join(smp_dir, filename)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r") as f:
                content = f.read()
            # 去掉 YAML frontmatter
            content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
            # 提取 ## 开头的公式标题作为技法
            techniques = []
            for m in re.finditer(r'###?\s+\d+\.\s+(.+?)(?:\n|$)', content):
                title = m.group(1).strip()
                # 提取第一段描述
                desc_start = m.end()
                desc_match = re.search(r'\n\n(.+?)(?:\n\n|$)', content[desc_start:desc_start+500], re.DOTALL)
                desc = desc_match.group(1).strip()[:120] if desc_match else ""
                # 去掉 markdown 加粗标记
                desc = re.sub(r'\*\*', '', desc)
                techniques.append({"name": title, "desc": desc})
            if techniques:
                result["scene_techniques"][scene_name] = techniques
        except Exception:
            pass

    # ── 氛围增色技法提取 ──
    fpath = os.path.join(smp_dir, "atmosphere-hacks.md")
    if os.path.exists(fpath):
        try:
            with open(fpath, "r") as f:
                content = f.read()
            content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
            for m in re.finditer(r'###?\s+\d+\.\s+(.+?)(?:\n|$)', content):
                title = m.group(1).strip()
                desc_start = m.end()
                desc_match = re.search(r'\n\n(.+?)(?:\n\n|$)', content[desc_start:desc_start+500], re.DOTALL)
                desc = desc_match.group(1).strip()[:120] if desc_match else ""
                desc = re.sub(r'\*\*', '', desc)
                result["atmosphere_hacks"].append({"name": title, "desc": desc})
        except Exception:
            pass

    _social_patterns_cache = result
    return result


def load_posing_router():
    """加载姿势路由表（posing-router.md）"""
    global _posing_router_cache
    if _posing_router_cache is not None:
        return _posing_router_cache

    fpath = os.path.join(_KNOWLEDGE_DIR, "matching", "posing-router.md")
    if not os.path.exists(fpath):
        _posing_router_cache = []
        return _posing_router_cache

    try:
        with open(fpath, "r") as f:
            content = f.read()
        content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)

        result = []
        # 提取场景类型 → 姿势策略表
        table_section = False
        for line in content.split("\n"):
            line = line.strip()
            if "场景类型" in line and "姿势核心策略" in line:
                table_section = True
                continue
            if table_section and line.startswith("|") and "场景类型" not in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 4:
                    result.append({
                        "scene": cells[0],
                        "strategy": cells[1],
                        "do": cells[2] if len(cells) > 2 else "",
                        "avoid": cells[3] if len(cells) > 3 else "",
                    })
            elif table_section and not line.startswith("|"):
                table_section = False

        _posing_router_cache = result
        return result
    except Exception:
        _posing_router_cache = []
        return _posing_router_cache


def load_knowledge_core():
    """加载压缩知识核心文件（如果存在）"""
    core_path = os.path.join(_KNOWLEDGE_DIR, "_compressed", "knowledge-core.md")
    if os.path.exists(core_path):
        try:
            with open(core_path, 'r') as f:
                content = f.read()
            # 去掉 YAML frontmatter
            content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
            return content
        except Exception:
            pass
    return None


def _match_scene_styles(scene_type):
    """从场景类型中提取关键词，匹配场景→风格矩阵，返回相关风格名集合。"""
    if not scene_type:
        return set(_all_styles().keys())

    # 场景关键词 → 相关风格（直接从 SCENE_STYLE_MATRIX 硬编码提取，避免字符串解析）
    SCENE_STYLE_MAP = {
        "海边": ["日系清新", "极简高级", "梦幻柔美", "电影感"],
        "海滩": ["日系清新", "极简高级", "梦幻柔美", "电影感"],
        "街拍": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪"],
        "街边": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪"],
        "街上": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪"],
        "马路": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪"],
        "路边": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪"],
        "巷": ["县城记忆", "纪实粗粝", "电影感", "胶片复古", "港风复古"],
        "室内": ["胶片复古", "日系清新", "电影感", "极简高级", "Lofi直闪"],
        "咖啡": ["胶片复古", "日系清新", "电影感", "极简高级", "Lofi直闪", "法式慵懒"],
        "餐厅": ["胶片复古", "日系清新", "电影感", "极简高级", "Lofi直闪"],
        "公园": ["日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "自然": ["日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "夜景": ["电影感", "纪实粗粝", "胶片复古", "Lofi直闪"],
        "夜间": ["电影感", "纪实粗粝", "胶片复古", "Lofi直闪"],
        "晚上": ["电影感", "纪实粗粝", "胶片复古", "Lofi直闪"],
        "便利店": ["便利店美学", "电影感", "Lofi直闪", "胶片复古"],
        "超市": ["便利店美学", "电影感", "Lofi直闪", "胶片复古"],
        "商店": ["便利店美学", "电影感", "Lofi直闪", "胶片复古"],
        "森林": ["森系", "日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "草地": ["森系", "日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "树": ["森系", "日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "林": ["森系", "日系清新", "梦幻柔美", "胶片复古", "极简高级"],
        "山": ["极简高级", "电影感", "日系清新", "纪实粗粝"],
        "花": ["梦幻柔美", "森系", "日系清新", "法式慵懒"],
        "园林": ["新中式", "极简高级"],
        "中式": ["新中式", "极简高级"],
        "寺庙": ["新中式", "极简高级"],
        "古建筑": ["新中式", "极简高级", "纪实粗粝"],
        "庭院": ["新中式", "极简高级", "日系清新"],
        "窗边": ["法式慵懒", "胶片复古", "日系清新", "电影感", "极简高级"],
        "窗": ["法式慵懒", "胶片复古", "日系清新", "电影感", "极简高级", "安静真实"],
        "阳台": ["法式慵懒", "日系清新", "电影感", "极简高级"],
        "露台": ["法式慵懒", "日系清新", "电影感", "极简高级"],
        "霓虹": ["港风复古", "电影感", "纪实粗粝", "Lofi直闪", "便利店美学"],
        "灯": ["港风复古", "电影感", "Lofi直闪"],
        "老街": ["县城记忆", "纪实粗粝", "胶片复古", "电影感"],
        "旧": ["县城记忆", "纪实粗粝", "胶片复古", "电影感"],
        "老城": ["县城记忆", "纪实粗粝", "胶片复古", "电影感"],
        "废墟": ["县城记忆", "纪实粗粝", "Lofi直闪", "极简高级"],
        "工厂": ["县城记忆", "纪实粗粝", "Lofi直闪", "极简高级"],
        "运动": ["纪实粗粝", "杂志时尚", "安静真实", "电影感", "Lofi直闪"],
        "静物": ["安静真实", "微观微距", "极简高级", "胶片复古", "日系清新"],
        "日常": ["安静真实", "微观微距", "极简高级", "胶片复古", "日系清新"],
        "食物": ["安静真实", "微观微距", "极简高级", "胶片复古", "日系清新"],
        "家居": ["安静真实", "极简高级", "日系清新", "胶片复古"],
        "人像": ["安静真实", "日系清新", "胶片复古", "电影感", "梦幻柔美", "法式慵懒", "杂志时尚"],
        "自拍": ["安静真实", "日系清新", "法式慵懒", "胶片复古"],
        "合影": ["安静真实", "日系清新", "胶片复古", "Lofi直闪"],
        "晴天": ["日系清新", "极简高级", "梦幻柔美", "电影感", "胶片复古"],
        "阴天": ["安静真实", "极简高级", "电影感", "纪实粗粝"],
        "傍晚": ["电影感", "梦幻柔美", "港风复古", "胶片复古"],
        "黄昏": ["电影感", "梦幻柔美", "港风复古", "胶片复古"],
        "日出": ["日系清新", "梦幻柔美", "电影感", "极简高级"],
        "日落": ["电影感", "梦幻柔美", "港风复古", "胶片复古"],
    }

    matched_styles = set()
    for keyword, styles in SCENE_STYLE_MAP.items():
        if keyword in scene_type:
            for s in styles:
                if s in STYLE_ONE_LINERS:
                    matched_styles.add(s)

    # 没匹配到 → 返回全部
    if not matched_styles:
        return set(_all_styles().keys())

    # 始终包含几个通用风格作为兜底
    matched_styles |= {"安静真实", "日系清新", "胶片复古"}
    return matched_styles


def get_knowledge_context(scene_type="", device_key="", light_condition=""):
    """
    返回注入 DIRECTIONS_PROMPT 的知识上下文。
    根据场景类型过滤 one_liner，减少 LLM 输入量。
    """
    parts = []

    # ── 1. 风格 one_liner 参考（按场景过滤，v4.1 性能优化）──
    relevant_styles = _match_scene_styles(scene_type)
    parts.append("## 📚 风格参考（带拍知识库 · 本场景相关）\n")
    parts.append("### 风格 one_liner（全局唯一标识）")
    all_styles = _all_styles()
    for name, one_liner in all_styles.items():
        if name in relevant_styles:
            parts.append(f"- **{name}**：{one_liner}")
    # 不相关的风格只列名字，不列 one_liner（省 token）
    other_styles = [n for n in all_styles if n not in relevant_styles]
    if other_styles:
        parts.append(f"\n> 其他可用风格（按需引用，无需展开）：{' / '.join(other_styles)}")
    parts.append("")

    # ── 2. 场景→风格匹配 ──
    parts.append("### 场景→风格匹配矩阵")
    parts.append(SCENE_STYLE_MATRIX.strip())
    parts.append("")

    # ── 3. 光线→风格匹配 ──
    parts.append("### 光线→风格匹配 + 诚实标注")
    parts.append(LIGHT_STYLE_MATRIX.strip())
    parts.append("")

    # ── 4. 题材优先级 ──
    parts.append("### 题材审美优先级")
    parts.append(GENRE_PRIORITY.strip())
    parts.append("")

    # ── 5. 情绪→风格 ──
    parts.append("### 情绪→风格翻译")
    parts.append(MOOD_STYLE_MAP.strip())
    parts.append("")

    # ── 6. 设备优势 ──
    parts.append("### 设备独有优势")
    parts.append(DEVICE_ADVANTAGES.strip())
    parts.append("")

    # ── 7. 用户能力边界 ──
    parts.append("### 用户能力边界")
    parts.append(USER_CAPABILITY.strip())
    parts.append("")

    # ── 8. 如果知识核心文件存在，追加精华部分 ──
    core = load_knowledge_core()
    if core:
        # 只取关键段落：光线矩阵 + 风格匹配 + 题材决策
        sections = []
        for section_name in ["## 一、题材决策表", "## 二、光线 → 风格", "## 三、风格匹配逻辑"]:
            start = core.find(section_name)
            if start >= 0:
                end = core.find("\n## ", start + len(section_name))
                if end < 0:
                    end = len(core)
                sections.append(core[start:end].strip())
        if sections:
            parts.append("### 📖 知识核心补充")
            parts.append("\n\n".join(sections))
            parts.append("")

    # ── 9. 实战拍摄技法（来自社交媒体验证，v4.2）──
    patterns = load_social_patterns()
    if patterns:
        parts.append("## 📱 实战拍摄技法（社交媒体验证 · 普通用户可直接操作）\n")
        # 按场景匹配注入相关技法
        for scene_key, techniques in patterns.get("scene_techniques", {}).items():
            parts.append(f"### {scene_key}")
            for t in techniques[:3]:  # 每个场景最多3条
                parts.append(f"- **{t['name']}**：{t['desc']}")
            parts.append("")
        # 通用增色技法
        parts.append("### 🎨 氛围增色（适用所有场景）\n")
        for a in patterns.get("atmosphere_hacks", [])[:5]:
            parts.append(f"- **{a['name']}**：{a['desc']}")
        parts.append("")

    # ── 10. 姿势引导（v4.2）──
    posing = load_posing_router()
    if posing:
        parts.append("## 🧍 姿势引导（场景匹配 · 可直接转化为拍摄指令）\n")
        for p in posing[:6]:
            parts.append(f"- **{p['scene']}**：{p['strategy']}（✅ {p['do']} / ❌ {p['avoid']}）")
        parts.append("")

    # ── 11. 使用说明 ──
    parts.append("""
## 🚨 知识库使用规则

以上是带拍的专业摄影知识库。你必须：
1. **风格命名**：使用上述 one_liner 中的中文风格名——禁止自创英文名如 "casual_pet_daily"
2. **光线诚实标注**：对照光线矩阵，给每个风格标注 🟢完美/🟡可模拟(说明效果约X%)/🔴需等待
3. **设备诚实标注**：对照设备优势+用户能力边界，标注 🟢直接拍/🟡微调/🟠替代方案
4. **场景匹配参照**：参考场景→风格矩阵，但不要被限制——如果场景有独特之处，可以超出矩阵推荐
5. **优势思维**：不说"没有长焦所以裁切凑合"——说"手机最近对焦距离比相机更近，可以靠得更近拍微距"
6. **one_liner 优先**：引用风格时，使用上述 one_liner 的描述，不要自己重新描述
7. **实战技法优先**：上述「实战拍摄技法」来自社交媒体验证——方案中优先采用这些技法，它们比教科书理论更直接有效
8. **姿势指令翻译**：上述「姿势引导」需转化为具体动作指令——不说"站姿放松"，说"重心放单腿，手插口袋拇指露外面"
""")

    return "\n".join(parts)


def get_style_detail(style_name):
    """获取指定风格的详细信息（用于方案生成 prompt）"""
    # 尝试匹配 one_liner（先搜 style-recipes，再搜 cross-media）
    style_name_clean = style_name.strip()
    all_styles = _all_styles()
    for name, one_liner in all_styles.items():
        if name in style_name_clean or style_name_clean in name:
            return f"**{name}**：{one_liner}"

    # 模糊匹配
    for name, one_liner in all_styles.items():
        # 检查关键词重叠
        name_chars = set(name)
        input_chars = set(style_name_clean)
        overlap = len(name_chars & input_chars)
        if overlap >= 2:
            return f"**{name}**（最接近匹配）：{one_liner}"

    return None


def get_device_adaptation(device_key):
    """获取设备适配参考（用于方案生成 prompt）"""
    device_tips = {
        "iphone-17-pro": "iPhone 17 Pro：48MP全系、5×长焦压缩空间、可关闭AI降噪。优势：全焦段自由+微距+夜景。建议：大胆用5×拍远景压缩感，2×人像模式拍半身。",
        "iphone-17": "iPhone 17：48MP主摄+2×裁切底气足、无长焦需走近。优势：主摄素质好+2×人像可用。建议：走近代替变焦，发挥最近对焦距离优势拍微距。",
        "iphone-pro-13-16": "iPhone Pro(13-16)：三摄完整、ProRAW后期空间大。优势：色彩科学最稳定。注意：缺独立中焦、长焦弱光差。建议：弱光用1×主摄而非长焦。",
        "iphone-standard-13-16": "iPhone标准版：仅0.5×+1×、无长焦硬约束。优势：主摄素质好+不引人注意。注意：2×裁切像素紧张、夜景模式中等。建议：走近代替变焦、发挥手机灵活角度优势。",
        "android-flagship": "安卓旗舰：焦段覆盖最完整、中焦独立光学人像最大优势。注意：AI过度处理是最大短板——建议关掉AI场景优化、用专业模式。",
        "sony-a7m4": "Sony A7M4全画幅：3300万像素、对焦快准、高感优秀。优势：人像/风光全场景。建议：搭配85 f/1.4拍人像虚化、24-70 f/2.8日常万能。",
        "fujifilm-xt5": "Fujifilm X-T5：胶片模拟直出色彩无敌——这是最大的前期优势。建议：Classic Chrome拍街拍、Nostalgic Neg拍人像、ACROS拍黑白。",
        "fujifilm-x100vi": "Fujifilm X100VI：35mm定焦街拍神器、镜间快门几乎无声。注意：定焦不可换——所有方案靠走位而非变焦。建议：发挥不引人注意的优势拍真实瞬间。",
        "ricoh-gr3": "Ricoh GR III：真口袋机、快拍模式秒拍、森山大道高对比黑白。建议：街拍/快拍/黑白——发挥snapshot优势，不跟大相机比虚化。",
        "canon-r6ii": "Canon R6 II全画幅：肤色色彩科学讨喜、防抖强、对焦快。优势：人像/活动/视频。建议：RF 85 f/2拍人像、RF 24-105 f/4日常全能。",
    }
    return device_tips.get(device_key, "")


# ============================================================
# v3.8: 知识库来源质量验证
# ============================================================

# 可查证的真实来源（摄影教材/大师/艺术家）
VERIFIED_SOURCES = [
    "Freeman", "Adams", "Barnbaum", "Hunter", "Valenzuela",
    "Cartier-Bresson", "Albers", "Arnheim", "Wertheimer", "Koffka", "Köhler",
    "Barrett", "Morandi", "Hopper", "Slim Aarons",
    "Monet", "Hokusai", "Hiroshige", "Vermeer", "Rembrandt",
    "森山大道", "滨田英明", "何藩", "张艺谋", "王家卫", "杜可风",
    "川内伦子", "张克纯", "Martin Parr", "William Klein", "Saul Leiter",
    "Wes Anderson", "宫崎骏", "新海诚", "Christopher Doyle",
    "Liam Wong", "Todd Hido",
]

# AI 工具名（出现在 source 字段中 = AI 参与生成）
AI_SOURCES = ["豆包", "Claude", "ChatGPT"]

# 互联网真实趋势（出现在 source 字段中 = 来自真实平台）
REAL_WORLD_SOURCES = [
    "小红书", "抖音", "Instagram", "IG", "TikTok",
    "Pinterest", "Tumblr", "VOGUE", "Bilibili", "微博", "YouTube"
]

# 知识库种子技法（从 verified 文件中提取的构图/光线/姿势核心技法）
VERIFIED_TECHNIQUES = [
    {"name": "引导线构图", "description": "利用场景中的线条（道路/栏杆/建筑边缘）引导视线至主体——Freeman《摄影师的视界》"},
    {"name": "三分法构图", "description": "将主体放在画面1/3处而非正中，创造视觉张力——Freeman《摄影师的视界》"},
    {"name": "对称构图", "description": "利用水面倒影/建筑中轴创造镜像对称，表达秩序与稳定"},
    {"name": "框架构图", "description": "用门窗/拱门/树枝作前景框架，增加空间层次感——Freeman《摄影师的视界》"},
    {"name": "留白构图", "description": "大量负空间让主体呼吸，极简高级——Barnbaum《摄影的艺术》"},
    {"name": "对角线构图", "description": "利用倾斜线条增加动感和张力，打破画面的静态平衡"},
    {"name": "逆光人像", "description": "人物背对光源，产生轮廓光/发丝光——Hunter《Light Science & Magic》"},
    {"name": "窗光侧光", "description": "利用窗户形成天然柔光箱，产生立体感——维米尔式布光"},
    {"name": "黄金时刻拍摄", "description": "日落前后1小时的低角度暖光，色温约3000-4000K"},
    {"name": "蓝调时刻拍摄", "description": "日落后20-40分钟天空呈深蓝色，适合城市灯光与天色冷暖对比"},
    {"name": "决定性瞬间", "description": "等待人物动作/表情/光线最佳交汇的一瞬间按下快门——Cartier-Bresson"},
    {"name": "景深虚化", "description": "用大光圈(f/1.4-f/2.8)分离主体与背景，突出人物"},
    {"name": "低角度仰拍", "description": "从低处向上拍摄，让主体显得更有力量感和延伸感"},
    {"name": "俯拍鸟瞰", "description": "从高处向下拍摄，创造扁平化图案感和上帝视角"},
    {"name": "运动连拍选片", "description": "动态场景用高速连拍+后期选最佳瞬间，而非追求单张完美"},
    {"name": "前景虚化增加层次", "description": "在镜头前放置半透明物体（树叶/玻璃/纱帘）虚化后形成梦幻前景"},
]


def get_source_quality_map():
    """
    扫描知识库全部文件，按 frontmatter source 字段标注来源质量。
    返回 {filename: quality} 及分布统计。
    quality: verified | real_world | ai_inferred | ai_generated
    """
    import os as _os
    kb_dir = _os.path.join(_os.path.dirname(__file__), "..", ".claude", "skills", "daipai", "knowledge")
    if not _os.path.isdir(kb_dir):
        return {"distribution": {}, "files": {}}

    distribution = {"verified": 0, "real_world": 0, "ai_inferred": 0, "ai_generated": 0}
    files = {}

    for root, dirs, filenames in _os.walk(kb_dir):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            fpath = _os.path.join(root, fn)
            rel = _os.path.relpath(fpath, kb_dir)
            try:
                with open(fpath, "r") as f:
                    content = f.read(2000)  # 只读前面部分找 frontmatter
                # 提取 source 字段
                source_val = ""
                in_fm = False
                for line in content.split("\n"):
                    line = line.strip()
                    if line == "---":
                        if not in_fm:
                            in_fm = True
                            continue
                        else:
                            break
                    if in_fm and line.startswith("source:"):
                        source_val = line.split(":", 1)[1].strip()
                        break

                quality = _classify_source(source_val)
                distribution[quality] = distribution.get(quality, 0) + 1
                files[rel] = quality
            except Exception:
                files[rel] = "ai_generated"  # 读失败视为AI生成
                distribution["ai_generated"] += 1

    return {"distribution": distribution, "files": files}


def _classify_source(source_str):
    """分类单个 source 字段"""
    if not source_str:
        return "ai_generated"

    has_verified = any(s in source_str for s in VERIFIED_SOURCES)
    has_ai = any(s in source_str for s in AI_SOURCES)
    has_real = any(s in source_str for s in REAL_WORLD_SOURCES)

    if has_verified and not has_ai and not has_real:
        return "verified"
    if has_real:
        return "real_world"
    if has_verified and has_ai:
        return "ai_inferred"
    if has_ai:
        return "ai_generated"
    # 兜底：有来源但不是标准来源 → AI 推理
    return "ai_inferred"


def get_all_knowledge_for_prompt(scene_type="", device_key="", light_condition=""):
    """
    主入口：返回完整知识注入文本，直接拼入 LLM prompt。
    """
    return get_knowledge_context(scene_type, device_key, light_condition)


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    ctx = get_knowledge_context("室外公园", "iphone-17-pro", "侧光软光")
    print(f"知识上下文长度: {len(ctx)} 字符")
    print("---前200字符---")
    print(ctx[:200])
    print("---后200字符---")
    print(ctx[-200:])
