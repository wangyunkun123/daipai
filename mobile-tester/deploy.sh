#!/bin/bash
#
# 带拍 · 自动部署脚本 v1.0
# 放在服务器 /opt/daipai/deploy.sh
# 用法：./deploy.sh           # 手动部署
#      ./deploy.sh --auto     # 自动部署（cron/webhook 调用）
#

set -e

PROJECT_DIR="/opt/daipai"
SERVICE_NAME="daipai"
LOG_FILE="/var/log/daipai-deploy.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$PROJECT_DIR"

# ── 记录当前 commit ──
BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# ── 拉取最新代码 ──
log "Pulling latest code..."
git fetch origin main 2>&1 | tee -a "$LOG_FILE"
git reset --hard origin/main 2>&1 | tee -a "$LOG_FILE"

AFTER=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# ── 检查是否有变化 ──
if [ "$BEFORE" = "$AFTER" ] && [ "$1" = "--auto" ]; then
    log "No changes detected, skipping restart."
    exit 0
fi

log "Changes detected: $BEFORE → $AFTER"

# ── 安装依赖（如有更新）──
if [ -f "mobile-tester/requirements.txt" ]; then
    log "Checking Python dependencies..."
    cd "$PROJECT_DIR/mobile-tester"
    if [ -d "venv" ]; then
        ./venv/bin/pip install -r requirements.txt --quiet 2>&1 | tee -a "$LOG_FILE"
    else
        pip3 install -r requirements.txt --quiet 2>&1 | tee -a "$LOG_FILE"
    fi
    cd "$PROJECT_DIR"
fi

# ── 同步知识库文件（从 Claude 端）──
if [ -d ".claude/skills/daipai/knowledge" ]; then
    log "Knowledge base files present ✅"
else
    log "⚠️  Knowledge base not found in repo"
fi

# ── 触发数据库同步（应用 Claude 端的待处理数据）──
log "Applying pending Claude sync data..."
cd "$PROJECT_DIR/mobile-tester"
python3 -c "from database import apply_pending_sync; n = apply_pending_sync(); print(f'Applied {n} pending items')" 2>&1 | tee -a "$LOG_FILE"
cd "$PROJECT_DIR"

# ── 重启服务 ──
log "Restarting $SERVICE_NAME..."
systemctl restart "$SERVICE_NAME" 2>&1 | tee -a "$LOG_FILE"

# ── 验证 ──
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "✅ Deploy successful! Service is running."
else
    log "❌ Deploy failed! Service is not running. Check: journalctl -u $SERVICE_NAME -n 20"
    exit 1
fi

log "---"
