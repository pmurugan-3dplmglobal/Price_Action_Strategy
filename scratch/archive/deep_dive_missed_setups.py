import subprocess
import json

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VM_IP = '140.245.197.71'
VM_USER = 'opc'
VM_DIR = '/home/opc/Price_Action_Strategy'

REMOTE_SCRIPT = """
import json, os, sys
import pandas as pd
from datetime import datetime as dt, timedelta

from common.session import load_kite_session
from kiteconnect import KiteConnect
from common.trading_core import fetch_and_resample_candles
from common.resolve import scan_pattern_lifecycle_stage
from common.trading_core import (
    find_anchor_bullish_engulfing, find_anchor_ll_sweep,
    find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs
)

k, t = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(t)

from_date = (dt.now() - timedelta(days=10)).strftime('%Y-%m-%d')
to_date = dt.now().strftime('%Y-%m-%d')

targets = [
    {
        'sym': 'ASTRAL',
        'spot_token': 3677697, # NSE:ASTRAL
        'contract': 'ASTRAL26SEP1400PE',
        'opt_token': 18512130,
        'strike': 1400
    },
    {
        'sym': 'ATHERENERG',
        'spot_token': 193957121, # NSE:ATHERENERG
        'contract': 'ATHERENERG26SEP1660PE',
        'opt_token': 18543618,
        'strike': 1660
    }
]

# Verify tokens from quote
symbols_to_quote = ['NSE:ASTRAL', 'NFO:ASTRAL26SEP1400PE', 'NSE:ATHERENERG', 'NFO:ATHERENERG26SEP1660PE']
q = kite.quote(symbols_to_quote)
for t in targets:
    spot_q = q.get(f'NSE:{t[\"sym\"]}', {})
    opt_q = q.get(f'NFO:{t[\"contract\"]}', {})
    if spot_q.get('instrument_token'):
        t['spot_token'] = spot_q['instrument_token']
    if opt_q.get('instrument_token'):
        t['opt_token'] = opt_q['instrument_token']
    t['spot_ltp'] = spot_q.get('last_price')
    t['opt_ltp'] = opt_q.get('last_price')

print('=== TARGET METRICS RESOLVED ===')
print(json.dumps(targets, indent=2))

for t in targets:
    sym = t['sym']
    contract = t['contract']
    opt_tok = t['opt_token']
    spot_tok = t['spot_token']
    print(f'\\n=============================================================')
    print(f'           ANALYZING {sym} & {contract}')
    print(f'=============================================================')

    # 1. Fetch Option 30m and 15m candles
    df_opt_30m = fetch_and_resample_candles(kite, opt_tok, from_date, to_date, '30minute')
    df_opt_15m = fetch_and_resample_candles(kite, opt_tok, from_date, to_date, '15minute')
    df_spot_30m = fetch_and_resample_candles(kite, spot_tok, from_date, to_date, '30minute')

    print(f'Option 30m candles count: {len(df_opt_30m) if df_opt_30m is not None else 0}')
    print(f'Option 15m candles count: {len(df_opt_15m) if df_opt_15m is not None else 0}')

    if df_opt_30m is not None and not df_opt_30m.empty:
        print('\\nLast 6 Option 30m candles:')
        for idx, row in df_opt_30m.tail(6).iterrows():
            print(f'  {row[\"date\"]} | O={row[\"open\"]:6.2f} H={row[\"high\"]:6.2f} L={row[\"low\"]:6.2f} C={row[\"close\"]:6.2f} V={row[\"volume\"]}')

    if df_spot_30m is not None and not df_spot_30m.empty:
        print('\\nLast 6 Spot 30m candles:')
        for idx, row in df_spot_30m.tail(6).iterrows():
            print(f'  {row[\"date\"]} | O={row[\"open\"]:7.2f} H={row[\"high\"]:7.2f} L={row[\"low\"]:7.2f} C={row[\"close\"]:7.2f} V={row[\"volume\"]}')

    # 2. Test Anchor Detection on Option 30m
    print('\\n--- Testing Anchor Scanners on Option 30m ---')
    try:
        scanners = [find_anchor_bullish_engulfing, find_anchor_ll_sweep, find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs]
        for sc in scanners:
            res = sc(df_opt_30m, is_option=True)
            if res:
                for match in res:
                    print(f'  Scanner: {sc.__name__} | Pattern: {match.get(\"pattern\")} | Date: {match.get(\"date\")} | High: {match.get(\"high\")} | Low: {match.get(\"low\")}')
    except Exception as e:
        print('Anchor scan error:', e)

    # 3. Test Lifecycle Stage on Option
    print('\\n--- Testing Lifecycle Stage (A+, A, B) on Option ---')
    try:
        stage_res = scan_pattern_lifecycle_stage(df_opt_15m, df_opt_30m, anchor_tf='30minute', entry_tf='15minute', is_option=True)
        if stage_res:
            print('Lifecycle Stage Result:')
            for k in ['stage', 'pattern', 'tier_label', 'benchmark', 'entry_spot', 'current_sl', 't1', 'dist_to_trigger_pct']:
                print(f'  {k}: {stage_res.get(k)}')
        else:
            print('Lifecycle Stage: None (no valid lifecycle coiling detected)')
    except Exception as e:
        print('Lifecycle stage error:', e)
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
