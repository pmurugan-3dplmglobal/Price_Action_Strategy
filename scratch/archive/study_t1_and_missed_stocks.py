import subprocess
import json

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VM_IP = '140.245.197.71'
VM_USER = 'opc'
VM_DIR = '/home/opc/Price_Action_Strategy'

REMOTE_SCRIPT = """
import glob, re, os, json
from datetime import datetime as dt, timedelta

# 1. Search logs for 80% T1 hit / eviction
log_dir = 'output/logs'
print('=== 1. SEARCHING FOR 80% T1 HITS ACROSS ALL LOGS ===')
for log_file in sorted(glob.glob(os.path.join(log_dir, '*.log'))):
    fname = os.path.basename(log_file)
    with open(log_file, 'r', errors='ignore') as f:
        lines = f.readlines()
    matches = [line.strip() for line in lines if any(k in line for k in ['80% T1', '80%_EARLY_D', 'T1 HIT', 'RADAR EVICT: 80%'])]
    if matches:
        print(f'\\n--- {fname} (Total Matches: {len(matches)}) ---')
        # Print today's or latest 10 matches
        today_matches = [m for m in matches if '2026-09-15' in m]
        if today_matches:
            print('TODAY 2026-09-15 Matches:')
            for m in today_matches[-15:]:
                print(m)
        else:
            print('Recent Matches:')
            for m in matches[-10:]:
                print(m)

# 2. Search for ASTRAL and ATHERENERG in logs
print('\\n=== 2. SEARCHING FOR ASTRAL AND ATHERENERG IN SCAN / RADAR LOGS ===')
for sym in ['ASTRAL', 'ATHERENERG', '1400PE', '1660PE']:
    print(f'\\n>>> SEARCH FOR {sym} <<<')
    for log_file in sorted(glob.glob(os.path.join(log_dir, '*.log'))):
        fname = os.path.basename(log_file)
        with open(log_file, 'r', errors='ignore') as f:
            lines = f.readlines()
        matches = [line.strip() for line in lines if sym in line and '2026-09-15' in line]
        if matches:
            print(f'{fname}: {len(matches)} matches today')
            for m in matches[-5:]:
                print(f'   {m}')

# 3. Query Kite for ASTRAL spot & ASTRAL26SEP1400PE
print('\\n=== 3. LIVE KITE QUOTE & CANDLES FOR ASTRAL & ATHERENERG ===')
from common.session import load_kite_session
from kiteconnect import KiteConnect
try:
    k, t = load_kite_session()
    kite = KiteConnect(api_key=k)
    kite.set_access_token(t)
    q = kite.quote(['NSE:ASTRAL', 'NFO:ASTRAL26SEP1400PE', 'NSE:ATHERENERG', 'NFO:ATHERENERG26SEP1660PE'])
    for sym_k, data in q.items():
        ohlc = data.get('ohlc', {})
        ltp = data.get('last_price')
        prev_c = ohlc.get('close', 0)
        chg = round((ltp - prev_c) / prev_c * 100, 2) if prev_c > 0 else 0
        depth = data.get('depth', {})
        best_b = depth.get('buy', [{}])[0].get('price', 0)
        best_a = depth.get('sell', [{}])[0].get('price', 0)
        sp = round((best_a - best_b) / ltp * 100, 2) if ltp and best_a and best_b else 0
        print(f'{sym_k}: LTP={ltp} (Open={ohlc.get(\"open\")}, High={ohlc.get(\"high\")}, Low={ohlc.get(\"low\")}, PrevClose={prev_c}, Chg={chg}%) | Bid={best_b}, Ask={best_a}, Spread={sp}%')
except Exception as e:
    print('Kite quote error:', e)
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
