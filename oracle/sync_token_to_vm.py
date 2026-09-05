import os
import sys
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
TOKEN_FILE = os.path.join(PROJECT_ROOT, "input", "kite_access_token.txt")

VM_HOST = "opc@140.245.197.71"
VM_DIR = "/home/opc/Price_Action_Strategy"

def sync_token():
    print("=" * 70)
    print("    SYNC KITE ACCESS TOKEN TO POOVENDAN ORACLE CLOUD VM")
    print("=" * 70)

    if not os.path.exists(TOKEN_FILE):
        print(f"[ERROR] Local token file not found at: {TOKEN_FILE}")
        return False

    if not os.path.exists(DEFAULT_KEY):
        print(f"[ERROR] SSH key not found at: {DEFAULT_KEY}")
        return False

    print(f"\n[1/3] Uploading local token to VM ({VM_HOST})...")
    scp_cmd = [
        "scp", "-i", DEFAULT_KEY,
        "-o", "StrictHostKeyChecking=no",
        TOKEN_FILE,
        f"{VM_HOST}:{VM_DIR}/input/kite_access_token.txt"
    ]
    res = subprocess.run(scp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print(f"[ERROR] SCP failed:\n{res.stderr}")
        return False
    print(" -> Token uploaded successfully.")

    print("\n[2/3] Restarting systemd services on VM...")
    ssh_cmd = [
        "ssh", "-i", DEFAULT_KEY,
        "-o", "StrictHostKeyChecking=no",
        VM_HOST,
        "sudo systemctl restart trading-options trading-stock trading-export && sleep 2 && systemctl is-active trading-options trading-stock"
    ]
    res_ssh = subprocess.run(ssh_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(" -> Services status:")
    print(res_ssh.stdout.strip() or res_ssh.stderr.strip())

    print("\n[3/3] Verifying VM Kite Session...")
    verify_cmd = [
        "ssh", "-i", DEFAULT_KEY,
        "-o", "StrictHostKeyChecking=no",
        VM_HOST,
        f"{VM_DIR}/venv/bin/python -c 'import json; from kiteconnect import KiteConnect; td=json.load(open(\"{VM_DIR}/input/kite_access_token.txt\")); k=KiteConnect(api_key=td[\"api_key\"]); k.set_access_token(td[\"access_token\"]); print(\"Session verified for:\", k.profile()[\"user_name\"])'"
    ]
    res_ver = subprocess.run(verify_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_ver.returncode == 0 and "Session verified" in res_ver.stdout:
        print(f" -> {res_ver.stdout.strip()}")
        print("\n" + "=" * 70)
        print(" SUCCESS! Your Oracle Cloud VM is active and running with today's token.")
        print(" Options Dashboard: http://140.245.197.71:5050")
        print(" Stock Dashboard:   http://140.245.197.71:5051")
        print("=" * 70)
        return True
    else:
        print(f"[WARNING] Session verification had issues:\n{res_ver.stdout}\n{res_ver.stderr}")
        return False

if __name__ == "__main__":
    success = sync_token()
    sys.exit(0 if success else 1)
