"""
带拍 · 知识库模块 统一知识源——Claude 端和服务器端调用同一套知识。
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

# ── 风格 one_liner 表 ──
# 数据源: .claude/skills/daipai/knowledge/style-recipes/_index.md（17个风格配方）
# 这是运行时权威源——所有 prompt 注入和数据库种子均从此读取。
# 与 markdown 文件保持同步：修改风格列表时需同时更新此 dict 和 _index.md。
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

# ── 跨媒介风格 one_liner 表 ──
# 数据源: .claude/skills/daipai/knowledge/cross-media-styles/*.md（22个跨媒介风格）
# 导演/画派/互联网原生美学 → 摄影可执行描述
# 每个 one_liner 对应其源 .md 文件的「一句话」字段
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

# ── 已验证拍摄组合（社交媒体高赞验证）──
# 数据源: 小红书/抖音/ins 高赞摄影内容 + 摄影教程验证
# 用途: Stage 2 技巧设计中 LLM 参考 + 校验（不在已验证组合中的建议标记为 🧪实验性）
VERIFIED_COMBOS = {
    # ── 光线 × 姿势 ──
    "light_pose": [
        {
            "light": "侧光+硬光",
            "pose": "坐姿+半侧脸",
            "effect": "半明半暗——亮面勾勒轮廓、暗面藏入阴影，面部立体感最强",
            "principle": "侧光产生的光比在脸上形成天然光影过渡，比正面平光有层次",
            "verified": True,
            "source": "小红书侧光人像教程（2.3w赞）",
            "avoid": "正脸迎光→两半脸光比1:1显扁平、侧脸全入阴影",
        },
        {
            "light": "逆光+日落前30分钟",
            "pose": "站姿+回眸/侧头",
            "effect": "发丝镶金边+轮廓光，面部用环境反光自然补光",
            "principle": "低角度暖光穿透发丝产生透光效果，面部曝光靠环境漫反射",
            "verified": True,
            "source": "小红书日落人像（多个万赞帖子）",
            "avoid": "正午逆光→光比过大面部全黑、无环境反光物（深色建筑/密林）时面部曝光不足",
        },
        {
            "light": "斑驳树影/投影",
            "pose": "面部置于光斑中+身体在阴影里",
            "effect": "光影投射如天然纹理，画面有层次不单调",
            "principle": "树影=天然遮光板+纹理投射器，光斑落在面部=天然高光点",
            "verified": True,
            "source": "摄影教程：树影人像（1.7w赞）",
            "avoid": "光斑落在眼睛上→红眼/眯眼、光斑碎片过多→画面乱",
        },
        {
            "light": "顶光+硬光（正午）",
            "pose": "低头+帽檐遮脸/仰头闭眼",
            "effect": "帽檐制造面部阴影区，或仰头让光均匀铺满全脸",
            "principle": "正午顶光最不适合人像——要么遮，要么仰头让它变顺光",
            "verified": True,
            "source": "摄影教程：正午拍摄技巧",
            "avoid": "正午平视正脸→眼窝+鼻下+下巴三重阴影（熊猫眼+胡子影）",
        },
        {
            "light": "漫射光/阴天",
            "pose": "任意姿势均可",
            "effect": "面部无阴影、肤色均匀——天然柔光箱",
            "principle": "云层=巨型柔光罩，所有方向光线均匀",
            "verified": True,
            "source": "摄影基础：阴天人像优势",
            "avoid": "阴天逆光→天空过曝死白、阴天背景包含大片天空→灰蒙蒙",
        },
    ],

    # ── 色彩 × 场景 ──
    "color_scene": [
        {
            "colors": "红色强调色+蓝色主色（补色对比）",
            "scene": "海天蓝色背景+红色衣服/道具",
            "effect": "冷暖补色碰撞——红色在蓝色背景中自动成为视觉焦点",
            "principle": "红-蓝=色相环180°补色，天生吸引眼球。适合有力量感的风格",
            "verified": True,
            "source": "色彩理论+小红书穿搭摄影",
            "suits": "杂志时尚/运动风/街头潮牌",
            "avoid_for": "日系清新/梦幻柔美（需要同色系柔和过渡，补色对比太强）",
        },
        {
            "colors": "白衣+蓝天+米白沙滩（同色系+低饱和）",
            "scene": "海边/草地/任何自然场景",
            "effect": "画面干净统一，人融入环境而非跳脱——和谐感",
            "principle": "同色系+低饱和=高级感，适合极简/日系/安静风格",
            "verified": True,
            "source": "小红书极简风穿搭摄影",
            "suits": "日系清新/极简高级/安静真实/法式慵懒",
            "avoid_for": "杂志时尚/纪实粗粝（需要对比和非和谐元素）",
        },
        {
            "colors": "绿+棕+米（自然大地色系）",
            "scene": "森林/公园/草地",
            "effect": "森系/田园——人在自然中不突兀",
            "principle": "大地色系天然和谐，适合表达放松/自然/不刻意的感觉",
            "verified": True,
            "source": "森系摄影风格指南",
            "suits": "森系/梦幻柔美/日系清新/田园生活",
            "avoid_for": "赛博朋克/Grunge/杂志时尚",
        },
        {
            "colors": "黑+金/深绿+深棕（暗调高级）",
            "scene": "室内/咖啡厅/图书馆/夜景",
            "effect": "深沉有质感，像旧油画——光线只照亮局部",
            "principle": "暗调+局部高光=伦勃朗光效，画面有重量感和质感",
            "verified": True,
            "source": "暗调摄影教程（多个万赞帖子）",
            "suits": "暗调学院/伦勃朗光/电影感/极简高级",
            "avoid_for": "日系清新/梦幻柔美（需要高调明亮）",
        },
    ],

    # ── 构图 × 锚点 ──
    "composition_anchor": [
        {
            "composition": "三分法+天然画框",
            "anchor_use": "树枝/门框/窗框/拱门→包裹主体形成画框",
            "effect": "强制聚焦——观众视线被画框引导到主体",
            "principle": "画框构图=视觉强制引导+空间层次感",
            "verified": True,
            "source": "构图基础教程",
            "avoid": "画框元素占比>1/3→喧宾夺主、多个画框嵌套→混乱",
        },
        {
            "composition": "引导线+深纵深",
            "anchor_use": "枯木/栏杆/道路/海岸线→指向人物",
            "effect": "视线顺着引导线滑到人物——动态构图",
            "principle": "人眼天生被线条引导，引导线终点=视觉重心",
            "verified": True,
            "source": "构图基础教程+小红书构图技巧",
            "avoid": "引导线指向画面外→视线被导出、多条引导线方向不一致→混乱",
        },
        {
            "composition": "前景虚化+中景主体",
            "anchor_use": "花草/树叶/栏杆→作为虚化前景",
            "effect": "偷窥视角/层次感——像有人在旁边偷看",
            "principle": "前景=空间深度指示器+氛围制造机",
            "verified": True,
            "source": "小红书前景构图技巧（1.5w赞）",
            "avoid": "前景占比>1/2→主体被压、前景颜色太跳→抢视线",
        },
        {
            "composition": "留白+人物偏置",
            "anchor_use": "大片天空/水面/墙面→作为留白区域",
            "effect": "极简高级——人物小但因为有留白所以不被吞没",
            "principle": "负空间越大，主体越珍贵。留白=高级感的捷径",
            "verified": True,
            "source": "极简摄影构图原则",
            "suits": "极简高级/安静真实/新中式",
            "avoid": "留白区域纹理杂乱→破坏极简感",
        },
    ],

    # ── 禁忌组合（社交媒体验证"容易翻车"的组合）──
    "forbidden_combos": [
        {"combo": "顶光+平视正脸", "why": "眼窝/鼻下/下巴三重阴影，俗称'熊猫眼'，小红书踩坑帖万赞"},
        {"combo": "绿草地+红色衣服（未做褪色处理）", "why": "红绿补色直接碰撞='土'，除非走胶片褪色/港风霓虹路线"},
        {"combo": "手机+弱光+手持慢快门", "why": "没有防抖的手机弱光=糊片率>80%"},
        {"combo": "全身照+俯拍", "why": "头大身小变Q版——除非故意做可爱风"},
        {"combo": "闪光灯直打+油性皮肤", "why": "面部油光反光=灾难。用纸巾压一下或调角度"},
        {"combo": "逆光+深色背景+无补光", "why": "主体全黑剪影——除非这是你要的效果"},
    ],
}


def get_verified_combos():
    """返回已验证组合的格式化文本，供 Stage 2 PLANS_PROMPT 注入"""
    lines = ["## ✅ 已验证拍摄组合（社交媒体高赞验证）\n"]

    lines.append("### 光线 × 姿势\n")
    for c in VERIFIED_COMBOS["light_pose"]:
        verified_tag = "✅" if c["verified"] else "🧪"
        lines.append(f"- {verified_tag} {c['light']} + {c['pose']} → {c['effect']}")
        lines.append(f"  原理：{c['principle']} | 来源：{c['source']}")
        if c.get("avoid"):
            lines.append(f"  ⚠️ 避坑：{c['avoid']}")

    lines.append("\n### 色彩 × 场景\n")
    for c in VERIFIED_COMBOS["color_scene"]:
        lines.append(f"- {c['colors']} @ {c['scene']} → {c['effect']}")
        lines.append(f"  原理：{c['principle']} | 适合：{c['suits']}")
        if c.get("avoid_for"):
            lines.append(f"  ⚠️ 不适合：{c['avoid_for']}")

    lines.append("\n### 构图 × 锚点\n")
    for c in VERIFIED_COMBOS["composition_anchor"]:
        lines.append(f"- {c['composition']} + {c['anchor_use']} → {c['effect']}")
        lines.append(f"  原理：{c['principle']} | 来源：{c['source']}")
        if c.get("avoid"):
            lines.append(f"  ⚠️ 避坑：{c['avoid']}")
        if c.get("suits"):
            lines.append(f"  适合：{c['suits']}")

    lines.append("\n### 🚫 禁忌组合（不遵守必翻车）\n")
    for c in VERIFIED_COMBOS["forbidden_combos"]:
        lines.append(f"- ❌ {c['combo']} —— {c['why']}")

    return "\n".join(lines)


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


# ── 场景→风格匹配（同义词扩展 + 评分制）──
# 每个条目: {"styles": [...], "aliases": [...]}
# 主关键词命中 +3 分，同义词命中 +1 分
_SCENE_STYLE_ENTRIES = [
    {"styles": ["日系清新", "极简高级", "梦幻柔美", "电影感", "浮世绘"],
     "aliases": ["海边", "海滩", "海岸", "海滨", "沙滩", "beach", "coast", "海景", "滨海", "湾"]},
    {"styles": ["电影感", "纪实粗粝", "胶片复古", "杂志时尚", "Lofi直闪", "王家卫电影"],
     "aliases": ["街拍", "街边", "街上", "马路", "路边", "街头", "街道", "巷", "弄堂"]},
    {"styles": ["县城记忆", "纪实粗粝", "电影感", "胶片复古", "港风复古", "中式梦核"],
     "aliases": ["老城", "旧城", "老区", "拆迁", "城中村"]},
    {"styles": ["胶片复古", "日系清新", "电影感", "极简高级", "Lofi直闪", "法式慵懒", "暗调学院", "霍普式孤独", "奶油风", "韦斯安德森"],
     "aliases": ["室内", "咖啡", "咖啡馆", "咖啡厅", "咖啡店", "餐厅", "饮品店", "茶馆", "奶茶店", "水吧", "cafe", "café", "cafeteria", "食堂", "饭店", "小酒馆", "酒吧", "bar", "bistro"]},
    {"styles": ["日系清新", "梦幻柔美", "胶片复古", "极简高级", "莫奈印象派", "宫崎骏吉卜力", "田园生活", "张艺谋色彩", "韦斯安德森"],
     "aliases": ["公园", "自然", "户外", "花园", "植物园", "草地", "草坪", "野外", "田园", "郊外"]},
    {"styles": ["电影感", "纪实粗粝", "胶片复古", "Lofi直闪", "赛博朋克", "王家卫电影", "蒸汽波"],
     "aliases": ["夜景", "夜间", "晚上", "夜晚", "天黑", "暗光"]},
    {"styles": ["便利店美学", "电影感", "Lofi直闪", "胶片复古"],
     "aliases": ["便利店", "超市", "商店", "杂货店"]},
    {"styles": ["森系", "日系清新", "梦幻柔美", "胶片复古", "极简高级", "宫崎骏吉卜力"],
     "aliases": ["森林", "树林", "林间", "树", "林", "丛林", "密林"]},
    {"styles": ["极简高级", "电影感", "日系清新", "纪实粗粝", "宋画山水", "中国水墨"],
     "aliases": ["山", "山景", "山峦", "山峰", "山区", "山脉", "登山", "徒步"]},
    {"styles": ["梦幻柔美", "森系", "日系清新", "法式慵懒", "莫奈印象派", "田园生活"],
     "aliases": ["花", "花海", "花丛", "花卉", "花园", "樱花", "花田", "花树", "油菜花"]},
    {"styles": ["新中式", "极简高级", "中国水墨"],
     "aliases": ["园林", "中式", "庭院", "寺庙", "祠堂", "古建筑", "古风", "国风", "汉服"]},
    {"styles": ["法式慵懒", "胶片复古", "日系清新", "电影感", "极简高级", "安静真实", "霍普式孤独", "伦勃朗光"],
     "aliases": ["窗边", "窗", "窗台", "窗旁", "靠窗", "窗户"]},
    {"styles": ["法式慵懒", "日系清新", "电影感", "极简高级", "新海诚天空"],
     "aliases": ["阳台", "露台", "天台", "屋顶", "楼顶"]},
    {"styles": ["港风复古", "电影感", "纪实粗粝", "Lofi直闪", "便利店美学", "赛博朋克", "蒸汽波", "王家卫电影"],
     "aliases": ["霓虹", "霓虹灯", "灯牌", "招牌", "夜市"]},
    {"styles": ["县城记忆", "纪实粗粝", "胶片复古", "电影感"],
     "aliases": ["废墟", "废弃", "工厂", "厂房", "工业", "仓库"]},
    {"styles": ["纪实粗粝", "杂志时尚", "安静真实", "电影感", "Lofi直闪", "蜘蛛侠漫风"],
     "aliases": ["运动", "体育", "球场", "跑道", "健身房", "瑜伽", "舞蹈"]},
    {"styles": ["安静真实", "微观微距", "极简高级", "胶片复古", "日系清新", "莫兰迪色系", "奶油风"],
     "aliases": ["静物", "日常", "食物", "美食", "家居", "物件", "摆件"]},
    {"styles": ["安静真实", "日系清新", "胶片复古", "电影感", "梦幻柔美", "法式慵懒", "杂志时尚", "伦勃朗光", "老钱静奢"],
     "aliases": ["人像", "人物", "拍照", "照片"]},
    {"styles": ["安静真实", "日系清新", "法式慵懒", "胶片复古"],
     "aliases": ["自拍", "自拍照"]},
    {"styles": ["安静真实", "日系清新", "胶片复古", "Lofi直闪"],
     "aliases": ["合影", "合照", "集体照"]},
    {"styles": ["日系清新", "极简高级", "梦幻柔美", "电影感", "胶片复古", "新海诚天空", "宫崎骏吉卜力"],
     "aliases": ["晴天", "阳光", "大太阳", "蓝天", "白云"]},
    {"styles": ["安静真实", "极简高级", "电影感", "纪实粗粝", "莫兰迪色系"],
     "aliases": ["阴天", "多云", "阴沉", "灰蒙蒙"]},
    {"styles": ["电影感", "梦幻柔美", "港风复古", "胶片复古"],
     "aliases": ["傍晚", "黄昏", "日落", "夕阳", "落日", "晚霞", "余晖"]},
    {"styles": ["日系清新", "梦幻柔美", "电影感", "极简高级", "新海诚天空"],
     "aliases": ["日出", "清晨", "晨光", "黎明", "晨曦"]},
    {"styles": ["港风复古", "电影感", "纪实粗粝", "Lofi直闪", "赛博朋克", "王家卫电影"],
     "aliases": ["雨", "雨天", "雨夜", "下雨", "雨景", "倒影", "湿"]},
    {"styles": ["极简高级", "安静真实", "日系清新", "电影感"],
     "aliases": ["雪", "雪天", "雪景", "下雪", "积雪", "白雪"]},
    {"styles": ["电影感", "梦幻柔美", "极简高级", "安静真实", "中国水墨"],
     "aliases": ["雾", "雾天", "雾气", "雾蒙蒙", "朦胧"]},
    {"styles": ["纪实粗粝", "极简高级", "电影感", "Lofi直闪", "赛博朋克", "阈限空间"],
     "aliases": ["地下", "停车场", "车库", "隧道", "地铁", "通道"]},
]

# 始终兜底的通用风格
_ALWAYS_INCLUDE_STYLES = {"安静真实", "日系清新", "胶片复古"}


def _match_scene_styles(scene_type):
    """同义词扩展 + 评分匹配。
    返回 (matched_styles_set, scores_dict)。
    主关键词命中 +3 分，同义词命中 +1 分。
    取 Top-N 高分风格，而非全量。
    """
    if not scene_type:
        return set(_all_styles().keys()), {}

    scene_lower = scene_type.lower()
    scores = {}

    for entry in _SCENE_STYLE_ENTRIES:
        styles = entry["styles"]
        aliases = entry["aliases"]
        # 主关键词（aliases[0]）权重 3，其余 aliases 权重 1
        for i, alias in enumerate(aliases):
            weight = 3 if i == 0 else 1
            if alias.lower() in scene_lower:
                for s in styles:
                    if s in _all_styles():
                        scores[s] = scores.get(s, 0) + weight

    if not scores:
        # 完全没有匹配 → 返回全量（后续会由搜索优先策略决定是否使用）
        return set(_all_styles().keys()), {}

    # 取 Top-N（至少 5，最多 12）
    sorted_styles = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    threshold = max(1, sorted_styles[min(11, len(sorted_styles)-1)][1]) if len(sorted_styles) > 12 else 1
    matched = {s for s, score in scores.items() if score >= threshold}

    # 始终包含通用兜底风格
    matched |= _ALWAYS_INCLUDE_STYLES

    # 限制上限
    if len(matched) > 15:
        matched = set(list(matched)[:15])

    return matched, scores


def validate_search_results(search_text, scene_type=""):
    """用知识库检验搜索结果质量。
    返回 {
        "verified_styles": [...],     # 搜索中出现的、知识库认可的风格名
        "suspicious_styles": [...],   # 搜索中出现的、知识库不认识的可疑风格
        "has_social_proof": bool,     # 搜索结果是否显示高赞/高收藏信号
        "social_signals": [...],      # 检测到的高赞信号文本
        "conflicts_with_kb": [...],   # 与知识库冲突但高赞的内容
        "overall_quality": "high"|"medium"|"low",
    }
    """
    all_styles = _all_styles()
    known_style_names = set(all_styles.keys())
    # 也加上跨媒介风格名
    known_style_names |= set(CROSS_MEDIA_STYLE_ONE_LINERS.keys())
    # 加上常用技法名
    known_technique_names = {t["name"] for t in VERIFIED_TECHNIQUES}

    # 高赞信号检测
    SOCIAL_PROOF_PATTERNS = [
        "万赞", "万收藏", "万点赞", "万播放", "万浏览",
        "爆款", "热门", "火了", "刷屏", "刷爆",
        "10万+", "100万", "千万", "百万",
        "收藏", "点赞", "赞", "likes", "saves",
    ]
    social_signals = []
    for pat in SOCIAL_PROOF_PATTERNS:
        if pat in search_text:
            social_signals.append(pat)
    has_social_proof = len(social_signals) >= 2

    # 从搜索文本中提取可能的风格名
    verified_styles = []
    suspicious_styles = []
    conflicts_with_kb = []

    # 检查知识库中每个风格名是否出现在搜索结果中
    for style_name in known_style_names:
        if style_name in search_text:
            verified_styles.append(style_name)

    # 检测搜索中出现的陌生风格名（不在知识库中的中文2-6字术语）
    import re as _re
    # 匹配搜索结果中"XX风""XX感""XX系"等模式
    style_patterns = _re.findall(r'[一-鿿]{2,4}(?:风|感|系|美学|风格|色调|调色)', search_text)
    for pat in style_patterns:
        if pat not in known_style_names and pat not in suspicious_styles:
            if has_social_proof:
                # 高赞 → 即使不在知识库中也值得关注
                suspicious_styles.append({"name": pat, "note": "高赞新风格，知识库未收录"})
            else:
                # 低赞且不在知识库 → 标记为可疑
                suspicious_styles.append({"name": pat, "note": "低质量来源，知识库未验证"})

    # 搜索中推荐了知识库明确不适合当前场景的风格 → 检查冲突
    if scene_type:
        matched, _ = _match_scene_styles(scene_type)
        for style_name in verified_styles:
            if style_name not in matched and style_name in known_style_names:
                note = "搜索推荐该风格但知识库认为不适合此场景"
                if has_social_proof:
                    note += "（高赞信号 → 可采纳）"
                    conflicts_with_kb.append({"name": style_name, "action": "adopt", "note": note})
                else:
                    note += "（低赞 → 过滤）"
                    conflicts_with_kb.append({"name": style_name, "action": "filter", "note": note})

    # 综合质量评估
    if len(verified_styles) >= 3 and not conflicts_with_kb:
        overall = "high"
    elif len(verified_styles) >= 1 or has_social_proof:
        overall = "medium"
    else:
        overall = "low"

    return {
        "verified_styles": verified_styles,
        "suspicious_styles": suspicious_styles,
        "has_social_proof": has_social_proof,
        "social_signals": social_signals,
        "conflicts_with_kb": conflicts_with_kb,
        "overall_quality": overall,
    }


def get_knowledge_context(scene_type="", device_key="", light_condition="", fallback_level="medium"):
    """
    返回注入 DIRECTIONS_PROMPT 的知识上下文。
    根据搜索质量三档输出——
      - "low":    搜索空，知识库当主力 → 完整输出
      - "medium": 搜索一般，知识库补充 → 精简输出（one_liner + 矩阵 + 设备）
      - "high":   搜索丰富，知识库检验 → 仅风格名列表 + 设备 + 能力边界
    """
    parts = []

    # ── 1. 风格 one_liner 参考 ──
    if fallback_level == "high":
        # 搜索丰富 → 知识库只提供风格名列表供校验
        parts.append("## 📚 知识库风格名索引（仅用于校验搜索结果的风格名，非推荐）\n")
        all_styles = _all_styles()
        parts.append(f"> 可用风格名：{' / '.join(all_styles.keys())}\n")
        parts.append("> ⚠️ 搜索中出现的风格名若不在上述列表中，需谨慎评估其质量。\n")
        parts.append("> ⚠️ 若搜索结果有高赞信号（万赞/万收藏/刷屏），即使与知识库冲突也可采纳。\n")
    elif fallback_level == "medium":
        # 搜索一般 → 精简输出
        relevant_styles, _ = _match_scene_styles(scene_type)
        parts.append("## 📚 知识库参考（补充搜索未覆盖的部分）\n")
        parts.append("### 本场景相关风格 one_liner\n")
        all_styles = _all_styles()
        for name, one_liner in all_styles.items():
            if name in relevant_styles:
                parts.append(f"- **{name}**：{one_liner}")
        # 不相关风格只列名字
        other_styles = [n for n in all_styles if n not in relevant_styles]
        if other_styles:
            parts.append(f"\n> 其他可用风格：{' / '.join(other_styles)}")
        parts.append("")
    else:
        # 搜索空 → 完整输出（知识库当主力）
        relevant_styles, _ = _match_scene_styles(scene_type)
        parts.append("## 📚 专业知识库（本次搜索无结果，以下内容为主要参考源）\n")
        parts.append("### 风格 one_liner（全局唯一标识）\n")
        all_styles = _all_styles()
        for name, one_liner in all_styles.items():
            if name in relevant_styles:
                parts.append(f"- **{name}**：{one_liner}")
        other_styles = [n for n in all_styles if n not in relevant_styles]
        if other_styles:
            parts.append(f"\n> 其他可用风格（按需引用，无需展开）：{' / '.join(other_styles)}")
        parts.append("")

    # ── 后续章节仅在 not high 时输出 ──
    if fallback_level != "high":
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

    # ── 6. 设备优势（始终输出）──
    parts.append("### 设备独有优势")
    parts.append(DEVICE_ADVANTAGES.strip())
    parts.append("")

    # ── 7. 用户能力边界（始终输出）──
    parts.append("### 用户能力边界")
    parts.append(USER_CAPABILITY.strip())
    parts.append("")

    if fallback_level != "high":
        # ── 8. 知识核心补充 ──
        core = load_knowledge_core()
        if core:
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

        # ── 9. 实战拍摄技法 ──
        patterns = load_social_patterns()
        if patterns:
            parts.append("## 📱 实战拍摄技法（社交媒体验证 · 普通用户可直接操作）\n")
            for scene_key, techniques in patterns.get("scene_techniques", {}).items():
                parts.append(f"### {scene_key}")
                for t in techniques[:3]:
                    parts.append(f"- **{t['name']}**：{t['desc']}")
                parts.append("")
            parts.append("### 🎨 氛围增色（适用所有场景）\n")
            for a in patterns.get("atmosphere_hacks", [])[:5]:
                parts.append(f"- **{a['name']}**：{a['desc']}")
            parts.append("")

        # ── 10. 姿势引导 ──
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


# ── 跨媒介风格→摄影可执行参数（从知识文件提取的「视觉翻译：摄影怎么拍」段落）──
CROSS_MEDIA_PHOTO_PARAMS = {
    "宫崎骏吉卜力": """**宫崎骏吉卜力 · 摄影可执行参数**
🎯 前期拍法（这些是拍摄现场能操作的——不是后期滤镜）：
- 光线核心：找一棵树，让光从树叶缝隙中漏过来——光斑是吉卜力感的物理核心。软光优先，光比 1:2~1:3，不能有"残酷的阴影"
- 天空占比：天空必须占画面 30-50%——天空是吉卜力的情感容器。蓝天低饱和（色相 200-210°，饱和度 -10%，明度 +10%）
- 绿色处理：草/树叶的绿色向暖偏移（色相 80-100°）——不是一种绿，是一百种绿。找有多种绿色层次的场景
- 构图：广角 28-35mm，远景（人小天地大），人占画面 10-25%，水平线不歪斜
- 影调：亮调但不刺眼，画面整体明亮
❌ 禁止：城市背景 / 强阴影 / 人物占画面 >30% / 天空 < 20% / 绿色偏冷 / 高对比度
📎 技法锚点：日系清新 + 梦幻柔美""",

    "宋画山水": """**宋画山水 · 摄影可执行参数**
🎯 前期拍法（这些是拍摄现场能操作的——不是后期滤镜）：
- 构图核心：「巨碑式」——主体（山/建筑/大树）占画面 2/3，人在画面中只占 3-5%。垂直构图强调"高远"，仰拍增强崇高感
- 留白：天空/水面留白 20-30%
- 色彩：首选黑白（墨色五层——纯黑/浓墨/重墨/淡墨/清墨），可选浅绛（淡赭石+花青淡彩）
- 光线：软光/雾/阴天——散射光简化层次。最好有云雾在山间/建筑间/树间
- 清晰度：远处微柔——"远山无皴"
⚠️ 限制：需要山/高大建筑+雾/阴天。城市和平原难以拍摄。长焦压缩远山是辅助手段。
📎 技法锚点：新中式 + 极简高级""",

    "王家卫电影": """**王家卫电影 · 摄影可执行参数**
🎯 前期拍法：
- 色彩核心：绿色阴影偏移（阴影往青绿色调）、霓虹色点缀（红/橙/粉在暗部中发光）。高饱和暖色与冷绿阴影形成色彩张力
- 光线：窗边单一光源、霓虹灯/街灯作为主光源。亮面暖、暗面冷的色彩分离
- 构图：前景遮挡制造窥视感（门框/窗框/人群缝隙）。低角度仰拍，不对称构图
- 动态：低速快门拖影（1/15-1/30s）——走动的人留下运动痕迹
- 质感：胶片颗粒感，略微欠曝
❌ 禁止：均匀照明、正面光、对称构图、画面太亮
📎 技法锚点：电影感 + 港风复古""",

    "韦斯安德森": """**韦斯安德森 · 摄影可执行参数**
🎯 前期拍法：
- 构图核心：绝对对称——找到对称的建筑/走廊/楼梯/门窗。中心构图，主体必须放在正中间
- 色彩：马卡龙色系——粉/黄/蓝/绿都是高亮度低饱和的糖果色。同画面中 3-4 种马卡龙色并置
- 视角：正面平视为主——不仰不俯，像拍证件照一样正对主体
- 空间：平面化构图——压缩空间深度，让画面像平面设计
- 细节：整齐排列的物件、重复的几何形状
❌ 禁止：不对称构图、倾斜角度、单一色调
📎 技法锚点：极简高级""",

    "莫兰迪色系": """**莫兰迪色系 · 摄影可执行参数**
🎯 前期拍法：
- 色彩核心：所有颜色加灰——不是低饱和，是"灰度覆盖"。任何鲜艳颜色在心里加一层灰再拍
- 光线：柔光/窗光——莫兰迪画室的北窗光。不要直射光，不要硬阴影
- 构图：静物式的秩序感——物体之间有"呼吸间距"。几何化摆放，不拥挤
- 背景：素色/灰调背景——白墙/灰墙/原木色/亚麻色
- 质感：哑光——避免任何反光面
❌ 禁止：高饱和色块、强反光、杂乱背景、直射硬光
📎 技法锚点：极简高级 + 安静真实""",

    "中国水墨": """**中国水墨 · 摄影可执行参数**
🎯 前期拍法：
- 构图核心：大面积留白（天空/水面/雾/雪占画面 40-60%）。主体偏于一侧，给"空"留足空间
- 色彩：黑白优先。可选淡彩——低饱和灰蓝/灰绿/灰褐
- 光线：雾/阴天/雨/雪——散射光消除细节，让景物变成"墨块"
- 空间：远中近三层——远处淡（淡墨）、中间灰（重墨）、近处浓（浓墨）
- 元素：孤树/孤舟/远山/飞鸟/小桥——少即是多
❌ 禁止：鲜艳色彩、填满画面、硬光、复杂元素堆砌
📎 技法锚点：极简高级 + 新中式""",
}


def get_style_detail(style_name):
    """获取指定风格的详细信息（用于方案生成 prompt）。

    四层策略：
    - KB原生风格 → 直接返回可执行摄影参数
    - 有详细参数的跨媒介风格 → 注入「摄影可执行参数」——前期拍法+禁止事项
    - 其他跨媒介风格 → 美学描述 + 摄影翻译任务 + 落地约束
    - 社区发现新风格 → 纯翻译任务 + 严格落地约束
    """
    style_name_clean = style_name.strip()

    # ── 精确匹配 KB 原生风格 ──
    for name, one_liner in STYLE_ONE_LINERS.items():
        if name in style_name_clean or style_name_clean in name:
            return f"**{name}**：{one_liner}\n（来源：知识库——已含可执行摄影参数，直接用于方案）"

    # ── 精确匹配跨媒介风格（优先检查是否有详细摄影参数）──
    for name, one_liner in CROSS_MEDIA_STYLE_ONE_LINERS.items():
        if name in style_name_clean or style_name_clean in name:
            # 如果有详细摄影参数，直接注入
            if name in CROSS_MEDIA_PHOTO_PARAMS:
                return CROSS_MEDIA_PHOTO_PARAMS[name] + f"""

⛔ 铁律：上面标注了"前期拍法"的参数（光线、构图、天空占比、视角、元素选择）必须直接写入方案的 subject/shooter/enhance 字段——这是拍摄现场就能做的事。只有色彩倾向/清晰度/颗粒等才放到 quick_edit（后期修图）中。
⛔ 禁止把前期拍法写成后期滤镜。比如"找一棵树让光斑漏在人物身上"写进 shooter，"天空占画面30-50%"写进 shooter 的取景描述——这些都是按快门前要做的事。"""

            # 无详细参数——用翻译任务模板
            related_kb = _find_related_kb_style(name)
            return f"""**{name}**（跨媒介视觉风格）
美学描述：{one_liner}

🚨 摄影翻译任务——你必须把上述美学描述翻译成具体的、可执行的摄影方案。
⛔ 核心原则：方案必须以前期拍摄手法为主（subject/shooter/gear/enhance），后期修图（quick_edit）为辅。
⛔ 禁止反向：不能把风格效果写成后期滤镜。每个风格特征先问"拍摄现场能不能做"——能做就写进前期字段。

1. 光线：该风格需要什么光质和方向？对照场景视觉分析中的光线条件判断可行性
2. 色彩：推导色调偏移方向和饱和度范围——色彩倾向写进 enhance（前期打光/选背景），调色写进 quick_edit（后期）
3. 构图：推导景别偏好和空间策略——全部写进 shooter 字段
4. 器材：对照设备约束判断可行性——手机做不到的写替代方案
5. 后期：必须的后期调整方向——只写进 quick_edit

📎 知识库锚点（用于技法落地）：{related_kb}
> 以上锚点风格的知识库技法可作为摄影参照——用它们的技法路径来实现本风格的美学目标。

⚠️ 落地约束：
- 每个方案字段（subject/shooter/gear/enhance）必须能在「社区搜索参考」或「历史验证技法」或「知识库锚点」中找到支撑
- 无真实摄影参照的技法 → 不写。宁缺毋滥。
- 手机拍不出来的（如精确光圈控制/移轴/大画幅）→ 写替代方案或不写
- 优先引用社区搜索中的真实姿势/机位/技法"""

    # ── 社区发现的新风格（完全不在 KB 中）──
    return f"""**{style_name_clean}**（社区发现的新风格）
🚨 这是一个新风格——基于你的视觉文化知识，翻译成可执行的摄影方案：
⛔ 核心原则：方案必须以前期拍摄手法为主，后期修图为辅。

1. 推断该风格的光线/色彩/构图偏好
2. 对照设备约束判断哪些能做、哪些需要替代方案
3. 必须能从「社区搜索参考」中找到至少1条支撑——没有真实参照的技法不写

⚠️ 落地约束（比常规风格更严格）：
- 每个技法必须有来源标注（社区搜索/知识库类比/摄影原理）
- 社区搜索无支撑 → 用知识库最接近的风格技法类比，标注"类比自（某某风格）"
- 两者都无支撑 → 只写已验证的通用摄影原理，不创造新技法"""


def _find_related_kb_style(cross_media_name):
    """为跨媒介风格找到最接近的 KB 原生风格作为技法锚点"""
    # 手动映射——每个跨媒介风格对应 1-2 个 KB 原生风格的技法路径
    mapping = {
        "宫崎骏吉卜力": "日系清新 + 梦幻柔美（高调+柔光+蓝天比例）",
        "王家卫电影": "电影感 + 港风复古（霓虹色偏移+低快门拖影+绿色阴影）",
        "韦斯安德森": "极简高级（绝对对称+马卡龙色彩+中心构图）",
        "新海诚天空": "日系清新（高饱和蓝天+大光晕+细节锐利）",
        "张艺谋色彩": "杂志时尚（大块纯色+高饱和+色彩作为主体）",
        "莫奈印象派": "梦幻柔美（柔焦+色彩分区+刻意虚化前景背景）",
        "莫兰迪色系": "极简高级 + 安静真实（低饱和灰调+柔和光+几何秩序）",
        "霍普式孤独": "电影感（窗边单一光源+长阴影+暖光与暗部对比）",
        "赛博朋克": "电影感 + 港风复古（霓虹紫蓝+雨夜+湿路面反光）",
        "蒸汽波": "梦幻柔美（粉紫蓝渐变+柔焦+复古元素拼贴）",
        "中国水墨": "极简高级 + 新中式（大面积留白+黑白灰+远山近人）",
        "中式梦核": "县城记忆（褪色+柔和光+轻微过曝+2000年代元素）",
        "伦勃朗光": "电影感（单光源侧光+三角光斑+深阴影）",
        "暗调学院": "电影感 + 极简高级（深棕金绿+台灯单一光源+暗调）",
        "田园生活": "森系 + 法式慵懒（自然光+暖色+野花野草+松弛）",
        "宋画山水": "新中式 + 极简高级（山占2/3+人极小+留白+水墨调）",
        "浮世绘": "极简高级（平面化构图+清晰轮廓线+大块纯色+普鲁士蓝）",
        "蜘蛛侠漫风": "杂志时尚（半调网点+高饱和撞色+动态模糊线+漫画感）",
        "阈限空间": "安静真实（空荡空间+荧光灯绿+无人物+不安感）",
        "品牌视觉": "极简高级 + 杂志时尚（克制调色+质感优先+可复制公式）",
        "奶油风": "日系清新（米白奶咖+柔和到无阴影+高明度低对比）",
        "老钱静奢": "极简高级 + 法式慵懒（中性大地色+天然材质纹理+松弛从容）",
    }
    return mapping.get(cross_media_name, "极简高级（通用锚点——克制构图+中性色彩+自然光）")


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
# 知识库来源质量验证
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


# 跨媒介/艺术史/设计传统等真实文化来源（不含 AI）
BROAD_CULTURAL_SOURCES = [
    # 中国艺术传统
    "水墨画", "山水画", "宋代", "范宽", "郭熙", "国潮", "新中式", "中国画", "中国艺术史",
    "郎静山", "张克纯",
    # 西方艺术史
    "印象派", "莫奈", "印象主义", "伦勃朗", "维米尔", "荷兰绘画",
    "波普艺术", "浪漫主义",
    # 日本艺术
    "浮世绘", "北斋", "广重", "梵高受浮世绘", "日本美学",
    # 电影/动画
    "宫崎骏", "吉卜力", "动画美学", "日本动画", "赛博朋克", "银翼杀手",
    "蜘蛛侠", "漫画视觉", "电影摄影传统", "调色师", "电影叙事",
    # 互联网/设计美学
    "Dark Academia", "Liminal Space", "梦核", "阈限空间", "建筑心理学",
    "Apple", "MUJI", "品牌视觉", "极简主义艺术传统",
    # 摄影传统
    "胶片摄影传统", "胶片怀旧", "富士", "柯达", "柔光技法", "微距摄影传统",
    "梦幻人像", "反时尚摄影", "Grunge", "时尚摄影动能",
    # 教材/理论
    "孙京涛", "Robert Frank", "Gregory Halpern", "Jörg Colberg",
    "Ansel Adams", "Michael Frye", "Glenn Rand", "Barbara London",
    "Laura U. Marks", "Annebella Pollen", "Elizabeth Edwards",
    "Cartier-Bresson", "Crewdson", "Arnheim", "格式塔",
    # 中文互联网
    "松弛感", "元气感", "治愈感", "老照片", "审美语汇",
    "综合审美体系", "摄影风格流派",
    # 摄影运动/趋势
    "反AI摄影", "CCD复兴",
]


def _classify_source(source_str):
    """分类单个 source 字段"""
    if not source_str:
        return "ai_generated"

    has_verified = any(s in source_str for s in VERIFIED_SOURCES)
    has_ai = any(s in source_str for s in AI_SOURCES)
    has_real = any(s in source_str for s in REAL_WORLD_SOURCES)
    has_cultural = any(s in source_str for s in BROAD_CULTURAL_SOURCES)

    if has_verified and not has_ai:
        return "verified"
    if has_real:
        return "real_world"
    if has_verified and has_ai:
        return "ai_inferred"
    if has_ai:
        return "ai_generated"
    if has_cultural:
        return "real_world"
    # 兜底：有来源但不在任何已知列表 → 标记为 real_world（非 AI 生成）
    return "real_world"


def get_knowledge_files_by_quality(quality_filter=None):
    """
    返回指定来源质量的详细文件列表，含 source 字段和标题。
    quality_filter: None 返回全部, 或 'verified' | 'real_world' | 'ai_inferred' | 'ai_generated'
    返回 [{rel_path, quality, source, title}, ...]
    """
    import os as _os
    kb_dir = _os.path.join(_os.path.dirname(__file__), "..", ".claude", "skills", "daipai", "knowledge")
    if not _os.path.isdir(kb_dir):
        return []

    results = []
    for root, dirs, filenames in _os.walk(kb_dir):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            fpath = _os.path.join(root, fn)
            rel = _os.path.relpath(fpath, kb_dir)
            try:
                with open(fpath, "r") as f:
                    content = f.read(3000)
                # 提取 frontmatter
                source_val = ""
                title_val = ""
                in_fm = False
                for line in content.split("\n"):
                    line_s = line.strip()
                    if line_s == "---":
                        if not in_fm:
                            in_fm = True
                            continue
                        else:
                            break
                    if in_fm:
                        if line_s.startswith("source:"):
                            source_val = line_s.split(":", 1)[1].strip()
                        elif line_s.startswith("title:"):
                            title_val = line_s.split(":", 1)[1].strip()

                quality = _classify_source(source_val)
                if quality_filter and quality != quality_filter:
                    continue

                results.append({
                    "rel_path": rel,
                    "quality": quality,
                    "source": source_val or "(无来源标注)",
                    "title": title_val or fn.replace(".md", ""),
                })
            except Exception:
                if quality_filter and quality_filter != "ai_generated":
                    continue
                results.append({
                    "rel_path": rel,
                    "quality": "ai_generated",
                    "source": "(读取失败)",
                    "title": fn.replace(".md", ""),
                })

    # 按目录排序
    results.sort(key=lambda x: x["rel_path"])
    return results


def get_all_knowledge_for_prompt(scene_type="", device_key="", light_condition="", fallback_level="medium"):
    """
    主入口：返回知识注入文本，直接拼入 LLM prompt。
    fallback_level 控制输出量
      - "low":    搜索空，知识库当主力 → 完整输出
      - "medium": 搜索一般，知识库补充 → 精简输出
      - "high":   搜索丰富，知识库检验 → 仅风格名索引+设备
    """
    return get_knowledge_context(scene_type, device_key, light_condition, fallback_level)


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
