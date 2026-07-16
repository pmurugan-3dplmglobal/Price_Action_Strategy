#!/bin/bash
#
# start_bot.sh — Launch the Trading Control Center dashboard on Oracle Cloud.
# Run via cron at market open (e.g. 9:00 AM IST).
#
set -e

PROJECT_DIR="/home/ubuntu/Prod_code_02"
VENV="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/bot_start.log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Trading Control Center" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Make sure we are in the project directory
cd "$PROJECT_DIR"

# Activate virtual environment
if [ -f "$VENV/bin/activate" ]; then
    source "$VENV/bin/activate"
    echo "[$(date)] venv activated" >> "$LOG_FILE"
else
    echo "[$(date)] ERROR: venv not found at $VENV" >> "$LOG_FILE"
    exit 1
fi

# Verify the Kite access token is fresh (daily expiry). Requires manual login.
TOKEN_STATUS=$(bash "$PROJECT_DIR/oracle/check_token.sh" || true)
echo "[$(date)] Token check: $TOKEN_STATUS" >> "$LOG_FILE"
if [ "$TOKEN_STATUS" != "TOKEN_OK" ]; then
    echo "[$(date)] WARNING: Kite token not fresh — dashboard may fail to trade." >> "$LOG_FILE"
    echo "[$(date)] Run: ssh ubuntu@<VM_PUBLIC_IP> 'cd $PROJECT_DIR && source venv/bin/activate && python Kite_Access_Token_gen.py'" >> "$LOG_FILE"
    # Uncomment the next line to ABORT launch when token is stale:
    # exit 1
fi

# Check if dashboard is already running
if pgrep -f "app.py" > /dev/null; then
    echo "[$(date)] app.py already running — skipping launch" >> "$LOG_FILE"
    exit 0
fi

# Launch the Flask dashboard in the background, detached from this shell.
# app.py binds to 0.0.0.0:5051 and spawns engine subprocesses via its UI / API.
nohup python app.py >> "$LOG_DIR/dashboard.log" 2>&1 &

echo "[$(date)] app.py launched (PID $!)" >> "$LOG_FILE"
echo "[$(date)] Dashboard should be reachable at http://<VM_PUBLIC_IP>:5051" >> "$LOG_FILE"
