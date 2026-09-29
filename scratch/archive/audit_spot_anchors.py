import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.patterns_bull import (
    find_anchor_bullish_engulfing, find_anchor_ll_sweep,
    find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs
)
from common.patterns_bear import (
    find_anchor_bearish_engulfing, find_anchor_hh_sweep,
    find_anchor_shooting_star_baby, find_anchor_bearish_harami, find_anchor_two_lower_lows
)
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

symbols = ["MANKIND", "VMM", "VBL", "BSE", "ADANIENT", "GLENMARK", "POLICYBZR", "KFINTECH", "HAL"]
nse_inst = {i["tradingsymbol"]: i["instrument_token"] for i in kite.instruments("NSE") if i["tradingsymbol"] in symbols}

from_d = dt.date(2026, 9, 20)
to_d = dt.date(2026, 9, 29)

bull_funcs = [
    ("BULL_ENGULF", find_anchor_bullish_engulfing),
    ("LL_SWEEP", find_anchor_ll_sweep),
    ("HAMMER", find_anchor_hammer_baby),
    ("BULL_HARAMI", find_anchor_bullish_harami),
    ("TWO_HH", find_anchor_two_higher_highs),
]

bear_funcs = [
    ("BEAR_ENGULF", find_anchor_bearish_engulfing),
    ("HH_SWEEP", find_anchor_hh_sweep),
    ("STAR", find_anchor_shooting_star_baby),
    ("BEAR_HARAMI", find_anchor_bearish_harami),
    ("TWO_LL", find_anchor_two_lower_lows),
]

print("=== SPOT ANCHOR PATTERN AUDIT ACROSS ALL CASES (75m & 15m) ===")
for sym in symbols:
    tok = nse_inst.get(sym)
    if not tok:
        print(f"Token not found for {sym}")
        continue
    df_15m = fetch_and_resample_candles(kite, tok, from_d, to_d, "15minute")
    df_75m = fetch_and_resample_candles(kite, tok, from_d, to_d, "75minute")
    
    print(f"\n--------------------------------------------------")
    print(f"SYMBOL: {sym} (15m bars: {len(df_15m)}, 75m bars: {len(df_75m)})")
    print(f"Latest Spot Close: {df_15m.iloc[-1]['close']}, 28-Sep Close: {df_15m[df_15m['date'].astype(str) < '2026-09-29'].iloc[-1]['close']}")
    
    for tf_name, df_cand in [("15m", df_15m), ("75m", df_75m)]:
        print(f"  [{tf_name} Bull Anchors]:")
        found_bull = []
        for name, fn in bull_funcs:
            res = fn(df_cand)
            if res:
                found_bull.append(f"{name} (A-Time: {res.get('CandleATime')}, Close: {res.get('Close')}, SL: {res.get('SL')})")
        if found_bull:
            for b in found_bull: print(f"    + {b}")
        else:
            print("    (None)")
            
        print(f"  [{tf_name} Bear Anchors]:")
        found_bear = []
        for name, fn in bear_funcs:
            res = fn(df_cand)
            if res:
                found_bear.append(f"{name} (A-Time: {res.get('CandleATime')}, Close: {res.get('Close')}, SL: {res.get('SL')})")
        if found_bear:
            for b in found_bear: print(f"    - {b}")
        else:
            print("    (None)")
