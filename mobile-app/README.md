# 带拍 APP（Daipai）

AI 拍照灵感指南。v0.1 技术原型：iOS 真机跑通"拍 → AI 分析 → 三方向 → 方案"闭环。

## 技术栈

- React Native 0.86（New Architecture），iOS 优先
- react-native-vision-camera 4.7 —— 原生相机
- @shopify/react-native-skia 2.11 —— 叠加层/标注/后期（后期 v0.3）
- react-native-sse —— 流式 AI 事件
- react-native-quick-sqlite —— 会话缓存
- zustand —— 状态
- 后端：`../mobile-tester/`（Flask，零改造，新增 `/app/analyze`）

## 运行

```bash
npm install
cd ios && pod install && cd ..
cp .env.example .env   # 填 API_BASE_URL
npm run ios -- --device   # 相机需真机
```

本地开发若后端在 Mac 上跑（`mobile-tester/server.py`，监听 0.0.0.0:8888），
把 `.env` 的 `API_BASE_URL` 改成 Mac 局域网 IP。

## 测试

```bash
npm test          # 单测（SSE 解析 / token / 契约）
npx tsc --noEmit  # 类型检查
```

## 路线图

- v0.1（当前）：拍→AI→方向→方案闭环（真机验证中）
- v0.2：方案叠加进取景器（构图框/EV/焦段吸附）+ 手动控制
- v0.3：非破坏性后期编辑 + ProRAW
- v1.0：鉴权/反馈同步/上架
- 安卓在 v1.0 后启动（代码已用跨端库）

## 设计系统

奶油胶片杂志：奶油米 `#FAF6F0` + 焙茶褐 `#B5673E` + 暖金箔 `#C9A063`。
Token 见 `src/theme/tokens.ts`，组件禁止硬编码颜色。
