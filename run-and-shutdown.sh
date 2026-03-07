#!/bin/bash
# Run conflict digest pipeline, sync to S3, then shut down the instance.
# Triggered on boot via cron @reboot.

set -euo pipefail

LOG="/home/ubuntu/conflict-resolver/data/pipeline.log"
PROJECT="/home/ubuntu/conflict-resolver"
UV="/home/ubuntu/.local/bin/uv"

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

# Run full pipeline
$UV run python -m src.main

echo "Pipeline complete at $(date -u '+%H:%M:%S UTC')"

# Shut down in 2 minutes (gives time to cancel if you're SSH'd in)
echo "Shutting down in 120 seconds... (cancel with: sudo shutdown -c)"
sudo shutdown -h +2
