import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

import json, sqlite3
from common import paths
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

print("=== INSPECTING STAGED TRADES IN SCAN_DISPLAY.JSON ===")
with open(paths.SCAN_DISPLAY_FILE, "r", encoding="utf-8") as f:
    disp = json.load(f)

staged = disp.get("staged_trades", [])
print(f"Total staged trades: {len(staged)}")

# Categorize by tier
t1_gold = [s for s in staged if s.get("tier") in [1, "TIER_1_GOLD", "T1", "1"]]
t2_core = [s for s in staged if s.get("tier") in [2, "TIER_2_CORE", "T2", "2"]]
t3_mom = [s for s in staged if s.get("tier") in [3, "TIER_3_MOMENTUM", "T3", "3"]]
other_tier = [s for s in staged if s not in t1_gold and s not in t2_core and s not in t3_mom]

print(f"T1 Gold: {len(t1_gold)} | T2 Core: {len(t2_core)} | T3 Momentum: {len(t3_mom)} | Other: {len(other_tier)}")

# Sample quotes for top candidates across tiers
contracts_to_check = []
for s in staged[:40]:
    c = s.get("contract") or s.get("symbol")
    exch = "BFO" if ("SENSEX" in c or "BSE" in c) else "NFO"
    contracts_to_check.append(f"{exch}:{c}")

quotes = {}
if contracts_to_check:
    try:
        # Batch in chunks of 50
        for i in range(0, len(contracts_to_check), 50):
            chunk = contracts_to_check[i:i+50]
            q_res = kite.quote(chunk)
            quotes.update(q_res)
    except Exception as e:
        print("Quote error:", e)

results = []
for s in staged[:40]:
    c = s.get("contract") or s.get("symbol")
    exch = "BFO" if ("SENSEX" in c or "BSE" in c) else "NFO"
    q_key = f"{exch}:{c}"
    q = quotes.get(q_key, {})
    ltp = float(q.get("last_price") or 0.0)
    ohlc = q.get("ohlc", {})
    high = float(ohlc.get("high") or 0.0)
    low = float(ohlc.get("low") or 0.0)
    open_p = float(ohlc.get("open") or 0.0)
    close_p = float(ohlc.get("close") or 0.0)
    entry_s = float(s.get("benchmark") or s.get("entry_spot") or s.get("entry_price") or 0.0)
    t1 = float(s.get("t1") or 0.0)
    sl = float(s.get("current_sl") or s.get("sl") or 0.0)
    tier = s.get("tier")
    pattern = s.get("pattern")
    side = s.get("side", "CE")
    rr = s.get("rr", 0.0)

    # Max gain % from entry to day high
    max_gain_pct = round((high - entry_s) / entry_s * 100, 2) if entry_s > 0 and high > 0 else 0.0
    # Current gain % from entry to LTP
    curr_gain_pct = round((ltp - entry_s) / entry_s * 100, 2) if entry_s > 0 and ltp > 0 else 0.0

    hit_t1 = high >= t1 if (t1 > 0 and high > 0) else False
    hit_sl = low <= sl if (sl > 0 and low > 0) else False

    results.append({
        "contract": c,
        "side": side,
        "tier": tier,
        "pattern": pattern,
        "rr": rr,
        "entry": entry_s,
        "t1": t1,
        "sl": sl,
        "ltp": ltp,
        "high": high,
        "low": low,
        "max_gain_pct": max_gain_pct,
        "curr_gain_pct": curr_gain_pct,
        "hit_t1": hit_t1,
        "hit_sl": hit_sl
    })

print(f"\n{'Contract':<22} | {'Tier':<5} | {'Pattern':<20} | {'Entry':<6} | {'T1':<6} | {'High':<6} | {'LTP':<6} | {'MaxGain%':<9} | {'HitT1'}")
print("-" * 105)
for r in results:
    t_str = "T1 Gold" if str(r['tier']) in ['1', 'TIER_1_GOLD'] else ("T2 Core" if str(r['tier']) in ['2', 'TIER_2_CORE'] else str(r['tier']))
    print(f"{r['contract']:<22} | {t_str:<5} | {str(r['pattern'])[:20]:<20} | {r['entry']:<6.2f} | {r['t1']:<6.2f} | {r['high']:<6.2f} | {r['ltp']:<6.2f} | {r['max_gain_pct']:>7.1f}% | {str(r['hit_t1'])}")
