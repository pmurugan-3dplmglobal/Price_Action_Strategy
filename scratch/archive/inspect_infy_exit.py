import os, sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import sqlite3, json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol='INFY'")
rows = c.fetchall()
print("=== INFY TRADES IN SQLITE ===")
for r in rows:
    print(f"ID: {r[0]} | Sym: {r[1]} | Status: {r[3]} | Created: {r[4]} | Updated: {r[5]}")
    if r[6]:
        d = json.loads(r[6])
        print(f"  Exit Price: {d.get('exit_price')} | PnL%: {d.get('pnl_percent')} | Details: {d.get('details')}")

print("\n=== LOG LINES FOR INFY AROUND 09:50 - 09:54 ===")
with open('output/logs/bull_nifty50_scanner.log', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if '2026-09-29' in line and any(t in line for t in ['09:50', '09:51', '09:52', '09:53', '09:54']):
            if 'INFY' in line or 'SL' in line or 'EXIT' in line:
                clean = line.strip().encode('ascii', errors='backslashreplace').decode('ascii')
                print(clean)
