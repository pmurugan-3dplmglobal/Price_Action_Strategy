import json, sys, os
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

with open('output/monitor/scan_display.json') as f:
    d = json.load(f)

staged = d.get('all_staged_today', [])
print(f"Total Staged Setups Today: {len(staged)}")

# Pick top 20 candidates and check their day OHLC
tokens = {}
for s in staged:
    cnt = s.get('contract')
    tok = s.get('token') or s.get('option_token')
    if cnt and tok:
        tokens[f"NFO:{cnt}"] = s

keys = list(tokens.keys())[:30]
quotes = kite.quote(keys) if keys else {}

print("\n=== TOP SCANNED CANDIDATES PERFORMANCE AUDIT TODAY ===")
print(f"{'Contract':22s} | {'Pattern':18s} | {'BM / Entry':10s} | {'Day Low':8s} | {'Day High':8s} | {'LTP':8s} | {'Max Move %':10s}")
print("-" * 95)
for k, q in quotes.items():
    s = tokens.get(k, {})
    cnt = s.get('contract')
    pat = s.get('pattern')
    bm = float(s.get('benchmark') or 0.0)
    ohlc = q.get('ohlc', {})
    h = float(ohlc.get('high') or 0.0)
    l = float(ohlc.get('low') or 0.0)
    ltp = float(q.get('last_price') or 0.0)
    max_move = round(((h - bm) / bm) * 100.0, 1) if bm > 0 else 0.0
    print(f"{cnt:22s} | {str(pat):18s} | {bm:10.2f} | {l:8.2f} | {h:8.2f} | {ltp:8.2f} | {max_move:+9.1f}%")
