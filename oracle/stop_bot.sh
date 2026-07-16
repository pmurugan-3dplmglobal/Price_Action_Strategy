#!/bin/bash
#
# stop_bot.sh — Gracefully stop the Trading Control Center at market close
# (e.g. 4:00 PM IST). Stops engine subprocesses then the dashboard.
#
set -e

PROJECT_DIR="/home/ubuntu/Prod_code_02"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/bot_stop.log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping Trading Control Center" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Stop engine subprocesses first (live-trade engines)
pkill -f "live-trade/" >> "$LOG_FILE" 2>&1 && echo "[$(date)] engine subprocesses signalled" >> "$LOG_FILE" || echo "[$(date)] no engine subprocesses running" >> "$LOG_FILE"

# Give engines a moment to exit cleanly (atexit PID cleanup)
sleep 3

# Stop the Flask dashboard
pkill -f "app.py" >> "$LOG_FILE" 2>&1 && echo "[$(date)] dashboard signalled" >> "$LOG_FILE" || echo "[$(date)] no dashboard running" >> "$LOG_FILE"

echo "[$(date)] Stop sequence complete" >> "$LOG_FILE"
