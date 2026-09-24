import os
import json
import logging
import time
import threading
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
import paths
from datetime import datetime as dt, timedelta, time as datetime_time
import pandas as pd

from kiteconnect import KiteConnect
import trade_db

from trading_core import (
    load_kite_session,
    ensure_kite_session,
    optimize_kite_session,
    safe_kite_call,
    fetch_and_resample_candles,
    log_to_journal,
    is_market_open,
    is_new_entry_allowed,
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
    clear_executed_exit,
    slice_quantity_for_freeze,
    calculate_position_size,
    _avg_target_rank,
    _parse_candidate_tier,
    round_to_tick,
    calculate_option_profit_targets,
    get_live_available_cash,
    check_capital_affordability
)

LIVE_MARKET_DEPLOYMENT = True
LOOKBACK_DAYS = 10
INITIAL_CAPITAL = 100000.0
MAX_RISK_PERCENT = 1.0
TOKEN_FILE = paths.TOKEN_FILE
NFO_CACHE_FILE = paths.NFO_CACHE_FILE
SCAN_INTERVAL_SECONDS = 15

TIMEFRAME_ENTRY = "15minute"
TIMEFRAME_ANCHOR = "60minute"
TIMEFRAME_FALLBACK = "15minute"
STRIKE_RANGE = 1
BACKTEST_DATE = None

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
instrument_dump = None
ANCHOR_SCAN_REQUEST_FILE = paths.monitor_file("anchor_scan_request.txt")
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

        # 0DTE Expiry Day Protection:
        # If today is expiry day (days_rem == 0) and time >= 11:30 IST,
        # roll over to next weekly expiry series (expiries[1]) to eliminate severe 0DTE theta decay.
        curr_exp = expiries[0]
        today = get_ist_date()
        days_rem = (curr_exp - today).days
        now_ist = get_ist_now().time()
        if days_rem == 0 and now_ist >= datetime_time(11, 30) and len(expiries) > 1:
            selected_idx = min(selected_idx + 1, len(expiries) - 1)
            logging.info(f"[EXPIRY_ROLLOVER] {base_symbol}: 0DTE (>=11:30 IST) -> rolling from {curr_exp} to next weekly expiry {expiries[selected_idx]}")

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
        # Do not skip active symbols here; scan continuously so new setups appear on the Scan Tab
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
        q = safe_kite_call(kite.quote, [q_key])
        ltp = float(q.get(q_key, {}).get("last_price", 0))
        ask = 0
        depth_sell = q.get(q_key, {}).get("depth", {}).get("sell", [])
        if depth_sell and len(depth_sell) > 0 and depth_sell[0].get("price", 0) > 0:
            ask = float(depth_sell[0]["price"])
        depth_buy = q.get(q_key, {}).get("depth", {}).get("buy", [])
        bid = float(depth_buy[0]["price"]) if (depth_buy and len(depth_buy) > 0 and depth_buy[0].get("price", 0) > 0) else 0.0

        bm = float(pos.get("benchmark") or 0)
        is_spread = pos.get("position_type") == "option_spread"
        if bm > 0 and not is_spread:
            price = round_to_tick(bm * 1.005, 0.05)
        else:
            price = round_to_tick((ask if ask > 0 else ltp) * 1.005, 0.05)

        # Smart Pegged Limit Order Routing (Passive Mid-Price Peg)
        # If spread >= 0.8%, peg limit order at Mid price between Best Bid and Best Ask to capture spread savings
        if bid > 0 and ask > 0 and (ask - bid) / ask >= 0.008:
            mid_price = round_to_tick((bid + ask) / 2.0, 0.05)
            if mid_price > 0 and mid_price < price:
                logging.info(f"[INDEX PEGGED_LIMIT_ROUTING] {pos['contract']}: Pegging limit at Mid-Price {mid_price:.2f} (Bid={bid:.2f}, Ask={ask:.2f}) instead of {price:.2f}")
                price = mid_price

        from position_monitor import clamp_lpp_buy_price
        price = round_to_tick(clamp_lpp_buy_price(price, ask if ask > 0 else (ltp or price)), 0.05)
        lot_sz = pos.get("lot_size") or get_option_lot_size(pos["contract"]) or INDEX_REGISTRY.get(pos.get("symbol", ""), {}).get("lot_size", 1)

        cfg_eng = load_program_config_for_engine("index")
        cfg_liq = cfg_eng.get("liquidity_gate", {})
        base_max_spread = float(cfg_liq.get("max_spread_pct", 0.02))
        cand_tier = _parse_candidate_tier(pos, default=1)
        if cand_tier in [1, 2] or "T1" in str(pos.get("tier_badge", "")) or "GOLD" in str(pos.get("tier_label", "")):
            max_spread = float(cfg_liq.get("max_spread_pct_high_conviction", max(base_max_spread, 0.03)))
        else:
            max_spread = base_max_spread

        from liquidity_guard import check_bid_ask_spread_liquidity
        liq_ok, spread_val, liq_msg, _ = check_bid_ask_spread_liquidity(
            kite=kite, exchange=target_exch, contract=pos["contract"], max_spread_pct=max_spread
        )
        if not liq_ok:
            logging.warning(f"[LIQUIDITY_GATE] Entry rejected for {pos['contract']}: {liq_msg}")
            return False

        # Target Integrity Guard: Enforce Target 1 > Entry Price for long options
        curr_t1 = float(pos.get("t1") or 0.0)
        if curr_t1 <= price or curr_t1 <= 0.0:
            calc_t1, calc_t2, calc_t3 = calculate_option_profit_targets(
                entry_premium=price,
                sl_price=float(pos.get("current_sl") or 0.0),
                dte=pos.get("dte"),
                spot_t1=pos.get("spot_t1")
            )
            pos["t1"] = calc_t1
            pos["t2"] = calc_t2
            pos["t3"] = calc_t3
            logging.info(f"[TARGET INTEGRITY GUARD] Recomputed targets for index {pos.get('symbol')} ({pos['contract']}) based on entry {price:.2f} (SL: {pos.get('current_sl')}): T1={pos['t1']} T2={pos['t2']} T3={pos['t3']}")

        pos_size = int(pos.get("position_size", 0))
        total_qty = lot_sz * pos_size
        if pos_size <= 0 or total_qty <= 0:
            logging.warning(f"[ZERO_QTY_GUARD] Skipping index order placement for {pos.get('contract')}: position_size={pos_size} or total_qty={total_qty} <= 0")
            return False

        qty_slices = slice_quantity_for_freeze(pos["contract"], total_qty)
        placed_oids = []
        for s_qty in qty_slices:
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=pos["contract"],
                exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=s_qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=price, product=kite.PRODUCT_NRML
            )
            placed_oids.append(str(oid))
        primary_oid = placed_oids[0]
        pos["order_id"] = primary_oid
        pos["order_ids"] = placed_oids
        pos["order_status"] = "OPEN"
        sym = pos.get("symbol")
        if sym and sym in ACTIVE_POSITIONS:
            with position_lock:
                ACTIVE_POSITIONS[sym]["order_id"] = primary_oid
                ACTIVE_POSITIONS[sym]["order_ids"] = placed_oids
                ACTIVE_POSITIONS[sym]["order_status"] = "OPEN"
        if pos.get("trade_id"):
            trade_db.update_trade(pos["trade_id"], {"order_id": primary_oid, "order_status": "OPEN"})
        logging.info(f"Index Entry BUY LIMIT placed for {pos['contract']} TotalQty={total_qty} @ {price} (Orders: {placed_oids})")

        # Leg 2 Execution for Debit Spread (Sell OTM Short Leg)
        if pos.get("position_type") == "option_spread" and pos.get("leg2_contract"):
            leg2_c = pos["leg2_contract"]
            try:
                leg2_q_key = f"{target_exch}:{leg2_c}"
                leg2_q = safe_kite_call(kite.quote, [leg2_q_key])
                leg2_depth = leg2_q.get(leg2_q_key, {}).get("depth", {}).get("buy", [])
                leg2_bid = float(leg2_depth[0]["price"]) if (leg2_depth and len(leg2_depth) > 0 and leg2_depth[0].get("price", 0) > 0) else float(leg2_q.get(leg2_q_key, {}).get("last_price", 0))
                leg2_limit = round_to_tick(leg2_bid * 0.995, 0.05) if leg2_bid > 0 else 0.05
                leg2_otype = kite.ORDER_TYPE_LIMIT

                leg2_slices = slice_quantity_for_freeze(leg2_c, total_qty)
                leg2_placed = []
                for l2_qty in leg2_slices:
                    oid2 = kite.place_order(
                        variety=kite.VARIETY_REGULAR, tradingsymbol=leg2_c,
                        exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=l2_qty, order_type=leg2_otype,
                        price=leg2_limit,
                        product=kite.PRODUCT_NRML
                    )
                    leg2_placed.append(str(oid2))
                pos["leg2_order_id"] = leg2_placed[0]
                pos["leg2_order_ids"] = leg2_placed
                if sym and sym in ACTIVE_POSITIONS:
                    with position_lock:
                        ACTIVE_POSITIONS[sym]["leg2_order_id"] = leg2_placed[0]
                        ACTIVE_POSITIONS[sym]["leg2_order_ids"] = leg2_placed
                if pos.get("trade_id"):
                    trade_db.update_trade(pos["trade_id"], {"leg2_order_id": leg2_placed[0], "leg2_order_ids": leg2_placed})
                logging.info(f"[INDEX DEBIT SPREAD] Leg 2 (Short OTM) placed for {leg2_c} TotalQty={total_qty} @ {leg2_limit} (Orders: {leg2_placed})")
            except Exception as leg2_err:
                logging.error(f"[INDEX DEBIT SPREAD ERROR] Failed to place Leg 2 ({leg2_c}): {leg2_err}")
                # ROLLBACK GUARD: If Leg 2 fails, immediately cancel Leg 1 resting orders to prevent naked unhedged exposure
                for o_to_cancel in placed_oids:
                    try:
                        kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=o_to_cancel)
                        logging.warning(f"[DEBIT SPREAD ROLLBACK] Cancelled Leg 1 order {o_to_cancel} because Leg 2 failed: {leg2_err}")
                    except Exception as c_err:
                        logging.error(f"[DEBIT SPREAD ROLLBACK ERROR] Could not cancel Leg 1 order {o_to_cancel}: {c_err}")
                if sym and sym in ACTIVE_POSITIONS:
                    with position_lock:
                        ACTIVE_POSITIONS.pop(sym, None)
                if pos.get("trade_id"):
                    trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED", "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S")})
                return False

        return True
    except Exception as e:
        logging.error(f"Entry failed for {pos['contract']}: {e}")
        if sym and sym in ACTIVE_POSITIONS:
            with position_lock:
                ACTIVE_POSITIONS.pop(sym, None)
        if pos.get("trade_id"):
            trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED", "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S")})
        return False

def simulate_trade_outcome(kite, trade, target_date):
    return shared_simulate(kite, trade, target_date)

# ──────────────────────────────────────────────
#  EXECUTION FUNCTIONS
# ──────────────────────────────────────────────

def execute_highest_rr_trade(kite, staged):
    """After a scan cycle, evaluate staged candidates in descending order of composite rank and execute the best valid setup (ISSUE-071, ISSUE-073)."""
    if not staged:
        return
    from timeframe_utils import get_ist_now
    from datetime import time as dt_time
    now_ist = get_ist_now().time()
    live_ok = LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG)

    # General EOD Hard Cutoff: 15:00:00 IST (never enter any index derivative after 15:00 IST)
    if LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and BACKTEST_DATE is None:
        if now_ist > dt_time(15, 0):
            logging.info(f"[INDEX_CUTOFF_GUARD] All new index trade entries blocked after 15:00 IST (current time: {now_ist.strftime('%H:%M:%S')}). Skipping cycle execution.")
            return

    # Fix 5: Opening Bell 15-Minute Delay Guard
    # Suppress automated index entries before 09:30 AM to allow opening 15m candle close, avoiding opening spread/gap traps.
    if LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and BACKTEST_DATE is None:
        if now_ist < dt_time(9, 30):
            logging.info(f"[INDEX_OPENING_BELL_DELAY] Automated index entries suppressed before 09:30 IST (current time: {now_ist.strftime('%H:%M:%S')}) to allow opening 15m candle close and avoid opening spread/whipsaw traps.")
            return

    cfg_eng = load_program_config_for_engine("index")
    exec_mode = str(cfg_eng.get("execution_mode", "DEBIT_SPREAD")).upper()
    use_spread = (exec_mode in ["DEBIT_SPREAD", "SPREAD_ONLY", "AUTO"])
    # Rule 3: Late Afternoon (>= 14:00 IST) Spread Preference for Theta-Neutralization
    if now_ist >= dt_time(14, 0) and exec_mode != "NAKED_ONLY":
        use_spread = True
    cap_val_base = float(cfg_eng.get("capital") or 100000.0)
    live_cash_avail = get_live_available_cash(kite, default=cap_val_base) if (live_ok and kite) else cap_val_base
    if use_spread and exec_mode != "SPREAD_ONLY" and live_cash_avail < 200000.0:
        logging.info(f"[INDEX_SPREAD_MARGIN_GUARD] Available broker cash ₹{live_cash_avail:,.2f} < ₹2,00,000 threshold. Defaulting to clean naked option to prevent sequential short leg margin rejection.")
        use_spread = False

    # Prioritized Candidate Pools: Tier 1 Gold (Priority 1) and Tier 2 Core (Priority 2)
    t1_candidates = []
    t2_candidates = []
    seen_cand_ids = set()
    for t in staged:
        if not isinstance(t, dict):
            continue
        c_tier = _parse_candidate_tier(t, default=2)
        c_id = id(t)
        if c_tier == 1:
            t1_candidates.append(t)
            seen_cand_ids.add(c_id)
        elif c_tier == 2 and c_id not in seen_cand_ids:
            t2_candidates.append(t)
            seen_cand_ids.add(c_id)

    t1_sorted = sorted(t1_candidates, key=_avg_target_rank, reverse=True)
    t2_sorted = sorted(t2_candidates, key=_avg_target_rank, reverse=True)
    sorted_staged = t1_sorted + t2_sorted
    if not sorted_staged:
        sorted_staged = sorted(staged, key=_avg_target_rank, reverse=True)

    for best in sorted_staged:
        key = f"{best['symbol']}|{best['pattern']}|{best['side']}|{best.get('strike', '')}"
        if trade_db.is_pattern_executed("index", key):
            logging.info(f"Candidate trade {key} already executed; evaluating next candidate")
            continue

        sym = best.get("symbol", "")
        contract_cand = best.get("contract", "")

        # Gate 0: Adaptive DTE-Aware Cutoff Guard
        cand_dte = best.get("dte")
        try:
            cand_dte = int(cand_dte) if cand_dte is not None else None
        except (ValueError, TypeError):
            cand_dte = None

        if LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and BACKTEST_DATE is None:
            # 0DTE / Expiry Day cutoff: strictly blocked after 13:30 IST to prevent lethal gamma/theta decay
            if (cand_dte is None or cand_dte <= 1) and now_ist > dt_time(13, 30):
                logging.info(f"[INDEX_0DTE_CUTOFF_GUARD] Candidate {contract_cand} is 0DTE/Expiry (DTE={cand_dte}). Automated entries blocked after 13:30 IST to prevent lethal theta/gamma burn. Evaluating next candidate.")
                continue
            # Non-expiry contracts (DTE >= 2) in the 13:30 - 15:00 window require high-conviction R:R >= 2.0
            if now_ist > dt_time(13, 30):
                cand_rr = float(best.get("rr") or 0.0)
                if cand_rr < 2.0:
                    logging.info(f"[INDEX_LATE_WINDOW_RR_GUARD] Candidate {contract_cand} has RR={cand_rr:.2f} < 2.0 in late-day window ({now_ist.strftime('%H:%M:%S')}). Requires RR >= 2.0. Skipping.")
                    continue
                logging.info(f"[INDEX_LATE_WINDOW_APPROVED] Candidate {contract_cand} approved in late-day institutional window ({now_ist.strftime('%H:%M:%S')}): DTE={cand_dte} >= 2, RR={cand_rr:.2f} >= 2.0.")

        # Gate 1: Mandatory Spot Confluence Gate (ISSUE-071, ISSUE-073)
        # Auto-execution requires verified spot directional backing (100% win/loss separation).
        if not best.get("spot_confluence"):
            logging.info(f"[SPOT_CONFLUENCE_GATE] Index auto-execution blocked for {sym} ({contract_cand or sym}): "
                         f"spot_confluence={best.get('spot_confluence')} (type={best.get('spot_confluence_type', 'NONE')}); "
                         f"setup visible on Scans Tab; evaluating next candidate")
            continue

        lot_sz = int(best.get("lot_size") or (get_option_lot_size(contract_cand) if contract_cand else None) or INDEX_REGISTRY.get(sym, {}).get("lot_size", 1) or 1)
        raw_pos_size = best.get("position_size")
        c_tier = _parse_candidate_tier(best, default=1)
        if raw_pos_size is None:
            raw_pos_size = calculate_position_size(
                spot_price=float(best.get("entry_spot") or 0.0),
                stop_loss=float(best.get("current_sl") or 0.0),
                capital=float(cfg_eng.get("capital") or 100000.0),
                risk_percent=float(cfg_eng.get("MAX_RISK_PERCENT") or 1.0),
                lot_size=lot_sz,
                is_option=True,
                tier=c_tier,
                allow_zero=True
            )
        pos_size = int(raw_pos_size or 0)
        best["position_size"] = pos_size
        if pos_size <= 0:
            logging.warning(f"[RISK_BUDGET_EXCEEDED] Trade rejected for {best.get('symbol')} ({best.get('contract')}): Position size is 0 lots (Risk per lot exceeds capital budget).")
            continue

        # Gate 2: Low-DTE Premium Floor Gate & 11:30 0DTE Cutoff (ISSUE-071, ISSUE-073)
        dte_cand = best.get("dte")
        if dte_cand is None and contract_cand:
            try:
                from position_monitor import get_contract_days_to_expiry
                dte_cand = get_contract_days_to_expiry(contract_cand)
            except Exception:
                pass

        benchmark_val = float(best.get("benchmark") or best.get("entry_spot") or 0.0)
        if dte_cand is not None and dte_cand <= 5 and benchmark_val < 5.0:
            logging.warning(f"[PREMIUM_FLOOR_GATE] Index auto-execution skipped for {sym} ({contract_cand}): "
                            f"Benchmark premium ₹{benchmark_val:.2f} < ₹5.00 floor with DTE={dte_cand} <= 5 (lottery ticket risk); checking next candidate")
            continue

        if dte_cand is not None and dte_cand <= 0:
            from datetime import time as dt_time
            from trading_core import get_ist_now
            if get_ist_now().time() >= dt_time(11, 30):
                logging.info(f"[0DTE_CUTOFF_EXCEEDED] 0DTE Index setup {contract_cand} rejected: Current IST time {get_ist_now().strftime('%H:%M:%S')} >= 11:30 IST cutoff.")
                continue

        # Gate 3: Safe Option Value Corridor (-5% to +15% VWAP) (ISSUE-071, ISSUE-073)
        v_st = str(best.get("vwap_status", "")).upper()
        v_str = float(best.get("vwap_stretch", 0.0) or 0.0)
        if v_st == "STRETCHED" or v_str > 15.0:
            logging.warning(f"[OPTION_VALUE_GUARD] Index auto-execution skipped for {sym} ({contract_cand}): "
                            f"Option is overstretched ({v_str:.1f}% above VWAP, status={v_st}); wait for pullback/retest")
            continue
        if v_str < -5.0:
            logging.warning(f"[FALLING_KNIFE_GUARD] Index auto-execution skipped for {sym} ({contract_cand}): "
                            f"Option is broken down ({v_str:.1f}% below VWAP); skipping decaying asset")
            continue

        if live_ok or BACKTEST_DATE is not None:
            pos = best.copy()
            pos["entry_time"] = dt.now().isoformat()
            pos.setdefault("position_type", "option")

            # ── 2-Leg Debit Spread Resolution (Neutralizes Theta Decay) ──
            spread_info = None
            if use_spread:
                try:
                    try:
                        from common.position_monitor import _get_nfo_cache
                        from common.resolve import resolve_option_spread
                    except ModuleNotFoundError:
                        from position_monitor import _get_nfo_cache
                        from resolve import resolve_option_spread
                    nfo_df = _get_nfo_cache()
                    sym = best["symbol"]
                    cand_side = str(best.get("side", "CE")).upper()
                    cand_dir = "BEAR" if cand_side == "PE" else "BULL"
                    cp = float(best.get("spot_entry") or 0.0)
                    if cp <= 0:
                        reg_entry = INDEX_REGISTRY.get(sym, {})
                        spot_ts = "SENSEX" if sym == "SENSEX" else reg_entry.get("tradingsymbol")
                        exch_prefix = "BSE" if sym == "SENSEX" else "NSE"
                        if spot_ts and kite:
                            try:
                                q_spot = safe_kite_call(kite.quote, [f"{exch_prefix}:{spot_ts}"])
                                cp = float(q_spot.get(f"{exch_prefix}:{spot_ts}", {}).get("last_price", 0.0))
                            except Exception:
                                cp = 0.0
                    if cp <= 0:
                        cp = float(best.get("strike") or best.get("entry_spot") or 0.0)

                    strike_step = INDEX_REGISTRY.get(sym, {}).get("strike_step", 50)
                    spot_t1 = best.get("spot_t1")
                    if not spot_t1 or float(spot_t1) <= 0:
                        spot_t1 = None
                    else:
                        spot_t1 = float(spot_t1)
                    spread_info = resolve_option_spread(
                        nfo_instruments=nfo_df,
                        base_symbol=sym,
                        spot_price=cp,
                        step_size=strike_step,
                        direction=cand_dir,
                        target_price=spot_t1,
                        side=cand_side
                    )
                    if spread_info:
                        pos["contract"] = spread_info["leg1"]["contract"]
                        pos["option_token"] = spread_info["leg1"]["token"]
                        pos["strike"] = spread_info["leg1"]["strike"]
                        pos["position_type"] = "option_spread"
                        pos["spread_type"] = spread_info["spread_type"]
                        pos["leg2_contract"] = spread_info["leg2"]["contract"]
                        pos["leg2_token"] = spread_info["leg2"]["token"]
                        pos["leg2_strike"] = spread_info["leg2"]["strike"]
                        lot_sz_val = pos.get("lot_size") or get_option_lot_size(pos["contract"]) or INDEX_REGISTRY.get(sym, {}).get("lot_size", 1)
                        pos["leg2_qty"] = int(pos.get("position_size", 1)) * int(lot_sz_val)
                        logging.info(f"[INDEX DEBIT SPREAD RESOLVED] {sym}: Leg 1 (Long)={pos['contract']} @ {pos['strike']} | Leg 2 (Short)={spread_info['leg2']['contract']} @ {spread_info['leg2']['strike']}")
                except Exception as spread_err:
                    logging.warning(f"Index spread resolution fallback to naked for {best.get('symbol')}: {spread_err}")

            if live_ok:
                from vix_guard import evaluate_vix_regime
                conf_type = str(best.get("spot_confluence_type") or "").upper()
                is_vwap_conf = ("VWAP_REJECT" in conf_type) or ("VWAP_RECLAIM" in conf_type)
                rvol_val = float(best.get("rvol") or best.get("rvol_abs") or 0.0)
                trend_momentum_ok = is_vwap_conf and (rvol_val >= 1.5) and bool(best.get("spot_ema_trend", True))

                vix_ok, vix_msg, _ = evaluate_vix_regime(
                    kite,
                    tier_val=c_tier,
                    is_debit_spread=bool(spread_info),
                    has_momentum_override=trend_momentum_ok
                )
                if not vix_ok:
                    logging.info(f"[VIX_REGIME_GATE] Auto-execution skipped for {best['symbol']} ({best['contract']}): {vix_msg}")
                    try:
                        from watchlist_monitor import add_watchlist_item
                        add_watchlist_item(
                            contract=best.get("contract"),
                            base_symbol=best.get("symbol"),
                            entry_price=best.get("entry_spot"),
                            lot_size=pos.get("lot_size", 1),
                            tag="MISSED_OPPORTUNITY",
                            note=f"Skipped by {vix_msg} (R:R={best.get('rr', 0.0):.2f}, Tier={c_tier})"
                        )
                    except Exception as w_err:
                        logging.debug(f"[WATCHLIST] Missed opportunity log error: {w_err}")
                    continue

                from portfolio_risk import check_portfolio_risk_caps
                cap_val = float(cfg_eng.get("capital") or 100000.0)
                p_ok, p_msg, _ = check_portfolio_risk_caps(
                    engine="index",
                    symbol=best["symbol"],
                    candidate_tier=c_tier,
                    capital=cap_val,
                    live_positions=ACTIVE_POSITIONS,
                    kite=kite
                )
                if not p_ok:
                    logging.info(f"[PORTFOLIO_RISK_CAP] Auto-execution skipped for {best['symbol']} ({best['contract']}): {p_msg}")
                    try:
                        from watchlist_monitor import add_watchlist_item
                        add_watchlist_item(
                            contract=best.get("contract"),
                            base_symbol=best.get("symbol"),
                            entry_price=best.get("entry_spot"),
                            lot_size=pos.get("lot_size", 1),
                            tag="MISSED_OPPORTUNITY",
                            note=f"Skipped by {p_msg} (R:R={best.get('rr', 0.0):.2f}, Tier={c_tier})"
                        )
                    except Exception as w_err:
                        logging.debug(f"[WATCHLIST] Missed opportunity log error: {w_err}")
                    continue

                # Gate 0A: Pre-Execution Capital Affordability Gate (Fix 1)
                entry_price_val = float(best.get("benchmark") or best.get("entry_spot") or 0.0)
                required_capital = float(pos_size * lot_sz * entry_price_val)
                if live_ok and kite:
                    afford_ok, afford_msg, _ = check_capital_affordability(
                        kite, required_capital=required_capital, max_utilization_pct=0.90, default_capital=cap_val
                    )
                    if not afford_ok:
                        logging.warning(f"🛡️ [INDEX CAPITAL GATE] Auto-execution skipped for {best['symbol']} ({best.get('contract')}): {afford_msg}.")
                        continue

                with position_lock:
                    contract_cand = pos.get("contract") or best.get("contract")
                    sym_cand = best.get("symbol")
                    if sym_cand in ACTIVE_POSITIONS:
                        logging.info(f"{sym_cand} already active in ACTIVE_POSITIONS; evaluating next candidate")
                        continue

                    # Index Concurrency Cap (Fix 3): Max 1 open directional index trade across any index
                    max_idx_pos = int(cfg_eng.get("max_concurrent_positions", 1))
                    active_idx_in_mem = {s for s in ACTIVE_POSITIONS.keys() if s in INDEX_REGISTRY or s in ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "BANKEX"]}
                    active_db_trades = trade_db.get_active_trades(engine="index")
                    active_idx_db = {t.get("symbol") for t in active_db_trades if t.get("symbol")}
                    total_active_indices = active_idx_in_mem.union(active_idx_db)
                    if len(total_active_indices) >= max_idx_pos:
                        logging.info(f"[INDEX_CONCURRENCY_CAP] Max concurrent index positions reached ({len(total_active_indices)}/{max_idx_pos} active: {sorted(list(total_active_indices))}). Skipping {sym_cand}")
                        try:
                            from watchlist_monitor import add_watchlist_item
                            add_watchlist_item(
                                contract=contract_cand,
                                base_symbol=sym_cand,
                                entry_price=best.get("entry_spot"),
                                lot_size=pos.get("lot_size", 1),
                                tag="MISSED_OPPORTUNITY",
                                note=f"Skipped by INDEX_CONCURRENCY_CAP (R:R={best.get('rr', 0.0):.2f}, Tier={c_tier})"
                            )
                        except Exception as w_err:
                            logging.debug(f"[WATCHLIST] Missed opportunity log error: {w_err}")
                        continue

                    if trade_db.is_contract_active(contract_cand, "index") or trade_db.is_symbol_active(sym_cand, "index"):
                        logging.info(f"[DUPLICATE_GUARD] {sym_cand} ({contract_cand}) already active in trade_db; evaluating next candidate")
                        continue

                    from position_monitor import is_contract_held_on_broker
                    is_held, held_qty = is_contract_held_on_broker(kite, contract_cand)
                    if is_held:
                        logging.info(f"[DUPLICATE_GUARD] Contract {contract_cand} already held on broker (Qty: {held_qty}); evaluating next candidate")
                        continue

                    pos["entry_time"] = dt.now().strftime("%Y-%m-%d %H:%M:%S")
                    pos["mfe_pct"] = 0.0
                    pos["mae_pct"] = 0.0
                    pos["trade_dna"] = {
                        "spot_vwap_dist_pct": round(((float(best.get("spot_ltp", 0.0) or best.get("entry_spot", 0.0) or 0.0) - float(best.get("spot_vwap", 0.0) or 0.0)) / float(best.get("spot_vwap", 1.0) or 1.0)) * 100, 2) if float(best.get("spot_vwap", 0.0) or 0.0) > 0 else 0.0,
                        "spot_rvol": round(float(best.get("rvol") or best.get("spot_rvol") or 1.0), 2),
                        "spot_ema_trend": "BULL" if str(best.get("side", "CE")).upper() == "CE" else "BEAR",
                        "spot_atr_ratio": round(float(best.get("spot_atr_ratio", 1.0) or 1.0), 2),
                        "opt_vcp_ratio": round(float(best.get("opt_atr_ratio", 1.0) or 1.0), 2),
                        "opt_spread_pct": round(float(best.get("spread_pct", 0.0) or 0.0), 2),
                        "opt_vwap_sigma": round(float(best.get("opt_vwap_sigma", 0.0) or 0.0), 2)
                    }
                    pos["trade_id"], _created = trade_db.create_trade("index", sym_cand, {k: v for k, v in pos.items() if k != "trade_id"})
                    if not _created:
                        logging.info(f"[DUPLICATE_GUARD] Active trade for {contract_cand} already exists in trade_db (ID: {pos['trade_id']}); evaluating next candidate")
                        continue
                    ACTIVE_POSITIONS[sym_cand] = pos

            trade_db.record_executed_pattern("index", key, {"contract": pos.get("contract", best.get("contract")), "entry": best["entry_spot"]})
            ok = execute_index_entry(kite, pos)
            if not ok:
                if live_ok:
                    with position_lock:
                        ACTIVE_POSITIONS.pop(best["symbol"], None)
                if pos.get("trade_id"):
                    trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED", "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S")})
                logging.warning(f"Order placement failed for {best.get('contract')}. Locked pattern {key} to prevent rate-limit spam loops.")
                continue

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
            break
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
            break

def monitor_active_positions(kite):
    return shared_monitor_positions(kite, INDEX_REGISTRY, ACTIVE_POSITIONS, position_lock,
                                     kite.PRODUCT_NRML, "index", TIMEFRAME_ENTRY,
                                     trade_db, log_to_journal,
                                     live=LIVE_MARKET_DEPLOYMENT)

def position_monitor_loop(kite):
    """Dedicated background thread for index position monitoring (ISSUE-073).
    Decoupled from scan cycles so trailing SL, +BE lock, and target exits are evaluated continuously every 15s.
    """
    logging.info("[INDEX MONITOR THREAD] Dedicated position monitor loop started (15s interval).")
    while True:
        try:
            if LIVE_MARKET_DEPLOYMENT:
                monitor_active_positions(kite)
        except Exception as e:
            logging.error(f"[INDEX MONITOR THREAD] Error monitoring positions: {e}")
        time.sleep(15)


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
        kite_positions = safe_kite_call(kite.positions) or {}
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
            # DEBIT SPREAD RECOVERY: Check if there is an opposing short leg for this symbol on broker
            short_p = next((sp for sp in all_positions if sp.get("exchange") in ("NFO", "BFO") and int(sp.get("quantity", 0)) < 0 and match_registry_symbol(INDEX_REGISTRY, sp.get("tradingsymbol", "")) == symbol), None)
            if short_p:
                pos["position_type"] = "option_spread"
                pos["leg2_contract"] = short_p["tradingsymbol"]
                pos["leg2_qty"] = abs(int(short_p["quantity"]))
                pos["leg2_token"] = int(short_p.get("instrument_token", 0))
                logging.info(f"[KITE_RECOVER_SPREAD] Linked short leg {short_p['tradingsymbol']} (Qty: {pos['leg2_qty']}) to {p['tradingsymbol']}")

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
    # Warm Start: Preserve and reconcile existing staged setups on startup
    startup_staged_idx = []
    if os.path.exists(SCAN_DISPLAY_FILE):
        try:
            with open(SCAN_DISPLAY_FILE, "r", encoding="utf-8") as f_disp_idx:
                prev_disp_idx = json.load(f_disp_idx)
                startup_staged_idx = prev_disp_idx.get("staged_trades") or []
        except Exception as disp_idx_err:
            logging.debug(f"Index startup staged read error: {disp_idx_err}")
    with position_lock:
        shared_write_display(startup_staged_idx, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "index")
    cycle = 0
    while True:
        try:
            ensure_kite_session(kite)
            load_program_config()
            cycle += 1
            # Fast sync active trades from SQLite trade_db to catch manual/1-Click entries immediately
            try:
                db_active = trade_db.get_active_trades("index")
                with position_lock:
                    for at in db_active:
                        at_sym = at.get("symbol")
                        if at_sym and at_sym not in ACTIVE_POSITIONS:
                            pos_rec = {k: v for k, v in at.items() if k not in ("id", "engine", "symbol", "status", "updated_at")}
                            pos_rec["trade_id"] = at["id"]
                            pos_rec["entry_spot"] = pos_rec.get("entry_spot") or at.get("entry_spot")
                            pos_rec["entry_time"] = sanitize_entry_time(pos_rec)
                            ACTIVE_POSITIONS[at_sym] = pos_rec
                            logging.info(f"[FAST_DB_SYNC] Incorporated active trade for {at_sym} ({at.get('contract')}) into ACTIVE_POSITIONS")
            except Exception as db_sync_err:
                logging.debug(f"Fast DB active sync error: {db_sync_err}")

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
            if os.path.exists(ANCHOR_SCAN_REQUEST_FILE):
                try:
                    with open(ANCHOR_SCAN_REQUEST_FILE) as f:
                        engine_req = f.read().strip()
                    os.remove(ANCHOR_SCAN_REQUEST_FILE)
                    if engine_req != "index":
                        logging.info(f"Anchor scan flag not for index, skipping (got {engine_req})")
                    else:
                        logging.info(f"Anchor scan requested via flag file (engine: {engine_req})")
                        run_anchor_scan(kite)
                except Exception:
                    pass
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
                best = max(staged, key=_avg_target_rank)
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

def load_program_config():
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

def main():
    global BACKTEST_DATE, LIVE_MARKET_DEPLOYMENT
    load_program_config()
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
        optimize_kite_session(kite)
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
    monitor_worker = threading.Thread(target=position_monitor_loop, args=(kite,), daemon=True)
    monitor_worker.start()
    worker = threading.Thread(target=main_scan_loop, args=(kite,), daemon=True)
    worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Engine stopped by user.")

if __name__ == "__main__":
    main()
