#!/usr/bin/env python3
"""
直出相机 · 移动端测试工具 v3.4
在电脑上启动后，手机浏览器访问 http://<电脑IP>:8888
拍照上传 → 流式分析 → 渐进式展示 → Canvas 标注引导
"""

import base64
import io
import json
import os
import subprocess
import sys
import time
import threading
import urllib.request
from dotenv import load_dotenv
load_dotenv()
from PIL import Image
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

# ============================================================
# 配置
# ============================================================
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
EXIF_SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude/skills/zhichu/scripts/exif-extract.py")
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
REQUEST_TIMEOUT = 240

# 并发控制
_processing_lock = threading.Lock()
_processing = False

# 设备档案（精简版）
DEVICE_CONTEXTS = {
    "iphone-17-pro": {
        "name": "iPhone 17 Pro",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2× 人像 / 5× 长焦",
        "strengths": "48MP 主摄细节丰富, 5× 长焦压缩空间, 人像模式自然虚化, 夜景模式强",
        "limits": "5× 以下长焦为数码裁切, 极暗光需稳定支撑",
        "capability": "🟢 全焦段自由, 🟡 极暗光需三脚架, 🔴 无"
    },
    "iphone-17": {
        "name": "iPhone 17",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2× 长焦",
        "strengths": "48MP 主摄, 2× 人像模式, 日常场景全覆盖",
        "limits": "无 5× 长焦, 远摄靠数码变焦, 极暗光中等表现",
        "capability": "🟢 日常全场景, 🟡 远摄需走近, 🔴 体育/野生动物"
    },
    "iphone-pro-13-16": {
        "name": "iPhone Pro (13-16)",
        "lenses": "0.5× 超广角 / 1× 主摄 / 2×-5× 长焦（视型号）",
        "strengths": "三摄系统完整, ProRAW 可选, 人像模式成熟",
        "limits": "无 48MP（13-14）, 长焦画质弱于 17 Pro",
        "capability": "🟢 常规场景, 🟡 极暗/超远焦, 🔴 无"
    },
    "iphone-standard-13-16": {
        "name": "iPhone (13-16)",
        "lenses": "0.5× 超广角 / 1× 主摄",
        "strengths": "主摄素质好, 日常使用足够, 人像模式可用",
        "limits": "无长焦镜头, 远摄/空间压缩效果受限, 夜景模式中等",
        "capability": "🟢 日常记录, 🟡 远摄/人像虚化, 🔴 专业创作"
    },
    "android-flagship": {
        "name": "安卓旗舰",
        "lenses": "0.5×-0.6× 超广角 / 1× 主摄 / 3×-5× 长焦（视型号）",
        "strengths": "大底主摄像素高, 部分机型有 5× 以上潜望长焦, AI 增强可用",
        "limits": "焦段切换不如 iPhone 平滑, 人像虚化各品牌差异大, 色彩一致性弱于 iPhone",
        "capability": "🟢 主摄场景, 🟡 焦段一致性, 🔴 无"
    },
    "dslr-mirrorless": {
        "name": "单反/微单相机",
        "lenses": "取决于镜头选择",
        "strengths": "大尺寸传感器, 画质优秀, 可换镜头灵活性强, 景深控制好",
        "limits": "需选择正确镜头, 体积大不便携, 部分机型无防抖",
        "capability": "🟢 全焦段（取决于镜头）, 🟡 需用户选镜头, 🔴 无自动场景优化"
    },
    "unknown": {
        "name": "待选择",
        "lenses": "未知",
        "strengths": "未知",
        "limits": "未知",
        "capability": "🟡 设备未知, 方案将使用通用指导"
    }
}

# 相机镜头档案
LENSES = {
    "24-70-f2.8": {"name": "24-70mm f/2.8 标准变焦", "focal_range": "24-70mm", "aperture": "f/2.8", "type": "standard zoom"},
    "70-200-f2.8": {"name": "70-200mm f/2.8 长焦变焦", "focal_range": "70-200mm", "aperture": "f/2.8", "type": "telephoto zoom"},
    "16-35-f2.8": {"name": "16-35mm f/2.8 广角变焦", "focal_range": "16-35mm", "aperture": "f/2.8", "type": "wide zoom"},
    "24-105-f4": {"name": "24-105mm f/4 标准变焦", "focal_range": "24-105mm", "aperture": "f/4", "type": "standard zoom"},
    "50-f1.8": {"name": "50mm f/1.8 定焦", "focal_range": "50mm", "aperture": "f/1.8", "type": "standard prime"},
    "50-f1.2": {"name": "50mm f/1.2 定焦", "focal_range": "50mm", "aperture": "f/1.2", "type": "standard prime"},
    "85-f1.4": {"name": "85mm f/1.4 人像定焦", "focal_range": "85mm", "aperture": "f/1.4", "type": "portrait prime"},
    "85-f1.8": {"name": "85mm f/1.8 人像定焦", "focal_range": "85mm", "aperture": "f/1.8", "type": "portrait prime"},
    "35-f1.4": {"name": "35mm f/1.4 广角定焦", "focal_range": "35mm", "aperture": "f/1.4", "type": "wide prime"},
    "28-f2.8": {"name": "28mm f/2.8 广角定焦", "focal_range": "28mm", "aperture": "f/2.8", "type": "wide prime"},
    "kit-lens": {"name": "套机镜头 (18-55mm f/3.5-5.6)", "focal_range": "18-55mm", "aperture": "f/3.5-5.6", "type": "kit zoom"},
    "unknown-lens": {"name": "未知镜头", "focal_range": "未知", "aperture": "未知", "type": "unknown"}
}

# ============================================================
# 设备检测：从 EXIF 映射到设备档案
# ============================================================

def detect_device_from_exif(exif_result):
    """从 EXIF 数据中检测设备型号，返回 (device_key, device_name, is_camera)"""
    if not isinstance(exif_result, dict) or 'error' in exif_result:
        return None, None, False

    device_str = exif_result.get('device', '')
    if not device_str:
        return None, None, False

    dl = device_str.lower()

    # ── iPhone 检测 ──
    if 'iphone' in dl:
        import re
        match = re.search(r'iphone\s*(\d+)', dl)
        if match:
            model_num = int(match.group(1))
            if model_num >= 17:
                if 'pro' in dl or 'max' in dl:
                    return 'iphone-17-pro', device_str, False
                return 'iphone-17', device_str, False
            elif model_num >= 13:
                if 'pro' in dl or 'max' in dl:
                    return 'iphone-pro-13-16', device_str, False
                return 'iphone-standard-13-16', device_str, False
        return 'iphone-standard-13-16', device_str, False

    # ── Android 旗舰检测 ──
    android_flagships = [
        'pixel', 'samsung galaxy s', 'samsung galaxy z',
        'xiaomi 1', 'xiaomi m', 'oppo find', 'vivo x',
        'huawei p', 'huawei mate', 'oneplus', 'honor magic'
    ]
    if any(brand in dl for brand in android_flagships):
        return 'android-flagship', device_str, False
    if any(kw in dl for kw in ['android', 'samsung', 'xiaomi', 'oppo', 'vivo', 'huawei', 'oneplus', 'honor', 'redmi', 'poco', 'realme']):
        return 'android-flagship', device_str, False

    # ── 单反/微单检测 ──
    camera_brands = ['canon', 'sony', 'nikon', 'fujifilm', 'leica', 'panasonic', 'olympus', 'pentax', 'hasselblad', 'ricoh', 'sigma', 'lumix', 'fuji']
    if any(brand in dl for brand in camera_brands):
        return 'dslr-mirrorless', device_str, True

    return None, device_str, False


def get_lens_context(lens_key):
    """获取镜头上下文信息"""
    lens = LENSES.get(lens_key, LENSES.get('unknown-lens'))
    if not lens:
        return ""
    return f"""当前镜头：{lens['name']}
焦段范围：{lens['focal_range']}
最大光圈：{lens['aperture']}
镜头类型：{lens['type']}"""


# ============================================================
# 视觉分析 Prompt（保留核心逻辑，增强 EXIF 交叉验证提示）
# ============================================================
VISION_PROMPT = """请详细分析这张照片，输出严格的结构化JSON。必须包含以下8个字段，缺一不可。

## 核心原则：区分[观察]与[推测]

- [观察]：照片中能直接看到的视觉事实（如"天空灰白色""地面无清晰阴影""人物身着米白衬衫"）
- [推测]：从视觉线索推断的结论（如"可能为多云天气""可能为午后"）
- 禁止输出纯感受描述（如"空旷清幽""治愈松弛"）——那是下游AI的工作。

每个字段的值中，请用[观察]或[推测]标注每条信息的性质。

{
  "scene_type": "[观察]室外/室内/半室外 — [推测]具体场景类型及依据",
  "people": "人物数量、每人位置/衣着/动作/表情/姿态。如果没有人，写'无人物'。衣着用[观察]标注具体颜色和款式",
  "light": {
    "direction": "[推测]顺光/侧光/逆光/顶光/漫射 — 判断依据",
    "quality": "[推测]硬光/软光/混合 — 判断依据（阴影边缘锐利还是柔和）",
    "color_temp": "[推测]暖/中/冷 — 估算色温K值及依据",
    "special": "[观察]遮阳阴影区/斑驳树影/窗边漫射/混合色温/无特殊",
    "uncertainty": "不确定的字段名，确定就写'none'"
  },
  "color": {
    "primary": "[观察]最主导的颜色及位置",
    "secondary": "[观察]次要色及位置",
    "accent": "[观察]强调色及位置",
    "mood_axes": {
      "warmth": "0.0=全冷色, 0.5=中性, 1.0=全暖色。给一位小数。",
      "energy": "0.0=全低饱和暗沉, 0.5=中等, 1.0=全高饱和高明度。给一位小数。",
      "complexity": "0.0=单色, 0.5=2-3色系, 1.0=4+色系。给一位小数。"
    }
  },
  "space": {
    "foreground": "[观察]前景有什么",
    "midground": "[观察]中景有什么",
    "background": "[观察]背景有什么",
    "depth": "[观察]浅/中/深 — 判断依据",
    "anchors": "[观察]列出场景中可作为空间锚点的具体物体——门口盆栽、窗边沙发、路边消防栓、树荫边缘等。至少3个。这些将用于下游生成空间化拍摄指令。"
  },
  "composition": "[观察]当前构图方式 + [观察]画面中可利用的构图元素",
  "perspective": "[观察]拍摄视角（平视/俯视/仰视）+ [推测]机位高度",
  "weather_env": "[推测]天气状况及依据 + [观察]环境中可见的具体细节"
}

只输出JSON，不要任何额外文字。不要markdown代码块包裹。"""

# ============================================================
# 创意推理 Prompt（统一输出架构：摄影骨架 + 社媒包装）
# ============================================================
CREATIVE_PROMPT_TEMPLATE = """你是直出相机的摄影知识引擎。你的用户是普通大众——不是摄影师，甚至可能完全不懂拍照。他们想要的是"世俗意义上的好照片"：发朋友圈会有人点赞，看起来精致有美感，愿意分享出去。

根据以下视觉分析结果和EXIF数据，为这张照片生成拍摄指导。

## 视觉分析
{vision_json}

## EXIF数据
{exif_summary}

## 设备信息
{device_context}

## 你的任务

### Step 1: 场景沉浸
读视觉分析中的场景描述。想象你站在这个场景里——不要分类，去感受。
问自己：如果我是现场的人，我会被什么打动？这个场景里最安静的角落在哪里？

输出：2-3句"在场感受"（口语化、有画面感），然后提炼一句话洞察。
洞察必须有视觉锚点——一个能在照片里指出的具体东西（一束光、一个弧度、一个颜色）。
❌ 禁止模板句式："最动人的不是X——是Y"
❌ 禁止空洞话："刚好经过，阳光正好"

### Step 2: 风格发现
基于场景特征，从以下知识库中匹配最佳风格方向。

**风格匹配参考：**
- 室内弱暖光+人物 → 安静真实/胶片复古/电影感单光源
- 户外硬光+人物+运动 → 胶片复古/杂志时尚/负空间剪影
- 户外软光+人物+自然 → 森系/日系清新/安静真实
- 夜景暖光+建筑 → 新中式/电影感/极简建筑
- 户外漫射冷光+建筑/古村 → 中国水墨/极简建筑
- 户外硬光+旅行/环境 → 旅行纪实/风光大片
- 半室外混合光+热带/廊桥 → 旅行纪实/电影感·热带/建筑几何
- 户外漫射冷光+反季节景观 → 纪实景观/极简风光/新地形摄影
- 室内漫射晨光+居家 → 安静真实/日系清新·居家/玻璃叠影
- 户外漫射冷光+绿化 → 森系/日系清新/时尚对比
- 窗边软光+人物 → 日系清新/胶片复古/安静真实
- 夜景混合光+街拍 → 电影感/便利店美学/纪实粗粝

每个匹配风格标注：
- fit_rationale: 为什么适合
- light_annotation: 🟢完美/🟡可模拟/🔴需等待 + 说明
- device_annotation: 🟢直接拍/🟡微调/🟠替代方案 + 当前设备能做什么
- source_type: community/tutorial/portfolio/inference
- is_new_discovery: 是否在以上缓存中找不到

### Step 3: 技法选择
从以下技法池中匹配可用的拍摄技巧：

**技法池：**
- 降到宠物/儿童高度 → 改变视角，拍出新鲜感
- 人只占画面10% → 环境叙事
- 前景虚化做层次 → 花/叶/框做前景
- 蹲下让天空做背景 → 避开地面杂乱
- 只拍局部不拍脸 → 川内伦子式观看
- 等人物走过光带 → 动静对比
- 栏杆/窗框做框内框 → 框架构图
- 树冠做天然拱门 → 森系仰拍
- 侧身45°面朝光源 → 硬光面部轮廓
- 只拍影子不拍人 → 硬光剪影
- 退到暗处用负空间 → 暗调氛围
- 只拍手/道具特写 → 局部神圣化

### Step 4: 方向卡片 + 方案

按以下格式输出三个方向。每个方向自带 1-9 套拍摄方案：

🟢 **不会出错**：可执行性最高，拍出来一定好看，不需要任何技巧。焦虑型用户的 default choice。
🔥 **朋友圈会问在哪拍的**：辨识度最高，发出去会被赞的那种。社交驱动型用户的首选。
✨ **还能这样拍？**：用户想不到的视角，拍出来不像游客照。好奇心驱动型用户。

## 🚨 方案变化层次（防单调）

同一个方向下的多套方案必须有变化层次，不能让用户觉得"三套方案都在说同一件事"。变化手段按优先级：

**主要变化手段（摄影基础支撑）：**
1. **姿态变化**：站→坐→蹲→靠→走→回头。身体几何关系改变 = 照片结构改变。参考：重心转移、脊柱线方向、手部任务变化。
2. **景别变化**：远景（人物+环境关系）→ 中景（姿态+表情）→ 近景（表情+细节）→ 特写（纹理+光线）。不同景别=不同叙事重点。
3. **角度变化**：平视→俯拍（显脸小/地面图案感）→ 仰拍（显高/天空做背景）→ 侧拍（展示身体 S 曲线）。机位高度和方向的变化带来全新的画面结构。

**次要变化手段（辅助丰富）：**
4. **构图变化**：三分法→居中→负空间→对角线→框架构图。
5. **光线利用变化**：顺光→侧光→逆光→利用阴影/剪影。

**变化层次要求：**
- 1 套方案 = 最佳建议即可
- 2-3 套 = 必须使用不同的主要变化手段（如方案1姿态变化、方案2景别变化、方案3角度变化）
- 4+ 套 = 主要+次要变化手段组合使用
- 在原图基础上微调可以作为一个方案（如"站在原地不动，只是换个角度"），但不能所有方案都是微调
- 如果场景简单（如"安静真实""旅行纪实"等不依赖特殊光线/色彩的风格），更要多给姿态/景别/角度的变化——让用户感到"原来还能这样拍"
- 所有变化必须有摄影理论基础支撑（透视、景深、身体线条、视觉重量），不是 AI 随意发挥

每个方向包含：
- style: 内部风格名（如"日系清新"）
- style_promise: 风格翻译为效果语言（如"干净透亮，像日剧里的画面"）
- subtitle: 这个方向的效果承诺（如"拍出来一定好看"）
- reason: 推荐理由——朋友分享口吻，像拍过很多照片的人指着画面说话
- how: 一句话操作概述
- source_note: 来源标注
- plans: 1-9 套具体方案。数量按场景灵活决定——变化丰富的场景给 5-9 套，简单的给 2-4 套。不凑数。

每套方案的字段：

① **name**: 方案名——能让人记住的，不是"方案1""方案2"。如"让阳光给你打光"。

② **prep**（要准备什么）：降低心理门槛。能写"什么都不用准备，站过去就行"就不要写"准备三脚架和反光板"。

③ **where**（你站这）：空间锚点指令。必须引用视觉分析中[观察]到的具体场景元素（🚨 见下方场景锚点约束）。❌ 禁止写"距门3米"之类的距离数字——用"退到门口大盆栽旁边"这种空间参照。

④ **do**（这样做）：动作指令。❌ 禁止摄影术语（光圈、ISO、快门、焦距）。用"蹲下来""手机举到胸口""竖着拿""连拍"这种任何人一听就懂的动作语言。

⑤ **result**（拍出来）：效果预览。用效果语言描述拍出来会是什么感觉。如"窗边的光会打到侧脸，背景自然虚掉——整张照片像在巴黎街头咖啡馆，没人看得出是楼下瑞幸。"

⑥ **why**（为什么好看）：摄影原理。解释为什么这样拍好看——如"低机位改变了透视关系，地面线条向远处延伸，人物在环境中的比例被衬托得刚好。侧光让面部轮廓立体但不生硬。"这段话是给想深入了解的用户看的，用摄影知识但不堆术语。

⑦ **posture**（姿态与表情引导）：如果场景有人物，必须写。如果没有人物，设为空字符串""。
  不给"摆造型"指令——给"做一件事"的指令。
  引导框架：
  - 脊柱与重心：侧身还是正面？重心在哪条腿？（"重心放右腿，左腿微曲——像等公交车不是站军姿"）
  - 手部任务：手在做什么？不给空手（"手搭在栏杆上，拇指自然松开""一手插口袋，拇指露在外面"）
  - 眼神方向：看哪？（看镜头/看远方/看手中的东西/回头看）
  - 表情触发：不说"笑"——给动作或回忆触发（"想一件刚才发生的搞笑的事，忍住不笑""叹一口大气，叹气完那一瞬间"）
  三层指令优先级：
  L1 叙事："靠在栏杆上，像在等一个人"
  L2 感受："叹一口大气——叹气完肩膀自然下沉那一瞬间"
  L3 物理："重心放右腿，左腿微曲，下巴收一点，肩膀往后展开"
  如果被拍者紧张 → 给一个具体任务转移注意力（"你转头看看那边有什么"）。
  如果场景无人物 → posture 为空字符串 ""。

⑧ **annotations**（视觉标注）：只标注文字说不精确的内容。不是每个方案都需要标注——通常 1-2 个，最多 3 个。标注太多会遮挡照片。
  仅使用以下 4 种类型：
  - subject: 被摄者在画面内的精确位置——实心圆点。如画面1/3处，靠嘴说不准。
  - shooter: 拍摄者在画面外的站位和拍摄方向——📷图标在画面边缘 + 虚线引导线穿过画面指向目标 + 角度弧线。如"站左侧退三步蹲下朝右上方拍"。
  - frame: 取景范围——虚线矩形。如"把人和窗边绿植都框进去"，说不准边界。
  - crop: 裁剪建议——半透明遮罩 + 裁剪边框。如"裁掉上方1/4"，说不准比例。

  标注格式：{{"type": "subject", "x": 0.35, "y": 0.72, "label": "站这", "color": "#4ade80"}}
  - subject: x,y 为被摄者位置（0-1 相对坐标，0=左/上，1=右/下）
  - shooter: from={{x,y}} 为📷拍摄者位置（画面外边缘坐标），to={{x,y}} 为拍摄目标方向，另有 angle 字段标注角度文字
  - frame: 额外需要 w, h 字段
  - crop: 额外需要 w, h 字段
  - color 用 #4ade80（绿）/ #f59e0b（金）/ #a78bfa（紫），对应方向颜色
  - 一个方案通常只需 1-2 个标注，最多 3 个。不要为了标注而标注。

⑨ **perspective**（换个思路）：这套方案"看见的方式"和其他方案的本质不同。有真正差异才写，没差异不硬凑。

## 🚨 场景锚点强制约束

每个方案 where 和 do 中的空间指令，**必须**引用视觉分析 space.anchors 字段中 [观察] 到的具体场景元素。
不得使用任何不依赖具体场景就能执行的通用建议。

❌ 模板式（拒绝）："低角度仰拍，让人物显得修长"（任何场景通用）
✅ 场景锚点（通过）："站到左边那棵树的树荫边缘，让阳光从树叶间漏下来正好打在肩膀上"（只有这个场景能做到）

## 🚨 EXIF 交叉验证

- ISO≥800 但视觉识别为"明亮" → 采信 EXIF，修正光线分析。标注"光线实际较暗，建议稳定支撑"
- 闪光灯触发 → 自然光分析需整体修正
- 快门<1/60s → 方案中标注"手持可能糊片，建议找支撑点或连拍"
- 无 EXIF → 完全依赖视觉分析，不标注设备参数相关建议

## 🚨 风格翻译规则

输出中 style 保留内部风格名（供前端选择性展示），但 style_promise 必须翻译为效果语言：
- "日系清新" → "干净透亮，像日剧里的画面"
- "胶片复古" → "像胶片相机拍的，有颗粒感和怀旧色调"
- "电影感" → "像电影截图，有故事氛围"
- "森系" → "像森林里自然生长出来的画面"
- "安静真实" → "自然到像没拍过，但就是好看"
- "极简建筑" → "干净利落，像建筑杂志封面"
- "中国水墨" → "像一幅水墨画，留白有意境"
- "旅行纪实" → "像国家地理的旅行照片，有现场感"
- "杂志时尚" → "像时尚杂志的内页大片"
- "便利店美学" → "像王家卫电影里的深夜便利店"
- "新地形摄影" → "冷静客观，像在记录这个时代的风景"
- "负空间剪影" → "人物是剪影，环境讲故事"

## 🚨 口吻约束
- 像朋友分享观察，不像策展人写说明
- ❌ 禁止摄影术语直接出现（光圈、ISO、快门、焦距、焦段、曝光值、白平衡、景深）
- ❌ 禁止第一人称"我"
- ✅ 用"你"视角——"你没叫她看镜头""你站在这儿就能拍到"
- ✅ 允许意外："拍完才发现最好看的不是表情"
- 有话则长无话则短。平淡场景一句话真诚推荐比三句话空洞套路有价值

## 🚨 长度控制
- presence: 2-3句，不超过80字
- insight: 1句话，不超过30字
- reason: 2-3句，不超过100字
- where: 1-2句
- do: 2-4句
- result: 2-3句
- why: 2-3句
- style_promise: 1句，不超过25字

## 输出格式

严格输出以下 JSON（不要markdown包裹）。directions 必须是 ARRAY 格式，不是 OBJECT：

{{
  "presence": "在场感受——2-3句，口语化",
  "insight": "一句话洞察——最动人的视觉锚点，不超过30字",
  "directions": [
    {{
      "id": "now",
      "emoji": "🟢",
      "label": "不会出错",
      "subtitle": "拍出来一定好看",
      "style": "内部风格名",
      "style_promise": "风格翻译为效果语言",
      "reason": "推荐理由——朋友分享口吻，不超过100字",
      "how": "一句话操作概述",
      "source_note": "来源标注",
      "plans": [
        {{
          "name": "方案名，能让人记住的",
          "prep": "什么都不用准备" 或具体准备项,
          "where": "空间锚点——引用视觉分析中[观察]到的具体物体位置",
          "do": "动作指令——零术语，纯动词",
          "result": "效果预览——用效果语言描述拍出来是什么感觉",
          "why": "摄影原理——为什么这样好看，2-3句，不堆术语",
          "posture": "姿态与表情引导——有人物必写，无人物为空字符串",
          "annotations": [
            {{"type": "subject", "x": 0.35, "y": 0.72, "label": "站这", "color": "#4ade80"}},
            {{"type": "shooter", "from": {{"x": 0.05, "y": 0.85}}, "to": {{"x": 0.4, "y": 0.5}}, "angle": "蹲下·45°仰拍", "color": "#4ade80"}},
            {{"type": "frame", "x": 0.1, "y": 0.05, "w": 0.8, "h": 0.6, "label": "取景范围", "color": "#4ade80"}},
            {{"type": "crop", "x": 0, "y": 0, "w": 1, "h": 0.75, "label": "裁掉上方1/4", "color": "#f59e0b"}}
          ],
          "perspective": "🎯 换个思路——有真正差异才写，可选"
        }}
      ]
    }},
    {{
      "id": "best",
      "emoji": "🔥",
      "label": "朋友圈会问在哪拍的",
      "subtitle": "发出去会被赞的那种",
      "style": "内部风格名",
      "style_promise": "风格翻译为效果语言",
      "reason": "推荐理由",
      "how": "一句话操作概述",
      "source_note": "来源标注",
      "plans": []
    }},
    {{
      "id": "creative",
      "emoji": "✨",
      "label": "还能这样拍？",
      "subtitle": "不像游客照的视角",
      "style": "内部风格名",
      "style_promise": "风格翻译为效果语言",
      "reason": "推荐理由",
      "how": "一句话操作概述",
      "source_note": "来源标注",
      "plans": []
    }}
  ],
  "search_quality": {{
    "overall": "🟢/🟡/🔴",
    "honest_note": "如有需要诚实告知的内容"
  }},
  "discovered_styles": [
    {{
      "name": "风格名",
      "source_type": "community/tutorial/portfolio/inference",
      "fit_rationale": "为什么适合",
      "light_annotation": "🟢/🟡/🔴 + 说明",
      "device_annotation": "🟢/🟡/🟠 + 当前设备说明"
    }}
  ],
  "techniques_used": [
    {{
      "name": "技法名",
      "source_type": "community/tutorial/portfolio/inference",
      "description": "如何融入方案"
    }}
  ]
}}

如果一个方向没有合适的内容（如🔥没有高辨识度方向），把该方向除了 id/emoji/label/subtitle 外的所有字段设为 null。plans 设空数组。
🔥 和 ✨ 至少有一个有实质内容（不能两个都是 null）。
plans 按需给 1-9 套，不凑数。

## 🚨 格式警告
❌ WRONG: "directions": {{"now": {{...}}, "best": {{...}}}}  ← v2 OBJECT 格式，会崩溃
✅ CORRECT: "directions": [{{"id": "now", ...}}, {{"id": "best", ...}}]  ← v3 ARRAY 格式

🚨 IMPORTANT: directions 必须是数组 []，不是对象 {{}}。必须遵守！"""


# ============================================================
# 辅助函数
# ============================================================

def extract_exif(image_path):
    """提取 EXIF 数据"""
    try:
        result = subprocess.run(
            [sys.executable, EXIF_SCRIPT, image_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"error": result.stderr}
    except Exception as e:
        return {"error": str(e)}


def call_doubao(messages, max_tokens=2000):
    """调用豆包 API"""
    payload = {
        "model": DOUBAO_MODEL,
        "messages": messages,
        "max_tokens": max_tokens
    }
    req = urllib.request.Request(
        DOUBAO_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DOUBAO_API_KEY}"
        }
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        result = json.loads(resp.read().decode())
    content = result['choices'][0]['message']['content'].strip()

    # ── 健壮的 JSON 提取 ──
    import re

    # 策略 1: 提取 ```json ... ``` 或 ``` ... ``` 之间的内容
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if m:
        content = m.group(1).strip()
    elif content.startswith('```'):
        # 策略 1b: 开头有 ``` 但没匹配到闭合（可能 ``` 在行尾）
        lines = content.split('\n')
        # 去掉第一行（``` 或 ```json）
        content = '\n'.join(lines[1:])
        if content.endswith('```'):
            content = content[:-3].strip()

    # 策略 2: 如果仍不是有效 JSON，尝试提取第一个 { 到最后一个 }
    try:
        json.loads(content)
    except (json.JSONDecodeError, ValueError):
        start = content.find('{')
        end = content.rfind('}')
        if start >= 0 and end > start:
            extracted = content[start:end+1]
            # 验证提取后的是否有效
            try:
                json.loads(extracted)
                content = extracted
            except (json.JSONDecodeError, ValueError):
                pass  # 保持原 content，后续 parse_json_safe 会处理

    return content, result.get('usage', {})


def normalize_creative_output(data):
    """修复输出格式：v2 object → v3 array，处理各种边缘情况"""
    if not isinstance(data, dict):
        return data

    directions = data.get('directions')
    if directions is None:
        # directions 缺失——可能是 parse_error 对象
        if data.get('parse_error'):
            return data
        data['directions'] = []
        data['_format_warning'] = 'directions 字段缺失，已重置为空数组'
        return data

    # 已经是 array 格式
    if isinstance(directions, list):
        # 补齐缺失字段
        for d in directions:
            if not isinstance(d, dict):
                continue
            d.setdefault('emoji', '')
            d.setdefault('label', '')
            d.setdefault('style', '')
            d.setdefault('reason', '')
            d.setdefault('how', '')
            d.setdefault('source_note', '')
            d.setdefault('plans', [])
            d.setdefault('subtitle', '')
            d.setdefault('style_promise', '')
            # Ensure posture default on each plan
            for p in d.get('plans', []):
                if isinstance(p, dict):
                    p.setdefault('posture', '')
        return data

    # v2 object 格式（{"now": {...}, "best": {...}}） → 转换为 array
    if isinstance(directions, dict):
        dir_ids = {'now': {'emoji': '🟢', 'label': '不会出错', 'subtitle': '拍出来一定好看'},
                    'best': {'emoji': '🔥', 'label': '朋友圈会问在哪拍的', 'subtitle': '发出去会被赞的那种'},
                    'creative': {'emoji': '✨', 'label': '还能这样拍？', 'subtitle': '不像游客照的视角'}}
        array_dirs = []
        for key, defaults in dir_ids.items():
            d = directions.get(key, {})
            if isinstance(d, dict):
                d['id'] = key
                d.setdefault('emoji', defaults['emoji'])
                d.setdefault('label', defaults['label'])
                d.setdefault('subtitle', defaults['subtitle'])
                d.setdefault('style', '')
                d.setdefault('style_promise', '')
                d.setdefault('reason', '')
                d.setdefault('how', '')
                d.setdefault('source_note', '')
                d.setdefault('plans', [])
                for p in d.get('plans', []):
                    if isinstance(p, dict):
                        p.setdefault('posture', '')
                array_dirs.append(d)
        if array_dirs:
            data['directions'] = array_dirs
            return data
        # v2 dict 但没有任何可识别的 key —— 尝试把每个 value 当方向
        array_dirs = []
        for key, d in directions.items():
            if isinstance(d, dict):
                d.setdefault('id', str(key))
                d.setdefault('emoji', '')
                d.setdefault('label', str(key))
                d.setdefault('subtitle', '')
                d.setdefault('style', '')
                d.setdefault('style_promise', '')
                d.setdefault('reason', '')
                d.setdefault('how', '')
                d.setdefault('source_note', '')
                d.setdefault('plans', [])
                for p in d.get('plans', []):
                    if isinstance(p, dict):
                        p.setdefault('posture', '')
                array_dirs.append(d)
        if array_dirs:
            data['directions'] = array_dirs
            return data

    # 无法识别的 directions 格式 → 记录并重置
    direction_type = type(directions).__name__
    data['_format_warning'] = f'directions 格式异常（类型: {direction_type}），已重置为空数组'
    data['directions'] = []
    return data


def repair_json(text):
    """本地修复常见 JSON 语法错误 + 截断恢复"""
    import re

    stripped = text.rstrip()

    # 0. 截断恢复：检测 JSON 是否被 token 限制截断
    # 如果最后非空白字符不是 } ] " 或数字，可能被截断
    needs_closure = False
    if stripped and stripped[-1] not in ('}', ']', '"') and not stripped[-1].isdigit():
        # 被截断了——找到最后一个安全的截断点（逗号或冒号后面）
        # 回退到最后一个完整的 key-value 对
        last_comma = stripped.rfind(',')
        if last_comma > len(stripped) * 0.5:
            # 从最后一个逗号处截断
            truncated = stripped[:last_comma]
            needs_closure = True
        else:
            # 找不到逗号，找最后一个 }
            last_brace = stripped.rfind('}')
            if last_brace > len(stripped) * 0.5:
                truncated = stripped[:last_brace + 1]
                # 可能不需要额外闭合，但 directions 数组可能没闭合
                needs_closure = True
            else:
                truncated = stripped

        if needs_closure:
            # 计算需要补的闭合括号
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            truncated += '\n' + ']' * open_brackets + '}' * open_braces
            text = truncated

    # 1. 移除 trailing commas（在 ] 或 } 之前的逗号）
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # 2. 修复字符串中未转义的控制字符
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            result.append(ch)
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch == '\n':
            result.append('\\n')
            continue
        if in_string and ch == '\r':
            result.append('\\r')
            continue
        if in_string and ch == '\t':
            result.append('\\t')
            continue
        result.append(ch)
    text = ''.join(result)

    return text


def parse_json_safe(content, retry_prompt=None):
    """安全解析 JSON。先尝试直接解析，失败后本地修复，再失败才 API retry"""
    parse_errors = []

    # ── 尝试 1: 直接解析 ──
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        parse_errors.append(f"直接解析失败: {e}")

    # ── 尝试 2: 本地修复后解析 ──
    repaired = repair_json(content)
    try:
        data = json.loads(repaired)
        print(f"[SSE] JSON repaired locally (was {len(content)} chars)", file=sys.stderr, flush=True)
        return data, None
    except json.JSONDecodeError as e:
        parse_errors.append(f"本地修复后仍失败: {e}")

    # ── 尝试 3: 重新提取 JSON 边界 ──
    # 找最外层的 { }
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                extracted = content[start:i+1]
                # 修复后尝试
                extracted_repaired = repair_json(extracted)
                try:
                    data = json.loads(extracted_repaired)
                    print(f"[SSE] JSON extracted from braces (was {len(content)} chars, extracted {len(extracted)} chars)", file=sys.stderr, flush=True)
                    return data, None
                except json.JSONDecodeError as e:
                    parse_errors.append(f"括号提取后仍失败: {e}")
                break

    # ── 尝试 4: API retry（最后的办法） ──
    if retry_prompt:
        print(f"[SSE] JSON parse failed after 3 attempts: {'; '.join(parse_errors)}", file=sys.stderr, flush=True)
        # 保存原始内容前 200 字符供调试
        print(f"[SSE] Raw content start: {content[:200]}", file=sys.stderr, flush=True)
        print(f"[SSE] Raw content end: ...{content[-200:]}", file=sys.stderr, flush=True)

        # 改进 retry prompt：带上原始错误信息
        full_retry = f"""{retry_prompt}

原始输出的JSON解析错误：{parse_errors[-1]}
请务必输出完整JSON，包含所有字段。特别是 directions 必须是数组格式。"""
        try:
            retry_content, _ = call_doubao([
                {"role": "user", "content": full_retry}
            ], max_tokens=4000)
            retry_content = repair_json(retry_content)
            try:
                data = json.loads(retry_content)
                print(f"[SSE] Retry succeeded: {len(retry_content)} chars", file=sys.stderr, flush=True)
                return data, None
            except json.JSONDecodeError as e:
                parse_errors.append(f"API retry 仍失败: {e}")
        except Exception as e:
            parse_errors.append(f"API retry 异常: {e}")

    # ── 全部失败 ──
    print(f"[SSE] All JSON parse attempts failed: {'; '.join(parse_errors)}", file=sys.stderr, flush=True)
    return {"raw": content[:500], "parse_error": True, "errors": parse_errors}, parse_errors[-1]


# ============================================================
# 流式分析生成器
# ============================================================

def analyze_photo_stream(image_path, device_override=None, lens_key=None):
    """流式照片分析——SSE 事件生成器
    device_override: 用户手动选择的设备（优先级高于 EXIF 自动检测）
    lens_key: 相机镜头选择（仅相机设备时有效）
    """
    global _processing
    t0 = time.time()

    def emit(event, data):
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def emit_progress(phase, text):
        return emit("progress", {"phase": phase, "text": text})

    try:
        # ── Phase 0: 图片载入 ──
        print("[SSE] Starting analysis...", file=sys.stderr, flush=True)
        yield emit_progress("exif", "正在读取照片信息...")

        ext = os.path.splitext(image_path)[1].lower()
        try:
            img = Image.open(image_path)
            if img.mode in ('RGBA', 'P', 'LA'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=92)
            img_b64 = base64.b64encode(buf.getvalue()).decode()
            mime_type = "image/jpeg"
            print(f"[SSE] Image loaded: {img.size}, {len(img_b64)} chars base64", file=sys.stderr, flush=True)
        except Exception as imgerr:
            print(f"[SSE] Image open error: {imgerr}", file=sys.stderr, flush=True)
            yield emit("error", {"message": f"无法读取照片: {str(imgerr)}"})
            _processing = False
            return

        # ── Phase 1: EXIF + 视觉 API 并行 ──
        exif_result = {"error": "未执行"}
        vision_result = {"error": "未执行"}

        def do_exif():
            nonlocal exif_result
            try:
                exif_result = extract_exif(image_path)
            except Exception as e:
                exif_result = {"error": str(e)}
                print(f"[SSE] EXIF thread error: {e}", file=sys.stderr, flush=True)

        def do_vision():
            nonlocal vision_result
            try:
                print("[SSE] Vision API starting...", file=sys.stderr, flush=True)
                result, usage = call_doubao([
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}},
                        {"type": "text", "text": VISION_PROMPT}
                    ]}
                ], max_tokens=2000)
                print(f"[SSE] Vision API done: {usage.get('total_tokens','?')} tokens", file=sys.stderr, flush=True)
                vision_result = {"content": result, "usage": usage}
            except Exception as e:
                vision_result = {"error": str(e)}
                print(f"[SSE] Vision thread error: {e}", file=sys.stderr, flush=True)

        t_exif = threading.Thread(target=do_exif)
        t_vision = threading.Thread(target=do_vision)
        t_exif.start()
        t_vision.start()
        t_exif.join()  # EXIF 通常先完成（~1s vs 30-60s for vision）
        t_vision.join()
        print("[SSE] EXIF + Vision threads joined", file=sys.stderr, flush=True)

        # ── 设备自动检测（EXIF 优先，用户手动覆盖次之） ──
        exif_summary = "无EXIF数据"
        detected_device_key = None
        detected_device_name = None
        is_camera = False

        if isinstance(exif_result, dict) and 'error' not in exif_result:
            exif_summary = json.dumps(exif_result, ensure_ascii=False)
            detected_device_key, detected_device_name, is_camera = detect_device_from_exif(exif_result)

        # 确定最终设备：用户手动选择 > EXIF 自动检测 > unknown
        if device_override:
            final_device_key = device_override
            device_source = "manual"
        elif detected_device_key:
            final_device_key = detected_device_key
            device_source = "exif"
        else:
            final_device_key = "unknown"
            device_source = "none"

        device_ctx = DEVICE_CONTEXTS.get(final_device_key, DEVICE_CONTEXTS["unknown"])
        device_text = f"""当前设备：{device_ctx['name']}
可用焦段：{device_ctx['lenses']}
设备优势：{device_ctx['strengths']}
设备限制：{device_ctx['limits']}
能力边界：{device_ctx['capability']}"""

        # 镜头上下文（仅相机设备）
        if is_camera and lens_key:
            lens_text = get_lens_context(lens_key)
            if lens_text:
                device_text += f"\n{lens_text}"

        # 发送设备检测结果给前端
        yield emit("device_detected", {
            "device_key": final_device_key,
            "device_name": device_ctx['name'],
            "exif_device": detected_device_name or "",
            "is_camera": is_camera,
            "source": device_source,
            "lens_options": list(LENSES.keys()) if is_camera else None
        })

        print(f"[SSE] Device: {device_ctx['name']} (source={device_source}, is_camera={is_camera})", file=sys.stderr, flush=True)

        # ── 处理视觉结果 ──
        vision_content = vision_result.get("content", "")
        vision_usage = vision_result.get("usage", {})
        vision_error_msg = vision_result.get("error", "")

        if vision_error_msg:
            print(f"[SSE] Vision API failed: {vision_error_msg}", file=sys.stderr, flush=True)
            yield emit("error", {"message": f"视觉分析失败: {vision_error_msg}"})
            _processing = False
            return

        if not vision_content:
            print("[SSE] Vision API returned empty content", file=sys.stderr, flush=True)
            yield emit("error", {"message": "视觉分析返回空结果，请换张照片重试"})
            _processing = False
            return

        vision_json, vision_error = parse_json_safe(vision_content)
        if vision_error or (isinstance(vision_json, dict) and vision_json.get('parse_error')):
            print(f"[SSE] Vision parse error: {vision_error}", file=sys.stderr, flush=True)
            yield emit("error", {"message": "视觉分析结果解析失败，请换张照片重试"})
            _processing = False
            return

        print("[SSE] Vision parsed OK", file=sys.stderr, flush=True)
        yield emit_progress("vision", "场景识别完成，正在理解你的画面...")

        # ── Phase 2: 创意推理 ──
        yield emit_progress("creative", "正在为你设计拍摄方案...")

        creative_prompt = CREATIVE_PROMPT_TEMPLATE.format(
            vision_json=json.dumps(vision_json, ensure_ascii=False, indent=2),
            exif_summary=exif_summary,
            device_context=device_text
        )
        print(f"[SSE] Creative prompt size: {len(creative_prompt)} chars, starting API...", file=sys.stderr, flush=True)
        creative_content, creative_usage = call_doubao([
            {"role": "user", "content": creative_prompt}
        ], max_tokens=8000)
        print(f"[SSE] Creative API done: {creative_usage.get('total_tokens','?')} tokens", file=sys.stderr, flush=True)

        # 解析创意输出
        creative_json, creative_error = parse_json_safe(
            creative_content,
            retry_prompt="你上次的输出不是有效JSON。请重新输出，只输出纯JSON对象，不要markdown包裹，不要任何额外文字。确保所有字符串正确引号包裹，所有逗号位置正确。"
        )

        # ── 诊断日志：每次请求都打印 ──
        raw_len = len(creative_content)
        raw_preview = creative_content[:300].replace('\n', '\\n')
        is_parse_error = isinstance(creative_json, dict) and creative_json.get('parse_error')
        print(f"[SSE] Creative raw: {raw_len} chars, parse_error={is_parse_error}, preview: {raw_preview}", file=sys.stderr, flush=True)

        # 格式修复
        creative_json = normalize_creative_output(creative_json)

        # 验证 directions 格式
        if isinstance(creative_json, dict):
            dirs = creative_json.get('directions')
            if not isinstance(dirs, list):
                dir_type = type(dirs).__name__
                print(f"[SSE] WARNING: directions is {dir_type}, not list. Resetting.", file=sys.stderr, flush=True)
                # Log first 500 chars of raw creative content for debugging
                raw_preview = creative_content[:500].replace('\n', '\\n')
                print(f"[SSE] Raw creative preview: {raw_preview}", file=sys.stderr, flush=True)
                creative_json['directions'] = []
                if not creative_json.get('_format_warning'):
                    creative_json['_format_warning'] = f'directions 格式异常（{dir_type}），已重置为空数组'

        total_time = round(time.time() - t0, 1)
        total_tokens = vision_usage.get('total_tokens', 0) + creative_usage.get('total_tokens', 0)

        full_result = {
            "success": True,
            "elapsed": total_time,
            "tokens": total_tokens,
            "exif": exif_summary,
            "result": creative_json
        }

        result_json = json.dumps(full_result, ensure_ascii=False)
        has_warning = isinstance(creative_json, dict) and creative_json.get('_format_warning')
        dirs_count = len(creative_json.get('directions', [])) if isinstance(creative_json, dict) else 0
        print(f"[SSE] Result: {len(result_json)} chars, {dirs_count} dirs, warning={has_warning}", file=sys.stderr, flush=True)
        print(f"[SSE] Complete! {total_time}s, {total_tokens} tokens", file=sys.stderr, flush=True)
        yield emit("complete", full_result)

    except Exception as e:
        import traceback
        print(f"[SSE] ERROR: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        yield emit("error", {"message": str(e)})
    finally:
        _processing = False
        print("[SSE] Generator finished", file=sys.stderr, flush=True)


# ============================================================
# Flask 路由
# ============================================================

@app.route('/')
def index():
    """移动端主页"""
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    """流式分析上传的照片（SSE）"""
    global _processing

    if not DOUBAO_API_KEY:
        return jsonify({"success": False, "error": "API Key 未配置"}), 500

    if _processing:
        return jsonify({"success": False, "error": "正在处理上一个请求，请稍候"}), 429

    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "未收到照片"}), 400

    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 检查文件大小
    photo.seek(0, 2)  # seek to end
    size = photo.tell()
    photo.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"success": False, "error": f"照片太大（{size//1024//1024}MB），限制 {MAX_FILE_SIZE//1024//1024}MB"}), 400

    # 保存临时文件
    ext = os.path.splitext(photo.filename)[1] or '.jpg'
    tmp_path = f"/tmp/zhichu_{int(time.time())}_{os.getpid()}{ext}"
    photo.save(tmp_path)

    # 读取设备参数
    device_override = request.form.get('device', None) or None  # 空字符串 → None
    lens_key = request.form.get('lens', None) or None

    _processing = True

    def cleanup_and_generate():
        try:
            yield from analyze_photo_stream(tmp_path, device_override, lens_key)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return Response(
        stream_with_context(cleanup_and_generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # 禁用 nginx 缓冲
            'Connection': 'keep-alive'
        }
    )


@app.route('/health')
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "api_key_configured": bool(DOUBAO_API_KEY),
        "exif_script_exists": os.path.exists(EXIF_SCRIPT),
        "processing": _processing
    })


if __name__ == '__main__':
    # 打印访问地址
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    print(f"""
╔══════════════════════════════════════════╗
║       直出相机 · 移动端测试工具 v3.4      ║
║                                          ║
║  手机浏览器访问:                          ║
║  → http://{local_ip}:8888          ║
║                                          ║
║  确保手机和电脑在同一 WiFi 网络            ║
║  按 Ctrl+C 停止服务器                     ║
╚══════════════════════════════════════════╝
    """)

    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
