# ShotOracle 摄影知识库导航

## 如何使用本知识库

本知识库按照摄影教育的体系组织，共 14 个知识域。每个知识域围绕「原理 → 识别 → 执行」的路径编写：

1. **原理**：这个技法为什么成立？（底层视觉原理或物理原理）
2. **识别条件**：AI 在分析场景时，看到什么特征应该触发此知识条目？
3. **执行指令**：站哪、用什么焦段、怎么操作、模特怎么引导
4. **常见错误**：新手最容易犯的错，以及为什么错

> **设备适配说明**：所有知识条目均为设备无关的摄影原理。拍摄方案生成后，通过 `device-adaptation/_index.md` 将方案翻译为具体设备可执行的操作。先确定最好的方案，再根据设备筛选——不让设备限制在分析阶段就参与决策。

## 检索策略

### 按场景特征检索

| 场景特征 | 优先查阅 |
|---------|---------|
| 场景中有线（路/栏杆/海岸线/建筑边缘） | `composition/_index.md` → 引导线/对角线 |
| 场景中有框（门/窗/拱门/树枝空隙） | `composition/_index.md` → 框架构图 |
| 场景中有对称（水面倒影/建筑中轴） | `composition/_index.md` → 对称构图 |
| 场景大面积空旷（天空/墙面/海面） | `composition/_index.md` → 留白构图 |
| 色彩丰富/花卉/灯光密集 | `color/_index.md` → 色彩对比与引导 |
| 色彩单调/大面积统一色调 | `color/_index.md` → 色彩和谐与情绪 |
| 强光直射（锐利阴影） | `light/_index.md` → 硬光章节 |
| 阴天/阴影中（柔和过渡） | `light/_index.md` → 软光章节 |
| 逆光（轮廓发光） | `light/_index.md` → 逆光章节 |
| 日落/日出时分 | `light/_index.md` → 黄金时刻 |
| 空间层次丰富（近中远都有元素） | `space/_index.md` |
| 空间扁平（缺乏深度线索） | `space/_index.md` → 如何创造深度 |
| 模特需要摆姿势 | `posing/_index.md` |
| 需要抓拍动态 | `timing/_index.md` |
| 想拍出氛围感 > 想拍清楚 | `visual-weight/_index.md` + `light/_index.md` |

### 按拍摄意图检索

| 意图 | 优先查阅 |
|------|---------|
| 展示环境气势 | `shot-types/_index.md` → 远景 + `lens-language/_index.md` → 超广角 |
| 平衡人物与环境 | `shot-types/_index.md` → 中景 + `composition/_index.md` → 三分法 |
| 传达情绪/面部细节 | `shot-types/_index.md` → 近景 + `posing/_index.md` → 情绪引导 |
| 不露脸的文艺感 | `shot-types/_index.md` → 特写 + `visual-weight/_index.md` |
| 打破常规的惊喜视角 | `shot-types/_index.md` → 创意 + `lens-language/_index.md` |
| 街拍/抓拍 | `timing/_index.md` + `scenes/_index.md` |

### 按光线条件检索

| 光线条件 | 优先查阅 |
|---------|---------|
| 正午顶光 | `light/_index.md` → 顶光 + `weather/_index.md` |
| 阴天散射光 | `light/_index.md` → 软光 + `color/_index.md` → 阴天色温 |
| 黄金时刻 | `light/_index.md` → 黄金时刻 + `light/_index.md` → 逆光 |
| 蓝调时刻（日落后） | `light/_index.md` → 蓝调时刻 |
| 室内窗光 | `light/_index.md` → 侧光 + `scenes/cafe-indoor.md` |
| 混合光（室内灯+窗光） | `light/_index.md` → 色温 + `color/_index.md` |

## 文件清单

```
knowledge/
├── _README.md                    ← 你在这里
├── _template.md                  ← 标准知识条目模板
├── composition/_index.md         ← 构图决策树与 6 大构图法
├── light/_index.md               ← 光线决策树 + 曝光创作选择
├── color/_index.md               ← 色彩对比/和谐/情绪/引导
├── exposure-triangle/_index.md   ← 曝光三角基础（光圈/快门/ISO）+ 互易律
├── depth-of-field/_index.md      ← 景深虚实 + 主体分离 + 边缘控制
├── lens-language/_index.md       ← 四大焦段类别的视觉空间特性
├── visual-weight/_index.md       ← 视觉重心的确立方法
├── space/_index.md               ← 前景/中景/背景 + 线条纹理
├── shot-types/_index.md          ← 远景/中景/近景/特写/创意
├── posing/_index.md              ← 姿势引导 + 情绪引导 + 沟通技巧
├── timing/_index.md              ← 决定性瞬间 + 动态静态 + 抓拍策略
├── scenes/_index.md              ← 场景分类 + 勘察方法论
├── device-adaptation/_index.md   ← 设备能力矩阵 + 知识→操作翻译表（方案筛选层）
├── weather/_index.md             ← 天气与大气条件
├── masters/_index.md             ← 大师风格选择矩阵（Phase 3）
└── post-process/_index.md        ← 后期意识（Phase 3）
```

## 知识条目编号体系

每个知识条目有唯一 ID：`KB-{DOMAIN}-{NNN}`

域代码对照：
- `CMP` = Composition（构图）
- `LGT` = Light（光线）
- `CLR` = Color（色彩）
- `EXP` = Exposure Triangle（曝光三角）
- `DOF` = Depth of Field（景深虚实）
- `LNS` = Lens Language（焦段语言）
- `VWT` = Visual Weight（视觉重心）
- `SPC` = Space（空间）
- `SHT` = Shot Types（景别）
- `POS` = Posing（姿势）
- `TMM` = Timing（时机）
- `SCN` = Scenes（场景）
- `DEV` = Device Adaptation（设备适配）
- `WTH` = Weather（天气）
- `MST` = Masters（大师）
