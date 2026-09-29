import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
for vm_name, vm_ip in [("Poovendan", "140.245.197.71"), ("Bhavani", "129.225.69.131")]:
    print(f"\n==================== {vm_name} ({vm_ip}) ====================")
    cmd = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm_ip}",
        "grep -inE 'CANBK' /home/opc/Price_Action_Strategy/output/logs/*.log | tail -n 40"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout or res.stderr or "No matching log lines found.")
