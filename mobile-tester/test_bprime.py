#!/usr/bin/env python3
"""
B' 版对比测试：保留三条关键词 + 压缩辅助字段示例
"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
import httpx

DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
TIMEOUT = 180

VISION_JSON = {
    "scene_type": "[观察]室外 — [推测]高原湖泊沿岸的户外观景场景",
    "primary_subject": "[观察]扶着一体式大框墨镜的年轻东亚男性",
    "people": "1人，位于画面前景偏下区域；[观察]内搭浅蓝色翻领衬衫，外穿黑色皮质罗纹领夹克；[观察]左手抬起扶着脸上的透明边框一体式墨镜，面向镜头",
    "light": {"direction": "[推测]顺光", "quality": "[推测]硬光", "color_temp": "[推测]冷，约6200K", "special": "[观察]无特殊", "level": "[推测]充足"},
    "color": {"primary": "[观察]蓝色，天空和水体", "secondary": "[观察]黑色，皮质夹克", "accent": "[观察]透银色，墨镜边框"},
    "space": {"foreground": "[观察]人物上半身", "midground": "[观察]开阔平静水体", "background": "[观察]连绵灰褐色山体、白云蓝天", "depth": "[观察]深，前景中景背景层级明确", "anchors": "[观察]一体式大框墨镜、水体山体交界线、山脊线、白色积云"},
    "composition": "[观察]近景自拍构图，人物占下半部分，上半为开阔自然背景；可利用水平水岸线、山脊线、云带等水平线条",
    "location_clues": "符合云南大理洱海典型地貌",
    "specific_location": "中国云南大理洱海",
    "distinctive_traits": "无"
}

MATERIAL_INVENTORY = """## 📦 素材清单（每条方案必须引用 ≥1 个素材）

### 🧑 人物状态
1人，位于画面前景偏下区域；内搭浅蓝色翻领衬衫，外穿黑色皮质罗纹领夹克；左手抬起扶着脸上的透明边框一体式墨镜，面向镜头；嘴唇微张，看向镜头方向

### 📍 场景锚点（用于空间化指令）
一体式大框墨镜、水体与山体的交界线、山体的山脊线、天空中的白色积云
> 站位/坐位/靠位必须指名具体锚点

### 📐 空间层次
- 纵深：深
- 前景：人物上半身
- 中景：开阔平静水体
- 背景：连绵灰褐色山体、白云蓝天

### 💡 光线条件
- 方向：顺光
- 质感：硬光
- 色温：冷，约6200K
- 特殊光：无特殊
- 亮度：充足

### 🎨 色彩信息
- 主色：蓝色，天空和水体
- 次要色：黑色，皮质夹克
- 强调色：透银色，墨镜边框

### 🖼️ 构图元素
近景自拍构图，人物占下半部分，上半为开阔自然背景；可利用水平水岸线、山脊线、云带等水平线条"""

FORBIDDEN_SLIM = """## 🚫 禁止型约束

### 设备限制（手机）
- ❌ 不提专业灯光/具体光圈/专业修图软件
- ✅ 可用'人像模式''2×变焦''0.5×超广角'、'醒图''VSCO'

### 审美禁忌
- ❌ 全身照+俯拍 → 头大身小
- ❌ 闪光灯直打 → 油光反光"""

DEVICE_CONTEXT = """当前设备：iPhone (13-16)
可用焦段：0.5× 超广角 / 1× 主摄
设备优势：主摄素质好, 日常使用足够, 人像模式可用
设备限制：无长焦镜头, 远摄/空间压缩效果受限, 夜景模式中等
能力边界：🟢 日常记录, 🟡 远摄/人像虚化, 🔴 专业创作"""

ENV_CONTEXT = """## 🌤 拍摄环境上下文
- 光照时段：☀️ 下午光
- 日出 08:07 / 日落 18:42
- AI亮度评估：充足
- GPS地点：中国 · 云南省 · 大理市 · 大理镇"""

SCENE_TEMPLATE_MATCHED = """### 🌤 户外通用思路
- 找光：先看光线方向——顺光色彩饱和/侧光有立体感/逆光有氛围。让人物面朝光源方向或站在明暗交界处
- 简化背景：手机拍照背景容易乱——移动位置让背景变成纯色（天空/草地/墙面），或走近让人物填满画面
- 空间层次：前景+中景+背景三层——前景找一片叶子/花丛虚化，中景是人物，背景是环境"""

# ============================================================
# PROMPT B': 保留三条关键词 + 压缩辅助字段示例
# 保留：① 问题2的"一棵树"示例 ② 情绪起伏 ③ 破格位置
# 压缩：subject/shooter/enhance/result 保留示例，其余12字段只留一行
# ============================================================
PROMPT_B_PRIME = f"""你是摄影指导——把一条风格方向变成具体可执行的拍摄方案。

## 🚨 核心原则

### 1. 素材绑定（最高优先级）
每条方案的 subject/shooter/gear/enhance 都必须引用「素材清单」中的 ≥1 个具体元素。
❌ "换个角度""注意光线"——放任何照片都能用的 = 废案。

### 2. 前期优先（铁律）
⛔ subject/shooter/gear/enhance 四个字段必须全部是「拍摄现场就能做的事」。
风格中的光线/构图/视角/空间 → 写进 shooter/enhance（前期）。色彩倾向 → quick_edit（后期）。
⛔ 禁止把"改变构图""蹲下仰拍"写成后期操作。

### 3. 诚实原则
场景给不出9套 → 就少给。3-5套有真差异的 > 9套灌水的。

## 场景信息
{json.dumps(VISION_JSON, ensure_ascii=False, indent=2)}

## 📦 素材清单（每条方案必须引用 ≥1 个）
{MATERIAL_INVENTORY}

## 🎯 目标方向
🟢 现在就拍 — 风格：日系清新
效果承诺：拍出被阳光洗过的透亮洱海人像，干净有呼吸感
推荐理由：冷调顺光+大面积蓝色水面，与日系清新的低饱和冷调审美高度契合。

### 风格视觉特征
核心：透亮冷调洱海近景人像 / 色彩：低饱和冷蓝偏移 / 构图：人物居下半，上半留白 / 光线：顺光硬光 / 情绪：干净松弛

## 设备信息
{DEVICE_CONTEXT}
{ENV_CONTEXT}

## 🎬 读懂这张照片
先回答三个问题：
1. 最打动人的是什么？（光线/色彩/空间/人物状态——具体的，不是"氛围好"）
2. 有哪些「不同的东西」值得拍？（换角度/换焦点，不是换滤镜。一棵树下至少可以拍：人与树的空间关系、树皮纹理+人手细节、树冠光斑落在人身上、地面光斑中的影子）
3. 当前光线下什么角度和景别最自然？（顺光→拍色彩、侧光→拍立体感）

基于答案确定拍摄动机。方案间差异必须首先是前期差异（角度/焦点/景别），其次才是后期。

## 🧰 变化工具

**角度三要素**：相机高度（俯拍/平视/仰拍）× 拍摄方向（正面/45°/正侧/背面/回头）× 人物体位（站/坐/靠/蹲）
**视觉焦点**：人→环境 / 整体→细节 / 正面→背影 / 静态→动态 / 实物→光影
⛔ 有人的场景至少1张焦点不在脸上。

{SCENE_TEMPLATE_MATCHED}

### 多张节奏
景别分散：远景→中景→近景→创意→收束。首尾呼应（≥5张）。情绪起伏：不是每张都安静或都大笑——至少1张情绪不同于其他。破格方案放中间，不放开头或结尾。⛔ 不强凑，不全是中景。

## 每套方案字段
① name: 能记住的方案名——含素材元素+视角暗示
② prep: 准备什么（≤50字）
③ subject: 被拍摄者——给"做一件事"的自然指令。引用锚点。2-3句。
   ✅ "侧身倚靠粗浮木，右手搭膝上，头转向海面"
   ❌ "摆一个自然的姿势"
④ shooter: 摄影师——站哪/多远/高度/角度/取景范围。2-3句。
   ✅ "蹲在枯木后方，手机举到齐眼，天空占上半，人物在右下1/3"
⑤ gear: 设备调试——焦段/对焦/曝光（1-2句）
⑥ enhance: 拍摄时现场增色——光线利用/前景制造/道具调整。只写按快门前能操作的。
   ❌ 不混入后期
⑦ result: 画面视觉预览。2-3句。
   ✅ "侧光在球衣褶皱上切出利落阴影，海面化成淡蓝色块"
⑧ why: 为什么好看——摄影原理（2-3句）
⑨ annotations: 视觉标注（最多3个）——subject/shooter坐标
⑩ perspective: 换个思路（可选）——同风格不同维度的替代方案
⑪ shot_size: 景别（远景/全景/中景/近景/特写）
⑫ angle: 角度（平视/俯拍/仰拍/侧面/背面）
⑬ quick_edit: 手机修图傻瓜引导。只放后期。格式：{{{{"app":"醒图","goal":"","steps":["第1步（为什么）","第2步","第3步"]}}}}
⑭ img_gen_prompt: 图生图提示词（≤300汉字）。开头「参考上传的照片，保持人物面部特征和场景环境不变。修改如下：」→景别视角→人物动作表情→光线氛围→色调质感→「自然肤质，真实摄影感，无文字水印。」只写跟原片不同的部分。
⑮ ai_tips: AI可单独优化的小建议（2-3条字符串数组）
⑯ combo_label: "🧪实验性"

## 自检（生成后逐条过）
☐ 每条方案引用了素材清单中的 ≥1 个具体元素？
☐ subject/shooter/enhance 全是前期操作，quick_edit 全是后期？
☐ 方案之间拍了不同的东西（视角/焦点/景别有实质变化）？
☐ img_gen_prompt 包含景别+视角+人物变化+光线变化+色调？
☐ 不强凑——有意义的几套就几套

## 约束
- 口吻：朋友分享 ✅"你"视角 ❌摄影术语
- 前期优先：enhance 不混入调色/滤镜，quick_edit 不混入站位/构图
- 不强凑不套壳不说废话

## 输出格式
严格JSON，只输出 plans 数组。不要markdown包裹。

{{{{
  "plans": [
    {{{{
      "name": "", "prep": "", "subject": "", "shooter": "", "gear": "",
      "enhance": "", "result": "", "why": "", "annotations": [], "perspective": "",
      "shot_size": "", "angle": "",
      "quick_edit": {{{{"app":"","goal":"","steps":["","",""]}}}},
      "img_gen_prompt": "",
      "ai_tips": ["",""],
      "combo_label": "🧪实验性"
    }}}}
  ]
}}}}

{FORBIDDEN_SLIM}"""


def call_doubao(prompt, label):
    print(f"\n{'='*60}")
    print(f"🧪 {label}")
    print(f"   Prompt 长度: {len(prompt)} 字符 (~{len(prompt)//3} tokens)")
    t0 = time.time()
    try:
        client = httpx.Client(timeout=httpx.Timeout(TIMEOUT), http2=True)
        resp = client.post(
            DOUBAO_URL,
            json={"model": DOUBAO_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 8000},
            headers={"Authorization": f"Bearer {DOUBAO_API_KEY}"}
        )
        resp.raise_for_status()
        result = resp.json()
        content = result['choices'][0]['message']['content'].strip()
        usage = result.get('usage', {})
        elapsed = round(time.time() - t0, 1)

        try:
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            data = json.loads(content)
            plans = data.get('plans', [])
            plan_count = len(plans)
            has_subject = sum(1 for p in plans if p.get('subject', ''))
            has_shooter = sum(1 for p in plans if p.get('shooter', ''))
            has_enhance = sum(1 for p in plans if p.get('enhance', ''))
            has_img = sum(1 for p in plans if p.get('img_gen_prompt', ''))
            print(f"   ⏱️ 耗时: {elapsed}s")
            print(f"   📊 Tokens: prompt={usage.get('prompt_tokens','?')}, completion={usage.get('completion_tokens','?')}, total={usage.get('total_tokens','?')}")
            print(f"   📸 方案数: {plan_count}")
            print(f"   ✅ subject覆盖率: {has_subject}/{plan_count}")
            print(f"   ✅ shooter覆盖率: {has_shooter}/{plan_count}")
            print(f"   ✅ enhance覆盖率: {has_enhance}/{plan_count}")
            print(f"   ✅ img_gen覆盖率: {has_img}/{plan_count}")
            for i, p in enumerate(plans):
                print(f"   📋 方案{i+1}: {p.get('name','?')} | {p.get('shot_size','?')} | {p.get('angle','?')}")
                print(f"      subject: {p.get('subject','?')[:120]}")
            return {
                "label": label,
                "prompt_chars": len(prompt),
                "elapsed": elapsed,
                "plan_count": plan_count,
                "tokens": usage,
                "plans": plans,
                "quality": {"subject": has_subject, "shooter": has_shooter, "enhance": has_enhance, "img": has_img}
            }
        except (json.JSONDecodeError, KeyError) as e:
            print(f"   ⚠️ JSON 解析失败: {e}")
            print(f"   原始输出前200字: {content[:200]}")
            return {"label": label, "error": str(e), "elapsed": elapsed, "raw": content[:500]}
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        print(f"   ❌ 失败: {e} ({elapsed}s)")
        return {"label": label, "error": str(e), "elapsed": elapsed}


if __name__ == '__main__':
    # 加载之前的 A 和 B 结果用于对比
    try:
        with open("/tmp/prompt_compare_results.json") as f:
            old_results = json.load(f)
    except:
        old_results = []

    results = []
    # 先跑 B'
    print("🚀 开始测试 B' 版...")
    r = call_doubao(PROMPT_B_PRIME, "B'-保关键+压字段")
    results.append(r)

    # 再跑一次 A 作为对照（防止时间波动影响对比）
    # 这里不重跑A，直接引用之前的

    # ── 四版对比 ──
    print(f"\n\n{'='*60}")
    print("📊 四版对比汇总")
    print(f"{'='*60}")
    print(f"{'版本':<22} {'Prompt长度':>10} {'耗时':>8} {'方案数':>6} {'Tokens':>10}")
    print(f"{'-'*62}")
    
    # 先打印旧结果
    for r_old in old_results:
        if 'error' not in r_old:
            tokens = r_old['tokens'].get('total_tokens', '?')
            print(f"{r_old['label']:<22} {r_old['prompt_chars']:>8}字 {r_old['elapsed']:>6}s {r_old['plan_count']:>4}套 {tokens:>8}")
    
    # 打印新结果
    for r in results:
        if 'error' not in r:
            tokens = r['tokens'].get('total_tokens', '?')
            print(f"{r['label']:<22} {r['prompt_chars']:>8}字 {r['elapsed']:>6}s {r['plan_count']:>4}套 {tokens:>8}")
        else:
            print(f"{r['label']:<22} {'ERROR':>8} {r.get('elapsed','?'):>6}s {r.get('error','?')}")
    print(f"{'='*62}")

    # 保存
    with open("/tmp/prompt_bprime_result.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("B' 结果已存: /tmp/prompt_bprime_result.json")
