import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vms = [
    ("Poovendan", "140.245.197.71", "/home/opc/Price_Action_Strategy"),
    ("Bhavani", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy")
]

for name, ip, repo_dir in vms:
    print(f"\n=======================================================")
    print(f"Deploying to {name} ({ip})...")
    print(f"=======================================================")
    
    # 1. Git pull
    cmd_pull = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"cd {repo_dir} && sudo git pull origin master"
    ]
    res_pull = subprocess.run(cmd_pull, capture_output=True, text=True)
    print("GIT PULL OUTPUT:")
    print(res_pull.stdout or res_pull.stderr)
    
    # 2. Syntax smoke check
    cmd_smoke = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        "cd /home/opc/Price_Action_Strategy && python3 -c \"import ast; ast.parse(open('common/resolve.py').read()); ast.parse(open('Trade_Option/stock_options_trade_engine.py').read()); print('AST SYNTAX OK ON VM')\""
    ]
    res_smoke = subprocess.run(cmd_smoke, capture_output=True, text=True)
    print("SMOKE TEST OUTPUT:")
    print(res_smoke.stdout or res_smoke.stderr)
    
    # 3. Restart systemd services
    cmd_restart = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        "sudo systemctl restart trading-options trading-stock trading-export"
    ]
    res_restart = subprocess.run(cmd_restart, capture_output=True, text=True)
    print("SERVICES RESTARTED.")
    
    time.sleep(2)
    # 4. Check services status
    cmd_status = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        "systemctl is-active trading-options trading-stock trading-export"
    ]
    res_status = subprocess.run(cmd_status, capture_output=True, text=True)
    print("SERVICES STATUS:")
    print(res_status.stdout or res_status.stderr)

print("\nDeployment to both VMs complete!")
