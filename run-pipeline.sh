#!/bin/bash
# Run the conflict digest pipeline. Called via SSM RunCommand.
# Instance lifecycle is managed by AWS (Lambda/EventBridge), NOT this script.

set -euo pipefail

PROJECT="/home/ubuntu/conflict-resolver"
LOG="$PROJECT/data/pipeline.log"

# Ensure PATH includes uv (needed when running via SSM as ubuntu user)
export PATH="/home/ubuntu/.local/bin:$PATH"

# Ensure data dir exists (first run or clean instance)
mkdir -p "$PROJECT/data"

exec >> "$LOG" 2>&1
echo ""
echo "=========================================="
echo "Pipeline run: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="

cd "$PROJECT"

# Source env vars
set -a
source .env
set +a

# Pull latest code
git pull --ff-only || echo "Git pull failed (non-fatal), continuing with current code"

# Run full pipeline
uv run python -m src.main

echo "Pipeline complete at $(date -u '+%H:%M:%S UTC')"
