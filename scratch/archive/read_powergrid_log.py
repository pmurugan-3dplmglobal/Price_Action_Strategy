import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "tail -n 100 /home/opc/Price_Action_Strategy/output/logs/bull_nifty50_scanner.log"
]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
lines = res.stdout.splitlines()
for l in lines:
    safe_l = l.encode("ascii", errors="replace").decode("ascii")
    if any(k in safe_l.upper() for k in ["POWERGRID", "EXIT", "CLOSE", "TARGET", "SL", "ORDER", "SELL"]):
        print(safe_l)
