"""
Analyse a scanned trade's ABCD sequence using existing trading_core functions.
Usage: python analyse_trade.py <contract_name>
Example: python analyse_trade.py BEL26AUG405PE
"""
import sys, os, json

PROJECT = r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy"
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "common"))

import paths
import pandas as pd
from datetime import datetime, timedelta
from trading_core import (
    load_kite_session, fetch_and_resample_candles,
    scan_anchor_bcd_breakout, scan_anchor_bcd_breakout_bearish,
    find_profit_targets, find_profit_targets_bearish,
    get_fetch_timeframe, STOCK_REGISTRY
)
from kiteconnect import KiteConnect


def load_scan_trade(contract):
    """Find the trade in scan_display files."""
    for fname in [paths.SCAN_DISPLAY_FILE, paths.SCAN_DISPLAY_INDEX_FILE,
                  paths.SCAN_DISPLAY_STOCK_FILE, paths.SCAN_DISPLAY_BEAR_FILE]:
        if not os.path.exists(fname):
            continue
        with open(fname, "r", encoding="utf-8") as f:
            data = json.load(f)
        for section in ["staged_trades", "all_staged_today", "carry_forward", "active_live"]:
            for t in data.get(section, []):
                if t.get("contract", "").upper() == contract.upper():
                    return t
    return None


def get_option_token(contract):
    """Lookup instrument token from NFO cache."""
    nfo_file = os.path.join(paths.PROJECT_ROOT, "output", "monitor", "nfo_instruments_cache.csv")
    if not os.path.exists(nfo_file):
        return None, None
    nfo = pd.read_csv(nfo_file)
    match = nfo[nfo['tradingsymbol'].str.upper() == contract.upper()]
    if match.empty:
        return None, None
    return int(match.iloc[0]['instrument_token']), match.iloc[0]['tradingsymbol']


def analyse(contract):
    print(f"\n{'='*70}")
    print(f"  ABCD Trade Analysis: {contract}")
    print(f"{'='*70}")

    # 1. Load scan data
    trade = load_scan_trade(contract)
    if not trade:
        print(f"  {contract} not found in any scan_display file.")
        return

    symbol = trade["symbol"]
    side = trade["side"]
    tf = trade.get("timeframe", "60minute")
    benchmark = trade.get("benchmark")
    anchor_floor = trade.get("anchor_floor")
    direction = trade.get("direction", "BULL")
    a_time = trade.get("candle_a_time", "")
    entry_time = trade.get("entry_time", "")

    print(f"\n  Scan Data:")
    print(f"   Symbol:      {symbol}")
    print(f"   Contract:    {contract}")
    print(f"   Side:        {side} | Direction: {direction}")
    print(f"   Pattern:     {trade.get('pattern', '?')}")
    print(f"   Timeframe:   {tf}")
    print(f"   Anchor Time: {a_time}")
    print(f"   Entry Time:  {entry_time}")
    print(f"   Benchmark:   {benchmark}")
    print(f"   Anchor Floor:{anchor_floor}")
    print(f"   Entry Spot:  {trade.get('entry_spot')}")
    print(f"   SL:          {trade.get('current_sl')}")
    print(f"   T1/T2/T3:    {trade.get('t1')} / {trade.get('t2')} / {trade.get('t3')}")
    print(f"   R:R:         {trade.get('rr')}")

    # 2. Load Kite + fetch candles
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)

    token, tsym = get_option_token(contract)
    if not token:
        print(f"  Token not found for {contract}")
        return

    to_date = datetime.now()
    from_date = to_date - timedelta(days=15)

    df = fetch_and_resample_candles(kite, token, from_date, to_date, tf)
    if df is None or df.empty:
        print(f"  No candle data returned for {contract}")
        return

    print(f"\n  Fetched {len(df)} candles ({tf})")

    # 3. Print candles with manual ABCD detection using scan data
    bm = float(benchmark) if benchmark else 0
    floor_val = float(anchor_floor) if anchor_floor else 0

    print(f"\n{'Time':<25} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Color':<6} Label")
    print(f"{'_'*90}")

    anchor_hit = False
    b_found = c_found = d_found = False
    start_print = False

    for i in range(len(df)):
        row = df.iloc[i]
        t = str(row.get('date', ''))[:19]
        o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
        color = "GREEN" if c >= o else "RED"
        label = ""

        if a_time and a_time in t:
            label = f"<-- A (Anchor) BM={bm} Floor={floor_val}"
            anchor_hit = True
            start_print = True
        elif anchor_hit and not d_found:
            if direction == "BULL":
                if not b_found and c > bm and color == "GREEN":
                    label = "<-- B (Breakout: green close > BM)"
                    b_found = True
                elif b_found and not c_found and color == "RED":
                    label = "<-- C (Retest: red pullback)"
                    c_found = True
                elif c_found and not d_found and c > bm and color == "GREEN":
                    label = "<-- D (Confirmation: green close > BM) -> ENTRY"
                    d_found = True
            else:
                if not b_found and c < bm and color == "RED":
                    label = "<-- B (Breakout: red close < BM)"
                    b_found = True
                elif b_found and not c_found and color == "GREEN":
                    label = "<-- C (Retest: green pullback)"
                    c_found = True
                elif c_found and not d_found and c < bm and color == "RED":
                    label = "<-- D (Confirmation: red close < BM) -> ENTRY"
                    d_found = True

        if entry_time and entry_time in t:
            label += " ** SCANNER ENTRY **"

        # Print from 3 candles before anchor
        if not start_print and a_time:
            # Check if next few candles contain the anchor
            for look in range(1, 4):
                if i + look < len(df):
                    ft = str(df.iloc[i + look].get('date', ''))[:19]
                    if a_time in ft:
                        start_print = True
                        break

        if start_print:
            print(f"{t:<25} {o:>8.2f} {h:>8.2f} {l:>8.2f} {c:>8.2f} {color:<6} {label}")

    print(f"{'_'*90}")


if __name__ == "__main__":
    contract = sys.argv[1] if len(sys.argv) > 1 else "BEL26AUG405PE"
    analyse(contract)
