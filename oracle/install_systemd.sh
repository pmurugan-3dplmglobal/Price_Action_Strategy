#!/bin/bash
#
# install_systemd.sh — Install systemd service + market-hours timers on the VM.
# Run once after uploading the oracle/ folder and creating the venv.
#
set -e

SRC="/home/ubuntu/Prod_code_02/oracle"
UNIT_DIR="/etc/systemd/system"

echo "Installing unit files..."
sudo cp "$SRC/trading-dashboard.service" "$UNIT_DIR/"
sudo cp "$SRC/trading-start.timer"       "$UNIT_DIR/"
sudo cp "$SRC/trading-stop.timer"        "$UNIT_DIR/"
sudo cp "$SRC/trading-stop.service"      "$UNIT_DIR/"

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling timers (market open/close)..."
sudo systemctl enable trading-start.timer
sudo systemctl enable trading-stop.timer

echo "Starting timers..."
sudo systemctl start trading-start.timer
sudo systemctl start trading-stop.timer

echo ""
echo "Status:"
systemctl list-timers | grep trading || true
echo ""
echo "Manual control:"
echo "  sudo systemctl start trading-dashboard.service   # start now"
echo "  sudo systemctl stop  trading-dashboard.service   # stop now"
echo "  systemctl status trading-dashboard.service"
