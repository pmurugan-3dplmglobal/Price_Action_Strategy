import subprocess

remote_script = """
import os, time, json, sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
import paths, session
from kiteconnect import KiteConnect

try:
    k, t = session.load_kite_session(paths.TOKEN_FILE)
    kite = KiteConnect(api_key=k)
    kite.set_access_token(t)
    pf = json.load(open('/home/opc/Price_Action_Strategy/output/monitor/pattern_funnel.json'))
    n50 = pf.get('nifty50', {})
    aplus = n50.get('category_a_plus', [])
    symbols = [f"NFO:{item.get('contract')}" for item in aplus if item.get('contract')]
    q = kite.quote(symbols)
    for item in aplus:
        cntr = item.get('contract')
        sym = item.get('symbol')
        dat = q.get(f"NFO:{cntr}", {})
        ltp = dat.get('last_price', 0)
        bm = float(item.get('benchmark', 0))
        sl = float(item.get('current_sl', 0))
        t1 = float(item.get('t1', 0))
        diff = round(((ltp - bm) / bm * 100), 1) if bm > 0 else 0
        print(f"{sym:<12} {cntr:<24} LTP={ltp:<8} BM={bm:<8} SL={sl:<8} T1={t1:<8} Diff={diff:+}%")
except Exception as e:
    print('ERROR:', e)
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
