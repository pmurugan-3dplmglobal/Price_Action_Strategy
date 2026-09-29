import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VMS = [
    {
        "name": "VM1 (Poovendan)",
        "ip": "140.245.197.71",
        "user": "opc",
        "dir": "/home/opc/Price_Action_Strategy"
    },
    {
        "name": "VM2 (Bhavani)",
        "ip": "129.225.69.131",
        "user": "opc",
        "dir": "/home/trade/Trade_Kite/Price_Action_Strategy"
    }
]

BASH_TEMPLATE = r"""#!/usr/bin/env bash
set -e
cd "__DIR__"

echo "=== Pulling origin master ==="
git pull origin master

echo "=== Syncing program_config.json index capital and max daily loss ==="
python3 -c '
import json, os
cfg_path = "input/program_config.json"
if os.path.exists(cfg_path):
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "index" in cfg:
        cfg["index"]["capital"] = 100000
        cfg["index"]["max_daily_loss_pct"] = 3.0
    if "portfolio_risk" in cfg:
        cfg["portfolio_risk"]["max_daily_loss_pct"] = 5.0
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("program_config.json updated successfully on VM")
'

echo "=== Restarting trading services ==="
sudo systemctl restart trading-options trading-stock trading-export
sleep 2

echo -n "trading-options status: "
systemctl is-active trading-options
echo -n "trading-stock status: "
systemctl is-active trading-stock
echo -n "trading-export status: "
systemctl is-active trading-export
uptime
"""

def deploy_vm(vm):
    print(f"\n{'='*60}\nDeploying git update to {vm['name']} ({vm['ip']})...\n{'='*60}")
    script = (
        BASH_TEMPLATE
        .replace("__DIR__", vm["dir"])
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
    
    p = subprocess.run(cmd, input=script, capture_output=True)
    print("STDOUT:")
    print(p.stdout.decode("utf-8", errors="replace"))
    if p.stderr:
        print("STDERR:")
        print(p.stderr.decode("utf-8", errors="replace"))
    print(f"Exit code: {p.returncode}")
    return p.returncode == 0

def main():
    for vm in VMS:
        deploy_vm(vm)

if __name__ == "__main__":
    main()
