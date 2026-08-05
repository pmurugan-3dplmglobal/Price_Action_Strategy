import os
import sys
import json
import logging
import time
import threading
import atexit
import signal
from datetime import datetime as dt, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
from kiteconnect import KiteConnect

# Add project root to path for shared module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    CFG_FILE, LIVE_MARKET_DEPLOYMENT, BACKTEST_DATE, LOOKBACK_DAYS,
    INITIAL_CAPITAL, MAX_RISK_PERCENT, TOKEN_FILE,
    NIFTY50_TF_ENTRY, NIFTY50_TF_ANCHOR, TIMEFRAME_FALLBACK,
    NIFTY50_STRIKE_RANGE, STOCK_REGISTRY, SUPER_STOCKS,
    NIFTY50_SCAN_INTERVAL,
    SCANNER_CONFIG_FILE, ANCHOR_SCAN_REQUEST_FILE, ANCHOR_SCAN_STOP_FILE,
    VALID_TIMEFRAMES,
    JOURNAL_FILE,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments,
    get_instrument_df, load_kite_session, create_kite_client, is_market_hours,
    init_registries
)
from shared.patterns import (
    A_CACHE, _a_cache_key, detect_and_cache_a, find_bcd_forward,
    find_profit_targets_negation, calculate_rr, _trade_rr
)
from shared.option_utils import (
    resolve_option_strikes, resolve_option_contract, sync_instruments as sync_opt_instruments
)
from shared.journal import log_to_journal
from shared.trade_db import (
    create_trade,
    update_trade,
    get_active_trades,
    get_all_trades,
    get_completed_trades,
    remove_trades,
    stage_cycle_trade,
    get_cycle_trades,
    clear_cycle_trades,
    is_pattern_executed,
    clear_executed_patterns,
    record_executed_pattern,
)
from shared.pid_util import check_pid_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bull_nifty50_scanner.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_ID = "bull_nifty50"
ENGINE_TYPE = "nifty50"
PATTERN_TYPE = "bull"
OPTION_TYPE = "CE"

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
STATE_FILE = "output/monitor/bull_nifty50_state.json"
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

def save_state():
    with position_lock:
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(ACTIVE_POSITIONS, f, indent=4)
        except Exception as e:
            logging.error(f"State save failed: {e}")

def load_state():
    global ACTIVE_POSITIONS
    ACTIVE_POSITIONS = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                ACTIVE_POSITIONS.update(loaded)
            logging.info(f"Recovered {len(ACTIVE_POSITIONS)} positions from state file")
        except Exception:
            pass
    db_trades = get_active_trades(ENGINE_TYPE)
    for t in db_trades:
        sym = t.get("symbol", "")
        if not sym or sym in ACTIVE_POSITIONS:
            continue
        pos = {
            "contract": t.get("contract", ""),
            "token": t.get("token", 0),
            "entry_spot": t.get("entry_spot", 0),
            "current_sl": t.get("current_sl", 0),
            "t1": t.get("t1"),
            "t2": t.get("t2"),
            "t3": t.get("t3"),
            "trailing_stage": t.get("trailing_stage", 0),
            "lot_size": t.get("lot_size", 1),
            "position_size": t.get("position_size", 1),
            "pattern": t.get("pattern", ""),
            "timeframe": t.get("timeframe", ""),
            "side": t.get("side", OPTION_TYPE),
            "strike": t.get("strike", 0),
            "trade_id": t.get("id"),
        }
        ACTIVE_POSITIONS[sym] = pos
        logging.info(f"Recovered orphan position: {sym} (trade_id={pos['trade_id']})")
    if db_trades:
        save_state()
    logging.info(f"Total active positions loaded: {len(ACTIVE_POSITIONS)}")

def close_position(kite, pos, reason="MANUAL", symbol=None):
    if not LIVE_MARKET_DEPLOYMENT:
        logging.info(f"[BACKTEST EXIT] {pos['contract']} reason={reason}")
        return
    try:
        q = kite.quote(f"{kite.EXCHANGE_NFO}:{pos['contract']}")
        qd = q.get(f"{kite.EXCHANGE_NFO}:{pos['contract']}", {})
        ltp = qd.get("last_price", 0)
        bid = qd.get("depth", {}).get("buy", [{}])[0].get("price", 0)
        price = round((bid if bid > 0 else ltp) * 0.995, 1)
        qty = pos["lot_size"] * pos.get("position_size", 1)
        oid = kite.place_order(
            variety=kite.VARIETY_REGULAR, tradingsymbol=pos["contract"],
            exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
            price=price, product=kite.PRODUCT_NRML
        )
        entry = pos.get("entry_spot", 0)
        exit_price = price
        pnl = (exit_price - entry) * qty
        pnl_pct = round(((exit_price - entry) / entry) * 100, 2) if entry else 0
        tid = pos.get("trade_id")
        if tid:
            update_trade(tid, {"status": reason, "exit_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "pnl_percent": pnl_pct, "exit_price": exit_price})
        log_to_journal(symbol or pos.get("contract", "?"), pos.get("pattern", ""), pos.get("timeframe", ""),
                       reason, "SELL", f"OID:{oid} PnL:{pnl:.0f}",
                       entry=entry, sl=pos.get("current_sl"), target=pos.get("t1"), rr=pnl_pct)
        logging.info(f"EXIT {pos['contract']}: {reason} PnL={pnl:.0f} ({pnl_pct:.1f}%) oid={oid}")
    except Exception as e:
        logging.error(f"Exit failed for {pos['contract']}: {e}")
    with position_lock:
        for sym, p in list(ACTIVE_POSITIONS.items()):
            if p.get("contract") == pos.get("contract"):
                ACTIVE_POSITIONS.pop(sym, None)
                break
    save_state()

def monitor_positions(kite):
    if not ACTIVE_POSITIONS:
        return
    tokens = {sym: pos.get("token", 0) for sym, pos in list(ACTIVE_POSITIONS.items()) if pos.get("token")}
    if not tokens:
        return
    try:
        ltps = kite.ltp(list(tokens.values()))
    except Exception as e:
        logging.warning(f"Position monitor LTP fetch failed: {e}")
        return
    for symbol, pos in list(ACTIVE_POSITIONS.items()):
        token = pos.get("token", 0)
        ltp = 0
        if token and str(token) in ltps:
            ltp = ltps[str(token)].get("last_price", 0)
        elif token:
            for k, v in ltps.items():
                if int(k) == token:
                    ltp = v.get("last_price", 0)
                    break
        if ltp <= 0:
            continue
        entry = pos.get("entry_spot", 0)
        sl = pos.get("current_sl", 0)
        t1 = pos.get("t1")
        t2 = pos.get("t2")
        t3 = pos.get("t3")
        trailing = pos.get("trailing_stage", 0)
        side = pos.get("side", OPTION_TYPE)
        if side == "CE":
            if sl and ltp <= sl:
                close_position(kite, pos, "SL_HIT", symbol)
                continue
            if t3 and ltp >= t3:
                close_position(kite, pos, "T3_HIT", symbol)
                continue
            if t2 and ltp >= t2:
                close_position(kite, pos, "T2_HIT", symbol)
                continue
            if t1 and ltp >= t1:
                if trailing < 1 and sl:
                    old_sl = pos.get("current_sl")
                    pos["current_sl"] = round(entry * 1.002, 2)
                    pos["trailing_stage"] = 1
                    if pos.get("trade_id"):
                        update_trade(pos["trade_id"], {"current_sl": pos["current_sl"], "trailing_stage": 1})
                    logging.info(f"TRAIL {symbol}: SL moved up {old_sl} -> {pos['current_sl']} (T1 hit)")
                close_position(kite, pos, "T1_HIT", symbol)
                continue
        else:
            if sl and ltp >= sl:
                close_position(kite, pos, "SL_HIT", symbol)
                continue
            if t3 and ltp <= t3:
                close_position(kite, pos, "T3_HIT", symbol)
                continue
            if t2 and ltp <= t2:
                close_position(kite, pos, "T2_HIT", symbol)
                continue
            if t1 and ltp <= t1:
                if trailing < 1 and sl:
                    old_sl = pos.get("current_sl")
                    pos["current_sl"] = round(entry * 0.998, 2)
                    pos["trailing_stage"] = 1
                    if pos.get("trade_id"):
                        update_trade(pos["trade_id"], {"current_sl": pos["current_sl"], "trailing_stage": 1})
                    logging.info(f"TRAIL {symbol}: SL moved down {old_sl} -> {pos['current_sl']} (T1 hit)")
                close_position(kite, pos, "T1_HIT", symbol)
                continue

def execute_highest_rr_trade(kite, staged):
    if not staged:
        return
    best = max(staged, key=lambda s: (s.get("T3") or s.get("T1") or 0) - s.get("Entry", 0))
    sym = best["Symbol"]
    opt_sym = best["OptionSymbol"]
    opt_token = best["OptionToken"]
    side = best["Side"]
    key = f"{sym}|{best['Pattern']}|{side}|{best['Strike']}"
    if is_pattern_executed(ENGINE_TYPE, key):
        logging.info(f"Best cycle trade {key} already executed; skipping")
        return
    cfg = best["Config"]
    entry_premium = best["Entry"]
    pos_size = 1
    pos = {
        "contract": opt_sym,
        "token": opt_token,
        "entry_spot": entry_premium,
        "current_sl": best["SL"],
        "t1": best["T1"], "t2": best["T2"], "t3": best["T3"],
        "trailing_stage": 0, "lot_size": cfg["lot_size"], "position_size": pos_size,
        "pattern": best["Pattern"], "timeframe": NIFTY50_TF_ENTRY,
        "side": side, "strike": best["Strike"]
    }
    record_executed_pattern(ENGINE_TYPE, key, {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "contract": opt_sym})
    pos["entry_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    pos["trade_id"] = create_trade(ENGINE_TYPE, sym, {k: v for k, v in pos.items() if k != "trade_id"})
    with position_lock:
        ACTIVE_POSITIONS[sym] = pos
    save_state()
    if LIVE_MARKET_DEPLOYMENT:
        try:
            q = kite.quote(f"{kite.EXCHANGE_NFO}:{opt_sym}")
            qd = q.get(f"{kite.EXCHANGE_NFO}:{opt_sym}", {})
            ltp = qd.get("last_price", 0)
            sell = qd.get("depth", {}).get("sell", [])
            ask = sell[0]["price"] if sell and len(sell) > 0 else 0
            price = round((ask if ask > 0 else ltp) * 1.005, 1)
            qty = cfg["lot_size"] * pos_size
            if price <= 0 or qty <= 0:
                logging.warning(f"Invalid order params for {opt_sym}: price={price}, qty={qty}, ltp={ltp}, ask={ask}")
                log_to_journal(sym, best["Pattern"], NIFTY50_TF_ENTRY, "BUY", "FAILED",
                               f"Invalid price={price} qty={qty} ltp={ltp} ask={ask}",
                               entry=best["Entry"], sl=best["SL"], target=best["T1"])
                with position_lock:
                    ACTIVE_POSITIONS.pop(sym, None)
                save_state()
                return
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=opt_sym,
                exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=qty, order_type=kite.ORDER_TYPE_LIMIT, price=price,
                product=kite.PRODUCT_NRML
            )
            logging.info(f"ORDER PLACED: {opt_sym} qty={qty} price={price} oid={oid}")
            rr_best = round((best["Entry"] - best["T1"]) / (best["SL"] - best["Entry"]), 2) if best["SL"] != best["Entry"] else 0
            log_to_journal(sym, best["Pattern"], NIFTY50_TF_ENTRY, "BUY", "SUCCESS",
                           f"Order: {oid}, Qty: {qty}, {side}@{best['Strike']}", entry=best["Entry"], sl=best["SL"], target=best["T1"], rr=rr_best)
        except Exception as e:
            log_to_journal(sym, best["Pattern"], NIFTY50_TF_ENTRY, "BUY", "FAILED", str(e),
                           entry=best["Entry"], sl=best["SL"], target=best["T1"])
            logging.error(f"Order failed for {opt_sym}: {e}")

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
    strike_range = NIFTY50_STRIKE_RANGE
    scan_order = SUPER_STOCKS + [s for s in STOCK_REGISTRY if s not in SUPER_STOCKS]
    
    # 1. Fetch spot prices for all stocks
    spot_prices = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        spot_tasks = {}
        for symbol in scan_order:
            config = STOCK_REGISTRY[symbol]
            with position_lock:
                if symbol in ACTIVE_POSITIONS:
                    continue
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
        
        # Resolve CE contracts around ATM
        contracts = resolve_option_strikes(symbol, spot, step, OPTION_TYPE, strike_range, ENGINE_TYPE)
        if not contracts:
            logging.warning(f"No contracts resolved for {symbol} @ {spot}")
            continue
        
        # 3. Fetch option premium data for all contracts
        opt_data = {}
        with ThreadPoolExecutor(max_workers=10) as pool:
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
            if cache_key not in A_CACHE or A_CACHE[cache_key] is None:
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
            if is_pattern_executed(ENGINE_TYPE, key) or key in staged_keys:
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
            stage_cycle_trade(ENGINE_TYPE, trade_data)
            logging.info(f"OPTION MATCH staged: {symbol} {tsym} | {cache['pattern_name']} | Entry: {entry_price:.2f} | SL: {cache['SL']:.2f} | T3: {t3}")
    
    # Carry-forward: re-enter previous day's valid trades with RR >= 1.5
    cf_pool = load_carry_forward()
    for cf in cf_pool:
        sym = cf.get("Symbol")
        if sym in ACTIVE_POSITIONS or sym not in STOCK_REGISTRY:
            continue
        side = cf.get("Side", "CE")
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
                if sl_hit: logging.info(f"CF {sym} SL hit, removing")
                elif t_hit: logging.info(f"CF {sym} target hit, removing")
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
            stage_cycle_trade(ENGINE_TYPE, trade_data)
            logging.info(f"RE-ENTRY staged (carry-forward): {sym} | {cf['Pattern']} | RR={rr:.2f}")
        except Exception as e:
            logging.warning(f"CF check {sym}: {e}")
    
    # Save trades with RR >= 1.5 for future re-entry
    cf_save = []
    for t in staged:
        side = t.get("Side", "CE")
        rr = _trade_rr(t, side)
        if rr >= 1.5:
            cf_save.append({k: v for k, v in t.items() if k != "Config"})
    save_carry_forward(cf_save)
    
    return staged

def run_live(kite):
    logging.info(f"[{ENGINE_ID}] Starting live trading loop...")
    load_state()
    last_scan = 0
    last_monitor = 0
    while True:
        if not is_market_hours():
            time.sleep(30)
            continue
        now = time.time()
        if now - last_scan >= NIFTY50_SCAN_INTERVAL:
            try:
                staged = run_scan_cycle(kite)
                if staged:
                    execute_highest_rr_trade(kite, staged)
                clear_cycle_trades(ENGINE_TYPE)
            except Exception as e:
                logging.error(f"Scan cycle error: {e}")
            last_scan = now
        if now - last_monitor >= 3:
            try:
                monitor_positions(kite)
            except Exception as e:
                logging.error(f"Position monitor error: {e}")
            last_monitor = now
        time.sleep(1)

def run_anchor_scan(kite):
    """Run anchor scan for all Nifty50 stock CE contracts."""
    logging.info(f"[{ENGINE_ID}] Starting anchor scan...")
    _refresh_nopa_config()
    target_date = BACKTEST_DATE or dt.now().date()
    limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "4hour": 600, "day": 2000}
    max_days_anchor = limits.get(NIFTY50_TF_ANCHOR, 180)
    from_anchor = (target_date - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
    to_anchor = target_date.strftime("%Y-%m-%d")
    
    for symbol, config in STOCK_REGISTRY.items():
        try:
            df_spot = pd.DataFrame(safe_historical(kite, config["token"], from_anchor, to_anchor, NIFTY50_TF_ANCHOR))
            if df_spot.empty:
                continue
            spot = float(df_spot.iloc[-1]['close'])
        except Exception as e:
            logging.warning(f"Anchor spot fetch failed for {symbol}: {e}")
            continue
        
        step = config["strike_step"]
        contracts = resolve_option_strikes(symbol, spot, step, OPTION_TYPE, NIFTY50_STRIKE_RANGE, ENGINE_TYPE)
        if not contracts:
            continue
        
        for contract in contracts:
            try:
                df_anchor = pd.DataFrame(safe_historical(kite, contract["token"], from_anchor, to_anchor, NIFTY50_TF_ANCHOR))
                if df_anchor.empty:
                    continue
                detect_and_cache_a(df_anchor, contract["tradingsymbol"], target_date, PATTERN_TYPE)
                cache_key = _a_cache_key(contract["tradingsymbol"], target_date)
                if cache_key in A_CACHE and A_CACHE[cache_key]:
                    cache = A_CACHE[cache_key]
                    log_to_journal(symbol, cache['pattern_name'], NIFTY50_TF_ANCHOR,
                                   "ANCHOR_CE", "SCANNED", "A formation from anchor scan",
                                   entry=cache['benchmark'], sl=cache['SL'], target="")
            except Exception as e:
                logging.warning(f"Anchor scan failed for {contract['tradingsymbol']}: {e}")

def load_carry_forward():
    cf_file = "output/monitor/carry_forward_bull.json"
    if not os.path.exists(cf_file):
        return []
    try:
        with open(cf_file, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_carry_forward(data):
    cf_file = "output/monitor/carry_forward_bull.json"
    try:
        with open(cf_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Carry-forward save failed: {e}")

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
        run_anchor_scan(kite)
        return
    
    if args.date:
        BACKTEST_DATE = dt.strptime(args.date, "%Y-%m-%d").date()
        logging.info(f"Backtest mode for {BACKTEST_DATE} - not yet implemented")
        return
    
    if args.backtest_range:
        start_str, end_str = args.backtest_range.split(',')
        logging.info(f"Backtest range {start_str} to {end_str} - not yet implemented")
        return
    
    if LIVE_MARKET_DEPLOYMENT:
        run_live(kite)
    else:
        logging.info("Backtest mode selected but not implemented in live-trade engine")
        logging.info("Use backtest/bull_nifty50_backtest.py for backtesting")

if __name__ == "__main__":
    main()