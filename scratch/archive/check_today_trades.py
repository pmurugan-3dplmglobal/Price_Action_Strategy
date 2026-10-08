import sqlite3
import json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM trades WHERE created_at LIKE '2026-10-07%' OR updated_at LIKE '2026-10-07%' ORDER BY id DESC").fetchall()
print(f"Total trades in DB today: {len(rows)}")
for r in rows:
    data = json.loads(r['data_json']) if r['data_json'] else {}
    print(f"ID: {r['id']} | Eng: {r['engine']} | Sym: {r['symbol']} | Contract: {r['contract']} | Status: {r['status']}")
    print(f"  Entry: {data.get('entry_price') or data.get('entry_spot')} | Exit: {data.get('exit_price')} | PnL: {data.get('pnl')} | ExitReason: {data.get('exit_reason')}")
    print(f"  Pattern: {data.get('pattern')} | Created: {r['created_at']} | ExitTime: {data.get('exit_time')}")
    print(f"  SL: {data.get('current_sl')} | T1: {data.get('t1')} | SpotSL: {data.get('spot_sl')} | SpotT1: {data.get('spot_t1')}")
    print("-" * 60)
