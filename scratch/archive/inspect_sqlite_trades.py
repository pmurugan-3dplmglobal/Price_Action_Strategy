import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3
from common.paths import monitor_file

db_path = monitor_file("trades.sqlite3")
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("PRAGMA table_info(trades)")
cols = [r[1] for r in c.fetchall()]
print("Columns:", cols)

c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 25")
rows = c.fetchall()
print(f"=== RECENT TRADES IN SQLite ({len(rows)} rows) ===")
for r in rows:
    d = dict(zip(cols, r))
    print(f"ID={d.get('id')} sym={d.get('symbol')} contract={d.get('contract')} status={d.get('status')} entry={d.get('entry_time')} exit={d.get('exit_time')} pnl={d.get('pnl')}")

conn.close()
