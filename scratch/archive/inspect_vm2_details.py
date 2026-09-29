import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM2_IP = "129.225.69.131"

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

echo "=== GIT COMMIT ON VM2 ==="
git log -n 3 --oneline

echo "=== GIT STATUS ON VM2 ==="
git status --short

echo "=== RUNNING PROCESSES ==="
ps aux | grep -E "302895|302899|python" | grep -v grep

echo "=== CODE IN common/position_monitor.py ON VM2 AROUND LINE 1290-1320 ==="
grep -n -C 10 "Could not resolve valid token" common/position_monitor.py

echo "=== LOGS FROM 09:15:00 to 09:20:00 (FIRST 50 LINES OF WARNING/ERROR) ==="
journalctl -u trading-options -u trading-stock --since "2026-09-16 09:15:00" --until "2026-09-16 09:20:00" -p warning..emerg | head -n 50
'''

p = subprocess.run(
    ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{VM2_IP}", "bash -s"],
    input=BASH_SCRIPT.encode("utf-8"),
    capture_output=True
)
print(p.stdout.decode("utf-8", errors="replace"))
if p.stderr:
    print("STDERR:", p.stderr.decode("utf-8", errors="replace"))
