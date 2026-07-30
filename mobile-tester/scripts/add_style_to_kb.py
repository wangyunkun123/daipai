#!/usr/bin/env python3
"""
管理员入库工具：将 AI 发现的 🆕新风格 加入知识库。

用法：
  cd mobile-tester
  python3 scripts/add_style_to_kb.py --session <session_id> --direction <now|best|creative>

流程：
  1. 从 session 数据中提取风格的 photo_guide、style_brief、style_promise
  2. 在 cross-media-styles/ 下创建标准格式的 .md 文件
  3. 输出需要手动添加到 knowledge_base.py 的代码片段（one_liner + PHOTO_PARAMS）
  4. 如果传了 --apply，自动追加到 knowledge_base.py

前置条件：
  - session 数据存在（服务器已生成过该 session）
  - 该方向的 kb_status 为 🆕新发现
  - photo_guide 非空
"""

import argparse
import json
import os
import re
import sys
from datetime import date

# 确定路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # mobile-tester/
REPO_DIR = os.path.dirname(PROJECT_DIR)     # Photography/
KB_DIR = os.path.join(REPO_DIR, ".claude", "skills", "daipai", "knowledge")
CMS_DIR = os.path.join(KB_DIR, "cross-media-styles")
KB_PY = os.path.join(PROJECT_DIR, "knowledge_base.py")
SESSIONS_DIR = os.path.join(PROJECT_DIR, "sessions")


def load_session(session_id):
    """从磁盘加载 session JSON"""
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        # 尝试从单个文件目录查找
        alt_path = os.path.join(SESSIONS_DIR, session_id[:2], f"{session_id}.json")
        if os.path.exists(alt_path):
            path = alt_path
        else:
            return None
    with open(path, 'r') as f:
        return json.load(f)


def slugify(name):
    """中文风格名 → 英文 slug"""
    # 简单策略：拼音首字母或直接用英文关键词
    # 这里让用户手动确认
    slug = re.sub(r'[^\w\s-]', '', name.lower().replace(' ', '-'))
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def extract_style_info(session, direction_id):
    """从 session 中提取风格信息"""
    directions = session.get('directions', [])
    direction = None
    for d in directions:
        if d.get('id') == direction_id:
            direction = d
            break
    if not direction:
        return None, f"未找到方向 {direction_id}"

    style_name = direction.get('style', '').strip()
    kb_status = direction.get('kb_status', '').strip()
    photo_guide = direction.get('photo_guide', '').strip()
    style_brief = direction.get('style_brief', {}) or {}
    style_promise = direction.get('style_promise', '').strip()

    if not style_name:
        return None, "方向中无 style 字段"

    if '已有记录' in kb_status:
        return None, f"风格「{style_name}」已标记为 {kb_status}——不需要入库"

    if not photo_guide:
        return None, f"风格「{style_name}」无 photo_guide——方向阶段 AI 未生成摄影翻译"

    # 构建 one_liner（从 style_brief + style_promise 提取）
    sb_parts = []
    if style_brief.get('essence'):
        sb_parts.append(style_brief['essence'])
    if style_promise:
        sb_parts.append(style_promise)
    one_liner = '。'.join(sb_parts) if sb_parts else style_name

    return {
        'style_name': style_name,
        'kb_status': kb_status,
        'photo_guide': photo_guide,
        'style_brief': style_brief,
        'one_liner': one_liner,
        'style_promise': style_promise,
        'direction': direction,
    }, None


def generate_markdown(info):
    """生成标准格式的 cross-media-style .md 文件"""
    style_name = info['style_name']
    today = date.today().isoformat()
    slug = slugify(style_name) or f"style-{today}"

    # 从 photo_guide 中提取各部分
    pg = info['photo_guide']
    style_brief = info['style_brief']

    # 提取色彩/光线/构图信息
    color_info = style_brief.get('color', '')
    light_info = style_brief.get('light', '')
    comp_info = style_brief.get('composition', '')
    essence = style_brief.get('essence', info['style_promise'])

    # 尝试从 photo_guide 中提取「光线核心」
    light_match = re.search(r'光线核心[：:]\s*(.+?)(?:\n|$)', pg)
    light_detail = light_match.group(1).strip() if light_match else light_info

    # 尝试提取「色彩控制」
    color_match = re.search(r'色彩控制[：:]\s*(.+?)(?:\n|$)', pg)
    color_detail = color_match.group(1).strip() if color_match else color_info

    # 尝试提取「构图」
    comp_match = re.search(r'构图[：:]\s*(.+?)(?:\n|$)', pg)
    comp_detail = comp_match.group(1).strip() if comp_match else comp_info

    # 尝试提取「后期方向」
    post_match = re.search(r'📱 后期方向[：:]\s*(.+?)(?:\n(?!📎|🎯|❌|📱)|$)', pg, re.DOTALL)
    post_info = post_match.group(1).strip() if post_match else "（无特定后期要求）"

    # 尝试提取「技法类比」
    anchor_match = re.search(r'📎 技法类比[：:]\s*(.+?)(?:\n|$)', pg)
    anchor_info = anchor_match.group(1).strip() if anchor_match else ""

    # 尝试提取禁止项
    forbid_match = re.search(r'❌ 禁止[：:]\s*(.+?)(?:\n(?!📎|🎯|📱)|$)', pg, re.DOTALL)
    forbid_info = forbid_match.group(1).strip() if forbid_match else ""

    # 预计算可选章节（避免嵌套 f-string 中的反斜杠——Python 3.9 限制）
    anchor_section = "## 知识库锚点\n\n" + anchor_info if anchor_info else ""
    forbid_section = "## 禁止事项\n\n" + forbid_info if forbid_info else ""
    extra_comp_line = "- " + comp_detail if comp_detail else ""

    md = f"""---
id: KB-CMS-AUTO-{today}
domain: cross-media-styles
tags: [{style_name}, AI发现, 待验证]
level: basic
status: ai_discovered
source: [AI 自由探索发现, guidepic.cn]
---

# {style_name}

## 媒介源头

**AI 自由探索发现。** {essence}

## 一句话识别

{info['one_liner']}

## 色彩

- 主色调：（从 photo_guide 提取）{color_detail}
- 饱和度：（从 photo_guide 提取）
- 色温：（从 photo_guide 提取）
- 关键规则：（从 photo_guide 提取）

## 光线

- {light_detail}
{extra_comp_line}

## 构图

- {comp_detail if comp_detail else '（从方案实践中提取）'}

## 前期可操作技法（AI 翻译——待验证）

{pg}

## 后期参考

{post_info}

{anchor_section}

{forbid_section}

---
> 采集日期：{today} | via AI 自由探索 · guidepic.cn
> 状态：待验证——管理员审核后可提升为 mvp
"""
    return md, slug


def generate_code_snippet(info):
    """生成需要添加到 knowledge_base.py 的代码片段"""
    style_name = info['style_name']
    one_liner = info['one_liner']
    photo_guide = info['photo_guide']

    # 转义 photo_guide 中的引号
    pg_escaped = photo_guide.replace('"""', '\\"\\"\\"')

    # CROSS_MEDIA_STYLE_ONE_LINERS 条目
    one_liner_entry = f'    "{style_name}": "{one_liner}",'

    # CROSS_MEDIA_PHOTO_PARAMS 条目
    photo_params_entry = f'''    "{style_name}": """**{style_name} · 摄影可执行参数**
{pg_escaped}
📎 技法锚点：（人工审核后补充）""",'''

    return f"""
# === 添加到 CROSS_MEDIA_STYLE_ONE_LINERS（约第 68 行，"老钱静奢" 之后）===
{one_liner_entry}

# === 添加到 CROSS_MEDIA_PHOTO_PARAMS（约第 983 行，"}}" 之前）===
{photo_params_entry}
"""


def apply_to_kb_py(info):
    """自动追加到 knowledge_base.py"""
    if not os.path.exists(KB_PY):
        return False, f"knowledge_base.py 未找到: {KB_PY}"

    style_name = info['style_name']
    one_liner = info['one_liner']
    photo_guide = info['photo_guide']
    pg_escaped = photo_guide.replace('"""', '\\"\\"\\"')

    with open(KB_PY, 'r') as f:
        content = f.read()

    # 1. 追加到 CROSS_MEDIA_STYLE_ONE_LINERS（在 "老钱静奢" 之后）
    marker = '"老钱静奢":'
    one_liner_line = f'\n    "{style_name}": "{one_liner}",'
    if style_name not in content:
        if marker in content:
            # 在该行之后插入
            lines = content.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if marker in line:
                    new_lines.append(one_liner_line.rstrip('\n'))
            content = '\n'.join(new_lines)
        else:
            return False, f"标记 '{marker}' 未在 knowledge_base.py 中找到"

    # 2. 追加到 CROSS_MEDIA_PHOTO_PARAMS
    photo_params_entry = f'''    "{style_name}": """**{style_name} · 摄影可执行参数**
{pg_escaped}
📎 技法锚点：（人工审核后补充）""",
}}'''
    # 找到最后一个 }（闭合 CROSS_MEDIA_PHOTO_PARAMS 的）
    # 策略：找到 "📎 技法锚点：极简高级 + 新中式"""," 后面的 "}"
    marker2 = '技法锚点：极简高级 + 新中式"""'
    if marker2 in content and style_name not in content[content.find(marker2):]:
        # 在最后一个 CROSS_MEDIA_PHOTO_PARAMS 条目的 } 之前插入
        # 找到 CROSS_MEDIA_PHOTO_PARAMS 字典的最后一个 }
        # （在 CROSS_MEDIA_PHOTO_PARAMS = { 之后找到配对的 }）
        params_start = content.find('CROSS_MEDIA_PHOTO_PARAMS = {')
        if params_start >= 0:
            # 从 params_start 开始找最后一个 """ 后跟 ,\n} 的地方
            # 简单策略：在 CROSS_MEDIA_PHOTO_PARAMS 闭合的 } 之前插入
            # 找到 "奶油风" 条目的结尾
            cream_end = content.find('""",\n}', params_start)
            if cream_end < 0:
                cream_end = content.find('"""\n}', params_start)
            if cream_end >= 0:
                insert_pos = cream_end + 4  # 在 """, 之后
                content = content[:insert_pos] + '\n' + photo_params_entry.replace('}}', '') + content[insert_pos:]
            else:
                return False, "无法定位 CROSS_MEDIA_PHOTO_PARAMS 的闭合位置"
    else:
        print("  ⚠️  风格可能已存在于 PHOTO_PARAMS 中，跳过")

    with open(KB_PY, 'w') as f:
        f.write(content)

    return True, "knowledge_base.py 已更新"


def main():
    parser = argparse.ArgumentParser(description='AI 发现的新风格入库工具')
    parser.add_argument('--session', required=True, help='Session ID')
    parser.add_argument('--direction', required=True, choices=['now', 'best', 'creative'],
                        help='方向 ID（now/best/creative）')
    parser.add_argument('--apply', action='store_true',
                        help='自动追加到 knowledge_base.py（默认仅预览）')
    parser.add_argument('--slug', help='自定义文件 slug（默认自动生成）')
    args = parser.parse_args()

    # 1. 加载 session
    print(f"📂 加载 session: {args.session}")
    session = load_session(args.session)
    if not session:
        print(f"❌ Session 未找到: {args.session}")
        print(f"   检查路径: {SESSIONS_DIR}/{args.session}.json")
        sys.exit(1)

    # 2. 提取风格信息
    print(f"🔍 提取方向: {args.direction}")
    info, err = extract_style_info(session, args.direction)
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    print(f"   ✅ 风格: {info['style_name']}")
    print(f"   ✅ kb_status: {info['kb_status']}")
    print(f"   ✅ photo_guide: {len(info['photo_guide'])} chars")

    # 3. 生成 markdown
    md_content, slug = generate_markdown(info)
    slug = args.slug or slug
    md_path = os.path.join(CMS_DIR, f"{slug}.md")

    if os.path.exists(md_path):
        print(f"⚠️  文件已存在: {md_path}")
        resp = input("   覆盖？[y/N] ")
        if resp.lower() != 'y':
            print("   已取消")
            sys.exit(0)

    os.makedirs(CMS_DIR, exist_ok=True)
    with open(md_path, 'w') as f:
        f.write(md_content)
    print(f"📝 Markdown 已创建: {md_path}")

    # 4. 输出代码片段
    snippet = generate_code_snippet(info)
    print(f"\n{'='*60}")
    print("📋 需要添加到 knowledge_base.py 的代码：")
    print(f"{'='*60}")
    print(snippet)

    # 5. 可选：自动应用
    if args.apply:
        print(f"\n🔧 自动应用到 knowledge_base.py...")
        success, msg = apply_to_kb_py(info)
        print(f"   {'✅' if success else '❌'} {msg}")
    else:
        print(f"\n💡 提示：加 --apply 自动追加到 knowledge_base.py")
        print(f"   手动编辑: {KB_PY}")

    print(f"\n✅ 入库完成！接下来：")
    print(f"   1. 审核 {md_path} 的内容")
    print(f"   2. 手动补充「构图」「穿搭」等章节")
    print(f"   3. 将输出的代码片段添加到 knowledge_base.py")
    print(f"   4. git commit + push 部署")


if __name__ == '__main__':
    main()
