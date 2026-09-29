import sqlite3, json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE contract LIKE '%23350%'")
rows = cur.fetchall()
print(f"Found {len(rows)} rows for 23350 in trades.sqlite3:")
for r in rows:
    d = json.loads(r['data_json']) if r['data_json'] else {}
    print(f"ID:{r['id']} {r['engine']} {r['symbol']} ({r['contract']}) Stat:{r['status']} Created:{r['created_at']} Upd:{r['updated_at']}")
    print(f"  Entry:{d.get('entry_spot') or d.get('entry_price')} SL:{d.get('current_sl')} T1:{d.get('t1')}")
