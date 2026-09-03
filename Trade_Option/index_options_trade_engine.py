import os
import json
import logging
import time
import threading
import sys
COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)
import paths
from datetime import datetime as dt, timedelta
import pandas as pd

from kiteconnect import KiteConnect
import trade_db

from trading_core import (
    load_kite_session,
    ensure_kite_session,
    safe_kite_call,
    fetch_and_resample_candles,
    log_to_journal,
    is_market_open,
    get_ist_date,
    get_ist_now,
    scan_anchor_bcd_breakout,
    scan_trend_continuation_reentry,
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    trading_days_between,
    live_execution_enabled,
    load_program_config_for_engine,
    sync_kite_positions as shared_sync_kite,
    write_scan_display_data as shared_write_display,
    lookup_scan_sl_target,
    reconcile_positions as shared_reconcile,
    resolve_option_strikes as shared_resolve_strikes,
    scan_symbol,
    monitor_active_positions as shared_monitor_positions,
    sanitize_entry_time,
    simulate_trade_outcome as shared_simulate,
    INDEX_REGISTRY,
    match_registry_symbol,
    get_option_lot_size,
    clear_executed_exit
)

LIVE_MARKET_DEPLOYMENT = True
LOOKBACK_DAYS = 30
INITIAL_CAPITAL = 100000.0
MAX_RISK_PERCENT = 1.0
TOKEN_FILE = paths.TOKEN_FILE
NFO_CACHE_FILE = paths.NFO_CACHE_FILE
SCAN_INTERVAL_SECONDS = 15

TIMEFRAME_ENTRY = "3minute"
TIMEFRAME_ANCHOR = "15minute"
TIMEFRAME_FALLBACK = "3minute"
STRIKE_RANGE = 3
BACKTEST_DATE = None

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
instrument_dump = None
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANCHOR_SCAN_REQUEST_FILE = os.path.join(BASE_DIR, "output", "monitor", "anchor_scan_request.txt")
LIVE_EXECUTION_FLAG = paths.INDEX_LIVE_FLAG
SCAN_DISPLAY_FILE = paths.SCAN_DISPLAY_INDEX_FILE
SL_TARGET_OVERRIDES_FILE = paths.SL_TARGET_OVERRIDES_FILE

INDEX_LOG_FILE = paths.INDEX_LOG_FILE
os.makedirs(os.path.dirname(INDEX_LOG_FILE), exist_ok=True)

class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        FlushFileHandler(INDEX_LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)


def fetch_instruments(kite):
    global instrument_dump
    try:
        logging.info("Syncing NFO and BFO instruments...")
        nfo = kite.instruments("NFO")
        try:
            bfo = kite.instruments("BFO")
        except Exception as b_err:
            logging.warning(f"BFO sync warning: {b_err}")
            bfo = []
        combined = (nfo if nfo else []) + (bfo if bfo else [])
        instrument_dump = pd.DataFrame(combined)
        if not instrument_dump.empty:
            os.makedirs(os.path.dirname(NFO_CACHE_FILE), exist_ok=True)
            instrument_dump.to_csv(NFO_CACHE_FILE, index=False)
        logging.info(f"Synced {len(instrument_dump)} NFO/BFO contracts.")
    except Exception as e:
        err_msg = str(e) if str(e).strip() else type(e).__name__
        logging.error(f"Instrument sync failed: {err_msg}")
        raise

def resolve_option_contract(base_symbol, spot_price, step_size, option_type, expiry_offset=0):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty:
        return None
    strike = int(round(spot_price / step_size) * step_size)
    try:
        df = instrument_dump[
            (instrument_dump['name'] == base_symbol) &
            (instrument_dump['instrument_type'] == option_type) &
            (instrument_dump['strike'] == strike)
        ].copy()
        if df.empty:
            return None
        df['expiry'] = pd.to_datetime(df['expiry']).dt.date
        df = df[df['expiry'] >= get_ist_date()].sort_values(by='expiry')
        if df.empty:
            return None
        expiries = df['expiry'].unique()
        selected_idx = min(expiry_offset, len(expiries) - 1)
        target_expiry = expiries[selected_idx]
        sub = df[df['expiry'] == target_expiry]
        if not sub.empty:
            c = sub.iloc[0]
            c_lot = int(c['lot_size']) if 'lot_size' in c and pd.notna(c['lot_size']) else None
            return {"token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol'], "expiry": str(target_expiry), "lot_size": c_lot}
        c = df.iloc[0]
        c_lot = int(c['lot_size']) if 'lot_size' in c and pd.notna(c['lot_size']) else None
        return {"token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol'], "expiry": str(c['expiry']), "lot_size": c_lot}
    except Exception as e:
        logging.error(f"Contract resolution error: {e}")
        return None

# ──────────────────────────────────────────────
#  SCAN CYCLE — RUNS EVERY N SECONDS
# ──────────────────────────────────────────────

def run_scan_cycle(kite):
    cfg_applied = load_program_config_for_engine("index", [("strike_range", "STRIKE_RANGE"), ("strict_macro_gate", "STRICT_MACRO_GATE")])
    for k, v in cfg_applied.items():
        if k == "STRIKE_RANGE": globals()["STRIKE_RANGE"] = int(v) if isinstance(v, (int, float)) else v
        elif k == "STRICT_MACRO_GATE": globals()["STRICT_MACRO_GATE"] = bool(v)
        elif k in ("TIMEFRAME_ENTRY", "TIMEFRAME_ANCHOR"): globals()[k] = v
        elif k == "LIVE_MARKET_DEPLOYMENT": globals()["LIVE_MARKET_DEPLOYMENT"] = v
        elif k == "LOOKBACK_DAYS": globals()["LOOKBACK_DAYS"] = int(v)
        elif k == "SCAN_INTERVAL_SECONDS": globals()["SCAN_INTERVAL_SECONDS"] = int(v)
        elif k == "MAX_RISK_PERCENT": globals()["MAX_RISK_PERCENT"] = float(v)
        elif k == "INITIAL_CAPITAL": globals()["INITIAL_CAPITAL"] = float(v)

    target_date = BACKTEST_DATE
    if target_date is None:
        ref_now = dt.now()
    elif isinstance(target_date, str):
        ref_now = dt.strptime(target_date, "%Y-%m-%d")
    else:
        ref_now = target_date
    limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "75minute": 400, "75min": 400, "day": 2000}
    max_days_entry = limits.get(TIMEFRAME_ENTRY, 180)
    max_days_anchor = limits.get(TIMEFRAME_ANCHOR, 180)
    from_entry = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_entry))).strftime("%Y-%m-%d")
    to_entry = ref_now.strftime("%Y-%m-%d")
    from_anchor = (ref_now - timedelta(days=min(LOOKBACK_DAYS, max_days_anchor))).strftime("%Y-%m-%d")
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
    temp_stored_trades = []
    for symbol, config in INDEX_REGISTRY.items():
        with position_lock:
            if symbol in ACTIVE_POSITIONS:
                continue
        trades = scan_symbol(kite, symbol, config, from_entry, to_entry, from_anchor, to_anchor,
                             entry_scanners, anchor_scanners,
                             lambda sym, sp, step, opt, r: shared_resolve_strikes(instrument_dump, sym, sp, step, opt, r),
                             "index", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR, TIMEFRAME_FALLBACK,
                             ACTIVE_POSITIONS, position_lock, trade_db, STRIKE_RANGE,
                             log_to_journal)
        temp_stored_trades.extend(trades)
        with position_lock:
            shared_write_display(temp_stored_trades, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
    return temp_stored_trades

# ──────────────────────────────────────────────
#  ANCHOR SCAN — RUNS ON DEMAND VIA DASHBOARD
# ──────────────────────────────────────────────

def run_anchor_scan(kite):
    logging.info("On-demand scan requested: executing full A-B-C-D breakout scan across index option contracts...")
    staged = run_scan_cycle(kite)
    with position_lock:
        shared_write_display(staged or [], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
    logging.info(f"On-demand scan complete: found {len(staged or [])} full A-B-C-D breakout setup(s)")


def execute_index_entry(kite, pos):
    if not LIVE_MARKET_DEPLOYMENT:
        logging.info(f"[BACKTEST ENTRY] {pos['contract']} ({pos['side']})")
        return True
    try:
        c_str = str(pos['contract']).upper()
        clear_executed_exit(pos['contract'])
        target_exch = "BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO"
        q_key = f"{target_exch}:{pos['contract']}"
        q = kite.quote([q_key])
        ltp = float(q.get(q_key, {}).get("last_price", 0))
        ask = 0
        depth = q.get(q_key, {}).get("depth", {}).get("sell", [])
        bm = float(pos.get("benchmark") or 0)
        if bm > 0:
            price = round(bm * 1.005, 1)
        else:
            price = round((ask if ask > 0 else ltp) * 1.005, 1)
        lot_sz = pos.get("lot_size") or get_option_lot_size(pos["contract"]) or INDEX_REGISTRY.get(pos.get("symbol", ""), {}).get("lot_size", 1)
        kite.place_order(
            variety=kite.VARIETY_REGULAR, tradingsymbol=pos["contract"],
            exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_BUY,
            quantity=lot_sz * pos["position_size"], order_type=kite.ORDER_TYPE_LIMIT,
            price=price, product=kite.PRODUCT_NRML
        )
        return True
    except Exception as e:
        logging.error(f"Entry failed for {pos['contract']}: {e}")
        return False

def simulate_trade_outcome(kite, trade, target_date):
    return shared_simulate(kite, trade, target_date)

# ──────────────────────────────────────────────
#  EXECUTION FUNCTIONS
# ──────────────────────────────────────────────

def execute_highest_rr_trade(kite, staged):
    """After a scan cycle, pick best by profit and execute (if live)."""
    if not staged:
        return
    best = max(staged, key=lambda t: (t.get("t3") or t.get("t1") or 0) - t.get("entry_spot", 0))
    key = f"{best['symbol']}|{best['pattern']}|{best['side']}|{best.get('strike', '')}"
    if trade_db.is_pattern_executed("index", key):
        logging.info(f"Best cycle trade {key} already executed; skipping")
        return
    live_ok = LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and is_market_open()
    if live_ok or BACKTEST_DATE is not None:
        pos = best.copy()
        pos["entry_time"] = dt.now().isoformat()
        pos.setdefault("position_type", "option")
        if live_ok:
            from vix_guard import evaluate_vix_regime
            vix_ok, vix_msg, _ = evaluate_vix_regime(kite, tier_val=best.get("tier", 1))
            if not vix_ok:
                logging.info(f"[VIX_REGIME_GATE] Auto-execution skipped for {best['symbol']} ({best['contract']}): {vix_msg}")
                return

            from portfolio_risk import check_portfolio_risk_caps
            cfg_eng = load_config().get("index", {})
            cap_val = float(cfg_eng.get("capital") or 100000.0)
            p_ok, p_msg, _ = check_portfolio_risk_caps(
                engine="index",
                symbol=best["symbol"],
                candidate_tier=best.get("tier", 1),
                capital=cap_val,
                live_positions=ACTIVE_POSITIONS
            )
            if not p_ok:
                logging.info(f"[PORTFOLIO_RISK_CAP] Auto-execution skipped for {best['symbol']} ({best['contract']}): {p_msg}")
                return

            with position_lock:
                if best["symbol"] in ACTIVE_POSITIONS:
                    logging.info(f"{best['symbol']} already active; skipping new trade")
                    return
                pos["trade_id"], _created = trade_db.create_trade("index", best["symbol"], {k: v for k, v in pos.items() if k != "trade_id"})
                ACTIVE_POSITIONS[best["symbol"]] = pos
        trade_db.record_executed_pattern("index", key, {"contract": best["contract"], "entry": best["entry_spot"]})
        ok = execute_index_entry(kite, pos)
        if ok:
            profit = round((best.get("t3") or best.get("t1") or 0) - best["entry_spot"], 2)
            rr_best = best.get("rr", "")
            if live_ok:
                log_to_journal(best["symbol"], best["pattern"], best["timeframe"],
                               "BUY_" + best["side"], "SUCCESS", f"Contract: {best['contract']}, Qty: {best['position_size']}",
                               entry=best["entry_spot"], sl=best["current_sl"], target=best.get("t1", ""), rr=rr_best,
                               event_time=best.get("entry_time"))
            else:
                log_to_journal(best["symbol"], best["pattern"], best["timeframe"],
                               "DRY_" + best["side"], "SUCCESS", f"Contract: {best['contract']}, Size: {best['position_size']}",
                               entry=best["entry_spot"], sl=best["current_sl"], target=best.get("t1", ""), rr=rr_best,
                               event_time=best.get("entry_time"))
                sim = simulate_trade_outcome(kite, best, BACKTEST_DATE)
                if sim["result"]:
                    log_to_journal(best["symbol"], best["pattern"], best["timeframe"],
                                   sim["result"], "COMPLETED", sim["detail"],
                                   entry=best["entry_spot"], sl=best["current_sl"], target=best.get("t1", ""), rr=rr_best,
                                   event_time=sim.get("exit_time") or sim.get("entry_time"))
                    logging.info(f"[BACKTEST] Trade outcome: {sim['result']} | {sim['detail']}")
            logging.info(f"EXECUTED best cycle trade: {best['symbol']} {best['side']} | {best['pattern']} | max-profit={profit}")
        else:
            with position_lock:
                ACTIVE_POSITIONS.pop(best["symbol"], None)
            if pos.get("trade_id"):
                trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S")})
            logging.warning(f"Order placement failed for {best['contract']}. Locked pattern {key} to prevent rate-limit spam loops.")
    else:
        cp = best["entry_spot"]
        contract = best.get("contract", "")
        pos_size = best.get("position_size", 0)
        log_to_journal(best["symbol"], best["pattern"], best["timeframe"],
                       "SCAN_READY", "SUCCESS",
                       f"Contract: {contract}, Size: {pos_size} | Manual entry pending",
                       entry=cp, sl=best["current_sl"], target=best.get("t1", ""),
                       event_time=best.get("entry_time"))
        logging.info(f"SCAN_READY best trade: {best['symbol']} {contract} | Entry: {cp} | SL: {best['current_sl']}")
        return

def monitor_active_positions(kite):
    return shared_monitor_positions(kite, INDEX_REGISTRY, ACTIVE_POSITIONS, position_lock,
                                     kite.PRODUCT_MIS, "index", TIMEFRAME_ENTRY,
                                     trade_db, log_to_journal,
                                     live=LIVE_MARKET_DEPLOYMENT)

# ──────────────────────────────────────────────
#  DISPLAY DATA WRITER + KITE SYNC
# ──────────────────────────────────────────────



# ──────────────────────────────────────────────
#  MAIN LOOP — SCAN CYCLE + RISK MONITOR
# ──────────────────────────────────────────────

def main_scan_loop(kite):
    trade_db.run_db_housekeeping()
    active = trade_db.get_active_trades("index")
    seen_symbols = set()
    for t in active:
        sym = t.get("symbol")
        if sym in INDEX_REGISTRY and sym not in seen_symbols:
            seen_symbols.add(sym)
            with position_lock:
                pos = {k: v for k, v in t.items() if k not in ("id", "engine", "symbol", "status", "updated_at")}
                pos["trade_id"] = t["id"]
                pos["entry_spot"] = pos.get("entry_spot") or t.get("entry_spot")
                pos["entry_time"] = sanitize_entry_time(pos)
                ACTIVE_POSITIONS[sym] = pos
            logging.info(f"Recovered position: {sym} | {t.get('contract','')}")
    try:
        kite_positions = kite.positions()
        all_positions = kite_positions.get("net", []) or kite_positions.get("day", [])
        
        # Auto-complete positions closed on Zerodha (quantity == 0)
        zero_qty_contracts = {p["tradingsymbol"] for p in all_positions if int(p.get("quantity", 0)) == 0}
        for sym, pos in list(ACTIVE_POSITIONS.items()):
            cnt = pos.get("contract") or pos.get("symbol")
            if cnt in zero_qty_contracts or (pos.get("contract") and pos.get("contract") in zero_qty_contracts):
                logging.info(f"[KITE SYNC] Position {cnt} is closed on Zerodha (qty=0). Syncing DB status to COMPLETED.")
                if pos.get("trade_id"):
                    trade_db.update_trade_status(pos["trade_id"], "COMPLETED", exit_price=pos.get("entry_spot", 0), exit_reason="KITE_MANUAL_EXIT")
                ACTIVE_POSITIONS.pop(sym, None)

        for p in all_positions:
            if p["exchange"] not in ("NFO", "BFO") or int(p["quantity"]) <= 0:
                continue
            symbol = match_registry_symbol(INDEX_REGISTRY, p["tradingsymbol"])
            if not symbol or symbol in ACTIVE_POSITIONS:
                continue
            nq = abs(int(p["quantity"]))
            reg_lot = get_option_lot_size(p["tradingsymbol"]) or INDEX_REGISTRY[symbol]["lot_size"]
            lots = nq // reg_lot
            if lots == 0:
                continue
            side = "CE" if "CE" in p["tradingsymbol"] else "PE"
            pos = {
                "contract": p["tradingsymbol"], "option_token": int(p["instrument_token"]),
                "entry_spot": float(p.get("net_price") or p.get("buy_price") or p.get("average_price") or 0), "current_sl": 0,
                "t1": 0, "t2": 0, "t3": 0, "trailing_stage": 0,
                "lot_size": reg_lot, "position_size": lots,
                "pattern": "KITE_RECOVERED", "side": side,
                "timeframe": TIMEFRAME_ENTRY,
                "entry_time": dt.now().isoformat(),
                "position_type": "option",
                "benchmark": 0, "anchor_floor": 0, "direction": "BULL"
            }
            clear_executed_exit(p["tradingsymbol"])
            pos["trade_id"], _created = trade_db.create_trade("index", symbol, {k: v for k, v in pos.items() if k != "trade_id"})
            scan_sl = lookup_scan_sl_target(p["tradingsymbol"], symbol, "index", kite, pos["entry_spot"], TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR)
            if scan_sl:
                pos.update(scan_sl)
                trade_db.update_trade(pos["trade_id"], scan_sl)
                logging.info(f"[KITE_RECOVER] Applied scan SL/Target for {symbol}: SL={scan_sl['current_sl']} T1={scan_sl['t1']} T2={scan_sl['t2']} T3={scan_sl['t3']}")
            ACTIVE_POSITIONS[symbol] = pos
            logging.info(f"Recovered from Kite: {symbol} {p['tradingsymbol']} qty={nq}")
    except Exception as e:
        logging.warning(f"Kite position recovery failed: {e}")
    shared_reconcile(kite, INDEX_REGISTRY, ACTIVE_POSITIONS, position_lock, "index", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR, LOOKBACK_DAYS, lambda sym, sp, step, opt, r: shared_resolve_strikes(instrument_dump, sym, sp, step, opt, r))
    with position_lock:
        shared_write_display([], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
    cycle = 0
    while True:
        try:
            ensure_kite_session(kite)
            cycle += 1
            with position_lock:
                active = len(ACTIVE_POSITIONS)
                symbols = list(ACTIVE_POSITIONS.keys())
            logging.info(f"[BEAT] Starting Index scan cycle {cycle} | Active positions: {active} {symbols if active else ''}")
            if cycle % 10 == 0:
                shared_sync_kite(kite, INDEX_REGISTRY, ACTIVE_POSITIONS, position_lock, "index", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR)
            if os.path.exists(SL_TARGET_OVERRIDES_FILE):
                try:
                    with open(SL_TARGET_OVERRIDES_FILE) as f:
                        overrides = json.load(f)
                    eng_overrides = overrides.get("index", {})
                    if eng_overrides:
                        with position_lock:
                            for sym, vals in eng_overrides.items():
                                target_pos = None
                                if sym in ACTIVE_POSITIONS:
                                    target_pos = ACTIVE_POSITIONS[sym]
                                else:
                                    for k, p in ACTIVE_POSITIONS.items():
                                        if p.get("contract") == sym or p.get("symbol") == sym or sym in k:
                                            target_pos = p
                                            break
                                if target_pos:
                                    changed = False
                                    for key in ("current_sl", "t1", "t2", "t3"):
                                        if key in vals:
                                            target_pos[key] = vals[key]
                                            changed = True
                                    if changed:
                                        tid = target_pos.get("trade_id")
                                        if tid:
                                            trade_db.update_trade(tid, {k: target_pos[k] for k in ("current_sl", "t1", "t2", "t3") if k in target_pos})
                                        logging.info(f"[OVERRIDE] Applied SL/T for {target_pos.get('contract', sym)}: SL={target_pos.get('current_sl')} T1={target_pos.get('t1')} T2={target_pos.get('t2')} T3={target_pos.get('t3')}")
                except Exception as e:
                    logging.warning(f"Override apply failed: {e}")
            temp_stored_trades = run_scan_cycle(kite)

            if temp_stored_trades:
                execute_highest_rr_trade(kite, temp_stored_trades)
            else:
                logging.info("[CYCLE] No trades staged this cycle.")

            trade_db.clear_cycle_trades("index")
            with position_lock:
                shared_write_display(temp_stored_trades or [], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
            logging.info(f"[CYCLE COMPLETE] {cycle} cycle complete | Found {len(temp_stored_trades or [])} setup(s)")
            monitor_active_positions(kite)
            time.sleep(max(0, SCAN_INTERVAL_SECONDS))
        except Exception as e:
            logging.error(f"Background error: {e}")
            time.sleep(5)



def run_multi_day_backtest(kite, start_date, end_date):
    global BACKTEST_DATE, LIVE_MARKET_DEPLOYMENT
    LIVE_MARKET_DEPLOYMENT = False
    days = trading_days_between(start_date, end_date)
    logging.info(f"Multi-day backtest: {len(days)} trading days from {start_date} to {end_date}")
    results = {"total_days": len(days), "days_with_trades": 0, "total_trades": 0, "wins": 0, "losses": 0, "no_exits": 0, "by_symbol": {}}
    for idx, day in enumerate(days):
        BACKTEST_DATE = day
        logging.info(f"[{idx+1}/{len(days)}] Backtesting {day}...")
        try:
            staged = run_scan_cycle(kite)
            if staged and len(staged) >= 1:
                results["days_with_trades"] += 1
                results["total_trades"] += 1
                best = max(staged, key=lambda t: (t.get("t3") or t.get("t1") or 0) - t.get("entry_spot", 0))
                sym = best["symbol"]
                if sym not in results["by_symbol"]:
                    results["by_symbol"][sym] = {"trades": 0, "wins": 0, "losses": 0, "no_exits": 0}
                results["by_symbol"][sym]["trades"] += 1
                key = f"{best['symbol']}|{best['pattern']}|{best['side']}|{best.get('strike', '')}"
                if not trade_db.is_pattern_executed("index", key):
                    trade_db.record_executed_pattern("index", key, {"contract": best["contract"], "entry": best["entry_spot"]})
                contract_display = best.get('contract', sym)
                log_to_journal(contract_display, best['pattern'], best.get('timeframe', TIMEFRAME_ENTRY),
                               "BACKTEST_ENTRY", "ENTRY",
                               details=f"Symbol={sym} Strike={best.get('strike','')}",
                               entry=best['entry_spot'], sl=best['current_sl'],
                               target=best.get('t3') or best.get('t1') or "",
                               rr=best.get('rr'),
                               event_time=best.get("entry_time"))
                sim = simulate_trade_outcome(kite, best, day)
                sim_result = sim["result"]
                exit_action = ""
                pnl = sim.get("pnl_pct") or 0.0
                if sim_result == "SL_HIT":
                    exit_action = "EXIT_SL"
                    results["losses"] += 1
                    results["by_symbol"][sym]["losses"] += 1
                elif sim_result in ("T1_HIT", "T2_HIT", "T3_HIT"):
                    exit_action = sim_result.replace("_HIT", "")
                    results["wins"] += 1
                    results["by_symbol"][sym]["wins"] += 1
                else:
                    exit_action = "EXIT_UNKNOWN"
                    results["no_exits"] += 1
                    results["by_symbol"][sym]["no_exits"] += 1
                if exit_action:
                    log_to_journal(contract_display, best['pattern'], best.get('timeframe', TIMEFRAME_ENTRY),
                                   exit_action, sim_result or "NO_EXIT",
                                   details=f"Symbol={sym} Strike={best.get('strike','')}",
                                   entry=best['entry_spot'], sl=best['current_sl'],
                                   target=best.get('t3') or best.get('t1') or "",
                                   rr=best.get('rr'), pnl_pct=pnl,
                                   event_time=sim.get("exit_time") or sim.get("entry_time"))
                logging.info(f"  Trade: {best['contract']} | {best['pattern']} | outcome={sim_result or 'unknown'} | P&L={pnl:.2f}%")
            trade_db.clear_cycle_trades("index")
            time.sleep(3)
        except Exception as e:
            logging.error(f"  Error on {day}: {e}")
            time.sleep(3)
    wr = results["wins"] / (results["wins"] + results["losses"]) * 100 if (results["wins"] + results["losses"]) > 0 else 0
    logging.info(f"\n{'='*60}")
    logging.info(f"BACKTEST RESULTS: {start_date} to {end_date}")
    logging.info(f"{'='*60}")
    logging.info(f"Trading days scanned: {results['total_days']}")
    logging.info(f"Days with trades:     {results['days_with_trades']}")
    logging.info(f"Total trades found:   {results['total_trades']}")
    logging.info(f"Wins:                 {results['wins']}")
    logging.info(f"Losses:               {results['losses']}")
    logging.info(f"No exit:              {results['no_exits']}")
    logging.info(f"Win rate:             {wr:.1f}%")
    for sym, s in sorted(results["by_symbol"].items()):
        swr = s["wins"] / (s["wins"] + s["losses"]) * 100 if (s["wins"] + s["losses"]) > 0 else 0
        logging.info(f"  {sym}: {s['trades']} trades, {s['wins']}W/{s['losses']}L, {swr:.1f}% WR")
    logging.info(f"{'='*60}")
    return results

def main():
    global BACKTEST_DATE, LIVE_MARKET_DEPLOYMENT
    cfg_applied = load_program_config_for_engine("index", [("strike_range", "STRIKE_RANGE")])
    for k, v in cfg_applied.items():
        if k == "STRIKE_RANGE": globals()["STRIKE_RANGE"] = int(v) if isinstance(v, (int, float)) else v
        elif k in ("TIMEFRAME_ENTRY", "TIMEFRAME_ANCHOR"): globals()[k] = v
        elif k == "LIVE_MARKET_DEPLOYMENT": globals()["LIVE_MARKET_DEPLOYMENT"] = v
        elif k == "LOOKBACK_DAYS": globals()["LOOKBACK_DAYS"] = int(v)
        elif k == "SCAN_INTERVAL_SECONDS": globals()["SCAN_INTERVAL_SECONDS"] = int(v)
        elif k == "MAX_RISK_PERCENT": globals()["MAX_RISK_PERCENT"] = float(v)
        elif k == "INITIAL_CAPITAL": globals()["INITIAL_CAPITAL"] = float(v)
    anchor_only = "--anchor-only" in sys.argv
    date_arg = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--date=")), None)
    range_arg = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--backtest-range=")), None)
    if date_arg:
        try:
            BACKTEST_DATE = dt.strptime(date_arg, "%Y-%m-%d").date()
        except Exception:
            BACKTEST_DATE = None
            logging.warning(f"Invalid --date value: {date_arg}")
    if not anchor_only and BACKTEST_DATE is None and range_arg is None:
        logging.info("Starting Index Trade Engine...")
    try:
        api_key, access_token = load_kite_session()
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        fetch_instruments(kite)
    except Exception as e:
        logging.error(f"Init failed: {e}")
        return
    if anchor_only:
        run_anchor_scan(kite)
        return
    if range_arg:
        LIVE_MARKET_DEPLOYMENT = False
        parts = range_arg.split(",")
        start = dt.strptime(parts[0].strip(), "%Y-%m-%d").date()
        end = dt.strptime(parts[1].strip(), "%Y-%m-%d").date()
        run_multi_day_backtest(kite, start, end)
        return
    if BACKTEST_DATE is not None:
        LIVE_MARKET_DEPLOYMENT = False
        logging.info(f"Backtest run for date {BACKTEST_DATE} (dry, no real orders)...")
        staged = run_scan_cycle(kite)
        if staged:
            execute_highest_rr_trade(kite, staged)
        else:
            logging.info("[BACKTEST] No trades staged for this date.")
        with position_lock:
            ACTIVE_POSITIONS.clear()
            shared_write_display(staged or [], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
        trade_db.clear_cycle_trades("index")
        return
    if not LIVE_MARKET_DEPLOYMENT:
        logging.error("Config has _backtest=true but no --date= or --backtest-range= flag. "
                      "Use --date=YYYY-MM-DD or --backtest-range=START,END to run backtest. Exiting.")
        return
    logging.info(f"Scanner: {TIMEFRAME_ENTRY} | Anchor: {TIMEFRAME_ANCHOR} | Capital: {INITIAL_CAPITAL} | Risk: {MAX_RISK_PERCENT}%")
    worker = threading.Thread(target=main_scan_loop, args=(kite,), daemon=True)
    worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Engine stopped by user.")

if __name__ == "__main__":
    main()
