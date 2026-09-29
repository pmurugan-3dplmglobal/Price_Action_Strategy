import sqlite3, json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%NAUKRI%' OR contract LIKE '%NAUKRI%' ORDER BY id DESC")
rows = c.fetchall()
print(f"Total NAUKRI trades found: {len(rows)}")
for r in rows:
    tid, sym, cnt, st, cat, uat, dj = r
    d = json.loads(dj) if dj else {}
    print(f"ID: {tid} | {sym} ({cnt}) | Status: {st} | Created: {cat}")
    print(f"  Entry: {d.get('entry_price')} | Exit: {d.get('exit_price')} | Reason: {d.get('exit_reason')}")
    print(f"  SL: {d.get('current_sl')} | T1: {d.get('t1')} | Pattern: {d.get('pattern')}")
    print(f"  Spot Entry: {d.get('spot_entry')} | Spot SL: {d.get('spot_sl')} | Anchor High: {d.get('anchor_high')}")
