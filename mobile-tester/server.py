#!/usr/bin/env python3
"""
直出相机 · 移动端测试工具
在电脑上启动后，手机浏览器访问 http://<电脑IP>:8888
拍照上传 → 自动分析 → 输出拍摄方案卡片
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ============================================================
# 配置
# ============================================================
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2.0-pro"
EXIF_SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude/skills/zhichu/scripts/exif-extract.py")

# ============================================================
# 视觉分析 Prompt
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
    "depth": "[观察]浅/中/深 — 判断依据"
  },
  "composition": "[观察]当前构图方式 + [观察]画面中可利用的构图元素",
  "perspective": "[观察]拍摄视角（平视/俯视/仰视）+ [推测]机位高度",
  "weather_env": "[推测]天气状况及依据 + [观察]环境中可见的具体细节"
}

只输出JSON，不要任何额外文字。不要markdown代码块包裹。"""

# ============================================================
# 创意推理 Prompt（包含知识库核心规则）
# ============================================================
CREATIVE_PROMPT_TEMPLATE = """你是直出相机的摄影知识引擎。根据以下视觉分析结果和EXIF数据，为这张照片生成拍摄指导。

## 视觉分析
{vision_json}

## EXIF数据
{exif_summary}

## 你的任务

### Step 1: 场景沉浸
读视觉分析中的场景描述。想象你站在这个场景里——不要分类，去感受。
问自己：如果我是现场的人，我会被什么打动？这个场景里最安静的角落在哪里？

输出：2-3句"在场感受"，然后提炼一句话洞察。
洞察必须有视觉锚点——一个能在照片里指出的具体东西（一束光、一个弧度、一个颜色）。
❌ 禁止模板句式："最动人的不是X——是Y"
❌ 禁止空洞话："刚好经过，阳光正好"

### Step 2: 风格发现
基于场景特征，从以下知识库中匹配最佳风格方向。

**风格缓存（简化版）：**
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

每个风格标注：
- fit_rationale: 为什么适合
- light_annotation: 🟢完美/🟡可模拟/🔴需等待 + 详细说明
- device_annotation: 🟢直接拍/🟡微调/🟠替代方案
- source_type: 根据你的训练知识判断——community(社区分享)/tutorial(教程)/portfolio(摄影师作品)/inference(AI推理)
- is_new_discovery: 是否在以上缓存中找不到

### Step 3: 技法发现
从以下技法池中匹配可用的拍摄技巧：

**技法池（简化版）：**
- 降到宠物/儿童高度 → 改变视角
- 人只占画面10% → 环境叙事
- 前景虚化做层次 → 花/叶/框做前景
- 蹲下让天空做背景 → 避开杂乱
- 只拍局部不拍脸 → 川内伦子式观看
- 等人物走过光带 → 动静对比
- 栏杆/窗框做框内框 → 框架构图
- 树冠做天然拱门 → 森系仰拍
- 侧身45°面朝光源 → 硬光面部轮廓
- 只拍影子不拍人 → 硬光剪影
- 退到暗处用负空间 → 暗调氛围
- 只拍手/道具特写 → 局部神圣化

### Step 4: 方向卡片
按 zhichu 格式输出：

🟢 现在就拍：可执行性最高的方向（1个）
🔥 最出片：辨识度最高的方向（1个，有则给）
✨ 脑洞大开：最酷的方向（1个，有则给——没东西不强凑）

每个方向包含：
- style: 风格名
- reason: 推荐理由（朋友分享口吻，像拍过很多照片的人指着画面说话）
- how: 怎么做（1-2句话，具体操作，不是抽象概念）
- source_note: 来源标注（如"小红书上有人分享过——" 或 "这是AI想到的方法，还没人试过——说不定有惊喜"）

### Step 5: 拍摄方案
为选定的主方向（🟢）生成 3 套具体方案。每套方案：
- name: 方案名
- action: 具体操作步骤（站哪里、用什么焦段、怎么构图）
- perspective: 🎯 换个思路——这个方案"看见的方式"和其他方案的本质不同

## 输出格式
严格输出以下 JSON（不要markdown包裹）：

{{
  "presence": "在场感受——2-3句",
  "insight": "一句话洞察——最动人的视觉锚点",
  "directions": {{
    "now": {{
      "style": "风格名",
      "reason": "推荐理由",
      "how": "怎么做",
      "source_note": "来源标注"
    }},
    "best": {{
      "style": "风格名",
      "reason": "推荐理由",
      "how": "怎么做",
      "source_note": "来源标注"
    }},
    "creative": {{
      "style": "风格名",
      "reason": "推荐理由",
      "how": "怎么做",
      "source_note": "来源标注"
    }}
  }},
  "plans": [
    {{
      "name": "方案名",
      "action": "具体操作",
      "perspective": "换个思路的一句话"
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
      "device_annotation": "🟢/🟡/🟠 + 说明"
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

## 🚨 口吻约束
- 像朋友分享观察，不像策展人写说明
- ❌ 禁止摄影术语直接出现（引导线→"眼睛被推到远山"，空间层次→"一层一层看进去"）
- ❌ 禁止第一人称"我"
- ✅ 用"你"视角——"你没叫她看镜头""你站在这儿就能拍到"
- ✅ 允许意外："拍完才发现最好看的不是表情"
- 有话则长无话则短。平淡场景一句话真诚推荐比三句话空洞套路有价值
"""


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
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode())
    content = result['choices'][0]['message']['content'].strip()
    if content.startswith('```'):
        lines = content.split('\n')
        content = '\n'.join(lines[1:])
        if content.endswith('```'):
            content = content[:-3]
    return content, result.get('usage', {})


def analyze_photo(image_path):
    """完整的照片分析流程"""
    t0 = time.time()
    log = []

    # Step 1: EXIF
    t1 = time.time()
    exif = extract_exif(image_path)
    exif_time = round(time.time() - t1, 1)
    log.append(f"EXIF: {exif_time}s")

    exif_summary = exif.get('summary', '无EXIF数据') if isinstance(exif, dict) else 'EXIF提取失败'

    # Step 2: 视觉分析
    t2 = time.time()
    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "image/heic" if ext in ('.heic', '.heif') else "image/jpeg"
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    vision_content, vision_usage = call_doubao([
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}},
            {"type": "text", "text": VISION_PROMPT}
        ]}
    ], max_tokens=2000)
    vision_time = round(time.time() - t2, 1)
    log.append(f"视觉: {vision_time}s, tokens={vision_usage.get('total_tokens', '?')}")

    try:
        vision_json = json.loads(vision_content)
    except json.JSONDecodeError:
        vision_json = {"raw": vision_content, "parse_error": True}

    # Step 3: 创意推理
    t3 = time.time()
    creative_prompt = CREATIVE_PROMPT_TEMPLATE.format(
        vision_json=json.dumps(vision_json, ensure_ascii=False, indent=2),
        exif_summary=exif_summary
    )
    creative_content, creative_usage = call_doubao([
        {"role": "user", "content": creative_prompt}
    ], max_tokens=3000)
    creative_time = round(time.time() - t3, 1)
    log.append(f"推理: {creative_time}s, tokens={creative_usage.get('total_tokens', '?')}")

    try:
        creative_json = json.loads(creative_content)
    except json.JSONDecodeError:
        creative_json = {"raw": creative_content, "parse_error": True}

    total_time = round(time.time() - t0, 1)
    total_tokens = vision_usage.get('total_tokens', 0) + creative_usage.get('total_tokens', 0)

    return {
        "success": True,
        "elapsed": total_time,
        "tokens": total_tokens,
        "log": log,
        "exif": exif_summary,
        "vision": vision_json,
        "result": creative_json
    }


@app.route('/')
def index():
    """移动端主页"""
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    """分析上传的照片"""
    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "未收到照片"}), 400

    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 保存临时文件
    ext = os.path.splitext(photo.filename)[1] or '.jpg'
    tmp_path = f"/tmp/zhichu_{int(time.time())}{ext}"
    photo.save(tmp_path)

    try:
        result = analyze_photo(tmp_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.route('/health')
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "api_key_configured": bool(DOUBAO_API_KEY),
        "exif_script_exists": os.path.exists(EXIF_SCRIPT)
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
║       直出相机 · 移动端测试工具           ║
║                                          ║
║  手机浏览器访问:                          ║
║  → http://{local_ip}:8888          ║
║                                          ║
║  确保手机和电脑在同一 WiFi 网络            ║
║  按 Ctrl+C 停止服务器                     ║
╚══════════════════════════════════════════╝
    """)

    app.run(host='0.0.0.0', port=8888, debug=True)
