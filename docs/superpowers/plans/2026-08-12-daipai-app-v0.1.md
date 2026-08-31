# 带拍 APP v0.1 技术原型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 iPhone 真机上跑通"原生相机拍照 → 上传 → AI 视觉/方向/方案三阶段流式分析 → 三方向卡片 → 方案列表"的完整闭环，验证 React Native + VisionCamera v4 + Skia 技术栈。

> **实现注记（2026-08-13）**：本计划按 RN 0.76 撰写，实际脚手架为 **RN 0.86.2 新架构**（React 19.2 / VisionCamera 4.7.3 / Skia 2.11 / Navigation 7 / Reanimated 4.5 / Zustand 5 / lucide 1.31）。下述依赖版本以实际 `mobile-app/package.json` 为准；计划中的 `slot` 双字段、`progress.message`、`AnalyzingScreen` sessionId 等代码示例已在落地时修正，各 Task 下方有 ⚠️ 注记说明。

**Architecture:** RN 0.86 新架构 iOS 单端应用。VisionCamera v4 拍照输出临时 JPEG，读为 base64 后通过新增的后端 `POST /app/analyze`（JSON + SSE）复用现有 `analyze_photo_stream` 管线；`react-native-sse` 消费事件流。Skia 画方案标注。quick-sqlite 缓存会话。后端零改造，仅新增一个 `/app/*` 薄路由。安卓不实现、不测，但所有跨端抽象（文件、相机能力、渲染）不写死 iOS。

**Tech Stack:** React Native 0.86.2 (New Architecture, iOS only) · TypeScript · react-native-vision-camera v4.7.3 · @shopify/react-native-skia 2.11 · @react-navigation v7 (native-stack + bottom-tabs) · zustand v5 · react-native-sse · react-native-quick-sqlite · react-native-fs · react-native-device-info · 现有 Flask 后端

## Global Constraints

- **平台**：v0.1 只开发/测试 iOS（iPhone 13 及更新，iOS 16+）。所有代码用跨端库，不写 `Platform.OS === 'ios'` 分支（除非库本身要求），为安卓预留。
- **视觉系统**：奶油胶片杂志。内容态底色 `#FAF6F0`、正文墨 `#1C1917`、主色焙茶褐 `#B5673E`、暖金箔 `#C9A063`；取景器态亚光黑 `#0D0D0D` + 暖金引导。字体：标题 iOS 系统衬线（New York / `ui-serif`，v0.2 再换思源宋体打包），正文苹方，数字等宽。
- **触控**：所有可点元素 ≥44×44pt，相邻间距 ≥8pt，过渡 150-300ms。
- **后端**：现有 `mobile-tester/server.py` 的 `/analyze`、`/analyze/plans` 不动；新增 `/app/analyze` 复用 `analyze_photo_stream`。API base URL 走环境配置，默认 `https://guidepic.cn`。
- **模型**：视觉豆包 Lite、方向/方案 DeepSeek Flash（关思考）——全部在后端，APP 不直接调模型。
- **不做**：手动控制/叠加层、后期编辑、ProRAW、登录鉴权（v0.1 用静态 app token）、图生图、安卓。这些是 v0.2+ 的范围。
- **提交规范**：每个 Task 结束一次 commit，消息用 `feat(app): ...` / `chore(app): ...` 前缀。代码在 `mobile-app/` 目录，与 `mobile-tester/` 并列。
- **AI slop 禁令**：不用 emoji 当图标（用 Lucide 图标组件）、不做紫粉渐变、不做模糊玻璃卡、不全站一个圆角。

---

## 文件结构

v0.1 将创建以下结构（全部在 `mobile-app/` 下）：

```
mobile-app/
├── package.json
├── app.json                      # RN 应用配置（bundle id、权限文案）
├── index.js                      # 入口
├── tsconfig.json
├── babel.config.js
├── metro.config.js               # 启用 Skia 的 worklets/Reanimated 配置
├── .env.example                  # API_BASE_URL / APP_TOKEN
├── ios/                          # RN generate 生成 + pod install
└── src/
    ├── App.tsx                   # 根组件 + Provider 装配
    ├── theme/
    │   └── tokens.ts             # 颜色/字体/间距/圆角/阴影常量
    ├── api/
    │   ├── config.ts             # baseURL / token 读取
    │   ├── sse.ts                # SSE 事件解析器（纯函数，可单测）
    │   ├── client.ts             # analyzeStream() / fetchPlans() 封装
    │   └── types.ts              # 方向/方案/视觉结果 TS 类型
    ├── storage/
    │   └── session.ts            # quick-sqlite 初始化 + 会话读写
    ├── store/
    │   └── useSessionStore.ts    # zustand：当前会话状态
    ├── hooks/
    │   └── useCameraPermissions.ts
    ├── components/
    │   ├── CreamButton.tsx       # 焙茶褐主按钮 / 描边次按钮
    │   ├── PhaseIndicator.tsx    # SSE 阶段进度（Skia 线条动画）
    │   ├── DirectionCard.tsx     # 三方向杂志卡
    │   ├── PlanCard.tsx          # 方案卡（四段 + 标注）
    │   └── SketchAnnotation.tsx  # Skia 在原图上画 subject/shooter 标注
    ├── screens/
    │   ├── HomeScreen.tsx
    │   ├── CameraScreen.tsx
    │   ├── AnalyzingScreen.tsx
    │   ├── DirectionsScreen.tsx
    │   ├── PlansScreen.tsx
    │   ├── InspirationScreen.tsx # v0.1 占位
    │   ├── GalleryScreen.tsx     # v0.1 占位
    │   └── ProfileScreen.tsx     # v0.1 占位
    └── navigation/
        └── AppNavigator.tsx      # Bottom Tabs + 相机/分析 Stack
```

后端新增一个文件（薄路由）：
- Modify: `mobile-tester/server.py`（新增 `/app/analyze` 路由，复用 `analyze_photo_stream`，约 35 行）

---

## Task 1: 环境与 RN 工程脚手架

**Files:**
- Create: `mobile-app/` 整个 RN 工程
- Modify: 本机安装 Xcode/CocoaPods/Watchman

**Interfaces:**
- Produces: 可在 iOS 模拟器跑起来的空 RN 应用 `mobile-app/`，后续所有任务在此基础上开发。

- [ ] **Step 1: 安装本机依赖**

环境检查显示当前缺 Xcode（只有 CLT）、CocoaPods、Watchman、yarn。安装：

```bash
# 1. 从 App Store 安装 Xcode（必须，含 iOS SDK 和模拟器）
# 装完后激活：
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept

# 2. 用 Homebrew 装 Watchman + CocoaPods
brew install watchman cocoapods

# 3. 确认版本
node -v          # 期望 v20+ 或 v26（当前 v26.0.0，可用）
watchman --version
pod --version
xcodebuild -version  # 期望 Xcode 15+
```

- [ ] **Step 2: 创建 RN 0.76 TypeScript 工程**

在仓库根目录（与 `mobile-tester/` 同级）：

```bash
cd "/Users/rabbit/Claude code/Photography"
npx @react-native-community/cli@latest init DaipaiApp --directory mobile-app --version 0.86.2 --skip-install
```

`--skip-install` 先跳过，便于改 package.json 后一次装齐。

- [ ] **Step 3: 添加依赖到 `mobile-app/package.json`**

在 `dependencies` 里加入（⚠️ 实际落地的版本来自 `mobile-app/package.json`，以 `npm install` 装出的为准）：

```json
{
  "dependencies": {
    "react": "19.2.3",
    "react-native": "0.86.2",
    "react-native-vision-camera": "4.7.3",
    "@shopify/react-native-skia": "2.11.0",
    "@react-navigation/native": "^7.1.6",
    "@react-navigation/native-stack": "^7.3.10",
    "@react-navigation/bottom-tabs": "^7.3.10",
    "react-native-screens": "^4.13.0",
    "react-native-safe-area-context": "^5.5.2",
    "react-native-gesture-handler": "^3.1.0",
    "react-native-reanimated": "4.5.3",
    "react-native-worklets": "0.11.3",
    "react-native-sse": "^1.2.1",
    "react-native-quick-sqlite": "^8.2.7",
    "react-native-fs": "^2.20.0",
    "react-native-device-info": "^15.0.2",
    "react-native-svg": "^15.12.0",
    "zustand": "^5.0.14",
    "lucide-react-native": "^1.31.0",
    "react-native-dotenv": "^3.4.11"
  },
  "devDependencies": {
    "@react-native-community/cli": "20.1.0",
    "@react-native-community/cli-platform-android": "20.1.0",
    "@react-native-community/cli-platform-ios": "20.1.0",
    "@react-native/babel-preset": "0.86.2",
    "@react-native/metro-config": "0.86.2",
    "@react-native/typescript-config": "0.86.2",
    "@types/react": "^19.2.0",
    "typescript": "^5.8.3",
    "react-native-dotenv": "^3.4.11"
  }
}
```

> ⚠️ **Reanimated 4 与 worklets**：Reanimated 4 拆出了独立的 `react-native-worklets` 依赖。Babel 插件名也从 `react-native-reanimated/plugin` 改为 `react-native-worklets/plugin`（见下 Step 4）。

- [ ] **Step 4: 配置 Babel（启用 Skia/Reanimated worklets）**

写入 `mobile-app/babel.config.js`：

```js
module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    'react-native-reanimated/plugin',   // 必须放在最后
    ['module:react-native-dotenv', {
      moduleName: '@env',
      path: '.env',
      safe: true,
      allowUndefined: false,
    }],
  ],
};
```

- [ ] **Step 5: 配置 Metro（Skia 需要）**

写入 `mobile-app/metro.config.js`：

```js
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

const config = {
  // react-native-skia 需要加载 .mjs / .wasm
  resolver: {
    sourceExts: [...getDefaultConfig(__dirname).resolver.sourceExts, 'mjs'],
  },
};

module.exports = mergeConfig(getDefaultConfig(__dirname), config);
```

- [ ] **Step 6: 写入环境变量样例**

写入 `mobile-app/.env.example`：

```
API_BASE_URL=https://guidepic.cn
APP_TOKEN=daipai-ios-v0.1-dev
```

复制为 `mobile-app/.env`（实际值本地用；该文件加入 `.gitignore`）。

- [ ] **Step 7: 配置 iOS 权限文案**

用 Xcode 打开 `mobile-app/ios/DaipaiApp.xcworkspace`，在 `Info.plist` 里加入（或直接编辑文件）：

```xml
<key>NSCameraUsageDescription</key>
<string>带拍需要使用相机来拍摄并为你生成拍摄方案</string>
<key>NSPhotoLibraryAddUsageDescription</key>
<string>带拍需要保存你拍摄的照片到相册</string>
<key>NSLocationWhenInUseUsageDescription</key>
<string>带拍根据你所在位置的光线和天气给出更准的拍摄建议</string>
```

在 `mobile-app/app.json` 里设置 bundle id 与版本：

```json
{
  "name": "DaipaiApp",
  "displayName": "带拍",
  "ios": {
    "bundleIdentifier": "cn.guidepic.daipai",
    "buildNumber": "1",
    "infoPlist": {
      "CFBundleDisplayName": "带拍",
      "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait"]
    }
  }
}
```

> ⚠️ 实现注记：实际 `mobile-app/app.json` 精简为仅 `name`/`displayName`，bundle id 与权限文案落在 Xcode 工程 `ios/DaipaiApp/Info.plist` 与 target 配置。若要配置可审计，v0.2 可回填此文件。

- [ ] **Step 8: 装依赖 + pod install + 启动模拟器验证**

```bash
cd mobile-app
npm install
cd ios && bundle install 2>/dev/null; pod install && cd ..
npm run ios
```

**Expected:** Metro 启动，iOS 模拟器打开，显示 RN 默认欢迎屏。这步验证整条工具链通。如果 `pod install` 报 Ruby 版本问题，用 `sudo gem install cocoapods` 或系统自带 Ruby。

- [ ] **Step 9: 提交**

```bash
cd "/Users/rabbit/Claude code/Photography"
echo "mobile-app/.env" >> .gitignore
git add mobile-app/ .gitignore
git commit -m "chore(app): scaffold React Native 0.76 iOS project with camera/skia deps"
```

---

## Task 2: 设计 Token（奶油胶片杂志）

**Files:**
- Create: `mobile-app/src/theme/tokens.ts`

**Interfaces:**
- Produces: 导出的 `colors`、`fonts`、`spacing`、`radii`、`shadows` 常量对象，所有屏幕和组件从这里取值。后续任务禁止硬编码颜色。

- [ ] **Step 1: 写 token 常量**

写入 `mobile-app/src/theme/tokens.ts`：

```ts
/**
 * 带拍 APP 设计 Token —— 奶油胶片杂志 Cream Film Editorial
 * 唯一真相源。组件禁止硬编码颜色/字号/圆角。
 */

export const colors = {
  // 内容态（奶油底）
  cream: '#FAF6F0',
  ink: '#1C1917',
  hujia: '#B5673E',   // 焙茶褐，主色
  gold: '#C9A063',    // 暖金箔，强调/引导
  stone: '#78716C',   // 次要文字
  paper: '#FFFFFF',   // 卡片
  line: '#EDE6DB',    // 极淡描边
  mist: '#F3EDE3',    // 次级背景

  // 三方向状态色（低饱和，奶油底和谐）
  now: '#7C8A5E',     // 🟢 苔藓绿，现在就拍
  best: '#D98248',    // 🔥 焙茶橙，最出片
  creative: '#9B8AB4',// ✨ 灰紫，最大胆

  // 取景器态
  viewfinderBg: '#0D0D0D',
  guideGold: '#C9A063',
  guideWhite: 'rgba(255,255,255,0.85)',
  zebra: 'rgba(255,255,255,0.35)',

  // 后期态
  darkroomBg: '#161412',
  darkroomFg: '#F5EDE0',

  // 功能色
  success: '#7C8A5E',
  warning: '#D98248',
  danger: '#C0504A',
  info: '#7A8B99',
} as const;

export const fonts = {
  // 标题：iOS 系统衬线（New York），杂志感。v0.2 换打包的思源宋体
  serif: 'ui-serif',
  serifItalic: 'ui-serif',
  // 正文：系统无衬线（iOS 自动落苹方 PingFang SC）
  sans: 'ui-sans-serif',
  // 数字等宽（EV/ISO/焦段跳动时不晃）
  mono: 'ui-monospace',
} as const;

export const fontSizes = {
  hero: 34,
  h1: 28,
  h2: 20,
  body: 15,
  small: 13,
  caption: 11,
} as const;

export const lineHeights = {
  tight: 1.2,
  normal: 1.5,
  loose: 1.7,
} as const;

export const spacing = {
  xs: 4, s: 8, m: 12, l: 16, xl: 24, xxl: 32, xxxl: 48,
} as const;

// 层级分明，不全站一个圆角
export const radii = {
  tag: 10,
  input: 14,
  button: 16,
  card: 22,
} as const;

export const shadows = {
  card: {
    shadowColor: '#1C1917',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 30,
    elevation: 0, // iOS 优先，v0.1 不纠结安卓
  },
  button: {
    shadowColor: '#B5673E',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
    elevation: 0,
  },
} as const;
```

- [ ] **Step 2: 写一个最小渲染测试（可选但推荐）**

v0.1 不强引 Jest（RN 模板自带）。用一个简单断言确认 token 值未被误改：

写入 `mobile-app/__tests__/theme.test.ts`：

```ts
import { colors, radii } from '../src/theme/tokens';

describe('design tokens', () => {
  it('uses the cream film editorial palette', () => {
    expect(colors.cream).toBe('#FAF6F0');
    expect(colors.hujia).toBe('#B5673E');
    expect(colors.gold).toBe('#C9A063');
  });
  it('uses layered radii, not a single value', () => {
    expect(radii.card).toBeGreaterThan(radii.button);
    expect(radii.button).toBeGreaterThan(radii.tag);
  });
});
```

运行：

```bash
cd mobile-app && npm test -- theme.test.ts
```

Expected: 2 passed.

- [ ] **Step 3: 提交**

```bash
git add mobile-app/src/theme/tokens.ts mobile-app/__tests__/theme.test.ts
git commit -m "feat(app): add cream film editorial design tokens"
```

---

## Task 3: 后端新增 `/app/analyze` SSE 端点

**Files:**
- Modify: `mobile-tester/server.py`（在 `/analyze` 路由后新增）

**Interfaces:**
- Produces: `POST /app/analyze`，接收 JSON `{ "photo": "<base64>", "device"?: string, "lens"?: string, "app_token": string }`，返回与 `/analyze` 完全相同的 SSE 事件流（`exif_ready` / `vision_ready` / `directions_ready` / `complete` / `error`）。APP 端 Task 5 调用此端点。

**Why:** `react-native-sse` 对 multipart body 支持不可靠；base64 JSON 是 iOS 端最稳的 SSE 上传方式。现有 `/analyze` 一字不改。

- [ ] **Step 1: 定位插入点**

```bash
cd "/Users/rabbit/Claude code/Photography/mobile-tester"
grep -n "@app.route('/analyze/plans'" server.py
```

在 `/analyze` 路由结束（`/analyze/plans` 开始之前）插入新路由。

- [ ] **Step 2: 写入 `/app/analyze` 路由**

在 `server.py` 中 `/analyze` 路由的 `return Response(...)` 之后、`@app.route('/analyze/plans'...)` 之前加入：

```python
@app.route('/app/analyze', methods=['POST'])
def app_analyze():
    """APP 端专用入口：接收 base64 照片，走与 /analyze 相同的流式管线。
    与 /analyze 的唯一区别是请求体为 JSON（base64），而非 multipart——
    react-native-sse 对 multipart 支持不可靠。
    v0.1 用静态 APP_TOKEN 做最简单的接入控制；v1.0 换成 JWT。
    """
    data = request.get_json(silent=True) or {}
    expected_token = os.environ.get('APP_TOKEN', 'daipai-ios-v0.1-dev')
    if data.get('app_token') != expected_token:
        return jsonify({"error": "unauthorized"}), 401

    photo_b64 = data.get('photo')
    if not photo_b64:
        return jsonify({"error": "missing photo"}), 400

    # 去掉可能存在的 data URI 前缀
    if photo_b64.startswith('data:'):
        photo_b64 = photo_b64.split(',', 1)[1]

    try:
        img_bytes = base64.b64decode(photo_b64)
    except Exception:
        return jsonify({"error": "invalid base64"}), 400

    # 写入临时文件，复用现有管线（Pillow 压缩 + exiftool 都作用于文件）
    suffix = '.heic' if img_bytes[:4] == b'ftyp' and b'heic' in img_bytes[:16].lower() else '.jpg'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    device_override = data.get('device') or None
    lens_key = data.get('lens') or None
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or 'app'

    def stream():
        try:
            yield from analyze_photo_stream(tmp_path, device_override, lens_key, client_ip)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return Response(
        stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
```

确认文件顶部已有 `import base64, tempfile, os`（`server.py` 现有导入已含 `os`/`tempfile`；若缺 `base64` 则补上 `import base64`）。

- [ ] **Step 3: 本地启动后端验证端点**

```bash
cd "/Users/rabbit/Claude code/Photography/mobile-tester"
# 用一张测试图转 base64 调用
TESTIMG=$(base64 -i <一张本地JPG> | tr -d '\n')
curl -sN -X POST http://127.0.0.1:8888/app/analyze \
  -H "Content-Type: application/json" \
  -d "{\"app_token\":\"daipai-ios-v0.1-dev\",\"photo\":\"$TESTIMG\"}" \
  --max-time 180 | head -40
```

Expected: 看到 `event: exif_ready`、`event: vision_ready`、`event: directions_ready`、`event: complete` 依次输出，data 是 JSON。若看到 `event: error`，读 message 排查（常见：API key 未配置、照片无法读取）。

- [ ] **Step 4: 验证鉴权失败路径**

```bash
curl -s -X POST http://127.0.0.1:8888/app/analyze \
  -H "Content-Type: application/json" \
  -d '{"app_token":"wrong","photo":"x"}'
```

Expected: `{"error":"unauthorized"}` 状态码 401。

- [ ] **Step 5: 提交**

```bash
cd "/Users/rabbit/Claude code/Photography"
git add mobile-tester/server.py
git commit -m "feat(backend): add /app/analyze base64 SSE endpoint reusing analyze pipeline"
```

---

## Task 4: API 类型与 SSE 解析器（纯函数 + 单测）

**Files:**
- Create: `mobile-app/src/api/types.ts`
- Create: `mobile-app/src/api/config.ts`
- Create: `mobile-app/src/api/sse.ts`
- Test: `mobile-app/__tests__/sse.test.ts`

**Interfaces:**
- Produces:
  - TS 类型 `Direction`、`Plan`、`ExifReady`、`VisionReady`、`DirectionsReady`、`AnalyzeEvent`。
  - `parseSseChunks(prevBuffer, chunkText) -> { events: AnalyzeEvent[], remainder: string }` 纯函数。
  - `API_BASE_URL` / `APP_TOKEN` 配置读取。

- [ ] **Step 1: 写类型定义**

写入 `mobile-app/src/api/types.ts`：

```ts
// 与后端 server.py 的 SSE data 字段对齐。只列 v0.1 UI 用到的字段，
// 其余字段用 [key:string]: unknown 兜底，避免 TS 报错又不丢信息。

export interface PlanAnnotation {
  type: 'subject' | 'shooter';
  x: number; y: number; // 0-1 归一化坐标
  label?: string;
}

export interface Plan {
  name: string;
  prep?: string;
  subject: string;
  shooter: string;
  gear: string;
  enhance: string;
  result: string;
  why?: string;
  shot_size?: string;
  angle?: string;
  quick_edit?: { app?: string; goal?: string; steps?: string[] };
  img_gen_prompt?: string;
  annotations?: PlanAnnotation[];
  perspective?: string;
}

export interface Direction {
  id: DirectionSlot;     // ⚠️ 后端字段就是 id（best/now/creative），不是 slot——计划初稿的双字段已修掉
  style: string;
  kb_status?: string;
  style_promise: string;
  reason?: string;
  fit_rationale?: string;
  light_annotation?: string;
  device_annotation?: string;
  style_brief?: { essence?: string; color?: string; composition?: string; light?: string; mood?: string };
  photo_guide?: string;
  plans?: Plan[];        // 后端可能随方向附带（prewarm），否则单独拉
  [key: string]: unknown;
}

export interface ExifReadyData {
  device?: string;
  lens?: string;
  location?: string;
  weather?: string;
  light_period?: string;
  [key: string]: unknown;
}

export interface VisionReadyData {
  scene_type?: string;
  primary_subject?: string;
  people?: unknown;
  light?: unknown;
  color?: unknown;
  [key: string]: unknown;
}

export interface DirectionsReadyData {
  directions: Direction[];
  insight?: string;
  scene_tier?: string;
  session_id: string;    // ⚠️ 实际必须——AnalyzingScreen 用 e.data.session_id 落库导航
  [key: string]: unknown;
}

export type AnalyzeEvent =
  | { event: 'progress'; phase: string; text: string }   // ⚠️ 后端 emit_progress 发的是 text 不是 message
  | { event: 'exif_ready'; data: ExifReadyData }
  | { event: 'vision_ready'; data: VisionReadyData }
  | { event: 'directions_ready'; data: DirectionsReadyData }
  | { event: 'complete'; data: { session_id: string; [k: string]: unknown } }
  | { event: 'cancelled'; data: { message?: string } }
  | { event: 'error'; data: { message: string } };
```

说明：后端 `emit_progress` 发的是 `event: progress` + `data: {phase, message}`；`emit("exif_ready", {...})` 发的是 `event: exif_ready`。以 server.py L2519-2520 的 `f"event: {event}\ndata: {json}\n\n"` 格式为准。

- [ ] **Step 2: 写配置**

写入 `mobile-app/src/api/config.ts`：

```ts
import { API_BASE_URL, APP_TOKEN } from '@env';

export const config = {
  baseURL: API_BASE_URL || 'https://guidepic.cn',
  appToken: APP_TOKEN || 'daipai-ios-v0.1-dev',
};

// react-native-dotenv 类型声明
declare module '@env' {
  export const API_BASE_URL: string;
  export const APP_TOKEN: string;
}
```

- [ ] **Step 3: 写失败的 SSE 解析器测试**

写入 `mobile-app/__tests__/sse.test.ts`：

```ts
import { parseSseChunks } from '../src/api/sse';

describe('parseSseChunks', () => {
  it('parses a single complete event', () => {
    const raw = 'event: exif_ready\ndata: {"device":"iPhone 15 Pro"}\n\n';
    const { events, remainder } = parseSseChunks('', raw);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('exif_ready');
    expect((events[0] as any).data.device).toBe('iPhone 15 Pro');
    expect(remainder).toBe('');
  });

  it('buffers a partial chunk across calls', () => {
    const first = parseSseChunks('', 'event: progress\ndata: {"phase":"exif"');
    expect(first.events).toHaveLength(0);
    expect(first.remainder).toContain('phase');

    const second = parseSseChunks(first.remainder, ',"message":"读取中"}\n\n');
    expect(second.events).toHaveLength(1);
    expect(second.events[0].event).toBe('progress');
  });

  it('parses multiple events in one chunk', () => {
    const raw =
      'event: exif_ready\ndata: {}\n\n' +
      'event: vision_ready\ndata: {}\n\n';
    const { events } = parseSseChunks('', raw);
    expect(events.map(e => e.event)).toEqual(['exif_ready', 'vision_ready']);
  });

  it('emits error event for malformed JSON without throwing', () => {
    const raw = 'event: exif_ready\ndata: {not json}\n\n';
    const { events } = parseSseChunks('', raw);
    expect(events[0].event).toBe('error');
  });
});
```

运行 `cd mobile-app && npm test -- sse.test.ts`，Expected: FAIL（模块不存在）。

- [ ] **Step 4: 实现 SSE 解析器**

写入 `mobile-app/src/api/sse.ts`：

```ts
import type { AnalyzeEvent } from './types';

/**
 * 增量 SSE 解析器。网络块可能在任意位置断开，
 * 所以保留 remainder 缓冲，跨 chunk 拼接。
 *
 * SSE 协议：事件以空行 \n\n 分隔；事件内行格式为
 * "field: value"。我们只关心 event 和 data。
 */
export function parseSseChunks(
  prevRemainder: string,
  chunk: string,
): { events: AnalyzeEvent[]; remainder: string } {
  const events: AnalyzeEvent[] = [];
  const buffer = prevRemainder + chunk;

  // 以空行分帧。最后一帧可能不完整，留到 remainder。
  const parts = buffer.split('\n\n');
  const remainder = parts.pop() ?? '';

  for (const rawFrame of parts) {
    let eventName = 'message';
    let dataStr = '';
    for (const line of rawFrame.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataStr += line.slice(5).trim();
      }
    }
    if (!dataStr) continue;

    let data: unknown;
    try {
      data = JSON.parse(dataStr);
    } catch {
      events.push({ event: 'error', data: { message: `SSE JSON 解析失败: ${dataStr.slice(0, 80)}` } });
      continue;
    }

    switch (eventName) {
      case 'progress':
        events.push({
          event: 'progress',
          phase: (data as any)?.phase ?? '',
          text: (data as any)?.text ?? '',   // ⚠️ 后端字段是 text
        });
        break;
      case 'exif_ready':
        events.push({ event: 'exif_ready', data: data as any });
        break;
      case 'vision_ready':
        events.push({ event: 'vision_ready', data: data as any });
        break;
      case 'directions_ready':
        events.push({ event: 'directions_ready', data: data as any });
        break;
      case 'complete':
        events.push({ event: 'complete', data: data as any });
        break;
      case 'cancelled':
        events.push({ event: 'cancelled', data: data as any });
        break;
      case 'error':
        events.push({ event: 'error', data: { message: (data as any)?.message ?? '未知错误' } });
        break;
      default:
        // 忽略未知事件（如 ping），不报错
        break;
    }
  }

  return { events, remainder };
}
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd mobile-app && npm test -- sse.test.ts
```

Expected: 4 passed.

- [ ] **Step 6: 提交**

```bash
cd "/Users/rabbit/Claude code/Photography"
git add mobile-app/src/api/types.ts mobile-app/src/api/config.ts mobile-app/src/api/sse.ts mobile-app/__tests__/sse.test.ts
git commit -m "feat(app): add API types and incremental SSE parser with tests"
```

---

## Task 5: API 客户端（analyze 流式 + plans 拉取）

**Files:**
- Create: `mobile-app/src/api/client.ts`

**Interfaces:**
- Consumes: `parseSseChunks`（Task 4）、`config`（Task 4）、`AnalyzeEvent`/`Direction`/`Plan` 类型。
- Produces:
  - `analyzeStream(params: { photoBase64: string; device?: string; lens?: string }, onEvent: (e: AnalyzeEvent) => void): Promise<{ sessionId: string }>`
  - `fetchPlans(params: { sessionId: string; directionId: string; device?: string; lens?: string }): Promise<Plan[]>`

- [ ] **Step 1: 写失败测试**

写入 `mobile-app/__tests__/client.test.ts`：

```ts
import { parseSseChunks } from '../src/api/sse';

// 客户端主要靠集成测试（真机）覆盖；这里只验证 onEvent 回调契约。
describe('analyzeStream event contract', () => {
  it('delivers parsed events to onEvent in order', () => {
    const stream =
      'event: exif_ready\ndata: {"device":"x"}\n\n' +
      'event: directions_ready\ndata: {"directions":[]}\n\n' +
      'event: complete\ndata: {"session_id":"s1"}\n\n';
    const received: string[] = [];
    const { events } = parseSseChunks('', stream);
    events.forEach(e => received.push(e.event));
    expect(received).toEqual(['exif_ready', 'directions_ready', 'complete']);
  });
});
```

运行 `npm test -- client.test.ts`，Expected: PASS（这是契约测试，不依赖网络）。

- [ ] **Step 2: 实现客户端**

写入 `mobile-app/src/api/client.ts`：

```ts
import EventSource from 'react-native-sse';
import RNFS from 'react-native-fs';
import { config } from './config';
import { parseSseChunks } from './sse';
import type { AnalyzeEvent, Plan } from './types';

/**
 * 读取 VisionCamera 拍下的临时照片文件，转 base64。
 * iOS path 形如 file:///var/.../IMG.JPG；去掉 file:// 前缀给 RNFS。
 */
export async function readPhotoAsBase64(filePath: string): Promise<string> {
  const clean = filePath.replace('file://', '');
  return RNFS.readFile(clean, 'base64');
}

export interface AnalyzeParams {
  photoBase64: string;
  device?: string;
  lens?: string;
}

/**
 * 发起分析，通过 onEvent 回调流式交付 SSE 事件。
 * complete 事件后 resolve sessionId。
 * 出错时 reject（含 SSE error 事件和网络错误）。
 */
export function analyzeStream(
  params: AnalyzeParams,
  onEvent: (e: AnalyzeEvent) => void,
): Promise<{ sessionId: string }> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${config.baseURL}/app/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        photo: params.photoBase64,
        device: params.device,
        lens: params.lens,
        app_token: config.appToken,
      }),
      // iOS 后台可能断连，调试期给足超时
      timeout: 180000,
    });

    let buffer = '';
    let settled = false;

    es.addEventListener('open', () => { /* 连接已开 */ });

    // react-native-sse 把所有事件都送到 'message'？不——它按 event 名分发。
    // 但我们要增量解析原始 chunk，所以用 'message' 之外的 approach：
    // 该库对每个 event 名触发 addEventListener；这里统一监听通用事件。
    const handleRaw = (eventName: string, rawData: string) => {
      // 把库已拆好的单事件重新走解析器，保证与真机字节流行为一致
      const synthetic = `event: ${eventName}\ndata: ${rawData}\n\n`;
      const { events, remainder } = parseSseChunks(buffer, synthetic);
      buffer = remainder;
      for (const e of events) {
        onEvent(e);
        if (e.event === 'complete') {
          if (!settled) { settled = true; resolve({ sessionId: e.data.session_id }); }
          es.close();
        }
        if (e.event === 'error') {
          if (!settled) { settled = true; reject(new Error(e.data.message)); }
          es.close();
        }
      }
    };

    ['progress', 'exif_ready', 'vision_ready', 'directions_ready', 'complete', 'cancelled', 'error']
      .forEach(name => {
        es.addEventListener(name, (e: any) => handleRaw(name, e.data));
      });

    es.addEventListener('error', (e: any) => {
      if (settled) return;
      settled = true;
      es.close();
      reject(new Error(e?.message ?? '网络连接失败，请检查网络后重试'));
    });
  });
}

export async function fetchPlans(params: {
  sessionId: string;
  directionId: string;
  device?: string;
  lens?: string;
}): Promise<Plan[]> {
  const res = await fetch(`${config.baseURL}/analyze/plans`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // v0.1 复用现有 IP 配额，不传 app token；v1.0 加 JWT
    },
    body: JSON.stringify({
      session_id: params.sessionId,
      direction_id: params.directionId,
      device: params.device,
      lens: params.lens,
    }),
  });
  if (!res.ok) {
    throw new Error(`方案拉取失败 (${res.status})`);
  }
  const json = await res.json();
  // 后端返回 { plans: [...] } 或直接数组，兼容两种
  return Array.isArray(json) ? json : (json.plans ?? []);
}
```

注意：`/analyze/plans` 现有路由读 JSON body 的 `session_id`/`direction_id`/`device`/`lens`（见 server.py L3462）。返回 JSON 含 plans 数组。Task 10 会以真机验证实际结构，若字段名有差异在此处修正。

- [ ] **Step 3: 运行测试**

```bash
cd mobile-app && npm test -- client.test.ts
```

Expected: PASS.

- [ ] **Step 4: 提交**

```bash
git add mobile-app/src/api/client.ts mobile-app/__tests__/client.test.ts
git commit -m "feat(app): add analyzeStream SSE client and fetchPlans"
```

---

## Task 6: 本地存储与会话状态

**Files:**
- Create: `mobile-app/src/storage/session.ts`
- Create: `mobile-app/src/store/useSessionStore.ts`

**Interfaces:**
- Produces:
  - `initDb(): Promise<void>`
  - `saveSession(session): Promise<void>` / `getSession(id): Promise<SessionRow | null>` / `getRecentSessions(limit): Promise<SessionRow[]>`
  - `useSessionStore` zustand hook：`{ photoPath, exif, vision, directions, sessionId, setXxx, reset }`

- [ ] **Step 1: 初始化 quick-sqlite 与会话表**

写入 `mobile-app/src/storage/session.ts`：

```ts
import { open } from 'react-native-quick-sqlite';

const db = open('daipai.db');

export function initDb(): void {
  db.execute(`
    CREATE TABLE IF NOT EXISTS sessions (
      session_id TEXT PRIMARY KEY,
      photo_path TEXT,
      device TEXT,
      exif_json TEXT,
      vision_json TEXT,
      directions_json TEXT,
      created_at INTEGER NOT NULL
    );
  `);
}

export interface SessionRow {
  session_id: string;
  photo_path: string | null;
  device: string | null;
  exif_json: string | null;
  vision_json: string | null;
  directions_json: string | null;
  created_at: number;
}

export async function saveSession(s: SessionRow): Promise<void> {
  db.execute(
    `INSERT OR REPLACE INTO sessions
     (session_id, photo_path, device, exif_json, vision_json, directions_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [s.session_id, s.photo_path, s.device, s.exif_json, s.vision_json, s.directions_json, s.created_at],
  );
}

export async function getSession(sessionId: string): Promise<SessionRow | null> {
  const res = db.execute('SELECT * FROM sessions WHERE session_id = ?', [sessionId]);
  return (res.rows?._array?.[0] as SessionRow | undefined) ?? null;
}

export async function getRecentSessions(limit = 20): Promise<SessionRow[]> {
  const res = db.execute(
    'SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?',
    [limit],
  );
  return (res.rows?._array as SessionRow[]) ?? [];
}
```

- [ ] **Step 2: 在 App 启动时初始化 DB**

这一步在 Task 8 的 `App.tsx` 里 `useEffect(() => { initDb(); }, [])` 调用。本任务先导出函数。

- [ ] **Step 3: 写 zustand store**

写入 `mobile-app/src/store/useSessionStore.ts`：

```ts
import { create } from 'zustand';
import type { Direction, ExifReadyData, VisionReadyData } from '../api/types';

interface SessionState {
  photoPath: string | null;
  device: string | null;
  exif: ExifReadyData | null;
  vision: VisionReadyData | null;
  directions: Direction[];
  sessionId: string | null;
  // 拍摄阶段进行中
  isAnalyzing: boolean;
  progressText: string;   // ⚠️ 实际命名 progressText（不是 progressMessage）

  setPhoto: (path: string) => void;
  setExif: (d: ExifReadyData) => void;
  setVision: (d: VisionReadyData) => void;
  setDirections: (dirs: Direction[], sessionId: string) => void;
  setProgressText: (text: string) => void;   // ⚠️ setProgressText
  setAnalyzing: (b: boolean) => void;
  reset: () => void;
}

const initial = {
  photoPath: null,
  device: null,
  exif: null,
  vision: null,
  directions: [],
  sessionId: null,
  isAnalyzing: false,
  progressText: '',
};

export const useSessionStore = create<SessionState>(set => ({
  ...initial,
  setPhoto: photoPath => set({ photoPath }),
  setExif: exif => set({ exif, device: exif.device_name ?? null }),  // ⚠️ 后端字段是 device_name
  setVision: vision => set({ vision }),
  setDirections: (directions, sessionId) =>
    set({ directions, sessionId, isAnalyzing: false }),
  setProgressText: progressText => set({ progressText }),
  setAnalyzing: isAnalyzing => set({ isAnalyzing }),
  reset: () => set(initial),
}));
```

- [ ] **Step 4: 提交**

```bash
git add mobile-app/src/storage/session.ts mobile-app/src/store/useSessionStore.ts
git commit -m "feat(app): add quick-sqlite session storage and zustand store"
```

---

## Task 7: 奶油风按钮与权限 Hook

**Files:**
- Create: `mobile-app/src/components/CreamButton.tsx`
- Create: `mobile-app/src/hooks/useCameraPermissions.ts`

**Interfaces:**
- Produces:
  - `<CreamButton title onPress variant? loading? />` —— `variant: 'primary' | 'secondary'`。
  - `useCameraPermissions(): { hasPermission: boolean | null; request: () => Promise<boolean> }`

- [ ] **Step 1: 实现 CreamButton**

写入 `mobile-app/src/components/CreamButton.tsx`：

```tsx
import React from 'react';
import {
  Pressable, Text, StyleSheet, ActivityIndicator, ViewStyle,
} from 'react-native';
import { colors, fonts, fontSizes, radii, spacing, shadows } from '../theme/tokens';

interface Props {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary';
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}

export function CreamButton({
  title, onPress, variant = 'primary', loading, disabled, style,
}: Props) {
  const isPrimary = variant === 'primary';
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.base,
        isPrimary ? styles.primary : styles.secondary,
        pressed && styles.pressed,
        (disabled || loading) && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={isPrimary ? colors.paper : colors.hujia} />
      ) : (
        <Text style={[styles.text, isPrimary ? styles.textPrimary : styles.textSecondary]}>
          {title}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 52,          // 远超 44pt 触控下限
    paddingHorizontal: spacing.xl,
    borderRadius: radii.button,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: {
    backgroundColor: colors.hujia,
    ...shadows.button,
  },
  secondary: {
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    borderColor: colors.hujia,
  },
  text: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.body,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  textPrimary: { color: colors.paper },
  textSecondary: { color: colors.hujia },
  pressed: { opacity: 0.85, transform: [{ scale: 0.98 }] },
  disabled: { opacity: 0.4 },
});
```

- [ ] **Step 2: 实现相机权限 Hook**

写入 `mobile-app/src/hooks/useCameraPermissions.ts`：

```ts
import { useState, useEffect, useCallback } from 'react';
import { Camera } from 'react-native-vision-camera';

export function useCameraPermissions() {
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    Camera.getCameraPermissionStatus().then(status => {
      if (mounted) setHasPermission(status === 'granted');
    });
    return () => { mounted = false; };
  }, []);

  const request = useCallback(async (): Promise<boolean> => {
    const status = await Camera.requestCameraPermission();
    const granted = status === 'granted';
    setHasPermission(granted);
    return granted;
  }, []);

  return { hasPermission, request };
}
```

> ⚠️ 实现注记：v0.1 未创建此自定义 hook——直接使用 VisionCamera 内置 `useCameraPermission`（见 `CameraScreen.tsx`）。内置 hook 的 `hasPermission` 是同步 `boolean`（初始即 `getCameraPermissionStatus()==='granted'`），无 null 态；`requestPermission` 用 `useCallback` 包裹、身份稳定，`useEffect` 不会无限循环。

- [ ] **Step 3: 提交**

```bash
git add mobile-app/src/components/CreamButton.tsx mobile-app/src/hooks/useCameraPermissions.ts
git commit -m "feat(app): add CreamButton and camera permissions hook"
```

---

## Task 8: App 骨架与导航（4 Tab + 全屏相机/分析栈）

**Files:**
- Create: `mobile-app/src/navigation/AppNavigator.tsx`
- Create: `mobile-app/src/App.tsx`
- Modify: `mobile-app/index.js`
- Create: 3 个占位屏 `InstitutionScreen/GalleryScreen/ProfileScreen`

**Interfaces:**
- Produces: 完整导航树。`HomeScreen` 的"开始拍"按钮 `navigation.navigate('Camera')`；相机拍照后 `navigation.replace('Analyzing', { photoPath, device })`；分析完进 `Directions`；方向卡进 `Plans`。

- [ ] **Step 1: 写三个占位屏（合并到一个文件）**

写入 `mobile-app/src/screens/PlaceholderScreens.tsx`：

```tsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';

function Placeholder({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
    </View>
  );
}

export const InspirationScreen = () => (
  <Placeholder title="灵感" subtitle="v0.2：风格库与场景教程" />
);
export const GalleryScreen = () => (
  <Placeholder title="作品" subtitle="v0.2：你拍过的照片和方案" />
);
export const ProfileScreen = () => (
  <Placeholder title="我的" subtitle="设置、配额、反馈" />
);

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.cream, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  title: { fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink, marginBottom: spacing.s },
  subtitle: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.stone },
});
```

- [ ] **Step 2: 写导航器**

写入 `mobile-app/src/navigation/AppNavigator.tsx`：

```tsx
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Camera as CameraIcon, Sparkles, Images, User } from 'lucide-react-native';
import { colors } from '../theme/tokens';

import { HomeScreen } from '../screens/HomeScreen';
import { CameraScreen } from '../screens/CameraScreen';
import { AnalyzingScreen } from '../screens/AnalyzingScreen';
import { DirectionsScreen } from '../screens/DirectionsScreen';
import { PlansScreen } from '../screens/PlansScreen';
import { InspirationScreen, GalleryScreen, ProfileScreen } from '../screens/PlaceholderScreens';

export type RootStackParamList = {
  Tabs: undefined;
  Camera: undefined;
  Analyzing: { photoPath: string; device?: string };
  Directions: undefined;
  Plans: { directionId: string; directionTitle: string };
};

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator<RootStackParamList>();

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: colors.hujia,
        tabBarInactiveTintColor: colors.stone,
        tabBarStyle: {
          backgroundColor: colors.cream,
          borderTopColor: colors.line,
          height: 82,
          paddingBottom: 20,
        },
        tabBarLabelStyle: { fontSize: 11, fontFamily: 'ui-sans-serif' },
        tabBarIcon: ({ color, size }) => {
          const icons = {
            Home: CameraIcon,
            Inspiration: Sparkles,
            Gallery: Images,
            Profile: User,
          } as const;
          const Icon = icons[route.name as keyof typeof icons] ?? CameraIcon;
          return <Icon color={color} size={size} />;
        },
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: '拍' }} />
      <Tab.Screen name="Inspiration" component={InspirationScreen} options={{ title: '灵感' }} />
      <Tab.Screen name="Gallery" component={GalleryScreen} options={{ title: '作品' }} />
      <Tab.Screen name="Profile" component={ProfileScreen} options={{ title: '我的' }} />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="Tabs" component={Tabs} />
        <Stack.Screen
          name="Camera"
          component={CameraScreen}
          options={{ presentation: 'fullScreenModal', animation: 'slide_from_bottom' }}
        />
        <Stack.Screen name="Analyzing" component={AnalyzingScreen} />
        <Stack.Screen name="Directions" component={DirectionsScreen} />
        <Stack.Screen name="Plans" component={PlansScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
```

注：`HomeScreen`/`CameraScreen` 等在后续 Task 创建。为避免编译断裂，下一步先建临时占位，再逐屏替换。

- [ ] **Step 3: 写根组件 App.tsx**

写入 `mobile-app/src/App.tsx`：

```tsx
import React, { useEffect } from 'react';
import { StatusBar } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { AppNavigator } from './navigation/AppNavigator';
import { initDb } from './storage/session';
import { colors } from './theme/tokens';

export function App() {
  useEffect(() => {
    try { initDb(); } catch (e) { console.warn('DB init failed', e); }
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar barStyle="dark-content" backgroundColor={colors.cream} />
        <AppNavigator />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
```

- [ ] **Step 4: 改 index.js 注册 App**

写入 `mobile-app/index.js`：

```js
import { AppRegistry } from 'react-native';
import { App } from './src/App';
import { name as appName } from './app.json';

AppRegistry.registerComponent(appName, () => App);
```

- [ ] **Step 5: 临时占位 Home/Camera/Analyzing/Directions/Plans 让工程先编过**

为每个屏幕先建一个最小占位（后续 Task 覆盖文件内容）。例如 `HomeScreen.tsx`：

```tsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors } from '../theme/tokens';
export function HomeScreen() {
  return <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.cream }]} />;
}
```

对 `CameraScreen/AnalyzingScreen/DirectionsScreen/PlansScreen` 各建一个相同的最小屏（组件名与导航 import 一致）。

- [ ] **Step 6: 跑起来验证导航**

```bash
cd mobile-app && npm run ios
```

Expected: 底部 4 个 Tab 出现，"拍/灵感/作品/我的"可切换，不崩溃。点"拍"现在是空白（Task 9 填）。

- [ ] **Step 7: 提交**

```bash
git add mobile-app/src/ mobile-app/index.js
git commit -m "feat(app): app shell with bottom tabs and full-screen stack"
```

---

## Task 9: 首页

**Files:**
- Create: `mobile-app/src/screens/HomeScreen.tsx`（覆盖 Task 8 占位）

**Interfaces:**
- Consumes: `CreamButton`（Task 7）、`useSessionStore`（Task 6）、`useNavigation`。
- Produces: 首页。"开始拍"按钮 `navigation.navigate('Camera')`。

- [ ] **Step 1: 实现 HomeScreen**

写入 `mobile-app/src/screens/HomeScreen.tsx`：

```tsx
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { CreamButton } from '../components/CreamButton';
import { useSessionStore } from '../store/useSessionStore';
import { getRecentSessions, type SessionRow } from '../storage/session';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../navigation/AppNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function HomeScreen() {
  const navigation = useNavigation<Nav>();
  const reset = useSessionStore(s => s.reset);
  const [recent, setRecent] = useState<SessionRow[]>([]);

  useEffect(() => {
    getRecentSessions(6).then(setRecent).catch(() => {});
  }, []);

  const start = () => {
    reset();
    navigation.navigate('Camera');
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.brand}>带拍</Text>
        <Text style={styles.slogan}>去了不会拍？带你拍。</Text>

        <View style={styles.hero}>
          <Text style={styles.heroTitle}>今天的光</Text>
          <Text style={styles.heroSub}>v0.2 接入位置与黄金时刻</Text>
        </View>

        <CreamButton title="开始拍" onPress={start} style={styles.cta} />

        {recent.length > 0 && (
          <View style={styles.recentWrap}>
            <Text style={styles.sectionTitle}>最近的方案</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {recent.map(s => {
                let title = '未命名场景';
                try {
                  const dirs = JSON.parse(s.directions_json ?? '[]');
                  title = dirs[0]?.style ?? title;
                } catch {}
                return (
                  <Pressable key={s.session_id} style={styles.recentCard}>
                    <Text style={styles.recentCardTitle} numberOfLines={2}>{title}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  content: { padding: spacing.xl, paddingBottom: spacing.xxxl },
  brand: {
    fontFamily: fonts.serif, fontSize: 40, color: colors.ink,
    marginTop: spacing.m, letterSpacing: 2,
  },
  slogan: {
    fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone,
    marginTop: spacing.xs, letterSpacing: 0.5,
  },
  hero: {
    backgroundColor: colors.paper, borderRadius: radii.card,
    padding: spacing.xl, marginTop: spacing.xxl, ...shadows.card,
  },
  heroTitle: { fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink },
  heroSub: { fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone, marginTop: spacing.s },
  cta: { marginTop: spacing.xl },
  recentWrap: { marginTop: spacing.xxxl },
  sectionTitle: {
    fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone,
    letterSpacing: 1, textTransform: 'uppercase', marginBottom: spacing.m,
  },
  recentCard: {
    width: 140, height: 180, backgroundColor: colors.paper,
    borderRadius: radii.card, padding: spacing.m, marginRight: spacing.m,
    justifyContent: 'flex-end', ...shadows.card,
  },
  recentCardTitle: { fontFamily: fonts.serif, fontSize: fontSizes.body, color: colors.ink },
});
```

- [ ] **Step 2: 真机/模拟器验证**

```bash
cd mobile-app && npm run ios
```

Expected: 首页显示"带拍"宋体大标题、slogan、焙茶色"开始拍"按钮；点击进入相机（Task 10 前会是黑屏占位，不崩即可）。

- [ ] **Step 3: 提交**

```bash
git add mobile-app/src/screens/HomeScreen.tsx
git commit -m "feat(app): home screen with brand, CTA, recent sessions"
```

---

## Task 10: 相机屏（VisionCamera 拍照）

**Files:**
- Create: `mobile-app/src/screens/CameraScreen.tsx`（覆盖占位）

**Interfaces:**
- Consumes: `useCameraDevice`/`Camera`/`useCameraPermission`、`useSessionStore.setPhoto`、`DeviceInfo`。
- Produces: 取景器 + 快门。拍完照：用 `react-native-device-info` 取设备型号，`setPhoto(path)`，`navigation.replace('Analyzing', { photoPath: path, device })`。

- [ ] **Step 1: 实现 CameraScreen**

写入 `mobile-app/src/screens/CameraScreen.tsx`：

```tsx
import React, { useRef, useState, useEffect } from 'react';
import {
  View, StyleSheet, Pressable, Text, Alert,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Camera, useCameraDevice, useCameraPermission, type PhotoFile,
} from 'react-native-vision-camera';
import DeviceInfo from 'react-native-device-info';
import { X, Circle, CameraFlip } from 'lucide-react-native';
import { colors, spacing, fonts } from '../theme/tokens';
import { useSessionStore } from '../store/useSessionStore';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Camera'>;

export function CameraScreen() {
  const navigation = useNavigation<Nav>();
  const device = useCameraDevice('back');
  const { hasPermission, requestPermission } = useCameraPermission();
  const cameraRef = useRef<Camera>(null);
  const setPhoto = useSessionStore(s => s.setPhoto);
  const [taking, setTaking] = useState(false);
  const [position, setPosition] = useState<'back' | 'front'>('back');
  const currentDevice = useCameraDevice(position);

  useEffect(() => {
    if (hasPermission === false) requestPermission();
  }, [hasPermission, requestPermission]);

  const takePhoto = async () => {
    if (!cameraRef.current || taking) return;
    setTaking(true);
    try {
      const photo: PhotoFile = await cameraRef.current.takePhoto({
        flash: 'off',
        enableShutterSound: true,
        // v0.1 用默认平衡；v0.2 加 photoQualityBalance: 'quality'
      });
      setPhoto(photo.path);
      const model = DeviceInfo.getModel(); // e.g. "iPhone 15 Pro"
      navigation.replace('Analyzing', {
        photoPath: photo.path,
        device: model,
      });
    } catch (e: any) {
      Alert.alert('拍照失败', e?.message ?? '请重试');
    } finally {
      setTaking(false);
    }
  };

  if (hasPermission === false) {
    return (
      <SafeAreaView style={styles.permWrap}>
        <Text style={styles.permText}>需要相机权限才能带拍</Text>
        <Pressable onPress={requestPermission} style={styles.permBtn}>
          <Text style={styles.permBtnText}>去开启</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  if (currentDevice == null) {
    return <View style={styles.black} />;
  }

  return (
    <View style={styles.container}>
      <Camera
        ref={cameraRef}
        style={StyleSheet.absoluteFill}
        device={currentDevice}
        isActive={true}
        photo={true}
        enableZoomGesture={false}
      />
      <SafeAreaView style={styles.ui} edges={['top', 'bottom']}>
        <View style={styles.topBar}>
          <Pressable onPress={() => navigation.goBack()} hitSlop={12} accessibilityLabel="关闭">
            <X color={colors.guideWhite} size={26} />
          </Pressable>
          <Pressable
            onPress={() => setPosition(p => (p === 'back' ? 'front' : 'back'))}
            hitSlop={12} accessibilityLabel="切换摄像头"
          >
            <CameraFlip color={colors.guideWhite} size={24} />
          </Pressable>
        </View>

        <View style={styles.bottomBar}>
          <Pressable
            onPress={takePhoto}
            disabled={taking}
            accessibilityRole="button"
            accessibilityLabel="拍照"
            style={({ pressed }) => [styles.shutter, pressed && styles.shutterPressed]}
          >
            <Circle color={colors.guideWhite} size={72} strokeWidth={3} fill="none" />
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.viewfinderBg },
  black: { flex: 1, backgroundColor: colors.viewfinderBg },
  ui: { flex: 1, justifyContent: 'space-between' },
  topBar: {
    flexDirection: 'row', justifyContent: 'space-between',
    padding: spacing.l,
  },
  bottomBar: { alignItems: 'center', paddingBottom: spacing.xl },
  shutter: {
    width: 84, height: 84, borderRadius: 42,
    alignItems: 'center', justifyContent: 'center',
  },
  shutterPressed: { opacity: 0.7, transform: [{ scale: 0.96 }] },
  permWrap: {
    flex: 1, backgroundColor: colors.cream,
    alignItems: 'center', justifyContent: 'center', padding: spacing.xl,
  },
  permText: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink, marginBottom: spacing.l },
  permBtn: {
    backgroundColor: colors.hujia, paddingHorizontal: spacing.xl,
    paddingVertical: spacing.m, borderRadius: 16,
  },
  permBtnText: { color: colors.paper, fontFamily: fonts.sans, fontWeight: '600' },
});
```

注意：VisionCamera v4 的权限 hook 在不同小版本可能叫 `useCameraPermission`（v4.6+）或需手动调 `Camera.getCameraPermissionStatus`。若编译报 hook 不存在，改用 Task 7 的 `useCameraPermissions` + `Camera.requestCameraPermission()` 手动管理。这是已知的 v4 API 微调点，v0.1 真机验证时确认。

- [ ] **Step 2: 真机验证（必须真机，模拟器无相机）**

```bash
cd mobile-app && npm run ios -- --device
```

Expected: 取景器出现后置画面；快门可拍；拍完跳到"分析中"屏（Task 11 前是占位黑屏，不崩）。照片是临时文件，路径写入 store。

- [ ] **Step 3: 提交**

```bash
git add mobile-app/src/screens/CameraScreen.tsx
git commit -m "feat(app): camera screen with VisionCamera capture"
```

---

## Task 11: 分析中屏（SSE 阶段进度）

**Files:**
- Create: `mobile-app/src/screens/AnalyzingScreen.tsx`（覆盖占位）
- Create: `mobile-app/src/components/PhaseIndicator.tsx`

**Interfaces:**
- Consumes: `readPhotoAsBase64` + `analyzeStream`（Task 5）、`useSessionStore`、`saveSession`（Task 6）。
- Produces: 进入后自动读照片→base64→`analyzeStream`，随事件更新阶段文字；`complete` 后存会话并 `navigation.replace('Directions')`；`error` 弹 Alert 并可返回。

- [ ] **Step 1: 实现 PhaseIndicator**

写入 `mobile-app/src/components/PhaseIndicator.tsx`：

```tsx
import React, { useEffect } from 'react';
import { View, Text, StyleSheet, Easing } from 'react-native';
import { Canvas, Line, mix } from '@shopify/react-native-skia';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';

const PHASES = [
  '正在看你的照片…',
  '识别光线和场景…',
  '想几个拍法…',
  '整理成方案…',
];

export function PhaseIndicator({ phaseIndex }: { phaseIndex: number }) {
  // 进度条宽度随 phaseIndex 0..3 变化
  const progress = Math.min(phaseIndex + 1, PHASES.length) / PHASES.length;
  const message = PHASES[Math.min(phaseIndex, PHASES.length - 1)];

  return (
    <View style={styles.wrap}>
      <Canvas style={styles.bar}>
        <Line p1={{ x: 0, y: 4 }} p2={{ x: 280, y: 4 }} color={colors.line} strokeWidth={4} />
        <Line
          p1={{ x: 0, y: 4 }}
          p2={{ x: 280 * progress, y: 4 }}
          color={colors.hujia}
          strokeWidth={4}
        />
      </Canvas>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },
  bar: { width: 280, height: 12 },
  text: {
    fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink,
    marginTop: spacing.xl, textAlign: 'center',
  },
});
```

- [ ] **Step 2: 实现 AnalyzingScreen**

写入 `mobile-app/src/screens/AnalyzingScreen.tsx`：

```tsx
import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image } from 'react-native';
import { colors, fonts, fontSizes, spacing, radii } from '../theme/tokens';
import { PhaseIndicator } from '../components/PhaseIndicator';
import { readPhotoAsBase64, analyzeStream } from '../api/client';
import { useSessionStore } from '../store/useSessionStore';
import { saveSession } from '../storage/session';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RouteProp } from '@react-navigation/native';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Analyzing'>;
type Rt = RouteProp<RootStackParamList, 'Analyzing'>;

export function AnalyzingScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Rt>();
  const { photoPath, device } = route.params;

  const setExif = useSessionStore(s => s.setExif);
  const setVision = useSessionStore(s => s.setVision);
  const setDirections = useSessionStore(s => s.setDirections);
  const [phase, setPhase] = useState(0);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;
    (async () => {
      try {
        const base64 = await readPhotoAsBase64(photoPath);
        // ⚠️ 不要解构 Promise 的 sessionId——它在 complete 事件才 resolve，
        // 而 directions_ready 先到，解构的 sessionId 会是 undefined（TDZ 隐患）。
        // 正确做法：从 e.data.session_id 取（后端 directions_ready 事件自带）。
        await analyzeStream(
          { photoBase64: base64, device },
          (e) => {
            if (cancelled) return;
            switch (e.event) {
              case 'progress':
                // 后端 phase: exif/vision/directions
                setPhase(p => ({ exif: 0, vision: 1, directions: 2, plans: 3 } as any)[e.phase] ?? p);
                break;
              case 'exif_ready':
                setPhase(1); setExif(e.data); break;
              case 'vision_ready':
                setPhase(2); setVision(e.data); break;
              case 'directions_ready': {
                setPhase(3);
                const sessionId = e.data.session_id;   // ⚠️ 从事件数据取，不是 Promise resolve 值
                setDirections(e.data.directions ?? [], sessionId);
                // 落库
                saveSession({
                  session_id: sessionId,
                  photo_path: photoPath,
                  device: device ?? null,
                  exif_json: JSON.stringify(useSessionStore.getState().exif ?? {}),
                  vision_json: JSON.stringify(useSessionStore.getState().vision ?? {}),
                  directions_json: JSON.stringify(e.data.directions ?? []),
                  created_at: Date.now(),
                }).catch(() => {});
                setTimeout(() => {
                  if (!cancelled) navigation.replace('Directions');
                }, 600);
                break;
              }
              case 'complete':
                // 后端 complete 也带 session_id；通常 directions_ready 已导航
                break;
              case 'error':
                Alert.alert('分析失败', e.data.message, [
                  { text: '返回', onPress: () => navigation.goBack() },
                ]);
                break;
            }
          },
        );
      } catch (e: any) {
        if (!cancelled) {
          Alert.alert('网络错误', e?.message ?? '请重试', [
            { text: '返回', onPress: () => navigation.goBack() },
          ]);
        }
      }
    })();

    return () => { cancelled = true; };
  }, [photoPath, device, navigation, setExif, setVision, setDirections]);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <Image
          source={{ uri: `file://${photoPath.replace('file://', '')}` }}
          style={styles.thumb}
          resizeMode="cover"
        />
        <View style={styles.indicatorWrap}>
          <PhaseIndicator phaseIndex={phase} />
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  thumb: {
    width: 200, height: 260, borderRadius: radii.card,
    marginBottom: spacing.xxxl, backgroundColor: colors.mist,
  },
  indicatorWrap: { width: '100%', alignItems: 'center' },
});
```

- [ ] **Step 3: 真机端到端验证**

确保后端 `https://guidepic.cn/app/analyze` 已部署（Task 3 的代码需要在服务器跑），或临时把 `.env` 的 `API_BASE_URL` 指向你 Mac 的局域网 IP（手机和 Mac 同一网络，`python server.py` 监听 0.0.0.0:8888）。

```bash
cd mobile-app && npm run ios -- --device
```

Expected: 拍完照 → 看到缩略图 + 焙茶色进度条 + 阶段文字依次变化（约 30-90 秒）→ 自动跳到方向屏（Task 12 前是占位）。若卡在某阶段，看 Metro console 的 SSE error message。

- [ ] **Step 4: 部署后端到线上（如需要）**

Task 3 改了 server.py，线上验证需要部署：

```bash
cd "/Users/rabbit/Claude code/Photography/mobile-tester"
ssh root@47.82.117.17 "cd /opt/daipai && git pull && pip install -r requirements.txt && systemctl restart daipai"
```

（凭据见记忆 `server-deploy-credentials`。）部署后用 curl 验证线上 `/app/analyze`（Task 3 Step 3 的命令换域名）。

- [ ] **Step 5: 提交**

```bash
git add mobile-app/src/screens/AnalyzingScreen.tsx mobile-app/src/components/PhaseIndicator.tsx
git commit -m "feat(app): analyzing screen with streaming phase progress"
```

---

## Task 12: 三方向屏（杂志卡轮播）

**Files:**
- Create: `mobile-app/src/components/DirectionCard.tsx`
- Create: `mobile-app/src/screens/DirectionsScreen.tsx`（覆盖占位）

**Interfaces:**
- Consumes: `useSessionStore.directions`、`useNavigation`。
- Produces: 横向 scroll-snap 三方向卡，每张显示 slot 标签、style（宋体大字）、style_promise、光线/设备标注；"看 N 套方案"按钮 `navigation.navigate('Plans', { directionId, directionTitle })`。

- [ ] **Step 1: 实现 DirectionCard**

写入 `mobile-app/src/components/DirectionCard.tsx`：

```tsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { CreamButton } from './CreamButton';
import type { Direction } from '../api/types';

const SLOT_META = {
  now:      { label: '🟢 现在就拍', color: colors.now,      en: 'RIGHT NOW' },
  best:     { label: '🔥 最出片',   color: colors.best,     en: 'THE SHOT' },
  creative: { label: '✨ 最大胆',   color: colors.creative, en: 'BOLD MOVE' },
} as const;
// ⚠️ 设计自洽问题（与 Global Constraints 的"AI slop 禁令：不用 emoji 当图标"冲突）：
// 标签里的 🟢🔥✨ 是文案不是图标，暂可接受；后续应换 Lucide 图标 + 纯文字，保持与禁令一致。

export function DirectionCard({
  direction,
  onSeePlans,
}: {
  direction: Direction;
  onSeePlans: () => void;
}) {
  const meta = SLOT_META[direction.id] ?? SLOT_META.now;   // ⚠️ 用 direction.id（后端字段），不是 slot
  return (
    <View style={styles.card}>
      <View style={[styles.badge, { backgroundColor: `${meta.color}22` }]}>
        <Text style={[styles.badgeText, { color: meta.color }]}>{meta.label}</Text>
      </View>

      <Text style={styles.en}>{meta.en}</Text>
      <Text style={styles.title}>{direction.style}</Text>
      <Text style={styles.promise}>{direction.style_promise}</Text>

      {direction.reason ? (
        <Text style={styles.reason}>{direction.reason}</Text>
      ) : null}

      <View style={styles.notes}>
        {direction.light_annotation ? (
          <View style={styles.noteRow}>
            <Text style={styles.noteLabel}>光线</Text>
            <Text style={styles.noteVal}>{direction.light_annotation}</Text>
          </View>
        ) : null}
        {direction.device_annotation ? (
          <View style={styles.noteRow}>
            <Text style={styles.noteLabel}>设备</Text>
            <Text style={styles.noteVal}>{direction.device_annotation}</Text>
          </View>
        ) : null}
      </View>

      <CreamButton
        title={`看 ${direction.plans?.length ?? '?'} 套方案`}
        onPress={onSeePlans}
        style={styles.btn}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: 320, minHeight: 480, backgroundColor: colors.paper,
    borderRadius: radii.card, padding: spacing.xl,
    marginHorizontal: spacing.m, ...shadows.card, justifyContent: 'space-between',
  },
  badge: { alignSelf: 'flex-start', paddingHorizontal: spacing.m, paddingVertical: spacing.xs, borderRadius: radii.tag },
  badgeText: { fontFamily: fonts.sans, fontSize: fontSizes.caption, fontWeight: '600' },
  en: {
    fontFamily: fonts.serif, fontStyle: 'italic', fontSize: fontSizes.caption,
    color: colors.gold, letterSpacing: 2, marginTop: spacing.l,
  },
  title: { fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink, marginTop: spacing.xs },
  promise: {
    fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink,
    lineHeight: 30, marginTop: spacing.m,
  },
  reason: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.stone, marginTop: spacing.m, lineHeight: 24 },
  notes: { marginTop: spacing.l, gap: spacing.s },
  noteRow: { flexDirection: 'row', gap: spacing.m },
  noteLabel: { fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone, width: 40 },
  noteVal: { flex: 1, fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.ink },
  btn: { marginTop: spacing.xl, width: '100%' },
});
```

- [ ] **Step 2: 实现 DirectionsScreen**

写入 `mobile-app/src/screens/DirectionsScreen.tsx`：

```tsx
import React from 'react';
import {
  View, Text, StyleSheet, ScrollView, Dimensions,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';
import { DirectionCard } from '../components/DirectionCard';
import { useSessionStore } from '../store/useSessionStore';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

type Nav = NativeStackNavigationProp<RootStackParamList>;
const { width } = Dimensions.get('window');

export function DirectionsScreen() {
  const navigation = useNavigation<Nav>();
  const directions = useSessionStore(s => s.directions);

  if (!directions.length) {
    return (
      <SafeAreaView style={styles.safe}>
        <Text style={styles.empty}>没有生成方向，请返回重拍。</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <Text style={styles.heading}>三个拍法</Text>
      <Text style={styles.subheading}>左右滑动挑一个</Text>
      <ScrollView
        horizontal
        pagingEnabled
        snapToInterval={336}            // card 320 + margin 16
        decelerationRate="fast"
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scroll}
      >
        {directions.map(d => (
          <DirectionCard
            key={d.id || d.slot}
            direction={d}
            onSeePlans={() => navigation.navigate('Plans', {
              directionId: d.id || d.slot,
              directionTitle: d.style,
            })}
          />
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  heading: {
    fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink,
    paddingHorizontal: spacing.xl, paddingTop: spacing.m,
  },
  subheading: {
    fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone,
    paddingHorizontal: spacing.xl, marginBottom: spacing.xl,
  },
  scroll: { paddingHorizontal: (width - 320) / 2 - spacing.m, paddingVertical: spacing.l },
  empty: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.stone, textAlign: 'center', marginTop: 100 },
});
```

- [ ] **Step 3: 真机验证**

Expected: 三屏横向卡片，焙茶/绿/紫色标签，宋体大标题，点"看 N 套方案"进入方案屏（Task 13 前是占位）。

- [ ] **Step 4: 提交**

```bash
git add mobile-app/src/components/DirectionCard.tsx mobile-app/src/screens/DirectionsScreen.tsx
git commit -m "feat(app): directions screen with magazine-style cards"
```

---

## Task 13: Skia 方案标注 + 方案列表屏

**Files:**
- Create: `mobile-app/src/components/SketchAnnotation.tsx`
- Create: `mobile-app/src/components/PlanCard.tsx`
- Create: `mobile-app/src/screens/PlansScreen.tsx`（覆盖占位）

**Interfaces:**
- Consumes: `fetchPlans`（Task 5）、`useSessionStore`（photoPath/sessionId/device）、`Plan` 类型。
- Produces: 进入时按 directionId 拉方案（loading）；垂直列表，每张方案卡显示原图 + Skia 标注 + subject/shooter/gear/enhance 四段 + result/why。v0.1 不跳相机（v0.2 才有"用这个方案拍"）。

- [ ] **Step 1: 实现 SketchAnnotation（Skia 画 subject/shooter 标注）**

写入 `mobile-app/src/components/SketchAnnotation.tsx`：

```tsx
import React from 'react';
import { View, StyleSheet } from 'react-native';
import {
  Canvas, Rect, Circle, Line, Text as SkText, useFont,
} from '@shopify/react-native-skia';
import { colors } from '../theme/tokens';
import type { PlanAnnotation } from '../api/types';

interface Props {
  width: number;
  height: number;
  annotations?: PlanAnnotation[];
}

/**
 * 在照片上画方案标注。坐标是 0-1 归一化，乘以容器宽高。
 * subject → 暖金矩形框；shooter → 暖金圆点 + 十字。
 * 用极淡描边，不挡脸。
 */
export function SketchAnnotation({ width, height, annotations = [] }: Props) {
  return (
    <Canvas style={[StyleSheet.absoluteFill, { width, height }]}>
      {annotations.map((a, i) => {
        const cx = a.x * width;
        const cy = a.y * height;
        if (a.type === 'subject') {
          return (
            <Rect
              key={i}
              x={cx - 40} y={cy - 60} width={80} height={120}   // ⚠️ Skia 2.x 用 width/height，不是 w/h
              color={colors.guideGold}
              style="stroke"
              strokeWidth={1.5}
              opacity={0.8}
            />
          );
        }
        return (
          <React.Fragment key={i}>
            <Circle cx={cx} cy={cy} r={8} color={colors.guideGold} style="stroke" strokeWidth={1.5} />
            <Line p1={{ x: cx - 14, y: cy }} p2={{ x: cx + 14, y: cy }} color={colors.guideGold} strokeWidth={1.5} />
            <Line p1={{ x: cx, y: cy - 14 }} p2={{ x: cx, y: cy + 14 }} color={colors.guideGold} strokeWidth={1.5} />
          </React.Fragment>
        );
      })}
    </Canvas>
  );
}
```

注意：Skia 的 `Text` 需字体，v0.1 标注只用图形不画字，避免字体加载复杂度。`useFont` 在 v0.2 加 label 时用。

- [ ] **Step 2: 实现 PlanCard**

写入 `mobile-app/src/components/PlanCard.tsx`：

```tsx
import React, { useState } from 'react';
import { View, Text, StyleSheet, Image, Dimensions } from 'react-native';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { SketchAnnotation } from './SketchAnnotation';
import type { Plan } from '../api/types';

const IMG_W = Dimensions.get('window').width - spacing.xl * 2;
const IMG_H = IMG_W * 1.3;

export function PlanCard({ plan, photoPath }: { plan: Plan; photoPath: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <View style={styles.card}>
      <View style={[styles.imgWrap, { width: IMG_W, height: IMG_H }]}>
        <Image
          source={{ uri: `file://${photoPath.replace('file://', '')}` }}
          style={StyleSheet.absoluteFill}
          resizeMode="cover"
          onLoad={() => setLoaded(true)}
        />
        {loaded && <SketchAnnotation width={IMG_W} height={IMG_H} annotations={plan.annotations} />}
      </View>

      <Text style={styles.name}>{plan.name}</Text>
      {(plan.shot_size || plan.angle) && (
        <Text style={styles.tags}>
          {[plan.shot_size, plan.angle].filter(Boolean).join(' · ')}
        </Text>
      )}

      <Section label="被拍摄者" text={plan.subject} />
      <Section label="摄影师" text={plan.shooter} />
      <Section label="设备调试" text={plan.gear} />
      <Section label="现场增色" text={plan.enhance} />
      <Section label="画面效果" text={plan.result} gold />
      {plan.why ? <Section label="为什么好看" text={plan.why} muted /> : null}
    </View>
  );
}

function Section({ label, text, gold, muted }: { label: string; text: string; gold?: boolean; muted?: boolean }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionLabel}>{label}</Text>
      <Text style={[
        styles.sectionText,
        gold && styles.goldText,
        muted && styles.mutedText,
      ]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.paper, borderRadius: radii.card,
    padding: spacing.l, marginBottom: spacing.xl, ...shadows.card,
  },
  imgWrap: { borderRadius: radii.input, overflow: 'hidden', backgroundColor: colors.mist },
  name: { fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink, marginTop: spacing.l },
  tags: { fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.gold, marginTop: spacing.xs },
  section: { marginTop: spacing.m },
  sectionLabel: {
    fontFamily: fonts.sans, fontSize: fontSizes.caption, color: colors.stone,
    letterSpacing: 1, textTransform: 'uppercase', marginBottom: 2,
  },
  sectionText: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.ink, lineHeight: 24 },
  goldText: { color: colors.hujia, fontFamily: fonts.serif, fontSize: fontSizes.body },
  mutedText: { color: colors.stone, fontStyle: 'italic' },
});
```

- [ ] **Step 3: 实现 PlansScreen**

写入 `mobile-app/src/screens/PlansScreen.tsx`：

```tsx
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';
import { PlanCard } from '../components/PlanCard';
import { fetchPlans } from '../api/client';
import { useSessionStore } from '../store/useSessionStore';
import type { Plan } from '../api/types';
import type { RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../navigation/AppNavigator';

type Rt = RouteProp<RootStackParamList, 'Plans'>;

export function PlansScreen() {
  const { directionId, directionTitle } = useRoute<Rt>().params;
  const sessionId = useSessionStore(s => s.sessionId);
  const device = useSessionStore(s => s.device);
  const photoPath = useSessionStore(s => s.photoPath);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!sessionId) { setError('会话已过期'); setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const list = await fetchPlans({ sessionId, directionId, device: device ?? undefined });
      setPlans(list);
    } catch (e: any) {
      setError(e?.message ?? '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <Text style={styles.title}>{directionTitle}</Text>
      <Text style={styles.sub}>{plans.length > 0 ? `${plans.length} 套方案` : '加载方案中…'}</Text>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.hujia} size="large" /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.err}>{error}</Text>
          <Text style={styles.retry} onPress={load}>点此重试</Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.hujia} />}
        >
          {photoPath && plans.map((p, i) => (
            <PlanCard key={i} plan={p} photoPath={photoPath} />
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  title: { fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink, paddingHorizontal: spacing.xl, paddingTop: spacing.m },
  sub: { fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone, paddingHorizontal: spacing.xl, marginBottom: spacing.l },
  list: { padding: spacing.xl, paddingBottom: spacing.xxxl },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  err: { fontFamily: fonts.sans, color: colors.danger, marginBottom: spacing.m },
  retry: { fontFamily: fonts.sans, color: colors.hujia, textDecorationLine: 'underline' },
});
```

- [ ] **Step 4: 真机验证完整闭环**

```bash
cd mobile-app && npm run ios -- --device
```

走完全流程：首页 → 开始拍 → 拍照 → 分析（进度条）→ 三方向 → 点一个方向 → 方案列表（照片上有金色标注框、四段文字）。这是 v0.1 的验收。

若 `fetchPlans` 返回结构字段名不对，用真机 console 打 `json`，修正 `client.ts` 的 `fetchPlans` 返回解析（以 server.py `analyze_plans` 实际返回为准）。

- [ ] **Step 5: 提交**

```bash
git add mobile-app/src/components/SketchAnnotation.tsx mobile-app/src/components/PlanCard.tsx mobile-app/src/screens/PlansScreen.tsx
git commit -m "feat(app): plans list with Skia annotations on photo"
```

---

## Task 14: v0.1 验收打磨与 README

**Files:**
- Create: `mobile-app/README.md`
- Modify: 任何真机测试中发现的小问题

- [ ] **Step 1: 真机走查清单**

在真机（至少一台 iPhone 13 或更新）上逐项确认：

- [ ] 首次启动弹相机权限，拒绝后有引导开启
- [ ] 首页品牌、按钮、Tab 视觉符合奶油风（无紫粉、无 emoji 图标）
- [ ] 拍照后取景器不残留、不黑屏
- [ ] 弱网（可在 Mac 用 Network Link Conditioner）下 SSE 有错误提示，不卡死
- [ ] 分析失败可返回重拍，不崩
- [ ] 三方向卡片横滑流畅，文字不溢出
- [ ] 方案列表下拉刷新可用
- [ ] 前后台切换再回来不白屏（相机 isActive 处理）
- [ ] 所有可点元素 ≥44pt

- [ ] **Step 2: 修真机发现的 bug**

每个 bug 一个 commit。常见项：
- VisionCamera `useCameraPermission` 若该版本不存在，改用 `Camera.getCameraPermissionStatus()` + 手动 state（已在 Task 10 注释）。
- 若 `/analyze/plans` 返回字段名与 `Plan` 类型不符，在 `client.ts` 加映射层。
- Skia `Rect`/`Circle` 在旧版 Skia 的 prop 名可能是 `r`/`width`（本计划用 v1.5 API：`w`/`h`）。按装到的实际版本调整。

- [ ] **Step 3: 写 README**

写入 `mobile-app/README.md`：

```markdown
# 带拍 APP（Daipai）

AI 拍照灵感指南。v0.1 技术原型：iOS 真机跑通"拍 → AI 分析 → 三方向 → 方案"闭环。

## 技术栈

- React Native 0.76（New Architecture），iOS only（v0.1）
- react-native-vision-camera v4 —— 原生相机
- @shopify/react-native-skia —— 叠加层/标注/后期（后期 v0.3）
- react-native-sse —— 流式 AI 事件
- react-native-quick-sqlite —— 会话缓存
- zustand —— 状态
- 后端：`../mobile-tester/`（Flask，零改造，新增 /app/analyze）

## 运行

\`\`\`bash
npm install
cd ios && pod install && cd ..
cp .env.example .env   # 填 API_BASE_URL
npm run ios -- --device   # 相机需真机
\`\`\`

## 路线图

- v0.1（当前）：拍→AI→方向→方案闭环
- v0.2：方案叠加进取景器（构图框/EV/焦段吸附）
- v0.3：非破坏性后期编辑 + ProRAW
- v1.0：鉴权/反馈同步/上架
- 安卓在 v1.0 后启动（代码已用跨端库）
```

- [ ] **Step 4: 最终提交**

```bash
git add mobile-app/README.md
git commit -m "docs(app): v0.1 README and acceptance checklist"
```

---

## 验收标准（v0.1 完成的定义）

1. iPhone 真机从首页到方案列表的完整链路可走通，无崩溃。
2. 拍照 → AI 分析（SSE 四阶段可视）→ 三方向卡 → 方案列表（含 Skia 金色标注）。
3. 视觉风格统一在奶油胶片杂志 token 之下，无硬编码颜色、无 emoji 图标、无紫粉渐变。
4. 后端 `/app/analyze` 线上可用，现有 Web 端 `/analyze` 不受影响。
5. 所有纯逻辑（SSE 解析、token）有单测且通过。
6. 代码全部在 `mobile-app/`，与 `mobile-tester/` 隔离；后端只新增一个文件段。
7. 至少一台 iPhone 真机走查清单全过。

---

## v0.2 – v1.0 路线图（待 v0.1 验证后细化为各自计划）

> 不在本计划内逐任务展开——每个里程碑单独写 plan，因为 v0.1 的真机验证结果会显著影响它们的技术选型（尤其 Skia 叠加层性能）。

| 里程碑 | 范围 | 预估 |
|---|---|---|
| **v0.2 方案进相机** | Skia 取景器叠加层（subject 框/三分线/EV 刻度）、方案卡浮层、焦段滚轮磁力吸附（haptics）、过曝 zebra、水平/角度引导、拍后对比、手动控制基础（EV/焦段/WB）、端侧人脸/亮度（VisionCamera frame processor）、思源宋体打包 | 4-6 周 |
| **v0.3 基础后期** | 非破坏性编辑栈 + Skia ColorMatrix 调节面板（曝光/对比/高光阴影/色温/饱和）、15 胶片预设、方案 quick_edit 落地、iOS ProRAW 解码桥接、导出 JPEG/HEIC、作品库 | 4-6 周 |
| **v1.0 上架** | Apple Sign In + JWT、配额/反馈/拍摄参数回流 `/app/sync`、Sentry 崩溃监控、TestFlight、隐私合规、应用商店素材、iOS App Store 上架 | 2-3 周 |

技术验证点（v0.1 期间就要留意，决定 v0.2 可行性）：
- Skia 在相机预览上叠加的帧率（目标 60fps，若掉帧则 v0.2 部分叠加层下沉原生）。
- VisionCamera frame processor 在 JS 线程跑亮度直方图的耗时（目标 <50ms/帧）。
- iOS 不同机型（13/15/17 Pro）的相机 API 差异。

---

## 风险与对策（v0.1 专属）

| 风险 | 对策 |
|---|---|
| VisionCamera v4 权限/拍照 API 在小版本间有差异 | Task 10 注释已给 fallback；真机第一步先验证 `takePhoto` |
| Skia v1.5 的 shape prop 名（`w/h` vs `width/height`） | Task 14 留了按实际版本调整的步骤 |
| `react-native-sse` 与 RN 0.76 新架构兼容性 | 若有冲突，回退到 `@microsoft/fetch-event-source`；SSE 解析器是纯函数，换库不影响业务 |
| 本地无 Xcode 导致 Task 1 卡住 | Step 1 明确要求先装 Xcode；CLI 工具不含 iOS SDK |
| 后端服务器未部署 `/app/analyze` | Task 11 Step 4 给出部署命令；本地调试可用 Mac 局域网 IP |
| 大照片 base64 上传慢 | VisionCamera 默认输出 1080p 量级，base64 约 1-3MB，可接受；v0.2 再考虑设备端压缩 |
