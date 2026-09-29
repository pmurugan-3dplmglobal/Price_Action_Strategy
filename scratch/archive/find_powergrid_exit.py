import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "sudo journalctl --since '2026-09-23 05:45:00' --until '2026-09-23 05:48:00' --no-pager | grep -i 'POWERGRID'"
]
res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("Journalctl grep result:")
print(res.stdout or res.stderr)

cmd2 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "grep -rn 'POWERGRID26OCT265CE' /home/opc/Price_Action_Strategy/output/ 2>/dev/null | head -n 30"
]
res2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("Output dir grep result:")
print(res2.stdout or res2.stderr)
