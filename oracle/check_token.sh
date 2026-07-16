#!/bin/bash
#
# check_token.sh — Verify the Kite access token is fresh before market open.
#
# Zerodha tokens expire daily and require a manual browser login (2FA), so this
# script CANNOT auto-generate the token. Instead it:
#   1. Checks if input/kite_access_token.txt exists and is from today.
#   2. If stale/missing, prints instructions and exits non-zero so the
#      start_bot.sh wrapper can warn you (and optionally skip launching).
#
set -e

PROJECT_DIR="/home/ubuntu/Prod_code_02"
TOKEN_FILE="$PROJECT_DIR/input/kite_access_token.txt"
LOG_FILE="$PROJECT_DIR/output/token_check.log"
TODAY=$(date '+%Y-%m-%d')

mkdir -p "$PROJECT_DIR/output"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking Kite token freshness..." >> "$LOG_FILE"

if [ ! -f "$TOKEN_FILE" ]; then
    echo "TOKEN_MISSING"
    echo "[$(date)] Token file missing at $TOKEN_FILE" >> "$LOG_FILE"
    exit 2
fi

# Extract the generated_at date from the JSON token file
GEN_DATE=$(grep -o '"generated_at": *"[^"]*"' "$TOKEN_FILE" 2>/dev/null | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' || echo "")

if [ "$GEN_DATE" = "$TODAY" ]; then
    echo "TOKEN_OK"
    echo "[$(date)] Token is fresh ($GEN_DATE)" >> "$LOG_FILE"
    exit 0
else
    echo "TOKEN_STALE"
    echo "[$(date)] Token stale (generated $GEN_DATE, today $TODAY)" >> "$LOG_FILE"
    echo ""
    echo ">>> ACTION REQUIRED: regenerate the Kite token before market open."
    echo "    1. SSH into the VM"
    echo "    2. cd $PROJECT_DIR && source venv/bin/activate"
    echo "    3. python Kite_Access_Token_gen.py"
    echo "    4. Paste the redirect URL from your browser login."
    echo "    5. Re-run start_bot.sh (or wait for next cron)."
    exit 1
fi
