#!/bin/bash
# ==============================================================================
# Price Action Unified Strategy System — Oracle Cloud / Ubuntu Auto-Deploy Script
# ==============================================================================
set -e

echo "🚀 Starting Price Action Strategy System Deployment..."

# 1. Update OS Packages & Install Dependencies
echo "📦 Updating system packages & installing Python environment..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl iptables-persistent

# 2. Open Firewall Ports 5050 & 5051
echo "🔥 Configuring Ubuntu OS Firewall (Opening ports 5050 & 5051)..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 5050 -j ACCEPT || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 5051 -j ACCEPT || true
sudo netfilter-persistent save || true

# 3. Setup Virtual Environment
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🐍 Setting up Python Virtual Environment in $APP_DIR/venv ..."
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install kiteconnect pandas numpy flask openpyxl requests schedule yfinance

# 4. Create Systemd Service: Options Dashboard (Port 5050)
echo "⚙️ Creating Systemd Service: trading-options.service (Port 5050)..."
sudo bash -c "cat <<EOF > /etc/systemd/system/trading-options.service
[Unit]
Description=Price Action Options Trading Dashboard (Port 5050)
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR/Trade_Option
ExecStart=$APP_DIR/venv/bin/python app_option_Trade.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 5. Create Systemd Service: Stock Dashboard (Port 5051)
echo "⚙️ Creating Systemd Service: trading-stock.service (Port 5051)..."
sudo bash -c "cat <<EOF > /etc/systemd/system/trading-stock.service
[Unit]
Description=Price Action Stock Trading Dashboard (Port 5051)
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR/Trade_Stock
ExecStart=$APP_DIR/venv/bin/python app_Sock_Trade.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 6. Create Systemd Service: Export Scheduler Daemon
echo "⚙️ Creating Systemd Service: trading-export.service..."
sudo bash -c "cat <<EOF > /etc/systemd/system/trading-export.service
[Unit]
Description=Price Action Strategy Export Scheduler Daemon
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python Trade_Option/run_export_scheduler_daemon.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 7. Enable and Start Services
echo "🔄 Reloading systemd daemon & starting services..."
sudo systemctl daemon-reload
sudo systemctl enable trading-options trading-stock trading-export
sudo systemctl restart trading-options trading-stock trading-export

echo ""
echo "=============================================================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=============================================================================="
echo "📊 Services Status:"
sudo systemctl status trading-options --no-pager | head -n 5
echo "---"
sudo systemctl status trading-stock --no-pager | head -n 5
echo "---"
sudo systemctl status trading-export --no-pager | head -n 5
echo ""
echo "🌐 Options Dashboard: http://<YOUR_SERVER_IP>:5050"
echo "🌐 Stock Dashboard:   http://<YOUR_SERVER_IP>:5051"
echo "=============================================================================="
