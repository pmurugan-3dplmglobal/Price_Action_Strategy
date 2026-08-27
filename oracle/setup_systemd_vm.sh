#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
if [ "$RUN_USER" = "root" ]; then
    RUN_USER="opc"
fi

echo "Configuring systemd services for $APP_DIR (User: $RUN_USER)..."

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

systemctl daemon-reload
systemctl enable trading-options trading-stock trading-export
systemctl restart trading-options trading-stock trading-export

echo '=== TRADING-OPTIONS STATUS ==='
systemctl status trading-options --no-pager
echo '=== TRADING-STOCK STATUS ==='
systemctl status trading-stock --no-pager
echo '=== TRADING-EXPORT STATUS ==='
systemctl status trading-export --no-pager

