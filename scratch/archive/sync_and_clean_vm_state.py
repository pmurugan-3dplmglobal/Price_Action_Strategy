import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan (VM 1)", "140.245.197.71", "/home/opc/Price_Action_Strategy", "/home/opc/Price_Action_Strategy/venv/bin/python"),
    ("Bhavani (VM 2)", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python")
]

for name, ip, repo_dir, py_cmd in vms:
    print(f"\nCleaning ghost state on {name} ({ip})...")
    # Copy cleanup script to VM
    cmd_scp = [
        "scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
        "scratch/cleanup_ghost_positions.py", f"opc@{ip}:{repo_dir}/cleanup_ghost_positions.py"
    ]
    subprocess.run(cmd_scp, capture_output=True, text=True, timeout=20)
    
    # Run cleanup script on VM
    cmd_run = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && {py_cmd} cleanup_ghost_positions.py && rm -f cleanup_ghost_positions.py"
    ]
    res_run = subprocess.run(cmd_run, capture_output=True, text=True, timeout=30)
    print(res_run.stdout or res_run.stderr)
