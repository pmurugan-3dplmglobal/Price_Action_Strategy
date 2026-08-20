
import sys, os, time, json
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
sys.path.insert(0, '/home/opc/Price_Action_Strategy/Trade_Option')

import app_option_Trade as aot
from session import load_kite_session
from kiteconnect import KiteConnect

print("1. Checking aot.TOKEN_FILE:", aot.TOKEN_FILE, "exists:", os.path.exists(aot.TOKEN_FILE))
api_k, acc_t = load_kite_session(aot.TOKEN_FILE)
print("2. Loaded API key:", api_k, "Access token:", acc_t[:8]+"...")
ks = KiteConnect(api_key=api_k)
ks.set_access_token(acc_t)
pos = ks.positions()
net = pos.get('net', [])
net_pos = [p for p in net if p.get('tradingsymbol') and int(p.get('quantity', 0)) != 0]
print(f"3. Net positions with non-zero qty: {len(net_pos)}")
for p in net_pos:
    print(f"   - {p.get('tradingsymbol')} (qty: {p.get('quantity')})")

print("4. Calling aot.refresh_data(single_run=True)...")
aot._kite_positions_last_fetch = 0 # force fetch
aot.refresh_data(single_run=True)
print("5. aot.cached_data['kite_positions'] count:", len(aot.cached_data.get('kite_positions', [])))
