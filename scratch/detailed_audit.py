import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sqlite3
import json
from common import paths

today_str = "2026-08-31"

print("=====================================================================")
print("                   TODAY'S EXECUTED TRADES (2026-08-31)")
print("=====================================================================")

db_path = os.path.join(os.path.dirname(paths.TRADES_DB), 'trades.sqlite3')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, contract, status, data_json, created_at, updated_at FROM trades")
    rows = cur.fetchall()
    
    today_trades = []
    for r in rows:
        tid, engine, sym, contract, status, djson, cat, uat = r
        try:
            d = json.loads(djson) if djson else {}
        except Exception:
            d = {}
        entry_time = d.get('entry_time', '') or cat or ''
        exit_time = d.get('exit_time', '') or uat or ''
        if str(entry_time).startswith(today_str) or str(exit_time).startswith(today_str) or str(cat).startswith(today_str) or str(uat).startswith(today_str):
            today_trades.append((tid, engine, sym, contract, status, d, cat, uat))
            
    print(f"Total trades found for today: {len(today_trades)}")
    for tid, engine, sym, contract, status, d, cat, uat in today_trades:
        print(f"\n[ID #{tid}] [{status}] {sym} ({contract}) | Engine: {engine}")
        print(f"   Entry: {d.get('entry_price')} @ {d.get('entry_time')}")
        print(f"   Exit:  {d.get('exit_price')} @ {d.get('exit_time')}")
        print(f"   Current/Close Price: {d.get('current_price')} | P&L: {d.get('pnl')} ({d.get('pnl_pct')}%)")
        print(f"   Exit Reason: {d.get('exit_reason')}")
        print(f"   SL: {d.get('sl')} (Orig SL: {d.get('orig_sl')}) | T1: {d.get('t1')} | T2: {d.get('t2')} | T3: {d.get('t3')}")
        print(f"   Setup: Pattern={d.get('pattern')} | Anchor={d.get('anchor_pattern')} | Tier={d.get('tier')} | Side={d.get('side')} | Strike={d.get('strike')}")
        print(f"   Trailing History: {d.get('trailing_history', [])}")
    conn.close()

print("\n=====================================================================")
print("                      ACTIVE POSITIONS AT CLOSE")
print("=====================================================================")
if os.path.exists(paths.ACTIVE_POSITIONS_DB):
    with open(paths.ACTIVE_POSITIONS_DB, 'r', encoding='utf-8') as f:
        active = json.load(f)
        print(f"Active positions count: {len(active)}")
        for k, v in active.items():
            print(f"Symbol: {v.get('symbol')} | Contract: {v.get('contract') or v.get('tradingsymbol')}")
            print(f"  Entry: {v.get('entry_price')} @ {v.get('entry_time')}")
            print(f"  Current Price: {v.get('current_price')} | P&L: {v.get('pnl')} ({v.get('pnl_pct')}%)")
            print(f"  SL: {v.get('sl')} (Original: {v.get('orig_sl')}) | T1: {v.get('t1')} | T2: {v.get('t2')}")
            print(f"  Tier: {v.get('tier')} | Pattern: {v.get('pattern')} | Trailing State: {v.get('trailing_state', 'N/A')}")
            print("  -------------------------------------------------------------")

print("\n=====================================================================")
print("                   TODAY'S TRADE JOURNAL EVENTS")
print("=====================================================================")
if os.path.exists(paths.TRADE_JOURNAL_CSV):
    with open(paths.TRADE_JOURNAL_CSV, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip() for l in f if l.startswith(today_str)]
        print(f"Total journal records today: {len(lines)}")
        for l in lines:
            parts = l.split('\t')
            print(" | ".join(parts))
