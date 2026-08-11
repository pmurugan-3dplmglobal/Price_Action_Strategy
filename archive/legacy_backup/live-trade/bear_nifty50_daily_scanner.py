import os
import sys
import json
import logging
from datetime import datetime as dt, timedelta

import pandas as pd
import numpy as np
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    CFG_FILE, TOKEN_FILE, BACKTEST_DATE,
    DAILY_TF, DAILY_LOOKBACK,
    STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, VALID_TIMEFRAMES,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments, create_kite_client,
    init_registries, NFO_INSTRUMENTS
)
from shared.patterns import (
    find_anchor_bearish_engulfing, find_anchor_hh_sweep,
    find_anchor_shooting_star, find_anchor_bearish_harami,
)
from shared.journal import log_to_journal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bear_daily_scanner.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_TYPE = "bear_daily"

def scan_symbols(kite):
    target_date = BACKTEST_DATE or dt.now().date()
    limits = {"day": 2000, "60minute": 400}
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
                    logging.info(f"DAILY BEAR {pname}: {sym} @ Close={close:.2f}")
        except Exception as e:
            logging.warning(f"Daily bear scan failed for {sym}: {e}")
    return results

def export_to_excel(results):
    if not results:
        logging.info("No bearish results to export")
        return
    df = pd.DataFrame(results)
    out_dir = "output/exports"
    os.makedirs(out_dir, exist_ok=True)
    ts = dt.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(out_dir, f"Bear_Nifty50_Daily_Scan_{ts}.xlsx")
    try:
        df.to_excel(path, index=False, engine="openpyxl")
        logging.info(f"Exported {len(results)} bearish results to {path}")
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
    logging.info(f"Bear daily scanner complete: {len(results)} patterns found")

if __name__ == "__main__":
    main()
