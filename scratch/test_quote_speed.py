import time
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
from common.session import load_kite_session
from kiteconnect import KiteConnect

k, t = load_kite_session()
kite = KiteConnect(k)
kite.set_access_token(t)

from registries import STOCK_REGISTRY
syms = [f"NSE:{s}" for s in list(STOCK_REGISTRY.keys())[:210]]

t0 = time.time()
q = kite.quote(syms)
elapsed = time.time() - t0
print(f"Fetched {len(q)} quotes in {elapsed:.2f}s")

# Print top 5 movers by abs pct change
movers = []
for s in STOCK_REGISTRY.keys():
    item = q.get(f"NSE:{s}")
    if not item:
        continue
    lp = float(item.get("last_price") or 0.0)
    ohlc = item.get("ohlc") or {}
    prev_close = float(ohlc.get("close") or 0.0)
    vol = float(item.get("volume") or 0.0)
    pct = ((lp - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
    turnover_cr = (vol * lp) / 1e7
    movers.append((s, lp, prev_close, pct, vol, turnover_cr))

movers.sort(key=lambda x: abs(x[3]), reverse=True)
print("\nTop 10 Movers by % Change:")
for m in movers[:10]:
    print(f"  {m[0]:<12} | LTP: {m[1]:>8.2f} | PrevClose: {m[2]:>8.2f} | Change: {m[3]:>+6.2f}% | Vol: {m[4]:>10,.0f} | Turnover: {m[5]:>6.1f} Cr")
