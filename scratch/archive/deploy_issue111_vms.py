import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan (VM 1)", "140.245.197.71", "/home/opc/Price_Action_Strategy", "/home/opc/Price_Action_Strategy/venv/bin/python"),
    ("Bhavani (VM 2)", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python")
]

for name, ip, repo_dir, py_cmd in vms:
    print(f"\n{'=' * 65}")
    print(f"Deploying ISSUE-111 to {name} ({ip})...")
    print(f"{'=' * 65}")

    # 1. Stash any runtime json changes & Git pull
    cmd_pull = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && sudo git stash && sudo git pull origin master"
    ]
    try:
        res_pull = subprocess.run(cmd_pull, capture_output=True, text=True, timeout=40)
        print("GIT PULL OUTPUT:")
        print((res_pull.stdout or res_pull.stderr).strip())
    except Exception as e:
        print(f"Git pull failed on {name}: {e}")
        continue

    # 2. Syntax smoke check on VM
    cmd_smoke = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && {py_cmd} -c \"import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['common/macro_gate.py', 'common/portfolio_risk.py', 'common/position_monitor.py', 'Trade_Option/stock_options_trade_engine.py', 'Trade_Option/index_options_trade_engine.py']]; print('AST SYNTAX OK ON VM')\""
    ]
    try:
        res_smoke = subprocess.run(cmd_smoke, capture_output=True, text=True, timeout=30)
        print("SMOKE TEST OUTPUT:")
        print((res_smoke.stdout or res_smoke.stderr).strip())
    except Exception as e:
        print(f"Smoke test failed on {name}: {e}")

    # 3. Clean ghost positions on VM using python script
    cmd_clean_ghost = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && {py_cmd} scratch/cleanup_ghost_positions.py"
    ]
    try:
        res_clean = subprocess.run(cmd_clean_ghost, capture_output=True, text=True, timeout=30)
        print("CLEANUP GHOST POSITIONS OUTPUT:")
        print((res_clean.stdout or res_clean.stderr).strip())
    except Exception as e:
        print(f"Ghost cleanup failed on {name}: {e}")

    # 4. Restart systemd services
    cmd_restart = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        "sudo systemctl restart trading-options trading-stock trading-export"
    ]
    try:
        res_restart = subprocess.run(cmd_restart, capture_output=True, text=True, timeout=40)
        print("SERVICES RESTARTED.")
    except Exception as e:
        print(f"Restart failed on {name}: {e}")

    time.sleep(3)

    # 5. Check services status
    cmd_status = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        "systemctl is-active trading-options trading-stock trading-export"
    ]
    try:
        res_status = subprocess.run(cmd_status, capture_output=True, text=True, timeout=20)
        print("SERVICES STATUS:")
        print((res_status.stdout or res_status.stderr).strip())
    except Exception as e:
        print(f"Status check failed on {name}: {e}")
