import os
import sys
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt, timedelta

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from kiteconnect import KiteConnect
from session import load_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" TATAPOWER 350 CE EXIT AUDIT & MINUTE CANDLES")
print("==================================================")

# 1. SQLite trade record
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE contract LIKE '%TATAPOWER26SEP350CE%' ORDER BY id DESC LIMIT 1")
    r = cur.fetchone()
    cols = [d[0] for d in cur.description]
    t_dict = dict(zip(cols, r))
    print(f"\n[SQLite Trade Record ID {t_dict.get('id')}]:")
    print(f"  Status: {t_dict.get('status')}")
    print(f"  Data JSON: {json.dumps(json.loads(t_dict.get('data_json', '{}')), indent=2)}")
    conn.close()

# 2. Executed exit order details
ex_path = os.path.join("output", "monitor", "executed_exit_orders.json")
if os.path.exists(ex_path):
    with open(ex_path) as f:
        ex = json.load(f)
    print(f"\n[executed_exit_orders.json]:")
    print(f"  {ex.get('TATAPOWER26SEP350CE')}")

# 3. 1-Minute Candles from 09:15 to 10:00 AM
tok = 39223298
from_d = (dt.now() - timedelta(days=2)).strftime("%Y-%m-%d")
to_d = dt.now().strftime("%Y-%m-%d")
candles = kite.historical_data(tok, from_d, to_d, "minute")
df = pd.DataFrame(candles)
if not df.empty:
    df['date'] = pd.to_datetime(df['date'])
    today_df = df[df['date'].dt.date == dt.now().date()]
    print(f"\n[1-Minute Candles on 2026-08-31 for TATAPOWER 350 CE]:")
    for idx, row in today_df.head(45).iterrows():
        print(f"  {row['date'].strftime('%H:%M')} | O: {row['open']:.2f} | H: {row['high']:.2f} | L: {row['low']:.2f} | C: {row['close']:.2f} | V: {row['volume']}")
