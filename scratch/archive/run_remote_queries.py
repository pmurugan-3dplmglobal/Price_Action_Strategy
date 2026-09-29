import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan (VM 1)", "140.245.197.71", "/home/opc/Price_Action_Strategy", "/home/opc/Price_Action_Strategy/venv/bin/python"),
    ("Bhavani (VM 2)", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python")
]

for name, ip, repo_dir, py_cmd in vms:
    print("=" * 60)
    print(f"QUERYING {name} ({ip})")
    print("=" * 60)
    cmd_scp = ["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", "scratch/remote_query_target_trades.py", f"opc@{ip}:{repo_dir}/remote_query.py"]
    subprocess.run(cmd_scp, capture_output=True, text=True, timeout=20)
    
    cmd_run = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}", f"cd {repo_dir} && {py_cmd} remote_query.py && rm -f remote_query.py"]
    res = subprocess.run(cmd_run, capture_output=True, text=True, timeout=30)
    print(res.stdout or res_run.stderr)
