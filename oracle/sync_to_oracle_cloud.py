import subprocess, sys, os, time, tarfile, json, argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

SERVERS = {
    "bhavni": {
        "name": "Bhavni Oracle Cloud VM",
        "host": "opc@129.225.69.131",
        "public_ip": "129.225.69.131",
        "remote_dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "api_key": "jgdjmtymfyea4yn4",
        "api_secret": "gr5mha1oag9rgguetvsx8cgg9xh2id52",
    },
    "poovendan": {
        "name": "Poovendan Oracle Cloud VM",
        "host": "opc@140.245.197.71",
        "public_ip": "140.245.197.71",
        "remote_dir": "/home/opc/Price_Action_Strategy",
        "api_key": "o8nnw6kxykvrsrhg",
        "api_secret": "9g7d5kktr38d7yvq11njsm4upz8kc6s1",
    }
}

def check_status(target_key, srv, key_path):
    print(f"\n--- Checking Status: {srv['name']} ({srv['public_ip']}) ---")
    cmd = "uptime; echo '--- Services ---'; systemctl is-active trading-options trading-stock trading-export"
    res = subprocess.run(["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", srv["host"], cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0:
        print(res.stdout.strip())
        print(f" -> Options Dashboard: http://{srv['public_ip']}:5050")
        print(f" -> Stock Dashboard:   http://{srv['public_ip']}:5051")
    else:
        print(f" [ERROR] Could not connect to {srv['host']}:\n{res.stderr.strip()}")

def sync_and_deploy(target_key, srv, key_path, tar_p):
    print("\n" + "=" * 75)
    print(f" DEPLOYING TO: {srv['name']} ({srv['host']})")
    print(f" Remote Directory: {srv['remote_dir']}")
    print("=" * 75)

    # 1. Upload via SCP
    print(f"\n[1/3] Uploading payload to {srv['public_ip']}...")
    scp_cmd = ["scp", "-i", key_path, "-o", "StrictHostKeyChecking=no", tar_p, f"{srv['host']}:{srv['remote_dir']}/cloud_sync_payload.tar.gz"]
    res_scp = subprocess.run(scp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_scp.returncode != 0:
        print(f" [ERROR] SCP Upload failed:\n{res_scp.stderr}")
        return False
    print(" -> Upload complete.")

    # 2. Extract and Restart on VM (with strict Account Credentials Isolation)
    print("\n[2/3] Extracting payload and enforcing server credentials on VM...")
    cmd = (
        f"cd {srv['remote_dir']} && "
        f"tar -xzf cloud_sync_payload.tar.gz && "
        f"rm -f cloud_sync_payload.tar.gz && "
        f"sudo bash {srv['remote_dir']}/oracle/setup_systemd_vm.sh '{srv['api_key']}' '{srv['api_secret']}'"
    )
    res = subprocess.run(["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", srv["host"], cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(res.stdout or res.stderr)
    print(" -> Services restarted with dedicated account credentials.")

    # 3. Launch trading engines via API
    print("\n[3/3] Launching trading engines via API...")
    time.sleep(3)
    api_cmd = "curl -s -X POST http://127.0.0.1:5050/api/programs/index/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5050/api/programs/nifty50/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/daily/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/bear_trade/start -H 'Content-Type: application/json' -d '{}'"
    subprocess.run(["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", srv["host"], api_cmd], capture_output=True)

    print("\n" + "-" * 75)
    print(f" SUCCESS: Deployed to {srv['name']}")
    print(f" Options Dashboard: http://{srv['public_ip']}:5050")
    print(f" Stock Dashboard:   http://{srv['public_ip']}:5051")
    print("-" * 75)
    return True

def package_codebase(tar_p):
    print("\nPackaging codebase (excluding active account tokens & sensitive DBs)...")
    with tarfile.open(tar_p, "w:gz") as tar:
        for folder in ["common", "Trade_Option", "Trade_Stock", "oracle", "scratch", "docs"]:
            fp = os.path.join(PROJECT_ROOT, folder)
            if os.path.exists(fp):
                tar.add(fp, arcname=folder)
        
        # Add non-token configs from input/
        input_dir = os.path.join(PROJECT_ROOT, "input")
        if os.path.exists(input_dir):
            for item in os.listdir(input_dir):
                if "token" in item.lower():
                    continue  # Never overwrite VM account tokens
                item_path = os.path.join(input_dir, item)
                tar.add(item_path, arcname=os.path.join("input", item))
        
        # Add output/monitor directory structure
        monitor_dir = os.path.join(PROJECT_ROOT, "output", "monitor")
        if os.path.exists(monitor_dir):
            tar.add(monitor_dir, arcname="output/monitor")
            
        for fn in ["ISSUE_MANAGEMENT.yaml", "MASTER_DOCUMENTATION.yaml", "AGENTS.md", "AI_CONTEXT_INDEX.md", "Kite_Access_Token_gen.py", "requirements.txt", "deploy_to_cloud.sh", "VERSION.txt"]:
            fp = os.path.join(PROJECT_ROOT, fn)
            if os.path.exists(fp):
                tar.add(fp, arcname=fn)
    print(" -> Package ready.")

def main():
    parser = argparse.ArgumentParser(description="Price Action Strategy - Multi-Cloud VM Sync & Deploy")
    parser.add_argument("--target", choices=["bhavni", "poovendan", "all"], default=None, help="Target Oracle Cloud VM")
    parser.add_argument("--key", default=DEFAULT_KEY, help="Path to SSH private key")
    parser.add_argument("--status", action="store_true", help="Check status of VMs without syncing")
    args = parser.parse_args()

    print("=" * 75)
    print("     PRICE ACTION STRATEGY - ORACLE CLOUD MULTI-VM CONTROL")
    print("=" * 75)

    if args.status:
        targets = ["bhavni", "poovendan"] if args.target in [None, "all"] else [args.target]
        for t in targets:
            check_status(t, SERVERS[t], args.key)
        return

    target = args.target
    if not target:
        print("\nSelect Deployment Target:")
        print(" [1] Bhavni VM   (129.225.69.131)")
        print(" [2] Poovendan VM (140.245.197.71)")
        print(" [3] Both VMs (All)")
        print(" [4] Status Check Only")
        try:
            choice = input("\nEnter choice [1-4] (default: 3): ").strip()
        except EOFError:
            choice = "3"
        if choice == "1":
            target = "bhavni"
        elif choice == "2":
            target = "poovendan"
        elif choice == "4":
            for t in ["bhavni", "poovendan"]:
                check_status(t, SERVERS[t], args.key)
            return
        else:
            target = "all"

    selected_targets = ["bhavni", "poovendan"] if target == "all" else [target]

    tar_p = os.path.join(PROJECT_ROOT, "cloud_sync_payload.tar.gz")
    try:
        package_codebase(tar_p)
        for t in selected_targets:
            sync_and_deploy(t, SERVERS[t], args.key, tar_p)
    finally:
        if os.path.exists(tar_p):
            try:
                os.remove(tar_p)
            except Exception:
                pass

    print("\n" + "=" * 75)
    print("                ALL OPERATIONS COMPLETED!")
    print("=" * 75)

if __name__ == "__main__":
    main()
