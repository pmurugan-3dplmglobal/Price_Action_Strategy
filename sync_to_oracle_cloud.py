import subprocess, sys, os, time, tarfile, json

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"
REMOTE_DIR = "/home/opc/Price_Action_Strategy"
PUBLIC_IP = "140.245.197.71"

print("=" * 75)
print("     PRICE ACTION STRATEGY - ORACLE CLOUD VM SYNC AND DEPLOY")
print("=" * 75)

# 1. Sync latest token
print("\n[1/5] Syncing latest Kite Access Token...")
token_paths = [
    os.path.join(ROOT, "input", "kite_access_token.txt"),
    os.path.join(os.path.dirname(ROOT), "kite_access_token.txt"),
    r"G:\Poovendan\AI\Trading\Share\kite_access_token.txt",
    r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\kite_access_token.txt"
]
best_tok, best_mt = None, 0
for tp in token_paths:
    if os.path.exists(tp):
        try:
            with open(tp, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            mt = os.path.getmtime(tp)
            if mt > best_mt and d.get("access_token"):
                best_mt, best_tok = mt, d
        except Exception:
            pass

if best_tok:
    target = os.path.join(ROOT, "input", "kite_access_token.txt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fp:
        json.dump(best_tok, fp, indent=4)
    print(f" -> Token Synced! Generated: {best_tok.get('generated_at')}")

# 2. Package codebase
print("\n[2/5] Packaging codebase...")
tar_p = os.path.join(ROOT, "cloud_sync_payload.tar.gz")
with tarfile.open(tar_p, "w:gz") as tar:
    for folder in ["common", "Trade_Option", "Trade_Stock", "input", "oracle"]:
        fp = os.path.join(ROOT, folder)
        if os.path.exists(fp):
            tar.add(fp, arcname=folder)
    for fn in ["ISSUE_MANAGEMENT.yaml", "MASTER_DOCUMENTATION.yaml", "Kite_Access_Token_gen.py"]:
        fp = os.path.join(ROOT, fn)
        if os.path.exists(fp):
            tar.add(fp, arcname=fn)
print(" -> Package ready.")

# 3. Upload via SCP
print("\n[3/5] Uploading to Oracle Cloud VM...")
subprocess.run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", tar_p, f"{HOST}:{REMOTE_DIR}/cloud_sync_payload.tar.gz"], check=True)
if os.path.exists(tar_p): os.remove(tar_p)
print(" -> Upload complete.")

# 4. Extract and Restart on VM
print("\n[4/5] Extracting payload and restarting services on VM...")
cmd = f"cd {REMOTE_DIR} ; git fetch origin && git reset --hard origin/master ; tar -xzf cloud_sync_payload.tar.gz ; rm -f cloud_sync_payload.tar.gz ; sudo bash {REMOTE_DIR}/oracle/setup_systemd_vm.sh"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True)
print(" -> Services restarted.")

# 5. Start trading engines via API
print("\n[5/5] Launching trading engines via API...")
time.sleep(3)
api_cmd = "curl -s -X POST http://127.0.0.1:5050/api/programs/index/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5050/api/programs/nifty50/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/daily/start -H 'Content-Type: application/json' -d '{}' ; curl -s -X POST http://127.0.0.1:5051/api/programs/bear_trade/start -H 'Content-Type: application/json' -d '{}'"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, api_cmd], capture_output=True)

print("\n" + "=" * 75)
print("                DEPLOYMENT AND SYNC COMPLETED!")
print("=" * 75)
print(f" Options Dashboard: http://{PUBLIC_IP}:5050")
print(f" Stock Dashboard:   http://{PUBLIC_IP}:5051")
print("=" * 75)
