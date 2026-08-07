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

print("=== DB RECORD FOR JIOFIN ===")
p_act = 'Trade_Option/output/monitor/active_positions_db.json'
jio_pos = None
if os.path.exists(p_act):
    with open(p_act) as f:
        data = json.load(f)
    for p in data.get('positions', []):
        if 'JIOFIN' in str(p.get('contract', '')) or 'JIOFIN' in str(p.get('symbol', '')):
            jio_pos = p
            print(json.dumps(p, indent=2))

token = jio_pos.get('option_token') if jio_pos else None
if not token:
    # Lookup token
    res = kite.quote(['NFO:JIOFIN26AUG265PE'])
    token = res.get('NFO:JIOFIN26AUG265PE', {}).get('instrument_token')
    print("Fetched token from Kite:", token)

print("\n=== LIVE QUOTE ===")
q = kite.quote(['NFO:JIOFIN26AUG265PE'])
print(json.dumps(q, indent=2, default=str))

print("\n=== TODAY CANDLES (15min) ===")
dt_today = datetime.now().strftime("%Y-%m-%d")
df = fetch_and_resample_candles(kite, token, dt_today, dt_today, "15minute")
if not df.empty:
    print(df[['date', 'open', 'high', 'low', 'close']])
else:
    print("No candles returned for today")

print("\n=== RECENT JOURNALTRAIL / SYSTEMD LOGS FOR JIOFIN ===")
