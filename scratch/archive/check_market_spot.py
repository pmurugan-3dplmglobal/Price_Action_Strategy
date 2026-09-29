import os, sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from common.session import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

syms = [
    'NSE:NIFTY 50', 'NSE:NIFTY BANK', 
    'NSE:INFY', 'NSE:SHRIRAMFIN', 'NSE:SBIN', 
    'NSE:BHARTIARTL', 'NSE:COALINDIA', 'NSE:INDIA VIX'
]

ltps = safe_kite_call(kite.ltp, syms)
ohlcs = safe_kite_call(kite.ohlc, syms)

for s in syms:
    lp = ltps.get(s, {}).get('last_price', 0)
    o_data = ohlcs.get(s, {}).get('ohlc', {})
    cp = o_data.get('close', 0)
    op = o_data.get('open', 0)
    chg = ((lp - cp) / cp * 100) if cp > 0 else 0.0
    print(f"{s:20} | LTP: {lp:9.2f} | Open: {op:9.2f} | PrevClose: {cp:9.2f} | Chg%: {chg:+6.2f}%")
