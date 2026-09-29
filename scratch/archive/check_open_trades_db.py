import sqlite3, json

conn = sqlite3.connect("output/monitor/trades.sqlite3")
symbols = ('BAJAJFINSV', 'APLAPOLLO', 'WIPRO', 'ASIANPAINT', 'CANBK', 'JSWENERGY', 'GODREJPROP')
placeholders = ','.join('?' for _ in symbols)
rows = conn.execute(f"SELECT id, engine, symbol, contract, status, created_at, updated_at FROM trades WHERE symbol IN ({placeholders}) ORDER BY id DESC LIMIT 15", symbols).fetchall()
print("=== TRADES IN DB FOR OPEN SYMBOLS ===")
for r in rows:
    print(r)
