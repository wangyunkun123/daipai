#!/bin/bash
# 直出相机 · 移动端测试工具启动脚本
# 自动建立 ngrok 公网隧道，手机在任何地方都能访问

cd "$(dirname "$0")"

cleanup() {
    echo ""
    echo "正在关闭..."
    [ -n "$SERVER_PID" ] && kill $SERVER_PID 2>/dev/null
    [ -n "$NG_PID" ] && kill $NG_PID 2>/dev/null
    echo "已停止"
    exit 0
}
trap cleanup INT TERM

# ── 检查依赖 ──
if [ -z "$DOUBAO_API_KEY" ]; then
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
        echo "✅ 已加载 .env"
    fi
fi

if [ -z "$DOUBAO_API_KEY" ]; then
    echo "❌ 未设置 DOUBAO_API_KEY"
    echo "  echo 'DOUBAO_API_KEY=你的密钥' > .env"
    exit 1
fi

if ! command -v ngrok &> /dev/null; then
    echo "❌ 未安装 ngrok"
    echo "  brew install ngrok"
    exit 1
fi

# ── 启动 Flask ──
echo "🔧 启动本地服务器..."
python3 server.py &
SERVER_PID=$!
sleep 2

if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ 服务器启动失败"
    exit 1
fi

# ── 启动 ngrok 隧道 ──
echo "🌐 建立 ngrok 公网隧道..."
ngrok http 8888 --log=stdout > /tmp/zhichu_ngrok.log 2>&1 &
NG_PID=$!

PUBLIC_URL=""
for i in $(seq 1 10); do
    sleep 1
    PUBLIC_URL=$(curl -s --max-time 2 http://localhost:4040/api/tunnels 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" 2>/dev/null)
    [ -n "$PUBLIC_URL" ] && break
done

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "127.0.0.1")

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       直出相机 · 移动端测试工具               ║"
echo "║                                              ║"
if [ -n "$PUBLIC_URL" ]; then
    echo "║  🌐 公网访问（手机在任何地方都可用）:         ║"
    echo "║  → $PUBLIC_URL   ║"
else
    echo "║  ⚠️  公网隧道建立失败，使用局域网模式          ║"
fi
echo "║                                              ║"
echo "║  🏠 局域网（同WiFi更快）:                     ║"
echo "║  → http://${LOCAL_IP}:8888                  ║"
echo "║                                              ║"
echo "║  📸 使用: 拍照→上传→等3分钟→看方案→拍         ║"
echo "║  🛑 Ctrl+C 停止                              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

wait $SERVER_PID
