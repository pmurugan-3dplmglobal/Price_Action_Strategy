import sqlite3
import json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("""
    SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json 
    FROM trades 
    WHERE id >= 1158 
    ORDER BY id DESC
""")
rows = c.fetchall()

print(f"Total trades fetched: {len(rows)}")
for r in rows:
    tid, engine, sym, contract, status, cat, uat, data_str = r
    print(f"\n==========================================")
    print(f"Trade ID: {tid} | Engine: {engine} | Symbol: {sym} | Contract: {contract} | Status: {status}")
    print(f"Created: {cat} | Updated: {uat}")
    if data_str:
        try:
            d = json.loads(data_str)
            print(f"  Pattern: {d.get('pattern')} | Tier: {d.get('tier')} | Direction: {d.get('direction')}")
            print(f"  Entry Price: {d.get('entry_price')} | Entry Spot: {d.get('entry_spot')}")
            print(f"  Current SL: {d.get('current_sl')} | Initial SL: {d.get('initial_sl')}")
            print(f"  T1: {d.get('t1')} | T2: {d.get('t2')} | T3: {d.get('t3')}")
            print(f"  RR: {d.get('rr')} | Exit Price: {d.get('exit_price')} | PnL%: {d.get('pnl_percent')}")
            print(f"  Details: {d.get('details')}")
        except Exception as e:
            print(f"  Error parsing data_json: {e}")
