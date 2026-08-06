import os
import sys
import json
import logging
import time
import threading
import atexit
import signal
from datetime import datetime as dt, timedelta, date as date_type

import pandas as pd

# Add project root to path for shared module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    CFG_FILE, LIVE_MARKET_DEPLOYMENT, BACKTEST_DATE, LOOKBACK_DAYS,
    INITIAL_CAPITAL, MAX_RISK_PERCENT, TOKEN_FILE,
    INDEX_TF_ENTRY, INDEX_TF_ANCHOR, TIMEFRAME_FALLBACK,
    BEAR_INDEX_STRIKE_RANGE, INDEX_REGISTRY,
    INDEX_SCAN_INTERVAL,
    SCANNER_CONFIG_FILE, ANCHOR_SCAN_REQUEST_FILE, ANCHOR_SCAN_STOP_FILE,
    VALID_TIMEFRAMES,
    JOURNAL_FILE,
)
from shared.kite_utils import (
    safe_historical, fetch_instruments, validate_stock_registry_tokens,
    get_instrument_df, load_kite_session, create_kite_client, is_market_hours,
    init_registries, is_auth_error, reload_kite_client
)
from shared.patterns import (
    A_CACHE, _a_cache_key, detect_and_cache_a, find_bcd_forward,
    find_profit_targets_negation, calculate_rr, _trade_rr
)
from shared.option_utils import (
    resolve_option_strikes, resolve_option_contract, approximate_delta, get_expiry_date,
    reresolve_token
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
    unrecord_executed_pattern,
)
from shared.pid_util import check_pid_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("output/logs/bear_index_trade_engine.log", mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

ENGINE_ID = "bear_index"
ENGINE_TYPE = "bear_index"
PATTERN_TYPE = "bear"
OPTION_TYPE = "PE"

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
STATE_FILE = "output/monitor/bear_index.pid"
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
            with open(STATE_FILE.replace('.pid', '_state.json'), "w", encoding="utf-8") as f:
                json.dump(ACTIVE_POSITIONS, f, indent=4)
        except Exception as e:
            logging.error(f"State save failed: {e}")

def load_state():
    global ACTIVE_POSITIONS
    ACTIVE_POSITIONS = {}
    sf = STATE_FILE.replace('.pid', '_state.json')
    if os.path.exists(sf):
        try:
            with open(sf, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                # Repair or drop state positions whose token was lost/stale (0/None)
                for s, p in list(loaded.items()):
                    if not p.get("token"):
                        try:
                            tk, sy = reresolve_token(s, p.get("entry_spot", 0),
                                                  p.get("side", OPTION_TYPE), ENGINE_TYPE)
                            if tk:
                                p["token"] = tk
                                if sy:
                                    p["contract"] = sy
                                logging.info(f"Repaired token for {s}: {tk}")
                            else:
                                loaded.pop(s, None)
                                logging.warning(f"Dropped unrecoverable state position: {s}")
                        except Exception:
                            loaded.pop(s, None)
                ACTIVE_POSITIONS.update(loaded)
            logging.info(f"Recovered {len(ACTIVE_POSITIONS)} positions from state file")
        except Exception:
            pass
    db_trades = get_active_trades(ENGINE_TYPE)
    for t in db_trades:
        sym = t.get("symbol", "")
        if not sym or sym in ACTIVE_POSITIONS:
            continue
        # Skip phantom db trades that were never given a valid token (not real orders)
        if not t.get("token"):
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
        if price <= 0:
            logging.warning(f"Skip close {pos['contract']}: invalid price {price} (ltp={ltp}); contract likely expired/illiquid")
            return
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
    # Repair positions whose stored token was lost/stale so monitoring can resume
    for sym, pos in list(ACTIVE_POSITIONS.items()):
        if not pos.get("token"):
            try:
                new_tk, new_sym = reresolve_token(sym, pos.get("entry_spot", 0),
                                              pos.get("side", OPTION_TYPE), ENGINE_TYPE)
                if new_tk:
                    pos["token"] = new_tk
                    if new_sym:
                        pos["contract"] = new_sym
                    if pos.get("trade_id"):
                        update_trade(pos["trade_id"], {"token": new_tk, "contract": pos["contract"]})
                    logging.info(f"Re-resolved token for {sym}: {new_tk}")
            except Exception as e:
                logging.warning(f"Token re-resolution failed for {sym}: {e}")
    tokens = {sym: pos.get("token", 0) for sym, pos in list(ACTIVE_POSITIONS.items()) if pos.get("token")}
    if not tokens:
        return
    try:
        ltps = kite.ltp(list(tokens.values()))
    except Exception as e:
        logging.warning(f"Position monitor LTP fetch failed: {e}")
        return
    for symbol, pos in list(ACTIVE_POSITIONS.items()):
        if pos.get("status") == "PENDING":
            continue
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
        # Safety: SL/targets must be in premium units (same as LTP). Legacy
        # state stored spot-denominated SLs; comparing to premium LTP would
        # fire instant false SL exits. Skip such positions.
        if ltp > 0 and sl and sl > ltp * 20:
            logging.warning(f"Skipping {symbol}: SL {sl} >> LTP {ltp} (unit mismatch?)")
            continue
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

def check_pending_orders(kite):
    """Carry-forward: verify fill status of pending LIMIT orders and free patterns
    when an order is cancelled/rejected so the symbol can re-enter on a later scan."""
    pending = {s: p for s, p in list(ACTIVE_POSITIONS.items()) if p.get("status") == "PENDING"}
    if not pending:
        return
    try:
        orders = kite.orders()
    except Exception as e:
        logging.warning(f"Pending order check failed: {e}")
        return
    status_by_id = {o.get("order_id"): o for o in orders}
    for symbol, pos in list(pending.items()):
        oid = pos.get("order_id")
        if not oid:
            with position_lock:
                ACTIVE_POSITIONS.pop(symbol, None)
            save_state()
            continue
        o = status_by_id.get(oid)
        if not o:
            continue
        st = (o.get("status") or "").upper()
        if st == "COMPLETE":
            pos["status"] = "ACTIVE"
            avg = o.get("average_price") or pos.get("entry_spot")
            if avg:
                pos["entry_spot"] = round(float(avg), 2)
            if pos.get("trade_id"):
                update_trade(pos["trade_id"], {"status": "ACTIVE", "entry_spot": pos["entry_spot"]})
            logging.info(f"PENDING FILLED: {symbol} order {oid} @ {pos['entry_spot']}")
            save_state()
        elif st in ("CANCELLED", "REJECTED", "EXPIRED"):
            key = f"{symbol}|{pos['pattern']}|{pos.get('side')}|{pos.get('strike')}"
            unrecord_executed_pattern(ENGINE_TYPE, key)
            if pos.get("trade_id"):
                update_trade(pos["trade_id"], {"status": st})
            with position_lock:
                ACTIVE_POSITIONS.pop(symbol, None)
            logging.info(f"PENDING CANCELLED: {symbol} order {oid} ({st}) freed for re-entry")
            save_state()


def execute_highest_rr_trade(kite, staged):
    if not staged:
        return
    best = max(staged, key=lambda s: s.get("Entry", 0) - (s.get("T3") or s.get("T1") or s.get("Entry", 0)))
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
        "pattern": best["Pattern"], "timeframe": INDEX_TF_ENTRY,
        "side": side, "strike": best["Strike"],
        "status": "PENDING"
    }
    pos["entry_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    pos["trade_id"] = create_trade(ENGINE_TYPE, sym, {k: v for k, v in pos.items() if k != "trade_id"})
    
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
                log_to_journal(sym, best["Pattern"], INDEX_TF_ENTRY, "BUY", "FAILED",
                               f"Invalid price={price} qty={qty} ltp={ltp} ask={ask}",
                               entry=best["Entry"], sl=best["SL"], target=best["T1"])
                return
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=opt_sym,
                exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=qty, order_type=kite.ORDER_TYPE_LIMIT, price=price,
                product=kite.PRODUCT_NRML
            )
            pos["order_id"] = oid
            logging.info(f"ORDER PLACED: {opt_sym} qty={qty} price={price} oid={oid}")
            record_executed_pattern(ENGINE_TYPE, key, {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "contract": opt_sym, "order_id": oid})
            rr_best = round((best["Entry"] - best["T1"]) / (best["SL"] - best["Entry"]), 2) if best["SL"] != best["Entry"] else 0
            log_to_journal(sym, best["Pattern"], INDEX_TF_ENTRY, "BUY", "SUCCESS",
                           f"Order: {oid}, Qty: {qty}, {side}@{best['Strike']}", entry=best["Entry"], sl=best["SL"], target=best["T1"], rr=rr_best)
        except Exception as e:
            log_to_journal(sym, best["Pattern"], INDEX_TF_ENTRY, "BUY", "FAILED", str(e),
                           entry=best["Entry"], sl=best["SL"], target=best["T1"])
            logging.error(f"Order failed for {opt_sym}: {e}")
            return
    else:
        record_executed_pattern(ENGINE_TYPE, key, {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "contract": opt_sym})

    with position_lock:
        ACTIVE_POSITIONS[sym] = pos
    save_state()

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
    scan_order = list(INDEX_REGISTRY.keys())

    for symbol in scan_order:
        if symbol not in INDEX_REGISTRY:
            continue
        config = INDEX_REGISTRY[symbol]
        with position_lock:
            if symbol in ACTIVE_POSITIONS:
                continue

        token = config["token"]

        try:
            df_spot_entry = pd.DataFrame(safe_historical(kite, token, from_entry, to_entry, INDEX_TF_ENTRY))
            df_spot_anchor = pd.DataFrame(safe_historical(kite, token, from_anchor, to_anchor, INDEX_TF_ANCHOR))
        except Exception as e:
            logging.warning(f"Spot data fetch failed for {symbol} (token={token}): {e}; skipping")
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
        contract = resolve_option_contract(symbol, current_spot, step, OPTION_TYPE, engine_type=ENGINE_TYPE)
        if contract is None:
            continue

        try:
            df_opt = pd.DataFrame(safe_historical(kite, contract["token"], from_entry, to_entry, INDEX_TF_ENTRY))
        except Exception as e:
            logging.warning(f"Option data fetch failed for {symbol} {contract.get('tradingsymbol')}: {e}; skipping")
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
        if is_pattern_executed(ENGINE_TYPE, key) or key in staged_keys:
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
            "Config": config
        }
        staged.append(trade_data)
        staged_keys.add(key)
        stage_cycle_trade(ENGINE_TYPE, trade_data)
        logging.info(f"OPTION MATCH staged: {symbol} {contract['tradingsymbol']} | {cache['pattern_name']} | Entry: {entry_premium:.2f} | SL: {sl_premium:.2f} | T1: {t1} | T2: {t2} | T3: {t3}")

    return staged

def run_live(kite):
    logging.info(f"[{ENGINE_ID}] Starting live trading loop...")
    load_state()
    last_scan = 0
    last_monitor = 0
    last_token_reload = 0
    while True:
        if not is_market_hours():
            time.sleep(30)
            continue
        now = time.time()
        if now - last_scan >= INDEX_SCAN_INTERVAL:
            try:
                staged = run_scan_cycle(kite)
                if staged:
                    execute_highest_rr_trade(kite, staged)
                clear_cycle_trades(ENGINE_TYPE)
            except Exception as e:
                if is_auth_error(e) and now - last_token_reload > 60:
                    logging.warning("Auth/token error - reloading Kite session from token file")
                    try:
                        kite = reload_kite_client(kite)
                        last_token_reload = now
                    except Exception as re:
                        logging.error(f"Token reload failed: {re}")
                logging.error(f"Scan cycle error: {e}")
            last_scan = now
        if now - last_monitor >= 3:
            try:
                monitor_positions(kite)
                check_pending_orders(kite)
            except Exception as e:
                logging.error(f"Position monitor error: {e}")
            last_monitor = now
        time.sleep(1)

def run_anchor_scan(kite):
    """Run anchor scan for all index PE contracts."""
    logging.info(f"[{ENGINE_ID}] Starting anchor scan...")
    _refresh_nopa_config()
    target_date = BACKTEST_DATE or dt.now().date()
    limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "4hour": 600, "day": 2000}
    max_days_anchor = limits.get(INDEX_TF_ANCHOR, 180)
    from_anchor = (target_date - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
    to_anchor = target_date.strftime("%Y-%m-%d")
    
    for symbol, config in INDEX_REGISTRY.items():
        try:
            df_spot = pd.DataFrame(safe_historical(kite, config["token"], from_anchor, to_anchor, INDEX_TF_ANCHOR))
            if df_spot.empty:
                continue
            spot = float(df_spot.iloc[-1]['close'])
        except Exception as e:
            logging.warning(f"Anchor spot fetch failed for {symbol}: {e}")
            continue
        
        step = config["strike_step"]
        contracts = resolve_option_strikes(symbol, spot, step, OPTION_TYPE, BEAR_INDEX_STRIKE_RANGE, ENGINE_TYPE)
        if not contracts:
            continue
        
        for contract in contracts:
            try:
                df_anchor = pd.DataFrame(safe_historical(kite, contract["token"], from_anchor, to_anchor, INDEX_TF_ANCHOR))
                if df_anchor.empty:
                    continue
                detect_and_cache_a(df_anchor, contract["tradingsymbol"], target_date, PATTERN_TYPE)
                cache_key = _a_cache_key(contract["tradingsymbol"], target_date)
                if cache_key in A_CACHE and A_CACHE[cache_key]:
                    cache = A_CACHE[cache_key]
                    log_to_journal(symbol, cache['pattern_name'], INDEX_TF_ANCHOR,
                                   "ANCHOR_PE", "SCANNED", "A formation from anchor scan",
                                   entry=cache['benchmark'], sl=cache['SL'], target="")
            except Exception as e:
                logging.warning(f"Anchor scan failed for {contract['tradingsymbol']}: {e}")

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
    validate_stock_registry_tokens(kite)
    
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
        logging.info("Use backtest/bear_index_backtest.py for backtesting")

if __name__ == "__main__":
    main()