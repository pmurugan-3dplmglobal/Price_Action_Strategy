import subprocess
import json

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VM_IP = '140.245.197.71'
VM_USER = 'opc'
VM_DIR = '/home/opc/Price_Action_Strategy'

REMOTE_SCRIPT = """
import json
from datetime import datetime as dt, timedelta
from common.session import load_kite_session
from kiteconnect import KiteConnect
from common import trading_core

k, t = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(t)

symbols = ['NSE:ATHERENERG', 'NFO:ATHERENERG26SEP1660PE']
q = kite.quote(symbols)
print('---QUOTE_START---')
print(json.dumps(q, default=str, indent=2))
print('---QUOTE_END---')

# Fetch candles for ATHERENERG spot and option
spot_tok = q.get('NSE:ATHERENERG', {}).get('instrument_token')
opt_tok = q.get('NFO:ATHERENERG26SEP1660PE', {}).get('instrument_token')

from_date = (dt.now() - timedelta(days=15)).strftime('%Y-%m-%d')
to_date = dt.now().strftime('%Y-%m-%d')

print('---SPOT_CANDLES_SUMMARY---')
if spot_tok:
    try:
        candles_spot = kite.historical_data(spot_tok, from_date, to_date, '15minute')
        print(f'Spot 15m candle count: {len(candles_spot)}')
        if candles_spot:
            print('Last 3 Spot 15m candles:', candles_spot[-3:])
    except Exception as e:
        print('Spot candle error:', e)

print('---OPTION_CANDLES_SUMMARY---')
if opt_tok:
    try:
        candles_opt = kite.historical_data(opt_tok, from_date, to_date, '15minute')
        print(f'Option 15m candle count: {len(candles_opt)}')
        if candles_opt:
            print('Last 3 Option 15m candles:', candles_opt[-3:])
    except Exception as e:
        print('Option candle error:', e)

# Check pattern funnel
f_path = 'output/monitor/pattern_funnel.json'
import os
if os.path.exists(f_path):
    with open(f_path) as f:
        funnel = json.load(f)
    print('---FUNNEL_START---')
    ather_items = [item for cat, items in funnel.get('nifty50', {}).items() for item in items if isinstance(item, dict) and 'ATHER' in str(item.get('symbol',''))]
    print(json.dumps(ather_items, indent=2))
    print('---FUNNEL_END---')

# Check scan display stock
sd_path = 'output/monitor/scan_display.json'
if os.path.exists(sd_path):
    with open(sd_path) as f:
        sd = json.load(f)
    print('---SCAN_DISPLAY_START---')
    staged = [item for item in sd.get('staged_trades', []) if 'ATHER' in str(item.get('symbol','')) or '1660' in str(item.get('contract',''))]
    print(json.dumps(staged, indent=2))
    print('---SCAN_DISPLAY_END---')
"""

cmd = [
    'ssh',
    '-i', SSH_KEY,
    '-o', 'StrictHostKeyChecking=no',
    f'{VM_USER}@{VM_IP}',
    f'cd {VM_DIR} && ./venv/bin/python -c "{REMOTE_SCRIPT}"'
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
