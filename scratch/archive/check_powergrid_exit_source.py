import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
py_code = """
import subprocess

cmd = [
    "ssh", "-i", r"G:\\Poovendan\\AI\\Trading\\Cloud\\Oracle_Cloud\\ssh-key-2026-08-05.key",
    "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "sudo journalctl -u trading-options --since '2026-09-23 05:45:00' --until '2026-09-23 05:48:00' --no-pager | grep -iE 'exit-position|POWERGRID|Closed'"
]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("VM1 Log Search around 11:16 AM:")
print(res.stdout or res.stderr)
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "sudo journalctl -u trading-options --since '2026-09-23 05:45:00' --until '2026-09-23 05:48:00' --no-pager | grep -iE 'exit-position|POWERGRID|Closed'"]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("Direct grep result:")
print(res.stdout or res.stderr)
