# 带拍项目性能优化建议

**来源**: Andrej Karpathy Perspective + Best Minds 分析
**日期**: 2026-07-30
**状态**: Tier 1 已完成，Tier 2+ 待后续优化

---

## 一、问题诊断

| 问题 | 根因 | 严重程度 |
|------|------|:--:|
| 等待时间长（60-120s） | 豆包 LLM API 延迟是瓶颈，非服务器 CPU | 🔴 |
| 多用户排队阻塞 | `_processing` 全局布尔锁串行化所有请求 | 🔴 |
| 单进程架构 | Flask 默认单进程，无法利用多核 | 🟡 |

**核心判断**: 这套系统是 IO-bound（等 LLM 返回），不是 CPU-bound。2核2GB 香港轻量云对计算来说够了——瓶颈在网络 IO。

---

## 二、Andrej Karpathy 视角

> 以 Karpathy 的工程现实主义框架分析

### 1. March of Nines —— 从 Demo 到部署的爬坡

> "The reliability of a system is not given by its average case, but by its tail behavior."

- **当前状态**: Demo 级可用（单用户能用），但尾部行为差（第二个用户来就 429）
- **核心问题**: `_processing` 锁把"系统忙"变成了"系统不可用"——这不是排队，是拒之门外
- **启示**: 优先消灭单点阻塞，让失败模式从"硬拒绝"降级为"慢一点"

### 2. Iron Man 套装 > Iron Man 机器人

> "It's less Iron Man robots and more Iron Man suits."

- 带拍的本质就是 Iron Man 套装——AI 增强拍摄者，不是替代拍摄者
- 方案生成是"给建议"不是"替决策"——用户选方向、用户按快门
- 产品设计上这个定位是对的，技术架构应该匹配：允许多人同时穿套装

### 3. 锯齿状智能

> "They're going to be superhuman in some problem-solving domains, and then they're going to make mistakes that basically no human will make."

- 豆包视觉分析很强（观察+推测分离）
- 但方案生成偶尔出"套后期滤镜"方案——这是 LLM 的凹陷点
- Prompt 设计要点：用具体反例堵凹陷点（✅"站粗浮木右侧" ❌"换个角度"）

### 4. 构建即理解

> "Don't be a hero. Resist adding complexity."

- 当前方案：线程池 + httpx + 预热 → 简单有效，不需要上消息队列
- gunicorn + gevent 是自然的下一步，但不要过早引入 Redis/Celery
- 复杂度增加之前，先问：瓶颈真的在 CPU 吗？

### 5. 数据飞轮优先

> 在技术选型时，优先考虑"哪个方案能积累最多可复用数据"

- 当前 `_save_session()` 持久化 + `usage.db` 统计是对的
- 后续可以：记录 prompt → 方案质量 → 用户是否采纳 → 反馈闭环

---

## 三、Best Minds —— 领域专家建议

### 并发：谁最懂？

**问题**: 一个 Flask 单进程应用，如何让多用户同时使用？

**专家共识**:

| 方案 | 复杂度 | 适用场景 | 推荐度 |
|------|:--:|------|:--:|
| gunicorn + gevent worker | 低 | IO-bound 为主，不改代码 | ⭐⭐⭐⭐⭐ |
| gunicorn + threads | 低 | 线程安全已有基础 | ⭐⭐⭐⭐ |
| FastAPI + asyncio 重写 | 高 | 长期演进 | ⭐⭐⭐ |
| Redis Queue / Celery | 中高 | 任务队列化 | ⭐⭐ |

**首选**: gunicorn + gevent。原因是：
1. Flask 代码不用改（gevent 猴子补丁自动让 `threading.Thread` 变协程）
2. 2核2GB 可以跑 4-8 个 worker
3. 配合 httpx async 客户端效果更好

### LLM 延迟：谁最懂？

**核心洞察**: 延迟大头在豆包 API，不在本地计算。

**优化层次**:

```
第 1 层：预热（已做 ✅）
├─ 分析完成 → 后台生成"现在就拍"方案
└─ 轮播切换 → 级联预热下一个方向的方案

第 2 层：并行（部分已做 ✅）
├─ 视觉分析 → 1 次 LLM 调用
├─ 风格搜索 → 2-4 路并行搜索
└─ 方向卡片 → 1 次 LLM 调用

第 3 层：缓存
├─ 同一张照片 + 同一方向 → 直接返回缓存方案 ✅
├─ 同一场景类型 + 同一风格 → 复用风格知识模板
└─ GPS 相近位置 → WTTw.in 天气缓存（30min）

第 4 层：降级
├─ 搜索超时 → 跳过搜索，用规则匹配
├─ LLM 超时 → 重试 1 次 → 降级为简短方案
└─ 并发满载 → 排队（带位置提示）而非拒绝
```

---

## 四、已实施优化（Tier 1）

| # | 改动 | 效果 | 文件 |
|:--:|------|------|------|
| 1 | 删除 `_processing` 全局锁 | 多用户可同时使用 | `server.py` |
| 2 | 级联预热（now→best→creative） | 切换方向时方案已生成 | `server.py` + `index.html` |
| 3 | httpx 替换 urllib | HTTP/2 复用连接，减少握手耗时 | `server.py` |
| 4 | `threading.Lock` 保护 sessions | 线程安全 | `server.py` |
| 5 | PLANS_PROMPT 精简（7553→4260 字） | 方案生成省 24% 耗时 + 33% token | `server.py` |

**总体效果**: 等待时间从 90-120s → 60-85s，多用户不再被拒。

---

## 五、待实施优化（Tier 2+）

### P0 — 直接提升并发能力

| # | 改动 | 预计效果 | 风险 |
|:--:|------|------|:--:|
| 1 | gunicorn + gevent（4 workers） | 4 人同时用不减速 | 需测试 session 共享 |
| 2 | 豆包 API 异步调用 | 搜索/分析阶段并行度提升 | httpx async 适配 |

### P1 — 知识库瘦身

| # | 改动 | 预计效果 | 风险 |
|:--:|------|------|:--:|
| 3 | 风格 KB 检索裁剪 | Prompt 更短 → LLM 更快 | 可能丢失小众风格 |
| 4 | 技法 KB 条件触发（有风格才搜） | 减少无效搜索 | 无风格时缺技法 |

### P2 — 缓存与降级

| # | 改动 | 预计效果 | 风险 |
|:--:|------|------|:--:|
| 5 | 方案缓存（同照片+同方向复用） | 回看已生成方案 0 等待 | 内存占用 |
| 6 | 搜索超时降级 | 搜索挂了不阻塞整体流程 | 方案缺少网络参考 |
| 7 | 排队改"带位置提示" | 用户知道排第几，不会狂刷新 | 前端改动 |

### P3 — v4 架构精简

| # | 改动 | 预计效果 | 风险 |
|:--:|------|------|:--:|
| 8 | ④ AI 综合判断 + ⑤ 审美主张引擎合并 | 减少 1 次 LLM 调用 | 合并后 prompt 更长 |
| 9 | ⑨ 审美验证改为内置自检 | 减少 1 次 LLM 调用 | 需确保自检足够严格 |

> 详细 v4 架构方案见 `docs/v4-optimization-plan.md`

---

## 六、Karpathy 金句速查

| 场景 | 适用金句 |
|------|------|
| 加复杂中间件之前 | "Don't be a hero. Resist adding complexity." |
| 纠结要不要上 Redis 时 | "第一步永远不是碰模型代码，而是彻底检查数据" |
| 方案生成质量波动时 | "LLM 是召唤的幽灵——prompt 在导引它的梦" |
| 想加更多 AI 模块时 | "从 90% 到 99.9% 的爬坡比从 0 到 90% 还难" |
| 评估新优化手段时 | "这个 demo 在 1 亿次使用下会怎样？" |

---

> **下一步**: 按 P0 → P1 → P2 → P3 顺序逐批评估和实施。每批完成后用真实照片测试验证。
