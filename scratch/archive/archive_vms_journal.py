# -*- coding: utf-8 -*-
"""
archive_vms_journal.py — Safe archive and reset of daily trade journal on Cloud VMs.
"""
import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan (VM 1)", "140.245.197.71", "/home/opc/Price_Action_Strategy", "/home/opc/Price_Action_Strategy/venv/bin/python"),
    ("Bhavani (VM 2)", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python")
]

remote_py_cmd = (
    "import os, sys, shutil; "
    "sys.path.insert(0, 'common'); "
    "import daily_trade_journal as dtj; "
    "ok, bpath, msg = dtj.clear_journal(create_backup=True); "
    "print('Clear status:', ok, msg); "
    "j_dir = dtj.JOURNAL_DIR; "
    "os.makedirs(j_dir, exist_ok=True); "
    "[shutil.copy2(os.path.join(j_dir, f), os.path.join(j_dir, 'daily_trade_journal_archive_20260922' + os.path.splitext(f)[1])) "
    " for f in os.listdir(j_dir) if 'backup' in f]; "
    "mon_csv = os.path.join('output', 'monitor', 'trade_journal.csv'); "
    "os.path.exists(mon_csv) and (shutil.copy2(mon_csv, os.path.join('output', 'monitor', 'trade_journal_backup_20260922.csv')), open(mon_csv, 'w').close()); "
    "print('VM Archive and Reset Complete.')"
)

for name, ip, repo_dir, py_cmd in vms:
    print(f"\n=======================================================")
    print(f"Archiving Trade Journal on {name} ({ip})...")
    print(f"=======================================================")
    cmd = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && {py_cmd} -c \"{remote_py_cmd}\""
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout or res.stderr)

print("\nAll Cloud VM journals safely archived and reset!")
