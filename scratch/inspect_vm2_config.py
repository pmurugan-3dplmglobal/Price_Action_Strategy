import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM2_IP = "129.225.69.131"

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

echo "=== scratch/set_bhavani_sl_pause.py ==="
cat scratch/set_bhavani_sl_pause.py 2>/dev/null || true

echo "=== input/program_config.json ==="
cat input/program_config.json

echo "=== WHEN DID ADANIPOWER GET ADDED TO ACTIVE_TRADES OR MONITORED? ==="
journalctl -u trading-options -u trading-stock --since "2026-09-15 00:00:00" | grep -i "ADANIPOWER" | head -n 30
'''

p = subprocess.run(
    ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{VM2_IP}", "bash -s"],
    input=BASH_SCRIPT.encode("utf-8"),
    capture_output=True
)
print(p.stdout.decode("utf-8", errors="replace"))
if p.stderr:
    print("STDERR:", p.stderr.decode("utf-8", errors="replace"))
