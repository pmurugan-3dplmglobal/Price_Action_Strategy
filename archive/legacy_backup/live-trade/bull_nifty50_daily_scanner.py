import os
import sys
import json
import logging
import time
from datetime import datetime as dt, timedelta

import pandas as pd
import numpy as np
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    CFG_FILE, TOKEN_FILE, BACKTEST_DATE, LOOKBACK_DAYS,
    DAILY_TF, DAILY_LOOKBACK,
    STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, VALID_TIMEFRAMES,
    EXPORT_STATE_FILE,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments, create_kite_client, is_market_hours,
    init_registries, NFO_INSTRUMENTS
)
from shared.patterns import (
    A_CACHE, _a_cache_key, detect_and_cache_a, find_bcd_forward,
    find_anchor_bullish_engulfing, find_anchor_ll_sweep, find_anchor_hammer_baby,
    find_anchor_bullish_harami, find_anchor_bearish_engulfing, find_anchor_hh_sweep,
    find_anchor_shooting_star, find_anchor_bearish_harami,
    find_swing_lows, find_swing_highs, find_pin_bars,
    _no_pa_left, find_profit_targets_negation,
)
from shared.journal import log_to_journal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bull_daily_scanner.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_TYPE = "daily"

def scan_symbols(kite):
    target_date = BACKTEST_DATE or dt.now().date()
    limits = {"day": 2000, "60minute": 400, "30minute": 200}
    max_days = limits.get(DAILY_TF, DAILY_LOOKBACK)
    from_date = (target_date - timedelta(days=max_days)).strftime("%Y-%m-%d")
    to_date = target_date.strftime("%Y-%m-%d")

    results = []
    all_symbols = list(STOCK_REGISTRY.items())
    for sym, config in SUPER_STOCKS + all_symbols:
        try:
            df = pd.DataFrame(safe_historical(kite, config["token"], from_date, to_date, DAILY_TF))
            if df.empty:
                continue
            close = float(df.iloc[-1]['close'])
            patterns = []
            # Bullish patterns
            eng = find_anchor_bullish_engulfing(df)
            if eng: patterns.append(("BULL_ENGULF", eng[-1]))
            ll = find_anchor_ll_sweep(df)
            if ll: patterns.append(("BULL_LL_SWEEP", ll[-1]))
            ham = find_anchor_hammer_baby(df)
            if ham: patterns.append(("BULL_HAMMER", ham[-1]))
            har = find_anchor_bullish_harami(df)
            if har: patterns.append(("BULL_HARAMI", har[-1]))
            # Bearish patterns
            be = find_anchor_bearish_engulfing(df)
            if be: patterns.append(("BEAR_ENGULF", be[-1]))
            hh = find_anchor_hh_sweep(df)
            if hh: patterns.append(("BEAR_HH_SWEEP", hh[-1]))
            ss = find_anchor_shooting_star(df)
            if ss: patterns.append(("BEAR_SHOOTING", ss[-1]))
            bhar = find_anchor_bearish_harami(df)
            if bhar: patterns.append(("BEAR_HARAMI", bhar[-1]))

            if patterns:
                for pname, pidx in patterns:
                    candle = df.iloc[pidx]
                    results.append({
                        "Symbol": sym, "Pattern": pname,
                        "Date": str(candle['date']) if hasattr(candle['date'], 'strftime') else str(candle['date']),
                        "Close": round(close, 2),
                        "Open": round(float(candle['open']), 2),
                        "High": round(float(candle['high']), 2),
                        "Low": round(float(candle['low']), 2)
                    })
                    logging.info(f"DAILY {pname}: {sym} @ Close={close:.2f}")
        except Exception as e:
            logging.warning(f"Daily scan failed for {sym}: {e}")
    return results

def export_to_excel(results):
    if not results:
        logging.info("No results to export")
        return
    df = pd.DataFrame(results)
    out_dir = "output/exports"
    os.makedirs(out_dir, exist_ok=True)
    ts = dt.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(out_dir, f"Nifty50_Daily_Scan_{ts}.xlsx")
    try:
        df.to_excel(path, index=False, engine="openpyxl")
        logging.info(f"Exported {len(results)} results to {path}")
    except Exception as e:
        logging.error(f"Export failed: {e}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--force-backtest", action="store_true")
    args = parser.parse_args()

    kite = create_kite_client()
    fetch_instruments(kite)
    results = scan_symbols(kite)
    export_to_excel(results)
    logging.info(f"Daily scanner complete: {len(results)} patterns found")

if __name__ == "__main__":
    main()
