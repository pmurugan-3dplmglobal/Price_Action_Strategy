#!/bin/bash
# ==============================================================================
# Price Action Unified Strategy System — Multi-OS Cloud Deployment Script
# Supports: Oracle Linux (opc), Ubuntu (ubuntu), Debian, RHEL, CentOS
# ==============================================================================
set -e

echo "🚀 Starting Price Action Strategy System Deployment..."

# 1. Detect Package Manager & Install Dependencies
if command -v apt &> /dev/null; then
    echo "📦 Detected Ubuntu/Debian OS (apt)..."
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y python3 python3-pip python3-venv git curl iptables-persistent
elif command -v dnf &> /dev/null; then
    echo "📦 Detected Oracle Linux / RHEL OS (dnf)..."
    sudo dnf update -y
    sudo dnf install -y python3 python3-pip git curl || sudo dnf install -y python3 git curl
elif command -v yum &> /dev/null; then
    echo "📦 Detected CentOS / RHEL OS (yum)..."
    sudo yum update -y
    sudo yum install -y python3 python3-pip git curl
else
    echo "⚠️ Unknown package manager. Proceeding with existing python3 installation..."
fi

# 2. Open OS Firewall Ports 5050 & 5051
echo "🔥 Configuring OS Firewall (Opening ports 5050 & 5051)..."
if command -v firewall-cmd &> /dev/null && sudo systemctl is-active --quiet firewalld; then
    sudo firewall-cmd --permanent --add-port=5050/tcp || true
    sudo firewall-cmd --permanent --add-port=5051/tcp || true
    sudo firewall-cmd --reload || true
fi

sudo iptables -I INPUT 1 -p tcp --dport 5050 -j ACCEPT || true
sudo iptables -I INPUT 1 -p tcp --dport 5051 -j ACCEPT || true

if command -v netfilter-persistent &> /dev/null; then
    sudo netfilter-persistent save || true
elif command -v service &> /dev/null; then
    sudo service iptables save || true
fi

# 3. Setup Virtual Environment
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🐍 Setting up Python Virtual Environment in $APP_DIR/venv ..."
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv || virtualenv venv
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
sudo systemctl status trading-options --no-pager | head -n 5 || true
echo "---"
sudo systemctl status trading-stock --no-pager | head -n 5 || true
echo "---"
sudo systemctl status trading-export --no-pager | head -n 5 || true
echo ""
echo "🌐 Options Dashboard: http://<YOUR_SERVER_IP>:5050"
echo "🌐 Stock Dashboard:   http://<YOUR_SERVER_IP>:5051"
echo "=============================================================================="
