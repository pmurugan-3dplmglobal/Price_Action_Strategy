import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sqlite3
import json
from common import paths

db_path = os.path.join(os.path.dirname(paths.TRADES_DB), 'trades.sqlite3')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, contract, status, data_json, created_at, updated_at FROM trades ORDER BY id DESC LIMIT 50")
    rows = cur.fetchall()
    
    print("=== LAST 50 TRADES AUDIT ===")
    for tid, engine, sym, contract, status, djson, cat, uat in rows:
        d = json.loads(djson) if djson else {}
        entry_t = d.get('entry_time', '') or cat
        exit_t = d.get('exit_time', '') or uat
        reason = d.get('exit_reason', '')
        pattern = d.get('pattern', '')
        pnl = d.get('pnl')
        pnl_pct = d.get('pnl_pct')
        entry_p = d.get('entry_price')
        exit_p = d.get('exit_price')
        print(f"ID #{tid:3d} | {sym:12s} | {contract:20s} | Status: {status:12s} | Pattern: {pattern:15s} | Reason: {str(reason)[:25]:25s} | Entry: {str(entry_p):6s} | Exit: {str(exit_p):6s} | EntryTime: {str(entry_t)[:19]}")
    conn.close()
