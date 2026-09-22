import json
import sqlite3

monitor = "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor"

print("=== EXECUTED EXIT FOR PFC ===")
with open(f"{monitor}/executed_exit_orders.json") as f:
    d = json.load(f)
    for k, v in d.items():
        if "PFC" in k or "PFC" in str(v):
            print(k, ":", v)

print("\n=== SQLITE SCHEMA & RECENT ROWS ===")
conn = sqlite3.connect(f"{monitor}/trades.sqlite3")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("PRAGMA table_info(trades)")
cols = [r["name"] for r in c.fetchall()]
print("Columns in trades table:", cols)

c.execute("SELECT * FROM trades WHERE symbol LIKE '%PFC%' OR contract LIKE '%PFC%' ORDER BY id DESC LIMIT 5")
for r in c.fetchall():
    print(dict(r))

print("\n=== ACTIVE POSITIONS DB ===")
with open(f"{monitor}/active_positions_db.json") as f:
    print(f.read())
