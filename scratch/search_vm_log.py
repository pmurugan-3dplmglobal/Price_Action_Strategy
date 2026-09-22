import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vm_ip = "140.245.197.71"
log_path = "/home/opc/Price_Action_Strategy/output/logs/bull_nifty50_scanner.log"

cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm_ip}",
    f"grep -iE '(LTM|TMPV|SWIGGY|WAAREEENER|VOLTAS|HCLTECH|KPITTECH)' {log_path} | tail -n 35"
]

res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout.strip() or res.stderr.strip() or "No output found.")
