#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
if [ "$RUN_USER" = "root" ]; then
    RUN_USER="opc"
fi

echo "Configuring systemd services for $APP_DIR (User: $RUN_USER)..."

API_KEY="$1"
API_SECRET="$2"
if [ -n "$API_KEY" ] && [ -n "$API_SECRET" ]; then
    echo "Enforcing server-specific API credentials for $RUN_USER..."
    python3 -c "
import json, os
p = '$APP_DIR/input/program_config.json'
if os.path.exists(p):
    with open(p) as f:
        d = json.load(f)
    d['api_key'] = '$API_KEY'
    d['api_secret'] = '$API_SECRET'
    with open(p, 'w') as f:
        json.dump(d, f, indent=2)
" || true
fi

if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
    chcon -R -t bin_t "$APP_DIR/venv/bin/" || true
fi

cat << EOF > /etc/systemd/system/trading-options.service
[Unit]
Description=Price Action Options Trading Dashboard (Port 5050)
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR/Trade_Option
Environment=PORT=5050
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/Trade_Option/app_option_Trade.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat << EOF > /etc/systemd/system/trading-stock.service
[Unit]
Description=Price Action Stock Trading Dashboard (Port 5051)
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR/Trade_Stock
Environment=PORT=5051
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/Trade_Stock/app_Stock_Trade.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat << EOF > /etc/systemd/system/trading-export.service
[Unit]
Description=Price Action Strategy Export Scheduler Daemon
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/Trade_Option/run_export_scheduler_daemon.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl stop trading-options trading-stock trading-export || true
pkill -f "$APP_DIR/venv/bin/python" || true
pkill -f "app_option_Trade.py" || true
pkill -f "app_Stock_Trade.py" || true
pkill -f "run_export_scheduler_daemon.py" || true
pkill -f "stock_reversal_scanner.py" || true
pkill -f "index_options_trade_engine.py" || true
pkill -f "stock_options_trade_engine.py" || true
sleep 2

systemctl daemon-reload
systemctl enable trading-options trading-stock trading-export
systemctl restart trading-options trading-stock trading-export

echo '=== TRADING-OPTIONS STATUS ==='
systemctl status trading-options --no-pager
echo '=== TRADING-STOCK STATUS ==='
systemctl status trading-stock --no-pager
echo '=== TRADING-EXPORT STATUS ==='
systemctl status trading-export --no-pager

