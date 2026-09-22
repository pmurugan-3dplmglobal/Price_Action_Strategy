import sqlite3
import json
import os

db_path = "output/monitor/trades.sqlite3"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE id=793")
    row = cur.fetchone()
    if row:
        print("Trade 793:")
        for k in row.keys():
            print(f"  {k}: {row[k]}")
    else:
        print("Trade 793 not found in trades table")
    
    cur.execute("SELECT id, symbol, contract, status, created_at FROM trades WHERE symbol='APLAPOLLO' ORDER BY id DESC")
    print("\nAll APLAPOLLO trades:")
    for r in cur.fetchall():
        print(f"  ID {r['id']}: {r['symbol']} | {r['contract']} | {r['status']} | {r['created_at']}")

with open("output/monitor/stock_positions_state.json", "r") as f:
    state = json.load(f)
    print("\nAPLAPOLLO in state file:")
    print(json.dumps(state.get("APLAPOLLO"), indent=2))
