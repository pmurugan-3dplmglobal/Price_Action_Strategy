import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "sudo journalctl -u trading-options --since '2026-09-23 05:45:30' --until '2026-09-23 05:47:30' --no-pager"
]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(res.stdout or res.stderr)
