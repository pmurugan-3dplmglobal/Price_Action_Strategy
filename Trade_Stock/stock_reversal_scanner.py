import os
import json
import logging
import time
import sys
import threading
COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)
import paths
from datetime import datetime as dt, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

from kiteconnect import KiteConnect

from trading_core import (
    load_kite_session,
    log_to_journal,
    scan_anchor_bcd_breakout_generic,
    get_adaptive_lookback,
    resample_timeframe,
    sync_stock_tokens,
    write_scan_display_data as shared_write_display,
    clean_timestamp,
    STOCK_REGISTRY
)
from equity_universe import get_universe_symbols_and_tokens, is_liquid_cash_stock

# Side-specific profile. Wrappers call configure_bull() / configure_bear() before use.
PROFILE = {
    "side": "BULL",
    "display_side": "BUY",
    "scanner_label": "S1_Anchor_BCD",
    "display_file": paths.SCAN_DISPLAY_STOCK_FILE,
    "export_prefix": "Nifty50_Daily_Scan_",
    "log_file": "output/logs/bull_daily_scanner.log",
    "journal_tag": "SCAN_MATCH",
    "config_section": "daily",
    "summary_title": "NIFTY 50 DAILY SCAN SUMMARY",
    "pattern_width": 20,
    "match_prefix": "MATCH",
    "anchor_msg": "bullish",
    "banner": "  NIFTY 50 DAILY TIMEFRAME SCANNER",
    "handle_anchor_flag": True,
}

TARGET_INDEX = "NIFTY50"
LOOKBACK_DAYS = 120
TIMEFRAME_ENTRY = "day"
TIMEFRAME_ANCHOR = "day"

OUTPUT_FILE = f"output/exports/{PROFILE['export_prefix']}{dt.now().strftime('%Y%m%d_%H%M')}.csv"

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
ANCHOR_SCAN_REQUEST_FILE = os.path.join("output", "monitor", "anchor_scan_request.txt")

SCAN_DISPLAY_FILE = PROFILE["display_file"]


def _configure_logging():
    logger = logging.getLogger()
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(PROFILE["log_file"], mode="a", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )


_configure_logging()


def configure_bull():
    global PROFILE, OUTPUT_FILE, SCAN_DISPLAY_FILE
    PROFILE.update({
        "side": "BULL",
        "display_side": "BUY",
        "scanner_label": "S1_Anchor_BCD",
        "display_file": paths.SCAN_DISPLAY_STOCK_FILE,
        "export_prefix": "Nifty50_Daily_Scan_",
        "log_file": "output/logs/bull_daily_scanner.log",
        "journal_tag": "SCAN_MATCH",
        "config_section": "daily",
        "summary_title": "NIFTY 50 DAILY SCAN SUMMARY",
        "pattern_width": 20,
        "match_prefix": "MATCH",
        "anchor_msg": "bullish",
        "banner": "  NIFTY 50 DAILY TIMEFRAME SCANNER",
        "handle_anchor_flag": True,
    })
    OUTPUT_FILE = f"output/exports/{PROFILE['export_prefix']}{dt.now().strftime('%Y%m%d_%H%M')}.csv"
    SCAN_DISPLAY_FILE = PROFILE["display_file"]
    _configure_logging()


def configure_bear():
    global PROFILE, OUTPUT_FILE, SCAN_DISPLAY_FILE
    PROFILE.update({
        "side": "BEAR",
        "display_side": "SELL",
        "scanner_label": "S1_Bear_Anchor_BCD",
        "display_file": paths.SCAN_DISPLAY_BEAR_FILE,
        "export_prefix": "Nifty50_Daily_Scan_BEAR_",
        "log_file": "output/logs/bull_bear_daily_scanner.log",
        "journal_tag": "SCAN_MATCH_BEAR",
        "config_section": "bear_trade",
        "summary_title": "NIFTY 50 BEARISH DAILY SCAN SUMMARY",
        "pattern_width": 25,
        "match_prefix": "BEAR MATCH",
        "anchor_msg": "bearish",
        "banner": "  NIFTY 50 BEARISH DAILY REVERSAL SCANNER",
        "handle_anchor_flag": False,
    })
    OUTPUT_FILE = f"output/exports/{PROFILE['export_prefix']}{dt.now().strftime('%Y%m%d_%H%M')}.csv"
    SCAN_DISPLAY_FILE = PROFILE["display_file"]
    _configure_logging()


def run_scan(kite):
    effective_lookback = get_adaptive_lookback(TIMEFRAME_ENTRY, "STOCK_SPOT", LOOKBACK_DAYS)
    from_date = (dt.now() - timedelta(days=min(effective_lookback, 2000))).strftime("%Y-%m-%d")
    to_date = dt.now().strftime("%Y-%m-%d")
    scanners = [
        (PROFILE["scanner_label"], lambda df_e, df_a: scan_anchor_bcd_breakout_generic(df_e, df_a, side=PROFILE["side"])),
    ]
    results = []
    results_lock = threading.Lock()
    symbols_list, token_map = get_universe_symbols_and_tokens(kite, TARGET_INDEX)
    scan_order = sorted(symbols_list)
    logging.info(f"Executing {PROFILE['side']} Scan for Universe '{TARGET_INDEX}' ({len(scan_order)} symbols) on timeframe '{TIMEFRAME_ENTRY}'...")
    tf_clean = str(TIMEFRAME_ENTRY).lower()
    if tf_clean in ["week", "weekly", "w", "1w", "day", "d", "1d"]:
        fetch_tf = "day"
    elif tf_clean in ["3hr", "3h", "180min", "180minute", "4h", "4hour", "240min", "240minute", "1hr", "1h", "60min", "60minute"]:
        fetch_tf = "60minute"
    elif tf_clean in ["75min", "75mins", "75m", "75minute", "75minutes"]:
        fetch_tf = "15minute"
    elif tf_clean in ["30min", "30mins", "30m", "30minute", "30minutes"]:
        fetch_tf = "30minute"
    elif tf_clean in ["15min", "15mins", "15m", "15minute", "15minutes"]:
        fetch_tf = "15minute"
    elif tf_clean in ["10min", "10mins", "10m", "10minute", "10minutes"]:
        fetch_tf = "10minute"
    elif tf_clean in ["5min", "5mins", "5m", "5minute", "5minutes"]:
        fetch_tf = "5minute"
    elif tf_clean in ["3min", "3mins", "3m", "3minute", "3minutes"]:
        fetch_tf = "3minute"
    else:
        fetch_tf = "day"

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {}
        for symbol in scan_order:
            tok = token_map.get(symbol, 0)
            if not tok:
                logging.warning(f"Skipping {symbol}: Instrument token missing")
                with results_lock:
                    results.append({"Symbol": symbol, "Pattern": "NO_TOKEN"})
                continue
            futures[pool.submit(
                lambda t=tok: pd.DataFrame(kite.historical_data(t, from_date, to_date, fetch_tf))
            )] = symbol
            time.sleep(0.2)
        for f in as_completed(futures):
            symbol = futures[f]
            try:
                df_raw = f.result()
                df_e = resample_timeframe(df_raw, TIMEFRAME_ENTRY)
            except Exception as e:
                logging.warning(f"Data error for {symbol}: {e}")
                with results_lock:
                    results.append({"Symbol": symbol, "Pattern": "ERROR", "Error": str(e)})
                continue
            if df_e.empty:
                with results_lock:
                    results.append({"Symbol": symbol, "Pattern": "NO_DATA"})
                continue
            if TARGET_INDEX != "NIFTY50" and not is_liquid_cash_stock(df_e):
                logging.info(f"Skipping {symbol} - failed cash liquidity shield (low volume/turnover)")
                with results_lock:
                    results.append({"Symbol": symbol, "Pattern": "ILLIQUID_SKIPPED"})
                continue
            df_a = df_e.copy()
            latest = df_e.iloc[-1]
            matched = False
            for name, scanner_func in scanners:
                result = scanner_func(df_e, df_a)
                if result:
                    entry_px = float(result.get("Close") or result.get("Entry") or result.get("entry") or 0.0)
                    result["Close"] = entry_px
                    result["Entry"] = entry_px
                    result["Symbol"] = symbol
                    result["Scan_Date"] = dt.now().strftime("%Y-%m-%d")
                    result["Latest_Close"] = round(float(latest['close']), 2)
                    result["Latest_High"] = round(float(latest['high']), 2)
                    result["Latest_Low"] = round(float(latest['low']), 2)
                    result["Latest_Open"] = round(float(latest['open']), 2)
                    result["Volume"] = int(latest.get('volume', 0))
                    result["Pattern_Name"] = name
                    with results_lock:
                        results.append(result)
                    logging.info(f"  -> {PROFILE['match_prefix']}: {symbol} | {result['Pattern']} | Entry: {entry_px:.2f} | SL: {result['SL']:.2f} | T1: {result['T1']:.2f} | RR: {result['RR']:.2f}")
                    log_to_journal(symbol, result["Pattern"], TIMEFRAME_ENTRY,
                                   PROFILE["journal_tag"], "MATCHED",
                                   f"Entry={entry_px:.2f} SL={result['SL']:.2f} RR={result['RR']:.2f}",
                                   entry=entry_px, sl=result['SL'],
                                   target=result.get('T3',''), rr=result['RR'])
                    c_time = clean_timestamp(result.get("CandleATime") or result.get("CandleTime") or dt.now().strftime("%Y-%m-%d %H:%M"))
                    with position_lock:
                        all_disp = [r for r in results if r.get("Pattern") and r.get("Pattern") not in ["NO_MATCH", "ERROR", "NO_DATA"]]
                        formatted_all = [{
                            "symbol": r.get("Symbol") or r.get("symbol", ""),
                            "contract": r.get("Symbol") or r.get("symbol", ""),
                            "entry_spot": r.get("Close") or r.get("Entry"),
                            "current_sl": r.get("SL"),
                            "t1": r.get("T1"),
                            "t2": r.get("T2"),
                            "t3": r.get("T3"),
                            "rr": r.get("RR", 0.0),
                            "pattern": r.get("Pattern"),
                            "timeframe": TIMEFRAME_ENTRY,
                            "side": PROFILE["display_side"],
                            "entry_time": clean_timestamp(r.get("CandleATime") or r.get("CandleTime")),
                            "candle_a_time": clean_timestamp(r.get("CandleATime") or r.get("CandleTime"))
                        } for r in all_disp if r.get("Symbol") or r.get("symbol")]
                        shared_write_display(formatted_all, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
                    matched = True
                    break
            if not matched:
                with results_lock:
                    results.append({"Symbol": symbol, "Pattern": "NO_MATCH"})
    formed_display = []
    for r in results:
        if r.get("Pattern") and r.get("Pattern") not in ["NO_MATCH", "ERROR", "NO_DATA"]:
            c_time = clean_timestamp(r.get("CandleATime") or r.get("CandleTime") or r.get("Scan_Date"))
            formed_display.append({
                "symbol": r.get("Symbol"),
                "contract": r.get("Symbol"),
                "entry_spot": r.get("Close") or r.get("Entry"),
                "current_sl": r.get("SL"),
                "t1": r.get("T1"),
                "t2": r.get("T2"),
                "t3": r.get("T3"),
                "rr": r.get("RR", 0.0),
                "pattern": r.get("Pattern"),
                "timeframe": TIMEFRAME_ENTRY,
                "side": PROFILE["display_side"],
                "entry_time": c_time,
                "candle_a_time": c_time
            })
    if formed_display:
        with position_lock:
            shared_write_display(formed_display, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
    return results

def export_results(results):
    rows = []
    for r in results:
        rows.append({
            "Symbol": r.get("Symbol", ""),
            "Pattern": r.get("Pattern", ""),
            "Entry": r.get("Close", ""),
            "Stop_Loss": r.get("SL", ""),
            "T1": r.get("T1", ""),
            "T2": r.get("T2", ""),
            "T3": r.get("T3", ""),
            "R_R_Ratio": round(r.get("RR", 0), 2) if r.get("RR") else "",
            "Latest_Close": r.get("Latest_Close", ""),
            "Latest_High": r.get("Latest_High", ""),
            "Latest_Low": r.get("Latest_Low", ""),
            "Latest_Open": r.get("Latest_Open", ""),
            "Volume": r.get("Volume", ""),
            "Error": r.get("Error", ""),
            "Scan_Date": r.get("Scan_Date", "")
        })
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)
    return OUTPUT_FILE

def run_anchor_scan(kite):
    logging.info(f"On-demand scan requested: executing full A-B-C-D {PROFILE['anchor_msg']} breakout scan across Nifty 50 stocks...")
    load_program_config()
    results = run_scan(kite)
    logging.info(f"On-demand scan complete: found {len([r for r in (results or []) if r.get('T1')])} full A-B-C-D {PROFILE['anchor_msg']} setup(s)")

def print_summary(results):
    matches = [r for r in results if r.get("T1")]
    no_match = [r for r in results if r.get("Pattern") == "NO_MATCH"]
    errors = [r for r in results if r.get("Pattern") == "ERROR"]
    print("\n" + "=" * 80)
    print(f"  {PROFILE['summary_title']}")
    print(f"  Scan Time: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print(f"  Total Stocks Scanned: {len(results)}")
    print(f"  Pattern Matches:     {len(matches)}")
    print(f"  No Match:            {len(no_match)}")
    print(f"  Errors:              {len(errors)}")
    print("-" * 80)
    if matches:
        print(f"\n  {'Symbol':<12} {'Pattern':<{PROFILE['pattern_width']}} {'Entry':<10} {'SL':<10} {'T1':<10} {'T2':<10} {'RR':<8}")
        print(f"  {'-'*12} {'-'*PROFILE['pattern_width']} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
        for m in sorted(matches, key=lambda x: x.get("RR", 0), reverse=True):
            rr = round(m["RR"], 2) if m.get("RR") else 0
            entry_s = f"{m['Close']:.2f}" if m.get("Close") is not None else "N/A"
            sl_s = f"{m['SL']:.2f}" if m.get("SL") is not None else "N/A"
            t1_s = f"{m['T1']:.2f}" if m.get("T1") is not None else "N/A"
            t2_s = f"{m['T2']:.2f}" if m.get("T2") is not None else "N/A"
            print(f"  {m['Symbol']:<12} {m['Pattern']:<{PROFILE['pattern_width']}} {entry_s:<10} {sl_s:<10} {t1_s:<10} {t2_s:<10} {rr:<8.2f}")
    print("=" * 80)

def load_program_config():
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "input", "program_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f).get(PROFILE["config_section"], {})
            if "timeframe" in cfg:
                globals().update({"TIMEFRAME_ENTRY": cfg["timeframe"], "TIMEFRAME_ANCHOR": cfg["timeframe"]})
            if "lookback_days" in cfg: globals().update({"LOOKBACK_DAYS": int(cfg["lookback_days"])})
            if "target_index" in cfg: globals().update({"TARGET_INDEX": str(cfg["target_index"])})
    except Exception as e:
        logging.warning(f"Config load: {e}")

def main():
    load_program_config()
    anchor_only = "--anchor-only" in sys.argv
    logging.info("=" * 60)
    logging.info(PROFILE["banner"])
    logging.info("=" * 60)
    try:
        ak, at = load_kite_session()
        kite = KiteConnect(api_key=ak)
        kite.set_access_token(at)
        sync_stock_tokens(kite)
        if anchor_only:
            logging.info(f"Running anchor-only scan (daily {PROFILE['side'].lower()})...")
            run_anchor_scan(kite)
            return
        logging.info(f"Scanning {len(STOCK_REGISTRY)} stocks for {PROFILE['side']} setups...")
        logging.info(f"Lookback: {LOOKBACK_DAYS} days")

        if PROFILE["handle_anchor_flag"] and os.path.exists(ANCHOR_SCAN_REQUEST_FILE):
            try:
                with open(ANCHOR_SCAN_REQUEST_FILE) as f:
                    engine = f.read().strip()
                os.remove(ANCHOR_SCAN_REQUEST_FILE)
                if engine != PROFILE["config_section"]:
                    logging.info(f"Anchor scan flag not for {PROFILE['config_section']}, skipping (got {engine})")
                else:
                    logging.info(f"Anchor scan requested via flag file (engine: {engine})")
                    run_anchor_scan(kite)
            except Exception:
                pass

        results = run_scan(kite)
        print_summary(results)
        out = export_results(results)
        logging.info(f"Results exported to: {os.path.abspath(out)}")
        print(f"\n  Report saved: {os.path.abspath(out)}")
        print()
    except Exception as e:
        logging.error(f"Scanner failed: {e}")
        import traceback
        traceback.print_exc()
