import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
py_code = """
import json, os, sqlite3, sys
sys.path.insert(0, os.path.abspath("common"))
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
print("=== POWERGRID ORDERS ===")
for o in orders:
    if "POWERGRID" in o.get("tradingsymbol", ""):
        t = o.get("order_timestamp")
        tt = o.get("transaction_type")
        qty = o.get("quantity")
        ap = o.get("average_price")
        p = o.get("price")
        st = o.get("status")
        msg = o.get("status_message") or ""
        print(f"[{t}] {tt} {o.get('tradingsymbol')} {qty} @ avg={ap} p={p} -> {st} {msg}")

# Also check trades.sqlite3
conn = sqlite3.connect("output/monitor/trades.sqlite3")
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%POWERGRID%' OR contract LIKE '%POWERGRID%' ORDER BY id DESC LIMIT 5")
rows = c.fetchall()
print("=== POWERGRID DB TRADES ===")
for r in rows:
    tid, sym, cnt, st, cat, uat, dj = r
    d = json.loads(dj) if dj else {}
    print(f"ID: {tid} | {sym} ({cnt}) | Status: {st} | ExitReason: {d.get('exit_reason')} | Entry: {d.get('entry_spot') or d.get('entry_price')} | Exit: {d.get('exit_price')} | SL: {d.get('current_sl')} | T1: {d.get('t1')} | PnL: {d.get('pnl')}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=py_code, capture_output=True, text=True)
print(res.stdout or res.stderr)
