import subprocess
import sys
import json
import time

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VMS = [
    {
        "name": "VM1 (Poovendan)",
        "ip": "140.245.197.71",
        "user": "opc",
        "dir": "/home/opc/Price_Action_Strategy",
        "service_user": "opc",
        "venv_python": "/home/opc/Price_Action_Strategy/venv/bin/python"
    },
    {
        "name": "VM2 (Bhavani)",
        "ip": "129.225.69.131",
        "user": "opc",
        "dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "service_user": "opc",
        "venv_python": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python"
    }
]

BASH_TEMPLATE = """#!/usr/bin/env bash
set -e

REPO_DIR="__DIR__"
SERVICE_USER="__SERVICE_USER__"
VENV_PYTHON="__VENV_PYTHON__"

echo "=== [1/6] Navigating to $REPO_DIR and Git Pull ==="
cd "$REPO_DIR"
git pull origin master

echo "=== [2/6] Updating input/program_config.json (lookback_days) ==="
python3 -c '
import json
cfg_path = "input/program_config.json"
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg.setdefault("index", {})["lookback_days"] = 10
cfg.setdefault("nifty50", {})["lookback_days"] = 15

with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
print("Updated program_config.json: index.lookback_days =", cfg["index"]["lookback_days"], "nifty50.lookback_days =", cfg["nifty50"]["lookback_days"])
'

echo "=== [3/6] Disabling dnf-makecache timers ==="
sudo systemctl disable --now dnf-makecache.timer dnf-makecache.service 2>/dev/null || true

echo "=== [4/6] Configuring systemd trading-options.service with MALLOC_ARENA_MAX=2 & Nice=-5 ==="
sudo tee /etc/systemd/system/trading-options.service > /dev/null << EOF
[Unit]
Description=Price Action Options Trading Dashboard (Port 5050)
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR/Trade_Option
EnvironmentFile=-/etc/trading.env
Environment=PORT=5050
Environment=PYTHONUNBUFFERED=1
Environment=MALLOC_ARENA_MAX=2
Nice=-5
ExecStart=$VENV_PYTHON $REPO_DIR/Trade_Option/app_option_Trade.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== [5/6] Configuring Persistent ZRAM Swap Service ==="
sudo tee /etc/systemd/system/zram-swap.service > /dev/null << 'EOF'
[Unit]
Description=Enable 256M LZ4 ZRAM compressed swap
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'grep -q "/dev/zram0" /proc/swaps || (modprobe zram && (zramctl /dev/zram0 --size 256M --algorithm lz4 2>/dev/null || zramctl -f -s 256M -a lz4) && mkswap /dev/zram0 && swapon -p 100 /dev/zram0)'
ExecStop=/bin/sh -c 'swapoff /dev/zram0 2>/dev/null && zramctl --reset /dev/zram0 2>/dev/null || true'

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now zram-swap.service 2>/dev/null || true

echo "=== [6/6] Restarting trading-options ==="
sudo systemctl restart trading-options
sleep 3

echo "=== Verification Results ==="
echo -n "trading-options status: "
systemctl is-active trading-options
echo "Active Swaps:"
swapon --show
echo "Memory & Swap Stats:"
free -h
echo "System Load & Uptime:"
uptime
echo "Lookback Config Verified:"
python3 -c '
import json
with open("input/program_config.json") as f:
    cfg = json.load(f)
print("Index lookback_days:", cfg.get("index", {}).get("lookback_days"))
print("Nifty50 lookback_days:", cfg.get("nifty50", {}).get("lookback_days"))
'
"""

def deploy_to_vm(vm):
    print(f"\n{'='*60}\nDeploying to {vm['name']} ({vm['ip']})...\n{'='*60}")
    bash_script = (
        BASH_TEMPLATE
        .replace("__DIR__", vm["dir"])
        .replace("__SERVICE_USER__", vm["service_user"])
        .replace("__VENV_PYTHON__", vm["venv_python"])
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    ).encode("utf-8")
    
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        f"{vm['user']}@{vm['ip']}",
        "bash -s"
    ]
    
    p = subprocess.run(cmd, input=bash_script, capture_output=True)
    print("STDOUT:")
    print(p.stdout.decode("utf-8", errors="replace"))
    if p.stderr:
        print("STDERR:")
        print(p.stderr.decode("utf-8", errors="replace"))
    print(f"Exit code: {p.returncode}")
    return p.returncode == 0

def main():
    success_count = 0
    for vm in VMS:
        ok = deploy_to_vm(vm)
        if ok:
            success_count += 1
            print(f"SUCCESS on {vm['name']}")
        else:
            print(f"FAILED on {vm['name']}")
    
    print(f"\\nFinished: {success_count}/{len(VMS)} VMs deployed successfully.")

if __name__ == "__main__":
    main()
