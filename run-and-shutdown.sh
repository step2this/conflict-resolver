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

# Only shut down if no one is logged in (SSH sessions, etc.)
# Also skip if a file /tmp/no-shutdown exists (manual override)
if [ -f /tmp/no-shutdown ]; then
    echo "Shutdown skipped: /tmp/no-shutdown exists"
elif who | grep -q .; then
    echo "Shutdown skipped: users logged in: $(who | awk '{print $1}' | sort -u | tr '\n' ' ')"
else
    echo "No users logged in — shutting down in 2 minutes (cancel with: sudo shutdown -c)"
    sudo shutdown -h +2
fi
