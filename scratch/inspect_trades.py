import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sqlite3
import json
import csv
from datetime import datetime
from common import paths

print("=" * 70)
print("             TODAY'S TRADES & RECENT TRADE ACTIVITY AUDIT")
print("=" * 70)

# 1. Check Active Positions
print("\n--- ACTIVE POSITIONS ---")
if os.path.exists(paths.ACTIVE_POSITIONS_DB):
    with open(paths.ACTIVE_POSITIONS_DB, 'r', encoding='utf-8') as f:
        try:
            active = json.load(f)
            print(f"Total active positions: {len(active)}")
            print(json.dumps(active, indent=2))
        except Exception as e:
            print("Error reading active positions:", e)

# 2. Check trades.sqlite3
print("\n--- SQLITE3 TRADES DB ---")
db_path = os.path.join(os.path.dirname(paths.TRADES_DB), 'trades.sqlite3')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    for tname in tables:
        print(f"\nTable: {tname}")
        cur.execute(f"SELECT * FROM {tname} ORDER BY rowid DESC LIMIT 15")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        for r in rows:
            print(dict(zip(cols, r)))
    conn.close()

# 3. Check trades_db.json
print("\n--- TRADES_DB.JSON ---")
if os.path.exists(paths.TRADES_DB):
    with open(paths.TRADES_DB, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            print(f"Total records: {len(data)}")
            for k, v in list(data.items())[-15:]:
                print(f"Key: {k}")
                print(f"  Symbol: {v.get('symbol')} | Contract: {v.get('contract') or v.get('tradingsymbol')}")
                print(f"  Entry Time: {v.get('entry_time')} | Exit Time: {v.get('exit_time')}")
                print(f"  Entry Price: {v.get('entry_price')} | Exit Price: {v.get('exit_price')}")
                print(f"  P&L: {v.get('pnl')} ({v.get('pnl_pct')}%) | Status: {v.get('status')}")
                print(f"  Exit Reason: {v.get('exit_reason')} | Setup: {v.get('pattern')} / {v.get('anchor_pattern')}")
        except Exception as e:
            print("Error:", e)

# 4. Check trade_journal.csv recent lines
print("\n--- RECENT TRADE JOURNAL CSV ENTRIES ---")
if os.path.exists(paths.TRADE_JOURNAL_CSV):
    with open(paths.TRADE_JOURNAL_CSV, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        print(f"Total journal lines: {len(lines)}")
        print("Header:", lines[0] if lines else "")
        for line in lines[-10:]:
            print(line.strip())

# 5. Check executed patterns / cycle trades
print("\n--- EXECUTED PATTERNS & CYCLE TRADES ---")
if os.path.exists(paths.EXECUTED_STORE_FILE):
    with open(paths.EXECUTED_STORE_FILE, 'r', encoding='utf-8') as f:
        try:
            ex_pat = json.load(f)
            print(f"Executed patterns ({len(ex_pat)}):", list(ex_pat.items())[-10:])
        except Exception as e:
            print("Error reading executed patterns:", e)

if os.path.exists(paths.CYCLE_STORE_FILE):
    with open(paths.CYCLE_STORE_FILE, 'r', encoding='utf-8') as f:
        try:
            cycle = json.load(f)
            print(f"Cycle trades ({len(cycle)}):", list(cycle.items())[-10:])
        except Exception as e:
            print("Error reading cycle trades:", e)
