import sqlite3
import json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM trades WHERE contract LIKE '%COALINDIA%' OR symbol = 'COALINDIA'").fetchall()
print(f"Total rows for COALINDIA: {len(rows)}")
for r in rows:
    print(f"ID: {r['id']} | status: {r['status']} | created_at: {r['created_at']} | updated_at: {r['updated_at']}")
    data = json.loads(r['data_json']) if r['data_json'] else {}
    for k, v in data.items():
        print(f"   {k}: {v}")
    print("=" * 60)
