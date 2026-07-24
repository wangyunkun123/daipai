#!/bin/bash
# 直出相机 · 移动端测试工具
# 通过 Tailscale 私有网络访问——手机在任何地方都可用

cd "$(dirname "$0")"

cleanup() {
    echo ""
    echo "正在关闭..."
    [ -n "$SERVER_PID" ] && kill $SERVER_PID 2>/dev/null
    echo "已停止"
    exit 0
}
trap cleanup INT TERM

# ── API 密钥 ──
if [ -z "$DOUBAO_API_KEY" ]; then
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
fi
if [ -z "$DOUBAO_API_KEY" ]; then
    echo "❌ 未设置 DOUBAO_API_KEY"
    echo "  echo 'DOUBAO_API_KEY=你的密钥' > .env"
    exit 1
fi

# ── Tailscale IP ──
TS_IP=$(tailscale ip -4 2>/dev/null)
if [ -z "$TS_IP" ]; then
    echo "❌ 未检测到 Tailscale IP，请先运行 tailscale up 登录"
    exit 1
fi

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "127.0.0.1")

# ── 启动 ──
echo "🔧 启动本地服务器..."
python3 server.py &
SERVER_PID=$!
sleep 2

if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ 服务器启动失败"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       直出相机 · 移动端测试工具               ║"
echo "║                                              ║"
echo "║  🔒 Tailscale 私有网络（手机任何地方可用）:    ║"
echo "║  → http://${TS_IP}:8888                     ║"
echo "║                                              ║"
echo "║  📱 手机也需要安装 Tailscale 并登录同一账号    ║"
echo "║                                              ║"
echo "║  🏠 局域网（同WiFi更快）:                     ║"
echo "║  → http://${LOCAL_IP}:8888                  ║"
echo "║                                              ║"
echo "║  🛑 Ctrl+C 停止                              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

wait $SERVER_PID
