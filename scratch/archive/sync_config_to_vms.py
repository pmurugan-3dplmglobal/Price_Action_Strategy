# -*- coding: utf-8 -*-
"""
sync_config_to_vms.py — Updates program_config.json on Cloud VMs with 2-tier scheduling options.
"""
import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan (VM 1)", "140.245.197.71", "/home/opc/Price_Action_Strategy", "/home/opc/Price_Action_Strategy/venv/bin/python"),
    ("Bhavani (VM 2)", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python")
]

update_cfg_py = (
    'import json, os; '
    'cfg_p = os.path.join("input", "program_config.json"); '
    'cfg = json.load(open(cfg_p)); '
    'n50 = cfg.setdefault("nifty50", {}); '
    'n50["core_scan_interval"] = 180; '
    'n50["full_scan_interval"] = 900; '
    'n50["enable_2tier_scheduling"] = True; '
    'n50["enable_premarket_seeding"] = True; '
    'json.dump(cfg, open(cfg_p, "w"), indent=2); '
    'print("Updated program_config.json on VM")'
)

for name, ip, repo_dir, py_cmd in vms:
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}", f"cd {repo_dir} && {py_cmd} -c '{update_cfg_py}'"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(f"{name}: {res.stdout.strip() or res.stderr.strip()}")

print("All VM configurations synchronized!")
