import json
import os
import sys
from datetime import datetime

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from trading_core import load_kite_session, fetch_and_resample_candles
from kiteconnect import KiteConnect

api_k, acc_t = load_kite_session()
kite = KiteConnect(api_key=api_k, access_token=acc_t)

print("=== DB RECORD FOR ADANIENT ===")
p_act = 'Trade_Option/output/monitor/active_positions_db.json'
pos_info = None
if os.path.exists(p_act):
    with open(p_act) as f:
        data = json.load(f)
    for p in data.get('positions', []):
        if 'ADANIENT' in str(p.get('contract', '')) or 'ADANIENT' in str(p.get('symbol', '')):
            pos_info = p
            print(json.dumps(p, indent=2))

print("\n=== LIVE QUOTE ADANIENT26AUG3050CE ===")
q = kite.quote(['NFO:ADANIENT26AUG3050CE'])
print(json.dumps(q, indent=2, default=str))

pos_tf = pos_info.get('timeframe', '60minute') if pos_info else '60minute'
entry_time = pos_info.get('entry_time', '') if pos_info else ''
token = pos_info.get('option_token') if pos_info else 22533890

print(f"\n=== CANDLE HISTORY ({pos_tf}) ===")
dt_today = datetime.now().strftime("%Y-%m-%d")
df = fetch_and_resample_candles(kite, token, (datetime.now() - __import__('datetime').timedelta(days=2)).strftime("%Y-%m-%d"), dt_today, pos_tf)
if not df.empty:
    print(df[['date', 'open', 'high', 'low', 'close']])
else:
    print("No candles returned")

print("\n=== 15-MINUTE CANDLE HISTORY ===")
df15 = fetch_and_resample_candles(kite, token, dt_today, dt_today, "15minute")
if not df15.empty:
    print(df15[['date', 'open', 'high', 'low', 'close']])
