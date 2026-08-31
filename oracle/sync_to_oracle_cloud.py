import subprocess, sys, os, time, tarfile, json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"
PUBLIC_IP = "129.225.69.131"

print("=" * 75)
print("     PRICE ACTION STRATEGY - ORACLE CLOUD VM SYNC AND DEPLOY")
print("=" * 75)

# 1. Package codebase (excluding active account tokens)
print("\n[1/4] Packaging codebase...")
tar_p = os.path.join(ROOT, "cloud_sync_payload.tar.gz")
with tarfile.open(tar_p, "w:gz") as tar:
    for folder in ["common", "Trade_Option", "Trade_Stock", "oracle", "scratch", "docs"]:
        fp = os.path.join(ROOT, folder)
        if os.path.exists(fp):
            tar.add(fp, arcname=folder)
    # Add input templates and non-token configs
    input_dir = os.path.join(ROOT, "input")
    if os.path.exists(input_dir):
        for item in os.listdir(input_dir):
            if "token" in item.lower():
                continue  # Never overwrite VM account tokens
            item_path = os.path.join(input_dir, item)
            tar.add(item_path, arcname=os.path.join("input", item))
    monitor_dir = os.path.join(ROOT, "output", "monitor")
    if os.path.exists(monitor_dir):
        tar.add(monitor_dir, arcname="output/monitor")
    for fn in ["ISSUE_MANAGEMENT.yaml", "MASTER_DOCUMENTATION.yaml", "Kite_Access_Token_gen.py", "requirements.txt", "deploy_to_cloud.sh", "VERSION.txt"]:
        fp = os.path.join(ROOT, fn)
        if os.path.exists(fp):
            tar.add(fp, arcname=fn)
print(" -> Package ready (Account tokens excluded).")

# 2. Upload via SCP
print("\n[2/4] Uploading to Oracle Cloud VM...")
subprocess.run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", tar_p, f"{HOST}:{REMOTE_DIR}/cloud_sync_payload.tar.gz"], check=True)
if os.path.exists(tar_p): os.remove(tar_p)
print(" -> Upload complete.")

# 3. Extract and Restart on VM
print("\n[3/4] Extracting payload and restarting services on VM...")
cmd = f"cd {REMOTE_DIR} && tar -xzf cloud_sync_payload.tar.gz && rm -f cloud_sync_payload.tar.gz && sudo bash {REMOTE_DIR}/oracle/setup_systemd_vm.sh"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
try:
    print(res.stdout or res.stderr)
except Exception:
    print((res.stdout or res.stderr).encode("ascii", errors="replace").decode("ascii"))
print(" -> Services restarted.")

# 4. Launch trading engines via API
print("\n[4/4] Launching trading engines via API...")
time.sleep(3)
api_cmd = "curl -s -X POST http://127.0.0.1:5050/api/programs/index/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5050/api/programs/nifty50/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/daily/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/bear_trade/start -H 'Content-Type: application/json' -d '{}'"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, api_cmd], capture_output=True)

print("\n" + "=" * 75)
print("                DEPLOYMENT AND SYNC COMPLETED!")
print("=" * 75)
print(f" Options Dashboard: http://{PUBLIC_IP}:5050")
print(f" Stock Dashboard:   http://{PUBLIC_IP}:5051")
print("=" * 75)

