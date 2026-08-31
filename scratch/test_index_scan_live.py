import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from kiteconnect import KiteConnect
from session import load_kite_session
from registries import INDEX_REGISTRY
from resolve import scan_symbol, resolve_option_strikes as shared_resolve_strikes
from patterns_bull import scan_anchor_bcd_breakout, scan_trend_continuation_reentry
from patterns_bull import (
    find_anchor_bullish_engulfing, find_anchor_ll_sweep,
    find_anchor_hammer_baby, find_anchor_bullish_harami,
    find_anchor_two_higher_highs
)
from datetime import datetime as dt, timedelta
import trade_db
import threading
import pandas as pd
import paths

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

# Load NFO instruments
from position_monitor import _get_nfo_cache
nfo_cache = _get_nfo_cache()
print(f"Loaded NFO instruments: {len(nfo_cache)}")

ref_now = dt.now()
from_entry = (ref_now - timedelta(days=20)).strftime("%Y-%m-%d")
to_entry = ref_now.strftime("%Y-%m-%d")
from_anchor = (ref_now - timedelta(days=60)).strftime("%Y-%m-%d")
to_anchor = ref_now.strftime("%Y-%m-%d")

entry_scanners = [
    ("Setup_1_Anchor_BCD", scan_anchor_bcd_breakout),
    ("Setup_2_Trend_Continuation", scan_trend_continuation_reentry),
]
anchor_scanners = [
    ("A1", find_anchor_bullish_engulfing),
    ("A2", find_anchor_ll_sweep),
    ("A3", find_anchor_hammer_baby),
    ("A4", find_anchor_bullish_harami),
    ("A5", find_anchor_two_higher_highs),
]

active_pos = {}
pos_lock = threading.Lock()

print(f"\n==================================================")
print(f" SCANNING INDEX UNIVERSE (3m Entry / 15m Anchor)...")
print(f"==================================================")

for sym, cfg in INDEX_REGISTRY.items():
    print(f"\n--- Scanning {sym} ---")
    try:
        trades = scan_symbol(
            kite, sym, cfg, from_entry, to_entry, from_anchor, to_anchor,
            entry_scanners, anchor_scanners,
            lambda s, sp, st, opt, r: shared_resolve_strikes(nfo_cache, s, sp, st, opt, r),
            "index", "3minute", "15minute", "minute",
            active_pos, pos_lock, trade_db, 3,
            lambda *args, **kwargs: None
        )
        print(f"  Result for {sym}: {len(trades)} trade(s) staged.")
        for t in trades:
            print(f"    -> {t['contract']} | {t['pattern']} | Entry: {t['entry_spot']} | SL: {t['current_sl']} | T1: {t['t1']} | RR: {t['rr']} | Tier: {t.get('tier_badge')}")
    except Exception as e:
        print(f"  Error scanning {sym}: {e}")
