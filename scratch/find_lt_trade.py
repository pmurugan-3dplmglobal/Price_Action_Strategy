import sqlite3
import json
import os
import glob

print("==================================================")
print(" SEARCHING FOR LT TRADES ACROSS ALL DATA SOURCES")
print("==================================================")

# 1. SQLite
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE symbol LIKE '%LT%' OR contract LIKE '%LT%'")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"\n[1] SQLite trades found: {len(rows)}")
    for r in rows:
        d = dict(zip(cols, r))
        print(json.dumps(d, indent=2, default=str))
    conn.close()

# 2. trades_db.json
tb_path = os.path.join("output", "monitor", "trades_db.json")
if os.path.exists(tb_path):
    with open(tb_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"\n[2] trades_db.json:")
    for section in ["active_positions", "completed_trades", "cycle_trades"]:
        items = data.get(section, {})
        if isinstance(items, dict):
            for k, v in items.items():
                if "LT" in str(k).upper() or "LT" in str(v).upper():
                    print(f"  {section} -> {k}: {v}")
        elif isinstance(items, list):
            for item in items:
                if "LT" in str(item).upper():
                    print(f"  {section} -> {item}")

# 3. executed_exit_orders.json
ex_path = os.path.join("output", "monitor", "executed_exit_orders.json")
if os.path.exists(ex_path):
    with open(ex_path, "r", encoding="utf-8") as f:
        ex = json.load(f)
    print(f"\n[3] executed_exit_orders.json:")
    for k, v in ex.items():
        if "LT" in str(k).upper() or "LT" in str(v).upper():
            print(f"  {k}: {v}")

# 4. sl_target_overrides.json
ov_path = os.path.join("output", "monitor", "sl_target_overrides.json")
if os.path.exists(ov_path):
    with open(ov_path, "r", encoding="utf-8") as f:
        ov = json.load(f)
    print(f"\n[4] sl_target_overrides.json:")
    for k, v in ov.items():
        if "LT" in str(k).upper() or "LT" in str(v).upper():
            print(f"  {k}: {v}")

# 5. trade_journal.csv
j_path = os.path.join("output", "monitor", "trade_journal.csv")
if os.path.exists(j_path):
    with open(j_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line.strip() for line in f if "LT" in line.upper()]
    print(f"\n[5] trade_journal.csv matches ({len(lines)}):")
    for l in lines[-10:]:
        print(f"  {l}")

# 6. Grep logs
print(f"\n[6] Recent log mentions for LT in output/logs:")
for log_f in glob.glob(os.path.join("output", "logs", "*.log")):
    if os.path.exists(log_f):
        with open(log_f, "r", encoding="utf-8", errors="ignore") as f:
            matches = [line.strip() for line in f if "LT" in line.upper() and ("EXIT" in line.upper() or "SL" in line.upper() or "4000" in line.upper())]
        if matches:
            print(f"  --- {log_f} ({len(matches)} matches) ---")
            for m in matches[-10:]:
                print(f"    {m}")
