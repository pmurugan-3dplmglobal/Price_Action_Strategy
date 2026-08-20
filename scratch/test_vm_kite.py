
import sys, os
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
sys.path.insert(0, '/home/opc/Price_Action_Strategy/Trade_Option')

from session import load_kite_session
from kiteconnect import KiteConnect
import paths

try:
    k, t = load_kite_session(paths.TOKEN_FILE)
    ks = KiteConnect(api_key=k)
    ks.set_access_token(t)
    pos = ks.positions()
    net = pos.get('net', [])
    print(f'SUCCESS! Total net positions from Kite: {len(net)}')
    for p in net:
        if int(p.get('quantity', 0)) != 0:
            print(f"  * {p.get('tradingsymbol')} | Qty: {p.get('quantity')} | LTP: {p.get('last_price')}")
except Exception as e:
    import traceback
    print('ERROR:', e)
    traceback.print_exc()
