import sqlite3
import pandas as pd
import json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
df_raw = pd.read_sql_query("SELECT * FROM trades", conn)
conn.close()

records = []
for idx, row in df_raw.iterrows():
    rec = row.to_dict()
    data = {}
    if rec['data_json']:
        try:
            data = json.loads(rec['data_json'])
        except Exception:
            pass
    records.append({**rec, **data})

df = pd.DataFrame(records)
df_real = df[~df['symbol'].str.contains('TEST|GHOST|MOCK', case=False, na=False) & ~df['engine'].str.contains('test', case=False, na=False)]
has_pnl = df_real[df_real['pnl_percent'].notna()].copy()
losses = has_pnl[has_pnl['pnl_percent'] < 0].copy()

# Sort losses
losses_sorted = losses.sort_values(by='pnl_percent')
for idx, r in losses_sorted.iterrows():
    print(f"ID {r['id']:4d} | PnL: {r['pnl_percent']:6.2f}% | Status: {r['status']:12s} | Details: {str(r.get('details'))[:45]}")

print("\nLosses < -8.0%:")
sub29 = losses[losses['pnl_percent'] < -8.0]
print(f"Count: {len(sub29)}, Mean: {sub29['pnl_percent'].mean():.4f}%")

print("\nLosses with status == 'SL_HIT' and loss < -5%:")
sub_sl = losses[(losses['status'] == 'SL_HIT') & (losses['pnl_percent'] < -5.0)]
print(f"Count: {len(sub_sl)}, Mean: {sub_sl['pnl_percent'].mean():.4f}%")

print("\nLosses excluding small scratches (< -5.0% and status == 'SL_HIT'):")
sub_all = losses[losses['pnl_percent'] <= -7.16]
print(f"Count: {len(sub_all)}, Mean: {sub_all['pnl_percent'].mean():.4f}%")
