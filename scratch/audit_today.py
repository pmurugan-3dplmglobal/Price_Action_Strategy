import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sqlite3
import json
import csv
from common import paths

today_str = "2026-08-31"

print(f"=== DETAILED AUDIT FOR DATE: {today_str} ===\n")

# 1. Inspect Active Positions
print("--- 1. ACTIVE POSITIONS ---")
if os.path.exists(paths.ACTIVE_POSITIONS_DB):
    try:
        with open(paths.ACTIVE_POSITIONS_DB, 'r', encoding='utf-8') as f:
            active = json.load(f)
            print(f"Active positions count: {len(active)}")
            for k, v in active.items():
                print(f"[{k}] {v.get('symbol')} | Contract: {v.get('contract') or v.get('tradingsymbol')} | Entry: {v.get('entry_price')} | Current: {v.get('current_price')} | P&L: {v.get('pnl')} ({v.get('pnl_pct')}%) | SL: {v.get('sl')} | T1: {v.get('t1')} | T2: {v.get('t2')}")
    except Exception as e:
        print("Error reading active positions:", e)

# 2. Inspect SQLite DB for Today's Trades
print("\n--- 2. SQLITE3 TRADES TABLE (TODAY) ---")
db_path = os.path.join(os.path.dirname(paths.TRADES_DB), 'trades.sqlite3')
if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        for tname in tables:
            print(f"\nTable: {tname}")
            cur.execute(f"SELECT * FROM {tname} WHERE entry_time LIKE '{today_str}%' OR exit_time LIKE '{today_str}%'")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print(f"Found {len(rows)} records for today:")
            for r in rows:
                d = dict(zip(cols, r))
                print(f" -> Symbol: {d.get('symbol')} | Contract: {d.get('contract')} | Status: {d.get('status')} | Entry: {d.get('entry_price')} @ {d.get('entry_time')} | Exit: {d.get('exit_price')} @ {d.get('exit_time')} | PnL: {d.get('pnl')} ({d.get('pnl_pct')}%) | Exit Reason: {d.get('exit_reason')} | Setup: {d.get('pattern')} | SL: {d.get('sl')} | Target: {d.get('target') or d.get('t1')}")
        conn.close()
    except Exception as e:
        print("Error reading SQLite3:", e)

# 3. Inspect trades_db.json
print("\n--- 3. TRADES_DB.JSON (TODAY) ---")
if os.path.exists(paths.TRADES_DB):
    try:
        with open(paths.TRADES_DB, 'r', encoding='utf-8') as f:
            trades = json.load(f)
            today_trades = {k: v for k, v in trades.items() if str(v.get('entry_time', '')).startswith(today_str) or str(v.get('exit_time', '')).startswith(today_str)}
            print(f"Total today's trades in trades_db.json: {len(today_trades)}")
            for k, v in today_trades.items():
                print(f"[{k}] {v.get('symbol')} ({v.get('contract') or v.get('tradingsymbol')}) | Status: {v.get('status')} | Entry: {v.get('entry_price')} @ {v.get('entry_time')} | Exit: {v.get('exit_price')} @ {v.get('exit_time')} | PnL: {v.get('pnl')} ({v.get('pnl_pct')}%) | Reason: {v.get('exit_reason')} | SL: {v.get('sl')} | T1: {v.get('t1')} | T2: {v.get('t2')} | Tier: {v.get('tier')} | Pattern: {v.get('pattern')}")
    except Exception as e:
        print("Error reading trades_db.json:", e)

# 4. Inspect Trade Journal for Today
print("\n--- 4. TRADE JOURNAL CSV (TODAY) ---")
if os.path.exists(paths.TRADE_JOURNAL_CSV):
    try:
        with open(paths.TRADE_JOURNAL_CSV, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f, delimiter='\t')
            headers = next(reader, None)
            today_journal_rows = []
            for row in reader:
                if row and len(row) > 0 and row[0].startswith(today_str):
                    today_journal_rows.append(row)
            print(f"Total journal entries for today: {len(today_journal_rows)}")
            print("Header:", headers)
            for r in today_journal_rows:
                print(" | ".join(r))
    except Exception as e:
        print("Error reading trade journal:", e)

# 5. Scan Display Snapshot for Today
print("\n--- 5. SCAN DISPLAY (TODAY'S SIGNALS) ---")
for s_name, s_file in [("Nifty50 Options", paths.SCAN_DISPLAY_FILE), ("Index Options", paths.SCAN_DISPLAY_INDEX_FILE), ("Stock Bull", paths.SCAN_DISPLAY_STOCK_FILE), ("Stock Bear", paths.SCAN_DISPLAY_BEAR_FILE)]:
    if os.path.exists(s_file):
        try:
            with open(s_file, 'r', encoding='utf-8') as f:
                s_data = json.load(f)
                items = s_data.get('data', []) if isinstance(s_data, dict) else s_data
                today_items = [item for item in items if str(item.get('date', '')).startswith(today_str) or str(item.get('candle_time', '')).startswith(today_str) or str(item.get('entry_time', '')).startswith(today_str)]
                print(f"{s_name}: {len(today_items)} items detected for today")
                for item in today_items[:5]:
                    print("  ->", item.get('symbol'), item.get('pattern'), item.get('side'), item.get('strike'), item.get('entry'), item.get('sl'), item.get('rr'), item.get('tier'))
        except Exception as e:
            print(f"Error reading {s_name}:", e)
