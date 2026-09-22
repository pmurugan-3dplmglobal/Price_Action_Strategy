import sqlite3
import json
import csv
import glob
import os

print("=== CHECKING trade_journal.csv ===")
if os.path.exists('output/monitor/trade_journal.csv'):
    with open('output/monitor/trade_journal.csv', 'r') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        print("Header:", header)
        for row in reader:
            if any('OIL' in str(col) for col in row):
                print("ROW:", row)

print("\n=== CHECKING executed_exit_orders.json ===")
if os.path.exists('output/monitor/executed_exit_orders.json'):
    with open('output/monitor/executed_exit_orders.json', 'r') as f:
        data = json.load(f)
        for k, v in data.items():
            if 'OIL' in str(k) or 'OIL' in str(v):
                print(k, "->", v)

print("\n=== CHECKING trades.sqlite3 ===")
if os.path.exists('output/monitor/trades.sqlite3'):
    conn = sqlite3.connect('output/monitor/trades.sqlite3')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables:", tables)
    for (t,) in tables:
        cursor.execute(f"PRAGMA table_info({t});")
        cols = [c[1] for c in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM {t}")
        rows = cursor.fetchall()
        for r in rows:
            if any('OIL' in str(x) for x in r):
                print(f"Table {t}:", dict(zip(cols, r)))
    conn.close()

print("\n=== CHECKING active_positions_db.json & trades_db.json ===")
for fname in ['active_positions_db.json', 'trades_db.json', 'journal_trades_db.json', 'cycle_trades.json', 'executed_patterns.json']:
    p = os.path.join('output/monitor', fname)
    if os.path.exists(p):
        try:
            with open(p, 'r') as f:
                d = json.load(f)
                s = json.dumps(d)
                if 'OIL' in s:
                    print(f"Found OIL in {fname}!")
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if 'OIL' in str(k) or 'OIL' in str(v):
                                print(f"  {k}: {v}")
                    elif isinstance(d, list):
                        for item in d:
                            if 'OIL' in str(item):
                                print(f"  {item}")
        except Exception as e:
            print(f"Error reading {fname}: {e}")
