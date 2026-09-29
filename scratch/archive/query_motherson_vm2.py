
import sqlite3, json
db = '/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3'
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%MOTHERSON%' OR symbol LIKE '%MOTHERSON%' ORDER BY id DESC LIMIT 5")
rows = c.fetchall()
print(f"Total rows: {len(rows)}")
for r in rows:
    print('ID:', r[0], r[1], r[2], r[3], 'Created:', r[5], 'Updated:', r[6])
    try:
        dj = json.loads(r[4])
        for k in ['entry_price', 'current_sl', 'spot_sl', 't1', 't2', 'exit_price', 'exit_reason', 'pnl', 'pattern', 'timeframe', 'side', 'tier_label', 'mfe_pct', 'mae_pct', 'order_id', 'exit_order_id']:
            if k in dj:
                print(f"  {k}: {dj[k]}")
    except Exception as e:
        print('Error:', e)
conn.close()
