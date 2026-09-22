import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import session
from common.trading_core import fetch_and_resample_candles
from kiteconnect import KiteConnect

d = json.load(open('scratch/poovendan_scan_display.json', encoding="utf-8"))
staged = d.get('staged_trades', []) + d.get('all_staged_today', []) + d.get('carry_forward', []) + d.get('active_live', [])

# 7 Big Winners + 3 Taken Stagnant/Losing Trades + 1 Taken Winner
all_symbols = {
    "WINNERS": ["LTM", "WAAREEENER", "VOLTAS", "SWIGGY", "HCLTECH", "TMPV", "KPITTECH"],
    "TAKEN_STAGNANT_LOSERS": ["GODREJPROP", "BAJAJFINSV", "JSWENERGY"],
    "TAKEN_WINNER": ["SIEMENS"]
}

found_setups = {}
for t in staged:
    s = t.get("symbol")
    for group, syms in all_symbols.items():
        if s in syms and s not in found_setups:
            found_setups[s] = (group, t)

print(f"Loaded {len(found_setups)} setups for in-depth comparative study.\n")

ak, at = session.load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

# Batch all quote keys in a single call
q_keys = []
for s, (grp, t) in found_setups.items():
    cntr = t.get("contract")
    q_key = f"NFO:{cntr}" if "SENSEX" not in cntr else f"BFO:{cntr}"
    q_keys.append(q_key)

quotes = kite.quote(q_keys)
comparison_records = []

for s, (grp, t) in found_setups.items():
    cntr = t.get("contract")
    side = t.get("side")
    bm = float(t.get("benchmark") or t.get("entry_spot") or t.get("entry_price") or 0)
    sl = float(t.get("current_sl") or t.get("sl") or 0)
    t1 = float(t.get("t1") or 0)
    rr = float(t.get("rr") or 0)
    risk_pts = bm - sl
    risk_pct = (risk_pts / bm * 100) if bm else 0
    t1_dist = t1 - bm
    t1_pct = (t1_dist / bm * 100) if bm else 0
    
    pat = t.get("pattern")
    tier = t.get("tier")
    atr_r = t.get("atr_ratio")
    sqz = t.get("is_squeeze")
    vcp_tier = t.get("vcp_tier")
    spot_vwap = t.get("spot_vwap")
    spot_conf = t.get("spot_confluence")
    spot_conf_type = t.get("spot_confluence_type")
    opt_vwap = t.get("vwap")
    stretch = t.get("vwap_stretch")
    waves = t.get("swing_waves")
    et = t.get("entry_time")
    at_time = t.get("candle_a_time")
    
    q_key = f"NFO:{cntr}" if "SENSEX" not in cntr else f"BFO:{cntr}"
    q = quotes.get(q_key, {})
    ltp = float(q.get("last_price") or 0)
    high = float(q.get("ohlc", {}).get("high") or ltp)
    low = float(q.get("ohlc", {}).get("low") or ltp)
    gain_high = ((high - bm) / bm * 100) if bm else 0
    curr_gain = ((ltp - bm) / bm * 100) if bm else 0
    vol = q.get("volume", 0)

    comparison_records.append({
        "group": grp,
        "symbol": s,
        "contract": cntr,
        "side": side,
        "pattern": pat,
        "tier": tier,
        "entry_time": et,
        "anchor_time": at_time,
        "benchmark": bm,
        "sl": sl,
        "risk_pct": risk_pct,
        "t1": t1,
        "t1_pct": t1_pct,
        "rr": rr,
        "waves": waves,
        "atr_ratio": atr_r,
        "is_squeeze": sqz,
        "vcp_tier": vcp_tier,
        "spot_confluence": spot_conf,
        "spot_confluence_type": spot_conf_type,
        "opt_vwap": opt_vwap,
        "stretch": stretch,
        "day_high": high,
        "day_low": low,
        "ltp": ltp,
        "gain_high": gain_high,
        "curr_gain": curr_gain,
        "volume": vol
    })

out_file = os.path.join(PROJECT_ROOT, "scratch", "comparative_study_winners_vs_losers.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(comparison_records, f, indent=2)

print("Analysis written to scratch/comparative_study_winners_vs_losers.json")
