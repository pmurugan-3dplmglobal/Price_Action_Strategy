import sqlite3
import json
import os
import subprocess

print("=== 1. LOCAL TRADES TODAY ===")
db = 'output/monitor/trades.sqlite3'
if os.path.exists(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("PRAGMA table_info(trades)")
    cols = [r[1] for r in c.fetchall()]
    print(f"Columns in trades table: {cols}")
    date_col = "created_at" if "created_at" in cols else "timestamp"
    c.execute(f"SELECT * FROM trades WHERE {date_col} LIKE '2026-09-22%'")
    rows = c.fetchall()
    print(f"Total trades today in local db: {len(rows)}")
    for r in rows:
        d = dict(r)
        print(f"{d.get('tradingsymbol')} | {d.get('symbol')} | Tier: {d.get('tier')} | Entry: {d.get('entry_price')} | Exit: {d.get('exit_price')} | PnL: {d.get('pnl')} | Status: {d.get('status')} | Exit Reason: {d.get('exit_reason')}")

print("\n=== 2. VM 2 (Bhavani) TRADES TODAY ===")
KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
    "sqlite3 -header -column /home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3 \"SELECT * FROM trades WHERE created_at LIKE '2026-09-22%';\""
]
res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout or res.stderr)

print("\n=== 3. VM 1 (Poovendan) TRADES TODAY ===")
cmd1 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "sqlite3 -header -column /home/opc/Price_Action_Strategy/output/monitor/trades.sqlite3 \"SELECT * FROM trades WHERE created_at LIKE '2026-09-22%';\""
]
res1 = subprocess.run(cmd1, capture_output=True, text=True)
print(res1.stdout or res1.stderr)
