import os
import sys
import json
import logging
import time
import threading
from datetime import datetime as dt, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path for shared module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from kiteconnect import KiteConnect

from shared.config import (
    CFG_FILE, LIVE_MARKET_DEPLOYMENT, BACKTEST_DATE, LOOKBACK_DAYS,
    INITIAL_CAPITAL, MAX_RISK_PERCENT, TOKEN_FILE,
    INDEX_TF_ENTRY, INDEX_TF_ANCHOR, INDEX_TF_FALLBACK,
    INDEX_STRIKE_RANGE, INDEX_REGISTRY,
    INDEX_SCAN_INTERVAL,
    SCANNER_CONFIG_FILE, ANCHOR_SCAN_REQUEST_FILE, ANCHOR_SCAN_STOP_FILE,
    VALID_TIMEFRAMES,
    STOCK_POSITIONS_FILE, EXECUTED_PATTERNS_FILE, CYCLE_TRADES_FILE,
    EXPORT_STATE_FILE, JOURNAL_FILE,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments, sync_instruments,
    get_instrument_df, load_kite_session, create_kite_client, is_market_hours,
    init_registries, NFO_INSTRUMENTS
)
from shared.patterns import (
    A_CACHE, _a_cache_key, detect_and_cache_a, find_bcd_forward,
    find_profit_targets_negation, calculate_rr, _trade_rr
)
from shared.option_utils import (
    resolve_option_strikes, resolve_option_contract, sync_instruments as sync_opt_instruments
)
from shared.journal import log_to_journal
from shared import trade_db
from shared.pid_util import check_pid_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bull_index_backtest.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_ID = "bull_index"
ENGINE_TYPE = "bull_index"
PATTERN_TYPE = "bull"
OPTION_TYPE = "CE"

_NOPA_DISABLED = False

def _refresh_nopa_config():
    global _NOPA_DISABLED
    try:
        with open(SCANNER_CONFIG_FILE) as f:
            _NOPA_DISABLED = json.load(f).get("disable_nopa", False)
    except Exception:
        _NOPA_DISABLED = False

def _load_config():
    with open(CFG_FILE) as f:
        return json.load(f)

def run_multi_day_backtest(kite, start_date, end_date):
    """Run backtest over date range."""
    results = []
    current = start_date
    while current <= end_date:
        if current.weekday() >= 5:  # Skip weekends
            current += timedelta(days=1)
            continue
        
        global BACKTEST_DATE
        BACKTEST_DATE = current
        
        staged = run_scan_cycle(kite)
        if staged:
            # Simulate trade outcome for each staged trade
            for trade in staged:
                outcome = simulate_trade_outcome(kite, trade, current)
                results.append(outcome)
        
        trade_db.clear_cycle_trades(ENGINE_TYPE)
        current += timedelta(days=1)
    
    return results

def simulate_trade_outcome(kite, trade, target_date):
    """Simulate trade outcome using option premium data."""
    try:
        opt_token = trade["OptionToken"]
        entry_premium = trade["Entry"]
        sl = trade["SL"]
        t1 = trade["T1"]
        t2 = trade["T2"]
        t3 = trade["T3"]
        
        # Get option premium data for the day
        from_str = target_date.strftime("%Y-%m-%d")
        to_str = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
        
        df = pd.DataFrame(safe_historical(kite, opt_token, from_str, to_str, INDEX_TF_ENTRY))
        if df.empty:
            return {"trade": trade, "result": "NO_DATA", "pnl": 0}
        
        # Track intraday movement
        entry_ts = None
        exit_ts = None
        entry_hit = False
        sl_hit = False
        t1_hit = False
        t2_hit = False
        t3_hit = False
        
        for _, row in df.iterrows():
            high = row['high']
            low = row['low']
            close = row['close']
            ts = row['date']
            
            if not entry_hit and low <= entry_premium <= high:
                entry_hit = True
                entry_ts = ts
                continue
            
            if entry_hit:
                if low <= sl:
                    sl_hit = True
                    exit_ts = ts
                    break
                if t1 and high >= t1:
                    t1_hit = True
                if t2 and high >= t2:
                    t2_hit = True
                if t3 and high >= t3:
                    t3_hit = True
                    exit_ts = ts
                    break
        
        # Calculate P&L
        if entry_ts is None:
            entry_ts = df.iloc[0]['date']
        
        if sl_hit:
            pnl = sl - entry_premium
            result = "SL_HIT"
            if exit_ts is None:
                exit_ts = df.iloc[-1]['date']
        elif t3_hit:
            pnl = t3 - entry_premium
            result = "T3_HIT"
        elif t2_hit:
            pnl = t2 - entry_premium
            result = "T2_HIT"
        elif t1_hit:
            pnl = t1 - entry_premium
            result = "T1_HIT"
        else:
            # Exit at close
            last_close = df.iloc[-1]['close']
            last_ts = df.iloc[-1]['date']
            pnl = last_close - entry_premium
            result = "TIME_EXIT"
            exit_ts = last_ts
        
        # Convert to points (multiply by lot size)
        lot_size = trade["Config"]["lot_size"]
        pnl_points = pnl * lot_size
        
        return {
            "trade": trade,
            "result": result,
            "pnl": pnl_points,
            "entry": entry_premium,
            "exit": entry_premium + pnl,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts
        }
    except Exception as e:
        logging.error(f"Simulation error: {e}")
        return {"trade": trade, "result": "ERROR", "pnl": 0}

def run_scan_cycle(kite):
    _refresh_nopa_config()
    target_date = BACKTEST_DATE
    ref_now = dt.now() if target_date is None else target_date
    limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "4hour": 600, "day": 2000}
    max_days_entry = limits.get(INDEX_TF_ENTRY, 180)
    max_days_anchor = limits.get(INDEX_TF_ANCHOR, 180)
    from_entry = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_entry))).strftime("%Y-%m-%d")
    to_entry = ref_now.strftime("%Y-%m-%d")
    from_anchor = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
    to_anchor = ref_now.strftime("%Y-%m-%d")
    staged = []
    staged_keys = set()
    strike_range = INDEX_STRIKE_RANGE
    scan_order = list(INDEX_REGISTRY.keys())
    
    # 1. Fetch spot prices for all indices
    spot_prices = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        spot_tasks = {}
        for symbol in scan_order:
            config = INDEX_REGISTRY[symbol]
            spot_tasks[pool.submit(
                lambda cfg=config: pd.DataFrame(safe_historical(kite, cfg["token"], from_entry, to_entry, INDEX_TF_ENTRY))
            )] = symbol
        
        for f in as_completed(spot_tasks):
            symbol = spot_tasks[f]
            try:
                df = f.result()
                if not df.empty:
                    spot_prices[symbol] = float(df.iloc[-1]['close'])
            except Exception as e:
                logging.warning(f"Spot fetch failed for {symbol}: {e}")
    
    # 2. For each index, scan option contracts
    for symbol in scan_order:
        if symbol not in spot_prices:
            continue
        config = INDEX_REGISTRY[symbol]
        spot = spot_prices[symbol]
        step = config["strike_step"]
        
        # Resolve CE contracts around ATM
        contracts = resolve_option_strikes(symbol, spot, step, OPTION_TYPE, strike_range, ENGINE_TYPE)
        if not contracts:
            logging.warning(f"No contracts resolved for {symbol} @ {spot}")
            continue
        
        # 3. Fetch option premium data for all contracts
        opt_data = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            opt_tasks = {}
            for contract in contracts:
                opt_tasks[pool.submit(
                    lambda c=contract: safe_historical(kite, c["token"], from_entry, to_entry, INDEX_TF_ENTRY)
                )] = ("entry", contract)
                opt_tasks[pool.submit(
                    lambda c=contract: safe_historical(kite, c["token"], from_anchor, to_anchor, INDEX_TF_ANCHOR)
                )] = ("anchor", contract)
            
            for f in as_completed(opt_tasks):
                tf_type, contract = opt_tasks[f]
                try:
                    df = pd.DataFrame(f.result())
                    if df.empty:
                        continue
                    tsym = contract["tradingsymbol"]
                    if tsym not in opt_data:
                        opt_data[tsym] = {}
                    opt_data[tsym][tf_type] = df
                except Exception as e:
                    logging.warning(f"Option data failed for {contract['tradingsymbol']}: {e}")
        
        # 4. Run pattern detection on each contract
        for contract in contracts:
            tsym = contract["tradingsymbol"]
            if tsym not in opt_data or "entry" not in opt_data[tsym] or "anchor" not in opt_data[tsym]:
                continue
            
            df_opt_entry = opt_data[tsym]["entry"]
            df_opt_anchor = opt_data[tsym]["anchor"]
            
            # Phase A: Detect/cache A-pattern on option anchor TF
            cache_key = _a_cache_key(tsym, target_date or BACKTEST_DATE or dt.now().date())
            if cache_key not in A_CACHE:
                if len(df_opt_anchor) >= 5:
                    detect_and_cache_a(df_opt_anchor, tsym, target_date or BACKTEST_DATE or dt.now().date(), PATTERN_TYPE)
            
            if cache_key not in A_CACHE or A_CACHE[cache_key] is None:
                continue
            
            cache = A_CACHE[cache_key]
            
            # Phase B: Check BCD on option entry TF
            if cache["needs_bcd"]:
                bcd = find_bcd_forward(df_opt_entry, cache["a_ts"], cache["benchmark"], PATTERN_TYPE)
                if bcd is None:
                    continue
                entry_price = bcd['close']
            else:
                entry_price = float(df_opt_entry.iloc[-1]['close'])
            
            # Validate targets in premium space
            t1, t2, t3 = cache.get("t1"), cache.get("t2"), cache.get("t3")
            if t1 and t1 <= entry_price: t1 = None
            if t2 and t2 <= (t1 or entry_price): t2 = None
            if t3 and t3 <= (t2 or t1 or entry_price): t3 = None
            
            # Stage trade with this option contract
            side = OPTION_TYPE
            key = f"{symbol}|{cache['pattern_name']}|{side}|{contract['strike']}"
            if trade_db.is_pattern_executed(ENGINE_TYPE, key) or key in staged_keys:
                continue
            
            trade_data = {
                "Symbol": symbol,
                "OptionSymbol": tsym,
                "OptionToken": contract["token"],
                "Strike": contract["strike"],
                "Side": side,
                "Entry": entry_price,
                "SL": cache["SL"],
                "T1": t1, "T2": t2, "T3": t3,
                "RR": "",
                "Pattern": cache["pattern_name"],
                "Config": config
            }
            staged.append(trade_data)
            staged_keys.add(key)
            trade_db.stage_cycle_trade(ENGINE_TYPE, trade_data)
            logging.info(f"BACKTEST OPTION MATCH: {symbol} {tsym} | {cache['pattern_name']} | Entry: {entry_price:.2f} | SL: {cache['SL']:.2f} | T3: {t3}")
    
    return staged

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Force live mode")
    parser.add_argument("--force-backtest", action="store_true", help="Force backtest mode")
    parser.add_argument("--date", type=str, help="Single day backtest YYYY-MM-DD")
    parser.add_argument("--backtest-range", type=str, help="Multi-day backtest START,END")
    parser.add_argument("--anchor-only", action="store_true", help="Run anchor scan once and exit")
    args = parser.parse_args()
    
    check_pid_file(ENGINE_ID)
    
    config = _load_config()
    backtest_mode = config.get("_backtest", False)
    if args.live:
        backtest_mode = False
    if args.force_backtest:
        backtest_mode = True
    
    global LIVE_MARKET_DEPLOYMENT, BACKTEST_DATE
    LIVE_MARKET_DEPLOYMENT = not backtest_mode
    
    kite = create_kite_client()
    fetch_instruments(kite)
    
    if args.anchor_only:
        # Run anchor scan for the target date
        target_date = BACKTEST_DATE or dt.now().date()
        logging.info(f"Anchor scan for {target_date} - not implemented in backtest engine")
        return
    
    if args.date:
        BACKTEST_DATE = dt.strptime(args.date, "%Y-%m-%d").date()
        results = run_multi_day_backtest(kite, BACKTEST_DATE, BACKTEST_DATE)
        print(f"Backtest completed for {BACKTEST_DATE}: {len(results)} trades")
        for r in results:
            ets = r['entry_ts'].strftime('%m-%d %H:%M') if r['entry_ts'] else '?'
            xts = r['exit_ts'].strftime('%m-%d %H:%M') if r['exit_ts'] else '?'
            print(f"  {r['result']:10s} | {r['pnl']:7.0f} pts | {ets}-{xts} | {r['trade']['Symbol']} {r['trade']['OptionSymbol']}")
        res_path = os.path.join("output", "monitor", f"backtest_results_{ENGINE_TYPE}.json")
        os.makedirs(os.path.dirname(res_path), exist_ok=True)
        with open(res_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Results saved -> {res_path}")
        return
    
    if args.backtest_range:
        start_str, end_str = args.backtest_range.split(',')
        start = dt.strptime(start_str, "%Y-%m-%d").date()
        end = dt.strptime(end_str, "%Y-%m-%d").date()
        results = run_multi_day_backtest(kite, start, end)
        print(f"Backtest completed {start} to {end}: {len(results)} trades")
        total_pnl = sum(r['pnl'] for r in results)
        wins = sum(1 for r in results if r['pnl'] > 0)
        print(f"Total P&L: {total_pnl:.0f} pts, Win rate: {wins}/{len(results)} = {wins/len(results)*100:.1f}%")
        for r in results:
            ets = r['entry_ts'].strftime('%m-%d %H:%M') if r['entry_ts'] else '?'
            xts = r['exit_ts'].strftime('%m-%d %H:%M') if r['exit_ts'] else '?'
            print(f"  {r['result']:10s} | {r['pnl']:7.0f} pts | {ets}-{xts} | {r['trade']['Symbol']} {r['trade']['OptionSymbol']}")
        res_path = os.path.join("output", "monitor", f"backtest_results_{ENGINE_TYPE}.json")
        os.makedirs(os.path.dirname(res_path), exist_ok=True)
        with open(res_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Results saved -> {res_path}")
        return
    
    if LIVE_MARKET_DEPLOYMENT:
        logging.info("Live mode not implemented in backtest engine - use live-trade/bull_index_engine.py")
    else:
        logging.info("Backtest engine ready. Use --date or --backtest-range to run.")

if __name__ == "__main__":
    main()