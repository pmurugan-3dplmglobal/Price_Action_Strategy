import os
import sys
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.patterns_bull import (
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout,
    scan_pattern_lifecycle_stage
)
from common.patterns_bear import (
    find_anchor_bearish_engulfing,
    find_anchor_hh_sweep,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_anchor_bcd_breakout_bearish,
    scan_pattern_lifecycle_stage_bearish
)

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

instruments = kite.instruments("NFO")
nfo_map = {inst["tradingsymbol"]: inst["instrument_token"] for inst in instruments}

nse_instruments = kite.instruments("NSE")
nse_map = {inst["tradingsymbol"]: inst["instrument_token"] for inst in nse_instruments}

to_dt = datetime.now()
from_dt = to_dt - timedelta(days=12)

def analyze_symbol(sym, contract):
    print("=" * 70)
    print(f"DEEP PATTERN & GEOMETRY ANALYSIS: {sym} (Option: {contract})")
    print("=" * 70)
    
    # 1. Spot Analysis
    spot_token = nse_map.get(sym)
    if spot_token:
        for tf in ["15minute", "30minute"]:
            candles = kite.historical_data(spot_token, from_dt, to_dt, tf)
            df = pd.DataFrame(candles)
            if not df.empty:
                print(f"\n--- {sym} SPOT ({tf}) ---")
                last5 = df.tail(5)
                for idx, row in last5.iterrows():
                    print(f"  {row['date']} | O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} | Vol:{row['volume']}")
                
                # Check Bearish BCD Breakouts on Spot
                bear_bcds = scan_anchor_bcd_breakout_bearish(df)
                print(f"Bearish BCD Breakouts on Spot: {len(bear_bcds) if bear_bcds else 0}")
                if bear_bcds:
                    for b in bear_bcds[-3:]:
                        print(f"  [BEAR D-BREAKOUT] {b.get('pattern')} | D_date: {b.get('d_date')} | Entry: {b.get('entry')} | SL: {b.get('sl')} | T1: {b.get('t1')}")

                # Check Bullish BCD Breakouts on Spot
                bull_bcds = scan_anchor_bcd_breakout(df)
                print(f"Bullish BCD Breakouts on Spot: {len(bull_bcds) if bull_bcds else 0}")
                if bull_bcds:
                    for b in bull_bcds[-3:]:
                        print(f"  [BULL D-BREAKOUT] {b.get('pattern')} | D_date: {b.get('d_date')} | Entry: {b.get('entry')} | SL: {b.get('sl')} | T1: {b.get('t1')}")

    # 2. Option Contract Analysis
    opt_token = nfo_map.get(contract)
    if opt_token:
        for tf in ["15minute", "30minute"]:
            candles = kite.historical_data(opt_token, from_dt, to_dt, tf)
            df = pd.DataFrame(candles)
            if not df.empty:
                print(f"\n--- {contract} OPTION PREMIUM ({tf}) ---")
                last5 = df.tail(5)
                for idx, row in last5.iterrows():
                    print(f"  {row['date']} | O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} | Vol:{row['volume']}")
                
                # Options Buyer Invariant: Long options are bought on Bullish Premium Breakout!
                opt_bull_bcds = scan_anchor_bcd_breakout(df)
                print(f"Option Premium Bullish Breakouts: {len(opt_bull_bcds) if opt_bull_bcds else 0}")
                if opt_bull_bcds:
                    for b in opt_bull_bcds[-3:]:
                        print(f"  [OPTION D-BREAKOUT] {b.get('pattern')} | D_date: {b.get('d_date')} | Entry: {b.get('entry')} | SL: {b.get('sl')} | T1: {b.get('t1')}")

print("\n>>> ANALYZING MOTHERSON (Bhavani VM) <<<")
analyze_symbol("MOTHERSON", "MOTHERSON26OCT165CE")

print("\n>>> ANALYZING SBILIFE (Poovendan Account) <<<")
analyze_symbol("SBILIFE", "SBILIFE26OCT1720PE")

print("\n>>> ANALYZING COLPAL (User Chart Question) <<<")
analyze_symbol("COLPAL", "COLPAL26OCT1820PE")
