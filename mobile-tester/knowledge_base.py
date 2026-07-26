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


def get_knowledge_context(scene_type="", device_key="", light_condition=""):
    """
    返回注入 DIRECTIONS_PROMPT 的知识上下文。
    根据场景类型和设备，选择最相关的知识块。
    """
    parts = []

    # ── 1. 风格 one_liner 参考（核心——所有场景都需要）──
    parts.append("## 📚 风格参考（带拍知识库）\n")
    parts.append("### 风格 one_liner（全局唯一标识）")
    for name, one_liner in STYLE_ONE_LINERS.items():
        parts.append(f"- **{name}**：{one_liner}")
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

    # ── 9. 使用说明 ──
    parts.append("""
## 🚨 知识库使用规则

以上是带拍的专业摄影知识库。你必须：
1. **风格命名**：使用上述 one_liner 中的中文风格名——禁止自创英文名如 "casual_pet_daily"
2. **光线诚实标注**：对照光线矩阵，给每个风格标注 🟢完美/🟡可模拟(说明效果约X%)/🔴需等待
3. **设备诚实标注**：对照设备优势+用户能力边界，标注 🟢直接拍/🟡微调/🟠替代方案
4. **场景匹配参照**：参考场景→风格矩阵，但不要被限制——如果场景有独特之处，可以超出矩阵推荐
5. **优势思维**：不说"没有长焦所以裁切凑合"——说"手机最近对焦距离比相机更近，可以靠得更近拍微距"
6. **one_liner 优先**：引用风格时，使用上述 one_liner 的描述，不要自己重新描述
""")

    return "\n".join(parts)


def get_style_detail(style_name):
    """获取指定风格的详细信息（用于方案生成 prompt）"""
    # 尝试匹配 one_liner
    style_name_clean = style_name.strip()
    for name, one_liner in STYLE_ONE_LINERS.items():
        if name in style_name_clean or style_name_clean in name:
            return f"**{name}**：{one_liner}"

    # 模糊匹配
    for name, one_liner in STYLE_ONE_LINERS.items():
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
