import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "sudo journalctl -u trading-options --since '2026-09-23 09:15:00' --until '2026-09-23 10:15:00' --no-pager | grep -E 'MIDCPNIFTY|NAUKRI|ASIANPAINT' | head -n 40"
]
res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout or res.stderr)
