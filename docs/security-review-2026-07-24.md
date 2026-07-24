# 直出相机 (zhichu) 安全审查报告

**日期**: 2026-07-24 | **版本**: v3.2 | **审查人**: Claude Code

## 项目概况

zhichu 是一个 Claude Code 的摄影知识引擎 skill，包含 4 个 Python 脚本和约 80 个 Markdown 知识文件。威胁模型以 AI pipeline 注入、脚本安全、数据隐私为主。

---

## 🔴 高危发现

### 1. SKILL.md 命令注入风险 — `wttr.in` 天气查询

**文件**: `SKILL.md:215` | **类型**: Command Injection

```bash
curl -s "wttr.in/{city}?format=j1"
```

**攻击链**:

```
用户照片含恶意GPS坐标 → Nominatim返回含shell元字符的地名
→ AI字符串插值构造curl命令 → Bash执行 → 任意命令执行
```

`{city}` 来自 `reverse-geocode.py` 输出，该输出由 Nominatim API 返回。如果攻击者通过 DNS 劫持、中间人攻击或 Nominatim 数据污染使 `city` 字段包含反引号或 `$()` 命令替换，当 AI 用 Bash tool 执行时会触发命令注入。

**修复建议**: 参数化请求，用 Python `urllib` 替代 curl；或将 city 变量做 shell 转义。

---

### 2. API Key 明文占位符

**文件**: `SKILL.md:383` | **类型**: Credential Leak

```
# 鉴权: Bearer <YOUR_API_KEY>
```

虽然是占位符，但该文件已被 git 跟踪。用户填入真实 key 后可能意外提交。豆包 API key 泄露 = 攻击者可用用户配额随意调用视觉 API，产生费用损失和配额耗尽。

**修复建议**:
- 将 API key 移到环境变量（如 `$DOUBAO_API_KEY`），在 settings.json 中配置
- 在 SKILL.md 使用环境变量引用而非明文占位符

---

### 3. EXIF GPS 隐私泄露 — 多服务静默外传

**涉及链路**: `exif-extract.py` → `reverse-geocode.py` → `suncalc.py` → wttr.in + WebSearch × 7 路 | **类型**: Privacy

用户照片的 GPS 坐标在用户无感知的情况下被发送到至少 4 个外部服务：
- `nominatim.openstreetmap.org`（地点识别）
- `wttr.in`（天气查询）
- 豆包视觉 API `ark.cn-beijing.volces.com`（图片内容分析）
- WebSearch 7 路并联位置搜索（如"故宫角楼 拍照 最佳机位"）

SKILL.md 虽然写了"静默执行，用户不可见中间结果"，但没有在执行前征得用户同意。

**修复建议**: 在阶段 0 之前增加隐私提示交互；或至少在首次使用时告知数据流向。

---

## 🟡 中危发现

### 4. exif-extract.py — 文件类型无校验

**文件**: `scripts/exif-extract.py:97-126` | **类型**: Input Validation

```python
result = subprocess.run(['exiftool', '-j', ..., image_path], ...)
```

`image_path = sys.argv[1]` 直接传入 exiftool，没有校验是否为图片文件。攻击者可以传入 `/etc/passwd` 等系统文件获取部分元数据，或传入恶意构造的图片触发 exiftool 历史 CVE。

**修复建议**: 校验文件扩展名白名单（`.jpg/.jpeg/.png/.heic/.dng/.tiff`）+ magic bytes 验证。

---

### 5. reverse-geocode.py — 坐标范围无校验

**文件**: `scripts/reverse-geocode.py:124-125` | **类型**: Input Validation

```python
lat = float(sys.argv[1])
lon = float(sys.argv[2])
```

没有检查 lat ∈ [-90, 90], lon ∈ [-180, 180]。极端值会直接传给 Nominatim API。

**修复建议**: 增加范围校验，无效坐标直接拒绝并给出明确错误信息。

---

### 6. exif-extract.py — dms_to_decimal 正则 ReDoS

**文件**: `scripts/exif-extract.py:60-63` | **类型**: DoS

正则表达式 `([\d.]+)\s*deg\s*...` 在极端长/恶意构造的 EXIF 数据上可能引发灾难性回溯。

**修复建议**: 对输入字符串增加长度上限（如 200 字符）。

---

### 7. reverse-geocode.py — 脚本层无缓存

**文件**: `scripts/reverse-geocode.py` | **类型**: Resource Exhaustion

SKILL.md 描述了 24 小时位置缓存策略（阶段 0E-5），但这是 AI 记忆层面的逻辑。`reverse-geocode.py` 脚本层每次调用都发 HTTP 请求。Nominatim 免费层有严格频率限制（1 req/s），密集使用可能被封。

**修复建议**: 脚本层加简单的文件缓存（如 `/tmp/zhichu_geocode_cache.json`，按坐标哈希 key）。

---

## 🟠 低危/建议改进

### 8. Prompt Injection — AI Pipeline 搜索注入链

**类型**: AI Safety

攻击者可通过精心构造的照片内容（视觉对抗样本）操控豆包视觉 API 输出的场景描述，进而影响 WebSearch 搜索词，实现间接 prompt injection。攻击链长但理论可行。

**修复建议**: 搜索词加前缀标签（如 `[摄影参考]`）隔离上下文。

---

### 9. 依赖版本未锁定

**文件**: `scripts/exif-extract.py` | **类型**: Supply Chain

Python 脚本依赖系统 `exiftool` 命令，但未检查版本。旧版 exiftool 有多起已知 CVE。

**修复建议**: 在脚本启动时检查 `exiftool -ver`，低于安全版本给出警告。

---

### 10. SKILL.md 文件膨胀（1743 行）

**文件**: `SKILL.md` | **类型**: Maintainability

超大 SKILL.md 每次触发 skill 都会全量注入上下文。大量内容为示例和文档，实际执行逻辑约 30%。

**修复建议**: 拆分为 `SKILL.md`（核心指令 ~500 行）+ 独立规范文档。

---

## 📊 风险矩阵

| # | 漏洞 | 等级 | 影响 | 利用难度 | 修复成本 |
|---|------|:--:|------|:--:|:--:|
| 1 | wttr.in curl 命令注入 | 🔴 高 | RCE | 中 | 低 |
| 2 | API Key git 泄露风险 | 🔴 高 | 凭证泄露 | 低 | 低 |
| 3 | GPS 隐私静默外传 | 🔴 高 | 隐私泄露 | 默认行为 | 中 |
| 4 | exif-extract 无文件类型校验 | 🟡 中 | 敏感信息读取 | 低 | 低 |
| 5 | 坐标无范围校验 | 🟡 中 | 服务异常 | 低 | 低 |
| 6 | ReDoS 正则风险 | 🟡 中 | DoS | 中 | 低 |
| 7 | Nominatim 脚本层无缓存 | 🟡 中 | API 限额耗尽 | 无需利用 | 中 |
| 8 | AI Pipeline Prompt Injection | 🟠 低 | AI 行为操控 | 高 | 中 |
| 9 | exiftool 版本未检查 | 🟠 低 | 依赖漏洞利用 | 中 | 低 |
| 10 | SKILL.md 过大致 token 浪费 | ⚪ 建议 | 性能/cost | N/A | 中 |

---

## 修复优先级

**P0 - 本周**:
1. 将 wttr.in 的 curl 调用改为 Python 脚本内 `urllib` 请求
2. API Key 从 SKILL.md 移到环境变量，添加 `.gitignore` 防护
3. 阶段 0 前增加隐私提示交互

**P1 - 本月**:
4. `exif-extract.py` 加文件类型白名单 + magic bytes 校验
5. `reverse-geocode.py` 加坐标范围校验 + 本地文件缓存
6. 搜索词加隔离前缀防 prompt injection

**P2 - 下月**:
7. SKILL.md 瘦身拆分
8. exiftool 版本检查
9. `dms_to_decimal` 输入长度限制
