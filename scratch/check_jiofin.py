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
if os.path.exists(p_act):
    with open(p_act) as f:
        data = json.load(f)
    for p in data.get('positions', []):
        if 'JIOFIN' in str(p.get('contract', '')) or 'JIOFIN' in str(p.get('symbol', '')):
            print(json.dumps(p, indent=2))

print("\n=== SL TARGET OVERRIDES FOR JIOFIN ===")
p_ov = 'Trade_Option/output/monitor/sl_target_overrides.json'
if os.path.exists(p_ov):
    with open(p_ov) as f:
        ov = json.load(f)
    for sec in ov:
        for k in ov[sec]:
            if 'JIOFIN' in k:
                print(sec, k, ov[sec][k])

print("\n=== LIVE QUOTE ===")
q = kite.quote(['NFO:JIOFIN26AUG265PE'])
print("LTP:", q.get('NFO:JIOFIN26AUG265PE', {}).get('last_price'))
print("OHLC:", q.get('NFO:JIOFIN26AUG265PE', {}).get('ohlc'))

