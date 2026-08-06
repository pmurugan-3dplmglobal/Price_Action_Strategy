import os
import sys
import json
import logging
import time
import threading
import atexit
import signal
from datetime import datetime as dt, timedelta, date as date_type
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path for shared module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from kiteconnect import KiteConnect

from shared.config import (
    CFG_FILE, LIVE_MARKET_DEPLOYMENT, BACKTEST_DATE, LOOKBACK_DAYS,
    INITIAL_CAPITAL, MAX_RISK_PERCENT, TOKEN_FILE,
    NIFTY50_TF_ENTRY, NIFTY50_TF_ANCHOR, NIFTY50_TF_FALLBACK,
    BEAR_NIFTY50_STRIKE_RANGE, STOCK_REGISTRY, SUPER_STOCKS,
    NIFTY50_SCAN_INTERVAL,
    SCANNER_CONFIG_FILE, ANCHOR_SCAN_REQUEST_FILE, ANCHOR_SCAN_STOP_FILE,
    VALID_TIMEFRAMES,
    STOCK_POSITIONS_FILE, EXECUTED_PATTERNS_FILE, CYCLE_TRADES_FILE,
    EXPORT_STATE_FILE, JOURNAL_FILE,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments, sync_instruments,
    get_instrument_df, load_kite_session, create_kite_client, is_market_hours,
    init_registries, NFO_INSTRUMENTS, resolve_futures_token
)
from shared.patterns import (
    A_CACHE, _a_cache_key, detect_and_cache_a, find_bcd_forward,
    find_profit_targets_negation, calculate_rr, _trade_rr
)
from shared.option_utils import (
    resolve_option_strikes, resolve_option_contract, approximate_delta, get_expiry_date
)
from shared.journal import log_to_journal
from shared import trade_db
from shared.pid_util import check_pid_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bear_nifty50_backtest.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_ID = "bear_nifty50"
ENGINE_TYPE = "bear_nifty50"
PATTERN_TYPE = "bear"
OPTION_TYPE = "PE"

NIFTY50_TF_ENTRY = "15minute"
NIFTY50_TF_ANCHOR = "30minute"
NIFTY50_TF_FALLBACK = "15minute"
BEAR_NIFTY50_STRIKE_RANGE = 1

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
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

def load_carry_forward():
    cf_file = "output/monitor/carry_forward_bear.json"
    if not os.path.exists(cf_file):
        return []
    try:
        with open(cf_file, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_carry_forward(data):
    cf_file = "output/monitor/carry_forward_bear.json"
    try:
        with open(cf_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Carry-forward save failed: {e}")

def run_multi_day_backtest(kite, start_date, end_date, max_carry=3):
    """Run backtest over date range with carry-forward for unfilled entries."""
    results = []
    current = start_date
    carry_forward = {}  # key -> {"trade": trade, "remaining": int}
    while current <= end_date:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        
        global BACKTEST_DATE
        BACKTEST_DATE = current
        
        try:
            staged = run_scan_cycle(kite)
        except Exception as e:
            logging.error(f"Scan cycle failed for {current}: {e}")
            staged = []
        staged_keys = {f"{t['Symbol']}|{t['Pattern']}|{t['Side']}|{t['Strike']}" for t in staged}
        
        for key, cf in list(carry_forward.items()):
            if key not in staged_keys:
                staged.append(cf["trade"])
        
        if staged:
            for trade in staged:
                key = f"{trade['Symbol']}|{trade['Pattern']}|{trade['Side']}|{trade['Strike']}"
                outcome = simulate_trade_outcome(kite, trade, current)
                if outcome.get("result") == "ENTRY_NOT_TRIGGERED" and max_carry > 0:
                    remaining = carry_forward.get(key, {}).get("remaining", max_carry) - 1
                    if remaining > 0:
                        carry_forward[key] = {"trade": trade, "remaining": remaining}
                        continue
                    outcome = {"trade": trade, "result": "SKIPPED", "pnl": 0,
                               "entry": trade["Entry"], "exit": trade["Entry"],
                               "entry_ts": None, "exit_ts": None}
                results.append(outcome)
                carry_forward.pop(key, None)
        
        trade_db.clear_cycle_trades(ENGINE_TYPE)
        current += timedelta(days=1)
    
    for key, cf in carry_forward.items():
        trade = cf["trade"]
        results.append({
            "trade": trade,
            "result": "SKIPPED",
            "pnl": 0,
            "entry": trade["Entry"],
            "exit": trade["Entry"],
            "entry_ts": None,
            "exit_ts": None
        })
    
    return results

def simulate_trade_outcome(kite, trade, target_date):
    """Simulate trade outcome using option premium data (long position: CE or PE).
    Returns ENTRY_NOT_TRIGGERED when entry level is not reached in any candle."""
    try:
        opt_token = trade["OptionToken"]
        entry_premium = trade["Entry"]
        sl = trade["SL"]
        t1 = trade["T1"]
        t2 = trade["T2"]
        t3 = trade["T3"]

        from_str = target_date.strftime("%Y-%m-%d")
        to_str = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")

        df = pd.DataFrame(safe_historical(kite, opt_token, from_str, to_str, NIFTY50_TF_ENTRY))
        if df.empty:
            return {"trade": trade, "result": "NO_DATA", "pnl": 0}

        entry_ts = None
        exit_ts = None
        entry_hit = False
        result = "TIME_EXIT"
        exit_price = entry_premium

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
                if sl and low <= sl:
                    exit_price = sl
                    exit_ts = ts
                    result = "SL_HIT"
                    break
                if t3 and high >= t3:
                    exit_price = t3
                    exit_ts = ts
                    result = "T3_HIT"
                    break
                if t2 and high >= t2:
                    pass
                if t1 and high >= t1:
                    pass

        if not entry_hit:
            return {"trade": trade, "result": "ENTRY_NOT_TRIGGERED", "pnl": 0,
                    "entry": entry_premium, "exit": entry_premium,
                    "entry_ts": None, "exit_ts": None}

        if not exit_ts:
            exit_price = float(df.iloc[-1]['close'])
            exit_ts = df.iloc[-1]['date']
            result = "TIME_EXIT"

        lot_size = trade["Config"]["lot_size"]
        pnl = exit_price - entry_premium
        pnl_points = round(pnl * lot_size, 2)

        return {
            "trade": trade,
            "result": result,
            "pnl": pnl_points,
            "entry": entry_premium,
            "exit": exit_price,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts
        }
    except Exception as e:
        logging.error(f"Simulation error: {e}")
        return {"trade": trade, "result": "ERROR", "pnl": 0,
                "entry": trade.get("Entry"), "exit": trade.get("Entry"),
                "entry_ts": None, "exit_ts": None}

def run_scan_cycle(kite):
    _refresh_nopa_config()
    target_date = BACKTEST_DATE
    ref_now = dt.now() if target_date is None else target_date
    limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "4hour": 600, "day": 2000}
    max_days_entry = limits.get(NIFTY50_TF_ENTRY, 180)
    max_days_anchor = limits.get(NIFTY50_TF_ANCHOR, 180)
    from_entry = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_entry))).strftime("%Y-%m-%d")
    to_entry = ref_now.strftime("%Y-%m-%d")
    from_anchor = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
    to_anchor = ref_now.strftime("%Y-%m-%d")
    staged = []
    staged_keys = set()
    scan_order = SUPER_STOCKS + [s for s in STOCK_REGISTRY if s not in SUPER_STOCKS]

    for symbol in scan_order:
        if symbol not in STOCK_REGISTRY:
            continue
        config = STOCK_REGISTRY[symbol]
        token = resolve_futures_token(symbol) or config["token"]

        try:
            df_spot_entry = pd.DataFrame(safe_historical(kite, token, from_entry, to_entry, NIFTY50_TF_ENTRY))
            df_spot_anchor = pd.DataFrame(safe_historical(kite, token, from_anchor, to_anchor, NIFTY50_TF_ANCHOR))
        except Exception as e:
            logging.warning(f"Spot data fetch failed for {symbol} (token={token}): {e}")
            continue
        if df_spot_entry.empty or df_spot_anchor.empty:
            continue

        cache_key = _a_cache_key(symbol, target_date or dt.now().date())
        if cache_key not in A_CACHE or A_CACHE[cache_key] is None:
            if len(df_spot_anchor) >= 5:
                detect_and_cache_a(df_spot_anchor, symbol, target_date or dt.now().date(), PATTERN_TYPE)

        cache = A_CACHE.get(cache_key)
        if cache is None:
            continue

        if cache["needs_bcd"]:
            bcd = find_bcd_forward(df_spot_entry, cache["a_ts"], cache["benchmark"], PATTERN_TYPE)
            if bcd is None:
                continue
            bcd_ts = bcd['date']
        else:
            bcd_ts = df_spot_entry.iloc[-1]['date']

        current_spot = float(df_spot_entry.iloc[-1]['close'])
        step = config["strike_step"]
        try:
            contract = resolve_option_contract(symbol, current_spot, step, OPTION_TYPE, engine_type=ENGINE_TYPE)
            if contract is None:
                logging.warning(f"No contract resolved for {symbol} @ {current_spot}")
                continue
            df_opt = pd.DataFrame(safe_historical(kite, contract["token"], from_entry, to_entry, NIFTY50_TF_ENTRY))
        except Exception as e:
            logging.warning(f"Option data fetch failed for {symbol}: {e}")
            continue
        if df_opt.empty:
            continue

        bcd_dt = pd.Timestamp(bcd_ts)
        opt_row = df_opt[df_opt['date'] >= bcd_dt]
        if opt_row.empty:
            continue
        entry_premium = float(opt_row.iloc[0]['close'])

        expiry_date = get_expiry_date(symbol)
        days_to_expiry = (expiry_date - date_type.today()).days
        delta = approximate_delta(current_spot, contract['strike'], OPTION_TYPE, days_to_expiry)

        sl_premium = round(entry_premium + delta * (cache['SL'] - current_spot), 2)
        sl_premium = max(round(0.1 * entry_premium, 2), sl_premium)
        t1 = round(entry_premium + delta * (cache['t1'] - current_spot), 2) if cache.get('t1') else None
        t2 = round(entry_premium + delta * (cache['t2'] - current_spot), 2) if cache.get('t2') else None
        t3 = round(entry_premium + delta * (cache['t3'] - current_spot), 2) if cache.get('t3') else None

        if sl_premium >= entry_premium or (t1 and t1 <= entry_premium):
            continue

        key = f"{symbol}|{cache['pattern_name']}|{OPTION_TYPE}|{contract['strike']}"
        if key in staged_keys:
            continue

        trade_data = {
            "Symbol": symbol,
            "OptionSymbol": contract["tradingsymbol"],
            "OptionToken": contract["token"],
            "Strike": contract["strike"],
            "Side": OPTION_TYPE,
            "Entry": entry_premium,
            "SL": sl_premium,
            "T1": t1, "T2": t2, "T3": t3,
            "Pattern": cache["pattern_name"],
            "Config": config,
            "carry_forward": False
        }
        staged.append(trade_data)
        staged_keys.add(key)
        trade_db.stage_cycle_trade(ENGINE_TYPE, trade_data)
        logging.info(f"BACKTEST MATCH: {symbol} {contract['tradingsymbol']} | {cache['pattern_name']} | Entry: {entry_premium:.2f} | SL: {sl_premium:.2f} | T1: {t1} | T2: {t2} | T3: {t3}")

    cf_pool = load_carry_forward()
    for cf in cf_pool:
        sym = cf.get("Symbol")
        if sym in staged_keys or sym not in STOCK_REGISTRY:
            continue
        side = cf.get("Side", OPTION_TYPE)
        try:
            tk = STOCK_REGISTRY[sym]["token"]
            cf_lookback = limits.get(NIFTY50_TF_ENTRY, 60)
            cf_from = (ref_now - timedelta(days=cf_lookback)).strftime("%Y-%m-%d")
            df_cf = pd.DataFrame(safe_historical(kite, tk, cf_from, to_entry, NIFTY50_TF_ENTRY))
            if df_cf.empty:
                continue
            cp = float(df_cf.iloc[-1]['close'])
            sl = cf.get("SL", 0)
            cf_t1 = cf.get("T1")
            rr = _trade_rr(cf, side)
            sl_hit = cp <= sl
            t_hit = cf_t1 and cp >= cf_t1
            if sl_hit or t_hit or rr < 1.5:
                continue
            step = STOCK_REGISTRY[sym].get("strike_step", 50)
            strike = int(round(cp / step) * step)
            key = f"{sym}|{cf['Pattern']}|{side}|{strike}"
            if key in staged_keys:
                continue
            trade_data = {
                "Symbol": sym, "Config": STOCK_REGISTRY[sym],
                "Side": side, "Strike": strike, "Close": cp,
                "SL": sl, "T1": cf.get("T1"), "T2": cf.get("T2"),
                "T3": cf.get("T3"), "RR": round(rr, 2),
                "Pattern": cf["Pattern"], "carry_forward": True
            }
            staged.append(trade_data)
            staged_keys.add(key)
            trade_db.stage_cycle_trade(ENGINE_TYPE, trade_data)
            logging.info(f"BACKTEST RE-ENTRY: {sym} | {cf['Pattern']} | RR={rr:.2f}")
        except Exception as e:
            logging.warning(f"CF check {sym}: {e}")

    cf_save = []
    for t in staged:
        side = t.get("Side", OPTION_TYPE)
        rr = _trade_rr(t, side)
        if rr >= 1.5:
            cf_save.append({k: v for k, v in t.items() if k != "Config"})
    save_carry_forward(cf_save)

    return staged
    from_anchor = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
    to_anchor = ref_now.strftime("%Y-%m-%d")
    staged = []
    staged_keys = set()
    strike_range = BEAR_NIFTY50_STRIKE_RANGE
    scan_order = SUPER_STOCKS + [s for s in STOCK_REGISTRY if s not in SUPER_STOCKS]
    
    # 1. Fetch spot prices for all stocks
    spot_prices = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        spot_tasks = {}
        for symbol in scan_order:
            config = STOCK_REGISTRY[symbol]
            spot_tasks[pool.submit(
                lambda cfg=config: pd.DataFrame(safe_historical(kite, cfg["token"], from_entry, to_entry, NIFTY50_TF_ENTRY))
            )] = symbol
        
        for f in as_completed(spot_tasks):
            symbol = spot_tasks[f]
            try:
                df = f.result()
                if not df.empty:
                    spot_prices[symbol] = float(df.iloc[-1]['close'])
            except Exception as e:
                logging.warning(f"Spot fetch failed for {symbol}: {e}")
    
    # 2. For each stock, scan option contracts
    for symbol in scan_order:
        if symbol not in spot_prices:
            continue
        config = STOCK_REGISTRY[symbol]
        spot = spot_prices[symbol]
        step = config["strike_step"]
        
        # Resolve PE contracts around ATM
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
                    lambda c=contract: safe_historical(kite, c["token"], from_entry, to_entry, NIFTY50_TF_ENTRY)
                )] = ("entry", contract)
                opt_tasks[pool.submit(
                    lambda c=contract: safe_historical(kite, c["token"], from_anchor, to_anchor, NIFTY50_TF_ANCHOR)
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
            
            if cache_key not in A_CACHE:
                continue
            
            cache = A_CACHE[cache_key]
            if cache is None:
                continue
            
            # Phase B: Check BCD on option entry TF
            if cache["needs_bcd"]:
                bcd = find_bcd_forward(df_opt_entry, cache["a_ts"], cache["benchmark"], PATTERN_TYPE)
                if bcd is None:
                    continue
                entry_price = bcd['close']
            else:
                entry_price = float(df_opt_entry.iloc[-1]['close'])
            
            # Validate targets in premium space (bear: targets below entry)
            t1, t2, t3 = cache.get("t1"), cache.get("t2"), cache.get("t3")
            if t1 and t1 >= entry_price: t1 = None
            if t2 and t2 >= (t1 or entry_price): t2 = None
            if t3 and t3 >= (t2 or t1 or entry_price): t3 = None
            
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
    
    # Carry-forward logic
    cf_pool = load_carry_forward()
    for cf in cf_pool:
        sym = cf.get("Symbol")
        if sym not in STOCK_REGISTRY:
            continue
        side = cf.get("Side", "PE")
        try:
            tk = STOCK_REGISTRY[sym]["token"]
            cf_lookback = limits.get(NIFTY50_TF_ENTRY, 60)
            cf_from = (ref_now - timedelta(days=cf_lookback)).strftime("%Y-%m-%d")
            df_cf = pd.DataFrame(safe_historical(kite, tk, cf_from, to_entry, NIFTY50_TF_ENTRY))
            if df_cf.empty:
                continue
            cp = float(df_cf.iloc[-1]['close'])
            sl = cf.get("SL", 0)
            t1 = cf.get("T1")
            rr = _trade_rr(cf, side)
            sl_hit = cp <= sl
            t_hit = t1 and cp >= t1
            if sl_hit or t_hit or rr < 1.5:
                continue
            step = STOCK_REGISTRY[sym].get("strike_step", 50)
            strike = int(round(cp / step) * step)
            key = f"{sym}|{cf['Pattern']}|{side}|{strike}"
            if key in staged_keys or trade_db.is_pattern_executed(ENGINE_TYPE, key):
                continue
            trade_data = {
                "Symbol": sym, "Config": STOCK_REGISTRY[sym],
                "Side": side, "Strike": strike, "Close": cp,
                "SL": sl, "T1": cf.get("T1"), "T2": cf.get("T2"),
                "T3": cf.get("T3"), "RR": round(rr, 2),
                "Pattern": cf["Pattern"], "carry_forward": True
            }
            staged.append(trade_data)
            staged_keys.add(key)
            trade_db.stage_cycle_trade(ENGINE_TYPE, trade_data)
            logging.info(f"BACKTEST RE-ENTRY: {sym} | {cf['Pattern']} | RR={rr:.2f}")
        except Exception as e:
            logging.warning(f"CF check {sym}: {e}")
    
    # Save trades with RR >= 1.5 for future re-entry
    cf_save = []
    for t in staged:
        side = t.get("Side", "PE")
        rr = _trade_rr(t, side)
        if rr >= 1.5:
            cf_save.append({k: v for k, v in t.items() if k != "Config"})
    save_carry_forward(cf_save)
    
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
        logging.info("Live mode not implemented in backtest engine - use live-trade/bear_nifty50_scanner.py")
    else:
        logging.info("Backtest engine ready. Use --date or --backtest-range to run.")

if __name__ == "__main__":
    main()