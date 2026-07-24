#!/bin/bash
# 直出相机 · 移动端测试工具启动脚本

cd "$(dirname "$0")"

# 检查 API 密钥
if [ -z "$DOUBAO_API_KEY" ]; then
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
        echo "✅ 已从 .env 文件加载配置"
    fi
fi

if [ -z "$DOUBAO_API_KEY" ]; then
    echo "❌ 未设置 DOUBAO_API_KEY 环境变量"
    echo ""
    echo "请选择以下方式之一设置："
    echo ""
    echo "方式 1（推荐）：创建 .env 文件"
    echo "  echo 'DOUBAO_API_KEY=你的API密钥' > .env"
    echo ""
    echo "方式 2：在终端中导出"
    echo "  export DOUBAO_API_KEY='你的API密钥'"
    echo ""
    exit 1
fi

# 获取本机 IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "127.0.0.1")

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       直出相机 · 移动端测试工具           ║"
echo "║                                          ║"
echo "║  📱 手机浏览器访问:                       ║"
echo "║  → http://${LOCAL_IP}:8888              ║"
echo "║                                          ║"
echo "║  ⚠️  确保手机和电脑在同一 WiFi            ║"
echo "║  🛑 按 Ctrl+C 停止服务器                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 启动服务器
python3 server.py
