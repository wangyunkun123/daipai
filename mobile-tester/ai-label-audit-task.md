# AI 标签文件审核——搜索真实来源任务记录

## 背景

知识库 119 个 markdown 文件按 frontmatter `source:` 字段分类：
- ✅ verified: 31（已有可查证教材/大师）
- 🌐 real_world: 28（已有真实互联网趋势）
- 💡 ai_inferred: 23（AI+真实混合，需审核AI部分）
- 🤖 ai_generated: 37（无来源或纯AI，需审核是否有遗漏真实来源）

目标：对 ai_inferred 和 ai_generated 共 60 个文件逐一搜索，找到真实来源的去除 AI 标签。

## 已跳过（内部工具逻辑，不适用外部来源）

- `device-adaptation/` (7 files) — 设备能力描述
- `matching/` (14 files) — 内部路由匹配器
- `_compressed/knowledge-core.md` — 编译聚合文件
- `_template.md` — 模板
- `_README.md` — 说明

## 待审核文件清单

### Group 1: 跨媒介风格 (11 files) — 已有部分艺术史来源，需搜索摄影界引用证据

| 文件 | 当前来源 | 搜索要点 |
|------|---------|---------|
| brand-aesthetics.md | ChatGPT品牌审美 | Apple/MUJI极简摄影是否有大师/教材 |
| chinese-ink.md | 水墨画传统+国潮 | 郎静山/张克纯等水墨摄影代表 |
| dark-academia.md | DA互联网美学 | 小红书/IG上DA摄影标签热度 |
| ghibli.md | 宫崎骏/吉卜力 | ChatGPT吉卜力滤镜现象+动画美术 |
| liminal-space.md | 阈限空间/梦核 | 中式梦核抖音17.8亿播放+建筑摄影 |
| monet-impressionism.md | 莫奈印象派 | 印象派摄影（画意摄影）传统 |
| song-landscape.md | 宋代山水画 | 郎静山集锦摄影/当代新山水摄影 |
| spider-verse.md | 蜘蛛侠动画美学 | 漫画/波普视觉在摄影中的应用 |
| ukiyo-e.md | 浮世绘传统 | 梵高受浮世绘影响→当代摄影参考 |
| vermeer-rembrandt.md | 伦勃朗/维米尔用光 | 摄影布光教材中的伦勃朗光 |
| cyberpunk.md | 赛博朋克科幻 | Liam Wong霓虹摄影/银翼杀手 |

### Group 2: 风格配方 (7 files)

| 文件 | 当前来源 | 搜索要点 |
|------|---------|---------|
| _index.md | 综合审美体系+AI | Freeman/Barnbaum风格分类 |
| cinematic.md | 电影摄影传统 | 电影感摄影教程/YouTube摄影师 |
| film-nostalgia.md | 胶片传统 | 富士胶片模拟/Xiaohongshu胶片标签 |
| grunge.md | 豆包Grunge复兴 | 90s Grunge摄影/David Carson/反时尚 |
| minimalist.md | 极简艺术传统 | Michael Kenna/杉本博司极简摄影 |
| dreamy.md | 梦幻人像传统 | 柔焦滤镜/小红书梦幻写真标签 |
| macro-micro.md | 川内伦子+微距 | 川内伦子具体作品集/微观摄影 |

### Group 3: 情绪词库 (5 files)

| 文件 | 当前来源 | 搜索要点 |
|------|---------|---------|
| _index.md | Claude/豆包/ChatGPT | 摄影情绪/氛围理论书籍 |
| energy.md | 时尚摄影动能 | 小红书"元气感"写真标签热度 |
| freedom.md | 互联网"松弛感" | 滨田英明松弛感/自由美学摄影 |
| nostalgia.md | Claude怀旧美学 | 胶片怀旧/老照片复兴趋势 |
| warmth.md | 豆包/Claude"治愈感" | 滨田英明/川内伦子治愈系摄影 |

### Group 4: 审美语法 (6 files)

| 文件 | 当前来源 | 搜索要点 |
|------|---------|---------|
| _index.md | Freeman+Barnbaum+AI | 已验证教材真实存在 |
| balance.md | Freeman+Arnheim+AI | 格式塔视觉平衡在摄影中的应用 |
| breaking-rules.md | 森山大道+William Klein+AI | 已有真实摄影师来源 |
| critique-framework.md | Barrett摄影批评+AI | Barrett摄影批评方法教材 |
| restraint.md | 豆包含弃/克制+AI | 极简摄影/舍弃美学理论 |
| unity-variety.md | Freeman+Arnheim+AI | 统一与变化设计原理 |

### Group 5: 质感/叙事/其他 (7 files)

| 文件 | 当前来源 | 搜索要点 |
|------|---------|---------|
| texture-aesthetics/_index.md | 豆包质感审美 | 材质摄影/触觉视觉理论 |
| texture-aesthetics/digital-texture.md | 豆包+CCD复兴 | 2026反AI摄影运动+CCD相机复兴 |
| series-rhythm/_index.md | Claude组图+电影叙事 | 摄影书编辑逻辑/组图节奏 |
| post-process/_index.md | 无 | 后期处理教材/教程 |
| visual-narrative/_index.md | Cartier-Bresson+Crewdson+AI | 决定性瞬间+叙事摄影 |
| social-media-patterns/direction-cards-design.md | 产品思考 | 小红书/IG卡片式内容设计 |
| social-media-patterns/why-it-works-examples.md | 产品思考+Prompt工程 | 摄影案例分析模板 |

## 操作指引

对每个文件：
1. 搜索「关键词 + 摄影 + 教材/大师/小红书/YouTube」确认来源真实性
2. 如找到真实来源 → 更新 frontmatter `source:` 字段，去掉 AI 标注
3. 如确认无真实来源 → 保持不变（标注为 AI 生成是诚实的）
4. 更新后 `get_source_quality_map()` 会自动重新分类

## 已知可靠来源（可复用）

- **教材**: Freeman《摄影师的视界》, Barnbaum《摄影的艺术》, Valenzuela《拍出绝世美姿》, Barrett《摄影批评》, Adams《The Camera》, Hunter《Light Science & Magic》
- **大师**: 布列松, 森山大道, William Klein, Saul Leiter, 川内伦子, 滨田英明, 郎静山, 何藩, 张克纯, Michael Kenna, 杉本博司, Liam Wong
- **设计理论**: Arnheim格式塔, Albers色彩, 莫奈印象派, 浮世绘, 宋代山水画
- **社媒趋势**: 小红书/抖音/IG标签热度可用搜索验证

**Why**: 用户要审核 AI 推理和 AI 原创标签的知识库文件，找到真实摄影大师、社区经验、社交媒体热度等来源后去除 AI 标签。

**How to apply**: 逐文件手动搜索，找到真实来源后编辑对应 markdown 的 frontmatter `source:` 字段，`get_source_quality_map()` 会自动重新分类。
