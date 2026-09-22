import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

from common.session import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect
from common.registries import STOCK_REGISTRY

k, t = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(t)

syms = [f"NSE:{s}" for s in list(STOCK_REGISTRY.keys())[:50]]
print(f"Testing quote for {len(syms)} symbols...")
t0 = time.time()
res = safe_kite_call(kite.quote, syms)
print(f"Quote result: {len(res) if res else 0} items in {time.time()-t0:.2f}s")
if res:
    first_key = list(res.keys())[0]
    print("Sample quote item:", first_key, res[first_key].get('last_price'), res[first_key].get('volume'), res[first_key].get('ohlc'))
