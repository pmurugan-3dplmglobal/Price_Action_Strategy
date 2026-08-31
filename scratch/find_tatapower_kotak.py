import sqlite3
import json
import os
import glob

print("==================================================")
print(" SEARCHING FOR TATAPOWER & KOTAKBANK TRADES")
print("==================================================")

# 1. SQLite
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE symbol LIKE '%TATAPOWER%' OR contract LIKE '%TATAPOWER%' OR symbol LIKE '%KOTAK%' OR contract LIKE '%KOTAK%'")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"\n[1] SQLite trades found: {len(rows)}")
    for r in rows:
        d = dict(zip(cols, r))
        print(json.dumps(d, indent=2, default=str))
    conn.close()

# 2. executed_exit_orders.json
ex_path = os.path.join("output", "monitor", "executed_exit_orders.json")
if os.path.exists(ex_path):
    with open(ex_path, "r", encoding="utf-8") as f:
        ex = json.load(f)
    print(f"\n[2] executed_exit_orders.json:")
    for k, v in ex.items():
        if any(s in k.upper() for s in ["TATAPOWER", "KOTAK", "350CE", "420PE"]):
            print(f"  {k}: {v}")

# 3. trade_journal.csv
j_path = os.path.join("output", "monitor", "trade_journal.csv")
if os.path.exists(j_path):
    with open(j_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line.strip() for line in f if any(s in line.upper() for s in ["TATAPOWER", "KOTAK"])]
    print(f"\n[3] trade_journal.csv matches ({len(lines)}):")
    for l in lines[-15:]:
        print(f"  {l}")

# 4. Logs
print(f"\n[4] Logs matches:")
for log_f in glob.glob(os.path.join("output", "logs", "*.log")):
    with open(log_f, "r", encoding="utf-8", errors="ignore") as f:
        matches = [line.strip() for line in f if any(s in line.upper() for s in ["TATAPOWER", "KOTAKBANK"]) and any(w in line.upper() for w in ["EXIT", "SL", "ORDER", "CLOSED", "LIMIT", "CANCEL", "WARNING"])]
    if matches:
        print(f"  --- {log_f} ({len(matches)} matches) ---")
        for m in matches[-15:]:
            print(f"    {m}")
