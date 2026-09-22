import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VMS = [
    {
        "name": "VM2 (Bhavani)",
        "ip": "129.225.69.131",
        "dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "venv_py": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python",
        "ak": "jgdjmtymfyea4yn4"
    },
    {
        "name": "VM1 (Poovendan)",
        "ip": "140.245.197.71",
        "dir": "/home/opc/Price_Action_Strategy",
        "venv_py": "/home/opc/Price_Action_Strategy/venv/bin/python",
        "ak": "o8nnw6kxykvrsrhg"
    }
]

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd __DIR__

echo "=== 1. KITE POSITIONS & ORDERS FOR ADANIPOWER ==="
__VENV_PY__ - << 'PYEOF'
import os, json
from kiteconnect import KiteConnect

ak = "__AK__"
at_path = "input/kite_access_token.txt"
if os.path.exists(at_path):
    with open(at_path) as f:
        raw = f.read().strip()
        try:
            at_data = json.loads(raw)
            at = at_data.get("access_token", raw)
        except Exception:
            at = raw
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    try:
        net = kite.positions().get("net", [])
        for p in net:
            if "ADANIPOWER" in p.get("tradingsymbol", ""):
                print("Kite Net Position:", p)
        orders = kite.orders()
        for o in orders:
            if "ADANIPOWER" in o.get("tradingsymbol", ""):
                print(f"Kite Order: {o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} @ {o.get('average_price')} | Status: {o.get('status')} | Tag: {o.get('tag')} | Msg: {o.get('status_message')}")
    except Exception as e:
        print("Kite query error:", e)
else:
    print("Token file missing:", at_path)
PYEOF

echo "=== 2. SQLITE ACTIVE TRADES ==="
sqlite3 input/trades.db "SELECT symbol, entry_price, stop_loss, target, current_sl, quantity, pnl, entry_time, strategy, exit_time, exit_price, exit_reason FROM active_trades WHERE symbol LIKE '%ADANIPOWER%';" 2>/dev/null || true
sqlite3 output/trades.db "SELECT symbol, entry_price, stop_loss, target, current_sl, quantity, pnl, entry_time, strategy, exit_time, exit_price, exit_reason FROM active_trades WHERE symbol LIKE '%ADANIPOWER%';" 2>/dev/null || true

echo "=== 3. SQLITE COMPLETED TRADES ==="
sqlite3 input/trades.db "SELECT symbol, entry_price, stop_loss, target, current_sl, quantity, pnl, entry_time, exit_time, exit_price, exit_reason FROM completed_trades WHERE symbol LIKE '%ADANIPOWER%';" 2>/dev/null || true
sqlite3 output/trades.db "SELECT symbol, entry_price, stop_loss, target, current_sl, quantity, pnl, entry_time, exit_time, exit_price, exit_reason FROM completed_trades WHERE symbol LIKE '%ADANIPOWER%';" 2>/dev/null || true

echo "=== 4. JOURNALCTL LOGS FOR ADANIPOWER ==="
journalctl -u trading-options -u trading-stock --since "2 days ago" | grep -i "ADANIPOWER" | tail -n 30 || true

echo "=== 5. SERVICE STATUS ==="
systemctl status trading-options trading-stock --no-pager -l | grep -E "Active:|Loaded:" || true
'''

for vm in VMS:
    print(f"\n{'='*60}\nInspecting {vm['name']} ({vm['ip']})...\n{'='*60}")
    script = (
        BASH_SCRIPT
        .replace("__DIR__", vm["dir"])
        .replace("__VENV_PY__", vm["venv_py"])
        .replace("__AK__", vm["ak"])
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    ).encode("utf-8")
    
    p = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm['ip']}", "bash -s"],
        input=script,
        capture_output=True
    )
    print(p.stdout.decode("utf-8", errors="replace"))
    if p.stderr:
        print("STDERR:", p.stderr.decode("utf-8", errors="replace"))
