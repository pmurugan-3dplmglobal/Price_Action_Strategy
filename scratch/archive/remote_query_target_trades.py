import sys
import os
import sqlite3
import json

db_path = os.path.expanduser("~/Price_Action_Strategy/output/monitor/trades.sqlite3")
if not os.path.exists(db_path):
    db_path = os.path.expanduser("~/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3")

if not os.path.exists(db_path):
    print("Database not found at expected paths")
    sys.exit(0)

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT id, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%MOTHERSON%' OR contract LIKE '%SBILIFE%' OR contract LIKE '%COLPAL%' OR symbol IN ('MOTHERSON', 'SBILIFE', 'COLPAL') ORDER BY id DESC LIMIT 10")
rows = c.fetchall()
print("Total rows found:", len(rows))
for r in rows:
    tid, sym, cnt, stat, dj_str, cat, uat = r
    print("-" * 50)
    print(f"ID={tid} | {sym} | {cnt} | status={stat} | created={cat} | updated={uat}")
    try:
        dj = json.loads(dj_str)
        for k in ['entry_price', 'current_sl', 'spot_sl', 't1', 't2', 'exit_price', 'exit_reason', 'pnl', 'pattern', 'timeframe', 'side', 'tier_label', 'mfe_pct', 'mae_pct', 'order_id', 'exit_order_id']:
            if k in dj:
                print(f"  {k}: {dj[k]}")
    except Exception as e:
        print("  Error:", e)

conn.close()
