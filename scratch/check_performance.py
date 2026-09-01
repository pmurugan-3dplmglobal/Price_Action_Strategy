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
    cur.execute("SELECT count(*), status FROM trades GROUP BY status")
    status_counts = cur.fetchall()
    print("=== OVERALL TRADE STATUS COUNTS ===")
    for count, status in status_counts:
        print(f"  {status:15s}: {count}")

    cur.execute("SELECT id, engine, symbol, contract, status, data_json FROM trades")
    rows = cur.fetchall()
    
    total_trades = 0
    wins = 0
    losses = 0
    total_pnl_pct = 0.0
    
    for tid, engine, sym, contract, status, djson in rows:
        d = json.loads(djson) if djson else {}
        pnl = d.get('pnl')
        pnl_pct = d.get('pnl_pct')
        exit_reason = d.get('exit_reason', '')
        
        if status in ['TARGET_HIT', 'COMPLETED', 'SL_HIT'] or pnl is not None or pnl_pct is not None:
            total_trades += 1
            if status == 'TARGET_HIT' or (pnl is not None and pnl > 0) or (pnl_pct is not None and pnl_pct > 0):
                wins += 1
            elif status == 'SL_HIT' or (pnl is not None and pnl < 0) or (pnl_pct is not None and pnl_pct < 0):
                losses += 1
                
    print("\n=== PERFORMANCE OVERVIEW ===")
    print(f"Total Completed / Closed Setups Tracked: {total_trades}")
    print(f"Winning Setups: {wins}")
    print(f"Losing / SL Setups: {losses}")
    if (wins + losses) > 0:
        win_rate = (wins / (wins + losses)) * 100
        print(f"Win Rate: {win_rate:.1f}%")
        
    conn.close()
