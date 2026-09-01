import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import csv
import json
import sqlite3
from common import paths

print("=== AUDITING ALL ADANI TRADES & SCANS ===")

# 1. Search in trade_journal.csv
print("\n--- 1. TRADE JOURNAL (ADANI) ---")
if os.path.exists(paths.TRADE_JOURNAL_CSV):
    with open(paths.TRADE_JOURNAL_CSV, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader, None)
        print("Header:", header)
        for row in reader:
            if row and len(row) > 1 and ("ADANI" in row[1] or "ADANI" in str(row)):
                print(" | ".join(row))

# 2. Search in trades.sqlite3
print("\n--- 2. SQLITE3 TRADES DB (ADANI) ---")
db_path = os.path.join(os.path.dirname(paths.TRADES_DB), 'trades.sqlite3')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE symbol LIKE '%ADANI%' OR contract LIKE '%ADANI%'")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    for r in rows:
        d = dict(zip(cols, r))
        print(f"[{d.get('status')}] {d.get('symbol')} ({d.get('contract')}) | Engine: {d.get('engine')}")
        print(f"  JSON: {d.get('data_json')}")
    conn.close()

# 3. Search in trades_db.json
print("\n--- 3. TRADES_DB.JSON (ADANI) ---")
if os.path.exists(paths.TRADES_DB):
    with open(paths.TRADES_DB, 'r', encoding='utf-8') as f:
        try:
            trades = json.load(f)
            for k, v in trades.items():
                if "ADANI" in str(k) or "ADANI" in str(v.get('symbol', '')) or "ADANI" in str(v.get('contract', '')):
                    print(f"Key: {k}")
                    print(json.dumps(v, indent=2))
        except Exception as e:
            print("Error reading trades_db.json:", e)

# 4. Search in scan_display.json
print("\n--- 4. SCAN_DISPLAY (ADANI) ---")
for s_name, s_file in [("Nifty50 Options", paths.SCAN_DISPLAY_FILE), ("Stock Bull", paths.SCAN_DISPLAY_STOCK_FILE), ("Stock Bear", paths.SCAN_DISPLAY_BEAR_FILE)]:
    if os.path.exists(s_file):
        with open(s_file, 'r', encoding='utf-8') as f:
            try:
                s_data = json.load(f)
                items = s_data.get('data', []) if isinstance(s_data, dict) else s_data
                for item in items:
                    if "ADANI" in str(item.get('symbol', '')) or "ADANI" in str(item.get('contract', '')):
                        print(f"{s_name}: {item.get('symbol')} | {item.get('side')} | {item.get('strike')} | Entry: {item.get('entry')} | SL: {item.get('sl')} | T1: {item.get('t1')} | T2: {item.get('t2')} | RR: {item.get('rr')}")
            except Exception as e:
                print(f"Error reading {s_name}:", e)
