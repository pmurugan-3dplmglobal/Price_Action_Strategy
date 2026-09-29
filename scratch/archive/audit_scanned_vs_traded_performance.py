import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

snippet = """
import sys, os, json
sys.path.insert(0, os.path.abspath("common"))
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

# 1. Load scan_display files
staged_candidates = []
for p in ['output/monitor/scan_display.json', 'output/monitor/scan_display_index.json', 'output/monitor/pattern_funnel.json']:
    if os.path.exists(p):
        try:
            with open(p, 'r') as f:
                d = json.load(f)
                if isinstance(d, dict):
                    if 'staged_trades' in d:
                        for item in d.get('staged_trades', []):
                            item['_source'] = os.path.basename(p)
                            staged_candidates.append(item)
                    if 'all_staged_today' in d:
                        for item in d.get('all_staged_today', []):
                            item['_source'] = os.path.basename(p)
                            staged_candidates.append(item)
                    for cat in ['category_a_plus', 'category_a', 'category_b']:
                        for eng, eng_d in d.items():
                            if isinstance(eng_d, dict) and cat in eng_d:
                                for item in eng_d[cat]:
                                    item['_source'] = f"funnel_{cat}"
                                    staged_candidates.append(item)
        except Exception as e:
            print(f"Error reading {p}: {e}")

# Deduplicate by (symbol, side, timeframe)
unique_candidates = {}
for c in staged_candidates:
    sym = c.get('symbol') or c.get('tradingsymbol')
    side = c.get('side', 'CE')
    tf = c.get('timeframe') or c.get('timeframe_anchor') or '30m'
    key = f"{sym}_{side}_{tf}"
    if key not in unique_candidates:
        unique_candidates[key] = c

print(f"Total Unique Scanned Candidates Found: {len(unique_candidates)}")

# Query Kite Quotes for Spot and Option
quote_keys = []
for k, c in unique_candidates.items():
    sym = c.get('symbol')
    cnt = c.get('contract')
    if sym:
        quote_keys.append(f"NSE:{sym}")
    if cnt:
        quote_keys.append(f"NFO:{cnt}")

# Batch quote
batch_size = 200
quotes = {}
for i in range(0, len(quote_keys), batch_size):
    batch = quote_keys[i:i+batch_size]
    try:
        q = kite.quote(batch)
        quotes.update(q)
    except Exception as e:
        print(f"Quote error: {e}")

results = []
for k, c in unique_candidates.items():
    sym = c.get('symbol')
    cnt = c.get('contract')
    pat = c.get('pattern')
    tf = c.get('timeframe') or c.get('timeframe_anchor') or '30m'
    tier = c.get('tier') or c.get('priority_tier')
    bm = float(c.get('benchmark') or 0.0)
    sl = float(c.get('current_sl') or c.get('sl') or 0.0)
    t1 = float(c.get('t1') or 0.0)
    side = c.get('side', 'CE')
    source = c.get('_source')

    # Get quote
    spot_q = quotes.get(f"NSE:{sym}", {})
    opt_q = quotes.get(f"NFO:{cnt}", {}) if cnt else {}

    spot_ltp = spot_q.get('last_price', 0.0)
    spot_high = spot_q.get('ohlc', {}).get('high', 0.0)
    spot_low = spot_q.get('ohlc', {}).get('low', 0.0)
    spot_open = spot_q.get('ohlc', {}).get('open', 0.0)

    opt_ltp = opt_q.get('last_price', 0.0)
    opt_high = opt_q.get('ohlc', {}).get('high', 0.0)
    opt_low = opt_q.get('ohlc', {}).get('low', 0.0)
    opt_open = opt_q.get('ohlc', {}).get('open', 0.0)

    # Calculate Move %
    if side == 'CE':
        spot_move_pct = ((spot_high - spot_open) / spot_open * 100) if spot_open > 0 else 0
        opt_move_pct = ((opt_high - opt_open) / opt_open * 100) if opt_open > 0 else 0
    else:
        spot_move_pct = ((spot_open - spot_low) / spot_open * 100) if spot_open > 0 else 0
        opt_move_pct = ((opt_high - opt_open) / opt_open * 100) if opt_open > 0 else 0

    results.append({
        'symbol': sym,
        'contract': cnt,
        'pattern': pat,
        'tf': tf,
        'side': side,
        'tier': tier,
        'bm': bm,
        'sl': sl,
        't1': t1,
        'spot_open': spot_open,
        'spot_ltp': spot_ltp,
        'spot_high': spot_high,
        'spot_low': spot_low,
        'spot_move_pct': round(spot_move_pct, 2),
        'opt_open': opt_open,
        'opt_ltp': opt_ltp,
        'opt_high': opt_high,
        'opt_move_pct': round(opt_move_pct, 2),
        'source': source
    })

# Sort by option move % or spot move % descending
results.sort(key=lambda x: x['opt_move_pct'] if x['opt_move_pct'] > 0 else x['spot_move_pct'], reverse=True)

print("=== TOP 20 SCANNED CANDIDATES PERFORMANCE TODAY ===")
for r in results[:20]:
    print(f"[{r['side']}] {r['symbol']} ({r['contract']}) | Pat: {r['pattern']} | TF: {r['tf']} | Tier: {r['tier']} | SpotMove: {r['spot_move_pct']}% (O:{r['spot_open']} H:{r['spot_high']} L:{r['spot_low']}) | OptMove: {r['opt_move_pct']}% (O:{r['opt_open']} H:{r['opt_high']} LTP:{r['opt_ltp']}) | BM: {r['bm']} T1: {r['t1']}")

print("")
print("=== BOTTOM 10 SCANNED CANDIDATES TODAY ===")
for r in results[-10:]:
    print(f"[{r['side']}] {r['symbol']} ({r['contract']}) | Pat: {r['pattern']} | TF: {r['tf']} | Tier: {r['tier']} | SpotMove: {r['spot_move_pct']}% | OptMove: {r['opt_move_pct']}% | BM: {r['bm']} T1: {r['t1']}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
print(res.stdout or res.stderr)
