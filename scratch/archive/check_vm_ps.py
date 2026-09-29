import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vm_ip = "140.245.197.71"

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm_ip}", "ps aux | grep -i python"]
res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout.strip() or res.stderr.strip())
