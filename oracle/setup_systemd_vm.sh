#!/bin/bash
set -e

cat << 'EOF' > /etc/systemd/system/trading-options.service
[Unit]
Description=Price Action Options Trading Dashboard (Port 5050)
After=network.target

[Service]
User=opc
WorkingDirectory=/home/opc/Price_Action_Strategy
Environment=PORT=5050
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/opc/Price_Action_Strategy/venv/bin/python Trade_Option/app_option_Trade.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat << 'EOF' > /etc/systemd/system/trading-stock.service
[Unit]
Description=Price Action Stock Trading Dashboard (Port 5051)
After=network.target

[Service]
User=opc
WorkingDirectory=/home/opc/Price_Action_Strategy
Environment=PORT=5051
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/opc/Price_Action_Strategy/venv/bin/python Trade_Stock/app_Stock_Trade.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart trading-options
systemctl restart trading-stock

echo '=== TRADING-OPTIONS STATUS ==='
systemctl status trading-options --no-pager
echo '=== TRADING-STOCK STATUS ==='
systemctl status trading-stock --no-pager
