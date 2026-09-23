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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, datetime as dt, timedelta, time as datetime_time
import pandas as pd

from kiteconnect import KiteConnect
import trade_db
import pattern_funnel

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
    calculate_position_size,
    scan_anchor_bcd_breakout,
    scan_trend_continuation_reentry,
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    trading_days_between,
    live_execution_enabled,
    close_position as shared_close_position,
    load_program_config_for_engine,
    sync_kite_positions as shared_sync_kite,
    write_scan_display_data as shared_write_display,
    derive_sl_targets_for_symbol,
    lookup_scan_sl_target,
    reconcile_positions as shared_reconcile,
    resolve_option_strikes as shared_resolve_strikes,
    scan_symbol,
    monitor_active_positions as shared_monitor_positions,
    sanitize_entry_time,
    simulate_trade_outcome as shared_simulate,
    clear_executed_exit,
    STOCK_REGISTRY,
    match_registry_symbol,
    extract_underlying_symbol,
    get_option_lot_size,
    calculate_sl_buffer,
    STOCK_EXPIRY_ROLLOVER_DAYS,
    slice_quantity_for_freeze
)

LIVE_MARKET_DEPLOYMENT = True
LOOKBACK_DAYS = 15
INITIAL_CAPITAL = 100000.0
MAX_RISK_PERCENT = 1.0
TOKEN_FILE = paths.TOKEN_FILE
STATE_FILE = paths.monitor_file("stock_positions_state.json")
SCAN_INTERVAL_SECONDS = 900
CORE_SCAN_INTERVAL_SECONDS = 180
FULL_SCAN_INTERVAL_SECONDS = 900
ENABLE_2TIER_SCHEDULING = True
ENABLE_PREMARKET_SEEDING = True
STRIKE_RANGE = 0

TIMEFRAME_ENTRY = "15minute"
TIMEFRAME_ANCHOR = "30minute"
TARGET_UNIVERSE = "FNO_ALL"
BACKTEST_DATE = None

ACTIVE_POSITIONS = {}
position_lock = threading.Lock()
NFO_INSTRUMENTS = pd.DataFrame()
instruments_lock = threading.Lock()
ANCHOR_SCAN_REQUEST_FILE = paths.monitor_file("anchor_scan_request.txt")
LIVE_EXECUTION_FLAG = paths.NIFTY50_LIVE_FLAG
SCAN_DISPLAY_FILE = paths.SCAN_DISPLAY_FILE
SL_TARGET_OVERRIDES_FILE = paths.SL_TARGET_OVERRIDES_FILE
_RADAR_ACTIVE = threading.Event()
_LAST_LIQ_WARN = {}
_LAST_FUNNEL_CLEANUP_DATE = None

class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

os.makedirs(os.path.dirname(paths.NIFTY50_LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        FlushFileHandler(paths.NIFTY50_LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def save_state():
    with position_lock:
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(ACTIVE_POSITIONS, f, indent=4)
        except Exception as e:
            logging.error(f"State save failed: {e}")

def load_state():
    global ACTIVE_POSITIONS
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                ACTIVE_POSITIONS = json.load(f)
        except Exception as e:
            logging.error(f"State load failed: {e}")

NFO_CACHE_FILE = paths.NFO_CACHE_FILE

def sync_instruments(kite):
    global NFO_INSTRUMENTS
    def _do_sync():
        global NFO_INSTRUMENTS
        from registries import sync_fno_stock_registry, sync_stock_tokens

        # Optimization 1: Reuse today's NFO cache if already fetched (< 12h old)
        if os.path.exists(NFO_CACHE_FILE):
            try:
                mtime = os.path.getmtime(NFO_CACHE_FILE)
                if (time.time() - mtime) < 43200:  # Fresh within 12 hours
                    df_cached = pd.read_csv(NFO_CACHE_FILE)
                    if not df_cached.empty and len(df_cached) >= 1000:
                        with instruments_lock:
                            NFO_INSTRUMENTS = df_cached
                            NFO_INSTRUMENTS['name'] = NFO_INSTRUMENTS['name'].str.strip().str.upper()
                            NFO_INSTRUMENTS['instrument_type'] = NFO_INSTRUMENTS['instrument_type'].str.strip().str.upper()
                        sync_stock_tokens(kite)
                        from registries import _populate_stock_registry_from_cache
                        _populate_stock_registry_from_cache()
                        logging.info(f"Loaded {len(NFO_INSTRUMENTS)} NFO/BFO contracts from today's cache ({len(STOCK_REGISTRY)} F&O equities in registry)")
                        return
            except Exception as c_err:
                logging.debug(f"Cache check error: {c_err}")

        # Optimization 2: Single-pass download for NSE, NFO, and BFO
        nse = kite.instruments("NSE")
        df_nse = pd.DataFrame(nse) if nse else pd.DataFrame()
        sync_stock_tokens(kite, df_nse=df_nse)

        nfo = kite.instruments("NFO")
        df_nfo = pd.DataFrame(nfo) if nfo else pd.DataFrame()
        sync_fno_stock_registry(kite, target_universe=TARGET_UNIVERSE, df_nfo=df_nfo, df_nse=df_nse)

        try:
            bfo = kite.instruments("BFO")
        except Exception:
            bfo = []
        combined = (nfo if nfo else []) + (bfo if bfo else [])
        with instruments_lock:
            NFO_INSTRUMENTS = pd.DataFrame(combined)
            if not NFO_INSTRUMENTS.empty:
                NFO_INSTRUMENTS['name'] = NFO_INSTRUMENTS['name'].str.strip().str.upper()
                NFO_INSTRUMENTS['instrument_type'] = NFO_INSTRUMENTS['instrument_type'].str.strip().str.upper()
                logging.info(f"Synced {len(NFO_INSTRUMENTS)} NFO/BFO contracts ({len(STOCK_REGISTRY)} F&O equities in registry)")
                os.makedirs(os.path.dirname(NFO_CACHE_FILE), exist_ok=True)
                NFO_INSTRUMENTS.to_csv(NFO_CACHE_FILE, index=False)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_do_sync)
        future.result(timeout=180)
    except Exception as e:
        err_msg = str(e) if str(e).strip() else type(e).__name__
        logging.warning(f"Instrument sync notice: {err_msg}, falling back to cached NFO data")
        _load_cached_nfo()
    finally:
        pool.shutdown(wait=False)

def _load_cached_nfo():
    global NFO_INSTRUMENTS
    if os.path.exists(NFO_CACHE_FILE):
        try:
            df = pd.read_csv(NFO_CACHE_FILE)
            if not df.empty:
                with instruments_lock:
                    NFO_INSTRUMENTS = df
                from registries import _populate_stock_registry_from_cache
                _populate_stock_registry_from_cache()
                logging.info(f"Loaded {len(NFO_INSTRUMENTS)} NFO contracts from cache ({len(STOCK_REGISTRY)} F&O equities in registry)")
        except Exception as e:
            logging.warning(f"Failed to load cached NFO: {e}")

# ──────────────────────────────────────────────
#  OPTION CONTRACT RESOLUTION
# ──────────────────────────────────────────────

def resolve_option_contract(symbol, spot, step, opt_type, target_strike=None):
    with instruments_lock:
        if NFO_INSTRUMENTS.empty:
            s = target_strike or int(round(spot / step) * step)
            return f"{symbol}{dt.now().strftime('%y%b').upper()}{s}{opt_type}"
        try:
            m = NFO_INSTRUMENTS[
                (NFO_INSTRUMENTS['name'] == symbol.strip().upper()) &
                (NFO_INSTRUMENTS['instrument_type'] == opt_type.upper())
            ].copy()
            if m.empty:
                return None
            m['strike'] = m['strike'].astype(float)
            target = target_strike or round(spot / step) * step
            sub = m[m['strike'] == float(target)].copy()
            if sub.empty:
                idx = (m['strike'] - spot).abs().idxmin()
                sel = m.loc[idx]
            else:
                sub['expiry_dt'] = pd.to_datetime(sub['expiry']).dt.date
                today = get_ist_date()
                future = sub[sub['expiry_dt'] >= today].sort_values(by='expiry_dt')
                if not future.empty:
                    expiries = future['expiry_dt'].unique()
                    curr_exp = expiries[0]
                    days_rem = (curr_exp - today).days
                    # 85% Threshold Rule: If <= 6 days remaining to monthly expiry, select NEXT MONTH
                    if days_rem <= STOCK_EXPIRY_ROLLOVER_DAYS and len(expiries) > 1:
                        target_exp = expiries[1]
                        logging.info(f"[STOCK EXPIRY ROLLOVER 85%] {symbol}: {days_rem}d to expiry ({curr_exp}) -> Selected NEXT MONTH ({target_exp})")
                        sel = future[future['expiry_dt'] == target_exp].iloc[0]
                    elif days_rem <= 2 and len(expiries) <= 1:
                        logging.warning(f"[PHYSICAL DELIVERY GUARD] {symbol}: Only {days_rem}d to monthly expiry with no next-month contract. Skipping to prevent physical settlement margin penalty.")
                        return None
                    else:
                        sel = future.iloc[0]
                else:
                    sel = sub.iloc[0] if not sub.empty else m.iloc[0]
            return str(sel['tradingsymbol'])
        except Exception as e:
            logging.error(f"Option resolve error for {symbol}: {e}")
            s = target_strike or int(round(spot / step) * step)
            return f"{symbol}{dt.now().strftime('%y%b').upper()}{s}{opt_type}"

def resolve_option_strikes(symbol, spot_price, step_size, option_type, n_range):
    with instruments_lock:
        return shared_resolve_strikes(NFO_INSTRUMENTS, symbol, spot_price, step_size, option_type, n_range)


# ──────────────────────────────────────────────
#  EXECUTION FUNCTIONS
# ──────────────────────────────────────────────

def close_position(kite, pos):
    return shared_close_position(kite, pos, LIVE_MARKET_DEPLOYMENT, kite.PRODUCT_NRML)

def _derive_sl_targets_for_symbol(kite, symbol, entry_price):
    return derive_sl_targets_for_symbol(kite, symbol, entry_price, STOCK_REGISTRY, TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR, LOOKBACK_DAYS, lambda sym, sp, step, opt, r: resolve_option_strikes(sym, sp, step, opt, r))

def reconcile_positions(kite):
    shared_reconcile(kite, STOCK_REGISTRY, ACTIVE_POSITIONS, position_lock, "nifty50", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR, LOOKBACK_DAYS, lambda sym, sp, step, opt, r: resolve_option_strikes(sym, sp, step, opt, r), save_state)

# ──────────────────────────────────────────────
#  SCAN CYCLE — RUNS EVERY N SECONDS
# ──────────────────────────────────────────────

def _process_stock(kite, symbol, config, from_entry, to_entry, from_anchor, to_anchor, entry_scanners, anchor_scanners, spot_ltp=None):
    # Priority Coordination: If Fast Radar is actively evaluating Category A/A+ candidates, pause briefly to yield Kite rate limits
    if _RADAR_ACTIVE.is_set():
        time.sleep(0.35)
    return scan_symbol(kite, symbol, config, from_entry, to_entry, from_anchor, to_anchor,
                       entry_scanners, anchor_scanners,
                       lambda sym, sp, step, opt, r: shared_resolve_strikes(NFO_INSTRUMENTS, sym, sp, step, opt, r),
                       "nifty50", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR, TIMEFRAME_ENTRY,
                       ACTIVE_POSITIONS, position_lock, trade_db, STRIKE_RANGE,
                       log_to_journal, spot_ltp=spot_ltp)


def run_scan_cycle(kite, universe_mode="AUTO"):
    if NFO_INSTRUMENTS.empty:
        sync_instruments(kite)
    cfg_applied = load_program_config_for_engine("nifty50", [("strike_range", "STRIKE_RANGE"), ("strict_macro_gate", "STRICT_MACRO_GATE")])
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

    from equity_universe import NIFTY50_SYMBOLS, INDICES_REGISTRY_MAP
    if TARGET_UNIVERSE == "NIFTY50":
        base_symbols = sorted([s for s in STOCK_REGISTRY.keys() if s in NIFTY50_SYMBOLS])
    elif TARGET_UNIVERSE in INDICES_REGISTRY_MAP:
        univ_syms = set(INDICES_REGISTRY_MAP[TARGET_UNIVERSE])
        base_symbols = sorted([s for s in STOCK_REGISTRY.keys() if s in univ_syms])
    else:
        base_symbols = sorted(STOCK_REGISTRY.keys())

    # Bulk pre-fetch all spot quotes (LTP, Volume, OHLC) in batches of 100
    spot_quotes = {}
    if kite:
        spot_query = [f"NSE:{s}" for s in base_symbols]
        for chunk_start in range(0, len(spot_query), 100):
            chunk = spot_query[chunk_start : chunk_start + 100]
            try:
                q_res = safe_kite_call(kite.quote, chunk)
                if q_res and isinstance(q_res, dict):
                    spot_quotes.update(q_res)
            except Exception as q_err:
                logging.debug(f"Chunk quote fetch error, falling back to LTP: {q_err}")
                try:
                    ltp_res = safe_kite_call(kite.ltp, chunk)
                    if ltp_res and isinstance(ltp_res, dict):
                        spot_quotes.update(ltp_res)
                except Exception as ltp_err:
                    logging.debug(f"Chunk LTP fallback error: {ltp_err}")

    # Identify Incubating Symbols from Pattern Funnel (Category A+, A, B)
    incubating_syms = set()
    try:
        current_funnel = pattern_funnel.load_funnel_state("nifty50")
        for pool in ["category_a_plus", "category_a", "category_b"]:
            for item in current_funnel.get(pool, []):
                sym = item.get("symbol")
                if sym:
                    incubating_syms.add(sym)
    except Exception as fn_err:
        logging.debug(f"Funnel priority check error: {fn_err}")

    # Dynamic Scan Priority Scoring:
    # 1. Funnel Incubating Setups (Category A+/A/B): +10,000 pts (Scan immediately)
    # 2. Intraday % Change Velocity: + (abs_pct_change * 100 pts)
    # 3. Traded Turnover Liquidity: + min(Turnover_Cr * 5.0, 500 pts)
    def _compute_scan_priority(sym):
        score = 0.0
        if sym in incubating_syms:
            score += 10000.0

        q = spot_quotes.get(f"NSE:{sym}", {})
        lp = float(q.get("last_price") or 0.0)
        ohlc = q.get("ohlc") or {}
        prev_close = float(ohlc.get("close") or 0.0)
        vol = float(q.get("volume") or 0.0)

        if prev_close > 0 and lp > 0:
            pct_change = abs(lp - prev_close) / prev_close * 100.0
            score += pct_change * 100.0

        turnover_cr = (vol * lp) / 1e7
        score += min(turnover_cr * 5.0, 500.0)
        return score

    # Sort descending by priority score; tie-break alphabetically
    scan_order = sorted(base_symbols, key=lambda s: (-_compute_scan_priority(s), s))

    # 2-Tier Universe Filtering (FEATURE-042: 2-Tier Fast Scheduling & Pre-Market Seeding)
    if universe_mode == "CORE":
        core_symbols = set()
        from equity_universe import NIFTY50_SYMBOLS
        core_symbols.update(incubating_syms)
        with position_lock:
            core_symbols.update(ACTIVE_POSITIONS.keys())
        core_symbols.update(NIFTY50_SYMBOLS)
        # Add active intraday movers (>=1.0% price move or >=10 Cr turnover)
        for s in base_symbols:
            q = spot_quotes.get(f"NSE:{s}", {})
            lp = float(q.get("last_price") or 0.0)
            vol = float(q.get("volume") or 0.0)
            ohlc = q.get("ohlc") or {}
            prev_close = float(ohlc.get("close") or 0.0)
            pct_chg = abs(lp - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
            turnover_cr = (vol * lp) / 1e7
            if pct_chg >= 1.0 or turnover_cr >= 10.0:
                core_symbols.add(s)

        filtered_core = [s for s in scan_order if s in core_symbols]
        logging.info(f"[TIER-1 CORE SCAN] Filtered {len(scan_order)} -> {len(filtered_core)} prioritized core & high-velocity stocks (Incubating: {len(incubating_syms)}, Nifty50: {len(NIFTY50_SYMBOLS)}).")
        scan_order = filtered_core
    elif universe_mode == "FULL":
        logging.info(f"[TIER-2 FULL SCAN] Comprehensive macro sweep across all {len(scan_order)} F&O stocks.")

    # Fast Bulk-Quote Screener (ISSUE-072 Speed Phase, Pillar 2)
    # Filter out dormant/zero-volume symbols during active market hours to cut scan cycle latency
    # Safeguards: Always retains incubating setups (Cat A+/A/B), active positions, NIFTY50 core stocks, and active movers
    if kite and is_market_open() and BACKTEST_DATE is None:
        active_scan_symbols = []
        skipped_count = 0
        from equity_universe import NIFTY50_SYMBOLS
        for sym in scan_order:
            if sym in incubating_syms or sym in ACTIVE_POSITIONS or sym in NIFTY50_SYMBOLS:
                active_scan_symbols.append(sym)
                continue
            q = spot_quotes.get(f"NSE:{sym}", {})
            lp = float(q.get("last_price") or 0.0)
            vol = float(q.get("volume") or 0.0)
            ohlc = q.get("ohlc") or {}
            prev_close = float(ohlc.get("close") or 0.0)
            pct_chg = abs(lp - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
            turnover_cr = (vol * lp) / 1e7

            # If stock has 0 volume or completely flat (<0.10% move and turnover < ₹25 Lakhs), skip heavy multi-TF candle fetch
            if lp <= 0 or vol <= 0 or (pct_chg < 0.10 and turnover_cr < 0.25):
                skipped_count += 1
                continue
            active_scan_symbols.append(sym)
        if skipped_count > 0:
            logging.info(f"[FAST_SCREENER] Screened {len(scan_order)} stocks: {len(active_scan_symbols)} active candidates prioritized, {skipped_count} dormant/flat stocks skipped.")
        scan_order = active_scan_symbols

    if scan_order:
        top_preview = ", ".join([f"{s}({_compute_scan_priority(s):.0f}pts)" for s in scan_order[:6]])
        logging.info(f"[PRIORITY SCAN ORDER] Evaluated {len(scan_order)} stocks. Top priority: {top_preview}")

    temp_stored_trades = []

    funnel_summary = pattern_funnel.get_funnel_summary("nifty50")
    radar_active_count = funnel_summary.get("count_a_plus", 0) + funnel_summary.get("count_a", 0)
    worker_threads = 2 if radar_active_count > 0 else 3
    if radar_active_count > 0:
        logging.info(f"[RADAR PRIORITY GATE] {radar_active_count} setup(s) on radar. Throttling macro scan (workers={worker_threads}) to preserve Zerodha Kite rate limits.")

    dispatched_in_cycle = set()
    live_ok = LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and is_new_entry_allowed(live_execution_active=True, is_option=True)

    with ThreadPoolExecutor(max_workers=worker_threads) as pool:
        futures = {}
        for symbol in scan_order:
            config = STOCK_REGISTRY.get(symbol)
            if not config or not config.get("token"):
                continue
            s_ltp = spot_quotes.get(f"NSE:{symbol}", {}).get("last_price")
            if s_ltp is None or s_ltp <= 0:
                continue
            futures[pool.submit(_process_stock, kite, symbol, config,
                from_entry, to_entry, from_anchor, to_anchor,
                entry_scanners, anchor_scanners, spot_ltp=s_ltp)] = symbol

        for f in as_completed(futures):
            symbol = futures[f]
            try:
                result = f.result()
                if result:
                    temp_stored_trades.extend(result)
                    with position_lock:
                        shared_write_display(temp_stored_trades, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")

                    # Instant Dispatch on Discovery (ISSUE-072 Speed Phase, Pillar 1)
                    # When a worker discovers a Tier 1 Gold candidate with confirmed spot confluence,
                    # dispatch it IMMEDIATELY rather than waiting 8-12 minutes for all 210 stocks to complete!
                    if live_ok:
                        for cand in result:
                            if not isinstance(cand, dict):
                                continue
                            c_tier = _parse_candidate_tier(cand, default=2)
                            if c_tier == 1 and cand.get("spot_confluence"):
                                sym_c = cand.get("symbol", "")
                                p_c = cand.get("pattern", "")
                                s_c = cand.get("side", "")
                                stk_c = cand.get("strike", "")
                                d_key = f"{sym_c}|{p_c}|{s_c}|{stk_c}"
                                if d_key not in dispatched_in_cycle and not trade_db.is_pattern_executed("nifty50", d_key):
                                    logging.info(f"[INSTANT_DISPATCH] 🥇 Tier 1 Gold setup discovered for {sym_c} ({cand.get('contract')}). Triggering instant execution without waiting for batch completion!")
                                    dispatched_in_cycle.add(d_key)
                                    execute_highest_rr_trade(kite, [cand])
            except Exception as e:
                logging.error(f"Error processing {symbol}: {e}")

        with position_lock:
            shared_write_display(temp_stored_trades, dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")

    # Audit incubating setups in Category B and Category A for Anchor TF T1 / SL closure / Runaway
    try:
        current_funnel = pattern_funnel.load_funnel_state("nifty50")
        for pool_key in ["category_a_plus", "category_a", "category_b"]:
            for item in list(current_funnel.get(pool_key, [])):
                sym = item.get("symbol")
                sl = float(item.get("current_sl") or 0.0)
                t1 = float(item.get("t1") or 0.0)
                bm = float(item.get("benchmark") or 0.0)
                tok = item.get("option_token") or item.get("spot_token")
                if tok and (sl > 0 or t1 > 0 or bm > 0):
                    from timeframe_utils import fetch_and_resample_candles
                    df_a_check = safe_kite_call(
                        fetch_and_resample_candles,
                        kite, tok,
                        (dt.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
                        dt.now().strftime('%Y-%m-%d'),
                        TIMEFRAME_ANCHOR
                    )
                    if df_a_check is not None and not df_a_check.empty:
                        last_candle = df_a_check.iloc[-1]
                        c_dt = get_ist_now(naive=True)
                        try:
                            parsed_dt = pd.to_datetime(str(last_candle.get('date', '')))
                            if hasattr(parsed_dt, 'tz') and parsed_dt.tz is not None:
                                parsed_dt = parsed_dt.tz_convert('Asia/Kolkata').tz_localize(None)
                            c_dt = parsed_dt
                        except Exception:
                            pass
                        from timeframe_utils import get_tf_minutes
                        anchor_mins = get_tf_minutes(TIMEFRAME_ANCHOR)
                        now_ist = get_ist_now(naive=True)
                        is_closed_anchor = (now_ist - c_dt).total_seconds() >= (anchor_mins * 60.0)

                        last_a_close = float(last_candle['close'])
                        t1_80pct = round(bm + 0.80 * (t1 - bm), 2) if (bm > 0 and t1 > bm) else round(t1 * 0.80, 2) if t1 > 0 else 0.0

                        from targets import calculate_sl_buffer
                        buffered_sl = calculate_sl_buffer(sl, side="BULL") if sl > 0 else 0.0

                        if buffered_sl > 0 and last_a_close <= buffered_sl:
                            if is_closed_anchor:
                                logging.info(f"[ANCHOR TF EVICT: SL BREACH] {sym} ({item.get('contract')}) closed at/below buffered SL on {TIMEFRAME_ANCHOR} ({last_a_close:.2f} <= {buffered_sl:.2f}, raw SL={sl:.2f}). Evicting from {pool_key}.")
                                pattern_funnel.evict_item("nifty50", item)
                            else:
                                logging.debug(f"[ANCHOR TF SL WICK HELD] {sym} ({item.get('contract')}) tick at/below buffered SL ({last_a_close:.2f} <= {buffered_sl:.2f}) on forming {TIMEFRAME_ANCHOR} bar. Not evicting.")
                        elif sl > 0 and buffered_sl < last_a_close <= sl:
                            logging.debug(f"[ANCHOR TF SL BUFFER HELD] {sym} ({item.get('contract')}) closed at {last_a_close:.2f} within SL buffer zone ({buffered_sl:.2f} to {sl:.2f}). Preserving setup.")
                        elif t1_80pct > 0 and last_a_close >= t1_80pct:
                            logging.info(f"[ANCHOR TF EVICT: 80% T1 HIT] {sym} ({item.get('contract')}) reached 80% T1 on {TIMEFRAME_ANCHOR} ({last_a_close:.2f} >= {t1_80pct:.2f}, T1={t1:.2f}, BM={bm:.2f}). Evicting from {pool_key}.")
                            pattern_funnel.evict_item("nifty50", item)
    except Exception as audit_err:
        logging.debug(f"Anchor TF funnel audit error: {audit_err}")

    if not temp_stored_trades:
        logging.info("No new trades meet criteria this cycle.")
    return temp_stored_trades

def _avg_target_rank(trade):
    """Composite priority score for candidate ranking (ISSUE-071).

    Priority hierarchy (strongest → weakest):
    1. Spot Confluence (mandatory for auto-entry, +2.0 bonus for ranking)
    2. VCP Compression (ATR ratio inversely scaled, squeeze bonus up to +1.5)
    3. Option VWAP discount (below VWAP = institutional accumulation, up to +0.5)
    4. Base R:R (capped at 5.0 to prevent distant-target inflation)
    5. VWAP overpay penalty (demote stretched contracts)

    Evidence (Sep 21 forensic analysis):
    - All 7 winners had spot_confluence=True, all 3 losers had False.
    - 3 most explosive runners (VOLTAS +90%, KPITTECH +63%, WAAREEENER +103%)
      had ATR ratio <= 0.67. All 3 losers had ATR = 1.00 (flat, no compression).
    - Old scoring: GODREJPROP (R:R=3.75, no confluence) = 3.75 outranked
      VOLTAS (R:R=3.66, confluence+VCP) = 3.66+0.40+0.30 = 4.36 in T1 pool.
    """
    targets = [t for t in [trade.get("t1"), trade.get("t2"), trade.get("t3")] if t]
    if not targets:
        return 0
    avg_target = sum(targets) / len(targets)
    entry_spot = float(trade.get("entry_spot", 0) or 0)
    current_sl = float(trade.get("current_sl", 0) or 0)
    risk = abs(entry_spot - current_sl)
    if risk <= 0:
        return 0
    # Cap base R:R at 5.0 to prevent far-target inflation
    base_rr = min(abs(avg_target - entry_spot) / risk, 5.0)

    # Spot Confluence: dominant ranking factor (+2.0)
    spot_bonus = 2.0 if trade.get("spot_confluence") else 0.0

    # VCP Compression: inversely scaled ATR bonus (coiled spring = explosive breakout)
    vcp_bonus = 0.0
    atr_r = float(trade.get("atr_ratio", 1.0) or 1.0)
    if trade.get("is_squeeze"):
        vcp_bonus = 1.5
    elif atr_r <= 0.50:
        vcp_bonus = 1.2
    elif atr_r <= 0.65:
        vcp_bonus = 0.8
    elif atr_r <= 0.80:
        vcp_bonus = 0.4

    # Safe Option VWAP discount: buying in the sweet spot (-5% to 0%) = institutional accumulation price
    vwap_discount = 0.0
    v_str = float(trade.get("vwap_stretch", 0.0) or 0.0)
    if -5.0 <= v_str < 0.0:
        vwap_discount = 0.5  # sweet spot discount: near VWAP support without breakdown

    # Option Contract VWAP Overpay / Breakdown penalty: demote stretched or broken down contracts
    vwap_penalty = 0.0
    v_st = str(trade.get("vwap_status", "")).upper()
    if v_st == "STRETCHED" or v_str > 15.0:
        vwap_penalty = 1.5  # overstretched FOMO chase
    elif v_st == "EXPANDED" or v_str > 8.0:
        vwap_penalty = 0.4
    elif v_str < -5.0:
        vwap_penalty = 1.5  # falling knife / IV breakdown penalty

    return max(0.0, base_rr + spot_bonus + vcp_bonus + vwap_discount - vwap_penalty)

def _parse_candidate_tier(cand, default=2):
    """
    Safely extract integer tier (1, 2, or 3) from candidate dict regardless of type
    (handles None, int, or string representations like 'TIER_1_GOLD', '🥇 T1', 'TIER_2_CORE', '🥈 T2').
    """
    if not isinstance(cand, dict):
        return default
    raw_tier = cand.get("tier")
    if raw_tier is not None:
        try:
            return int(raw_tier)
        except (ValueError, TypeError):
            pass
    t_str = str(raw_tier or cand.get("tier_badge") or cand.get("tier_label") or "").upper()
    if "1" in t_str or "GOLD" in t_str or "T1" in t_str:
        return 1
    elif "2" in t_str or "CORE" in t_str or "T2" in t_str:
        return 2
    elif "3" in t_str or "MOMENTUM" in t_str or "T3" in t_str:
        return 3
    return default


def execute_highest_rr_trade(kite, staged):
    """After a scan cycle, filter ONLY Tier 1 (🥇 T1 Gold) candidates, pick best by avg RR and execute (if live) at Benchmark limit price."""
    if not staged:
        return

    live_ok = LIVE_MARKET_DEPLOYMENT and live_execution_enabled(LIVE_EXECUTION_FLAG) and is_new_entry_allowed(live_execution_active=True, is_option=True)

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

    # Prioritized combined candidate pool: Tier 1 Gold evaluated first; if all T1 candidates
    # fail pre-order gates or sizing, immediately evaluate Tier 2 Core candidates in the exact same cycle.
    t1_sorted = sorted(t1_candidates, key=_avg_target_rank, reverse=True)
    t2_sorted = sorted(t2_candidates, key=_avg_target_rank, reverse=True)
    sorted_pool = t1_sorted + t2_sorted

    if not sorted_pool:
        if live_ok:
            logging.info("Auto-execution skipped: No 🥇 Tier 1 (Gold) or 🥈 Tier 2 (Core) candidates found in current cycle.")
        return
    cfg_eng = load_program_config_for_engine("nifty50")
    exec_mode = str(cfg_eng.get("execution_mode", "AUTO")).upper()
    use_spread = (exec_mode in ["DEBIT_SPREAD", "SPREAD_ONLY"]) or (exec_mode == "AUTO" and TIMEFRAME_ENTRY in ["15minute", "30minute", "60minute", "day"])

    for best in sorted_pool:
        try:
            sym = best["symbol"]
            side = best.get("side", "CE")
            strike = best.get("strike", "")
            pattern_name = best.get("pattern", "")
            key = f"{sym}|{pattern_name}|{side}|{strike}"
            if trade_db.is_pattern_executed("nifty50", key):
                logging.info(f"Candidate {key} already executed; evaluating next candidate in pool")
                continue

            with position_lock:
                if sym in ACTIVE_POSITIONS:
                    logging.info(f"{sym} already active in ACTIVE_POSITIONS; evaluating next candidate in pool")
                    continue
                if trade_db.is_symbol_active(sym, "nifty50"):
                    logging.info(f"[DUPLICATE_GUARD] {sym} already active in trade_db; evaluating next candidate in pool")
                    continue

            # Gate 1: Mandatory Spot Confluence Gate (ISSUE-071)
            # Auto-execution requires verified spot directional backing (100% win/loss separation).
            # If not confirmed, skip auto-entry while leaving setup visible on Scans Tab for manual review.
            if not best.get("spot_confluence"):
                logging.info(f"[SPOT_CONFLUENCE_GATE] Auto-execution blocked for {sym} ({best.get('contract') or sym}): "
                             f"spot_confluence={best.get('spot_confluence')} (type={best.get('spot_confluence_type', 'NONE')}); "
                             f"setup visible on Scans Tab for manual inspection; evaluating next candidate")
                continue

            # Strict Opposing Regime Guard (ISSUE-080)
            spot_anc = str(best.get("spot_anchor_name") or "")
            if side == "PE" and spot_anc == "BULL_SPOT_REGIME_TRAP":
                logging.info(f"[REGIME_TRAP_GATE] Auto-execution blocked for {sym} ({best.get('contract')}): Spot is trapped in Bullish Golden Cross above VWAP.")
                continue
            if side == "CE" and spot_anc == "BEAR_SPOT_REGIME_TRAP":
                logging.info(f"[REGIME_TRAP_GATE] Auto-execution blocked for {sym} ({best.get('contract')}): Spot is trapped in Bearish Death Cross below VWAP.")
                continue

            cp = best["entry_spot"]
            avg_rr = best.get("rr", 0)
            strike_step = best.get("strike_step", 50)
            cap_val = float(cfg_eng.get("capital") or 100000.0)
            target_strike = strike if strike else int(round(cp / strike_step) * strike_step)
            opt_type = "CE" if side == "CE" else "PE"

            spread_info = None
            contract = None
            option_token = None
            if use_spread:
                try:
                    try:
                        from common.position_monitor import _get_nfo_cache
                        from common.resolve import resolve_option_spread
                    except ModuleNotFoundError:
                        from position_monitor import _get_nfo_cache
                        from resolve import resolve_option_spread
                    nfo_df = _get_nfo_cache()
                    cand_side = str(best.get("side", "CE")).upper()
                    cand_dir = "BEAR" if cand_side == "PE" else "BULL"
                    # Pass real underlying spot & spot_t1 into resolve_option_spread()
                    real_spot = float(best.get("spot_entry") or 0.0)
                    if real_spot <= 0 and kite:
                        try:
                            reg_entry = STOCK_REGISTRY.get(sym, {})
                            spot_ts = reg_entry.get("tradingsymbol", sym)
                            q_spot = safe_kite_call(kite.quote, [f"NSE:{spot_ts}"])
                            real_spot = float(q_spot.get(f"NSE:{spot_ts}", {}).get("last_price", 0.0))
                        except Exception as q_err:
                            logging.debug(f"Underlying spot quote error for {sym}: {q_err}")
                    if real_spot <= 0:
                        real_spot = float(best.get("strike") or cp)

                    real_spot_t1 = best.get("spot_t1")
                    if not real_spot_t1 or float(real_spot_t1) <= 0:
                        real_spot_t1 = None
                    else:
                        real_spot_t1 = float(real_spot_t1)

                    spread_info = resolve_option_spread(
                        nfo_instruments=nfo_df,
                        base_symbol=sym,
                        spot_price=real_spot,
                        step_size=strike_step,
                        direction=cand_dir,
                        target_price=real_spot_t1,
                        side=cand_side
                    )
                    if spread_info:
                        # Pre-flight check: Verify short leg has buy liquidity before accepting spread
                        leg2_c = spread_info["leg2"]["contract"]
                        if live_ok and kite:
                            try:
                                q_l2 = safe_kite_call(kite.quote, [f"NFO:{leg2_c}"])
                                l2_bid = float(q_l2.get(f"NFO:{leg2_c}", {}).get("depth", {}).get("buy", [{}])[0].get("price", 0.0) or q_l2.get(f"NFO:{leg2_c}", {}).get("last_price", 0.0))
                                if l2_bid <= 0:
                                    logging.warning(f"[SPREAD_LIQUIDITY_GATE] Short leg {leg2_c} has zero buy liquidity (bid={l2_bid}). Falling back to naked contract for {sym}.")
                                    spread_info = None
                            except Exception as l2_check_err:
                                logging.debug(f"Leg 2 liquidity check error for {leg2_c}: {l2_check_err}")
                        if spread_info:
                            contract = spread_info["leg1"]["contract"]
                            option_token = spread_info["leg1"]["token"]
                            target_strike = spread_info["leg1"]["strike"]
                            logging.info(f"[DEBIT SPREAD RESOLVED] {sym}: Leg 1 (Long)={contract} @ {target_strike} | Leg 2 (Short)={spread_info['leg2']['contract']} @ {spread_info['leg2']['strike']}")
                except Exception as spread_err:
                    logging.warning(f"Spread resolution fallback to naked for {sym}: {spread_err}")

            if not contract:
                contract = resolve_option_contract(sym, cp, strike_step, opt_type, target_strike)
                if not contract:
                    logging.error(f"Could not resolve option for {sym}; skipping candidate")
                    continue
                option_token = _resolve_option_token(contract)

            lot_sz = int(best.get("lot_size") or (get_option_lot_size(contract) if contract else None) or STOCK_REGISTRY.get(sym, {}).get("lot_size", 1) or 1)
            allow_conviction = bool(cfg_eng.get("allow_single_lot_conviction", True))
            max_single_risk = float(cfg_eng.get("max_single_lot_risk_pct", 5.0))
            c_tier = _parse_candidate_tier(best, default=1)
            pos_size = int(best.get("position_size") or calculate_position_size(
                spot_price=cp,
                stop_loss=best.get("current_sl", 0.0),
                capital=cap_val,
                risk_percent=float(cfg_eng.get("MAX_RISK_PERCENT") or 1.0),
                lot_size=lot_sz,
                is_option=True,
                tier=c_tier,
                allow_zero=True,
                allow_single_lot_conviction=allow_conviction,
                max_single_lot_risk_pct=max_single_risk
            ))

            if pos_size <= 0:
                logging.warning(f"[RISK_BUDGET_EXCEEDED] Trade rejected for {sym} ({contract}): Position size is 0 lots (Risk per lot exceeds capital risk budget).")
                continue

            contract_quote_val = None
            if live_ok and contract and kite:
                try:
                    q_quote = safe_kite_call(kite.quote, [f"NFO:{contract}"])
                    c_ltp = float(q_quote.get(f"NFO:{contract}", {}).get("last_price", 0.0))
                    if c_ltp > 0:
                        contract_quote_val = c_ltp
                except Exception:
                    pass

            benchmark_val = float(contract_quote_val or best.get("benchmark") or cp)
            limit_price = round(benchmark_val * 1.005, 1) if benchmark_val > 0 else round(cp * 1.005, 1)

            if live_ok:
                from vix_guard import evaluate_vix_regime
                conf_type = str(best.get("spot_confluence_type") or "").upper()
                is_vwap_conf = ("VWAP_REJECT" in conf_type) or ("VWAP_RECLAIM" in conf_type)
                rvol_val = float(best.get("rvol") or best.get("rvol_abs") or best.get("rvol_projected") or 0.0)
                has_opt_rvol = bool(best.get("opt_rvol_badge") and "NORMAL" not in str(best.get("opt_rvol_badge")))
                trend_momentum_ok = is_vwap_conf and (rvol_val >= 1.5 or has_opt_rvol) and bool(best.get("spot_ema_trend", True))

                vix_ok, vix_msg, _ = evaluate_vix_regime(
                    kite,
                    tier_val=c_tier,
                    is_debit_spread=bool(spread_info),
                    has_momentum_override=trend_momentum_ok
                )
                if not vix_ok:
                    logging.info(f"[VIX_REGIME_GATE] Auto-execution skipped for {sym} ({contract}): {vix_msg}; checking next candidate")
                    try:
                        from watchlist_monitor import add_watchlist_item
                        add_watchlist_item(
                            contract=contract,
                            base_symbol=sym,
                            entry_price=limit_price,
                            lot_size=lot_sz,
                            tag="MISSED_OPPORTUNITY",
                            note=f"Skipped by {vix_msg} (R:R={best.get('rr', 0.0):.2f}, Tier={c_tier})"
                        )
                    except Exception as w_err:
                        logging.debug(f"[WATCHLIST] Missed opportunity log error: {w_err}")
                    continue

                from portfolio_risk import check_portfolio_risk_caps
                cap_val = float(cfg_eng.get("capital") or 100000.0)
                p_ok, p_msg, _ = check_portfolio_risk_caps(
                    engine="nifty50",
                    symbol=sym,
                    candidate_tier=c_tier,
                    capital=cap_val,
                    live_positions=ACTIVE_POSITIONS,
                    kite=kite
                )
                if not p_ok:
                    # Dynamic Slot Swap Gate (ISSUE-079):
                    # If blocked by MAX_CONCURRENT_POSITIONS_REACHED and candidate is pristine Tier 1 Gold (R:R >= 3.0),
                    # check if a stale/flat incumbent position can be swapped out to capture this high-conviction runner.
                    cand_rr_val = float(best.get("rr") or 0.0)
                    if "MAX_CONCURRENT_POSITIONS_REACHED" in str(p_msg) and c_tier <= 1 and cand_rr_val >= 3.0:
                        from portfolio_risk import find_weakest_swappable_position
                        with position_lock:
                            pos_snapshot = dict(ACTIVE_POSITIONS)
                        swappable = find_weakest_swappable_position(pos_snapshot, candidate_rr=cand_rr_val, kite=kite)
                        if swappable:
                            swap_sym = swappable["symbol"]
                            logging.info(f"[DYNAMIC_SLOT_SWAP] High-conviction Tier 1 Gold setup {sym} (RR={cand_rr_val:.2f} >= 3.0) triggered Dynamic Slot Swap for stale/flat position {swap_sym} ({swappable['reason']}).")
                            try:
                                from position_monitor import close_position
                                with position_lock:
                                    pos_to_close = ACTIVE_POSITIONS.get(swap_sym)
                                if pos_to_close:
                                    res_exit = close_position(kite, pos_to_close, live_market=True)
                                    logging.info(f"[DYNAMIC_SLOT_SWAP EXIT] Exited {swap_sym}: {res_exit}")
                                    with position_lock:
                                        ACTIVE_POSITIONS.pop(swap_sym, None)
                                    save_state()
                                    trade_id_exit = pos_to_close.get("trade_id")
                                    if trade_id_exit:
                                        trade_db.update_trade_status(trade_id_exit, "COMPLETED", exit_reason="DYNAMIC_SLOT_SWAP")
                                    # Re-evaluate portfolio risk cap
                                    p_ok, p_msg, _ = check_portfolio_risk_caps(
                                        engine="nifty50",
                                        symbol=sym,
                                        candidate_tier=c_tier,
                                        capital=cap_val,
                                        live_positions=ACTIVE_POSITIONS,
                                        kite=kite
                                    )
                            except Exception as swap_err:
                                logging.error(f"[DYNAMIC_SLOT_SWAP ERROR] Failed to execute swap for {swap_sym}: {swap_err}")

                    if not p_ok:
                        logging.info(f"[PORTFOLIO_RISK_CAP] Auto-execution skipped for {sym} ({contract}): {p_msg}; checking next candidate")
                        try:
                            from watchlist_monitor import add_watchlist_item
                            add_watchlist_item(
                                contract=contract,
                                base_symbol=sym,
                                entry_price=limit_price,
                                lot_size=lot_sz,
                                tag="MISSED_OPPORTUNITY",
                                note=f"Skipped by {p_msg} (R:R={best.get('rr', 0.0):.2f}, Tier={c_tier})"
                            )
                        except Exception as w_err:
                            logging.debug(f"[WATCHLIST] Missed opportunity log error: {w_err}")
                        continue

                # Gate 4: Premium Floor Gate on Low-DTE (ISSUE-071)
                # Avoid theta bleed and wide spread slippage on cheap lottery contracts (LTP/Benchmark < 5.0 when DTE <= 5)
                dte_val = best.get("dte")
                if dte_val is None and contract:
                    try:
                        from position_monitor import get_contract_days_to_expiry
                        dte_val = get_contract_days_to_expiry(contract)
                    except Exception as dte_err:
                        logging.debug(f"DTE check fallback for {contract}: {dte_err}")

                if dte_val is not None and dte_val <= 5 and benchmark_val < 5.0:
                    logging.warning(f"[PREMIUM_FLOOR_GATE] Auto-execution skipped for {sym} ({contract}): "
                                    f"Benchmark premium ₹{benchmark_val:.2f} < ₹5.00 floor with DTE={dte_val} <= 5 (lottery ticket risk); checking next candidate")
                    log_to_journal(sym, best.get("pattern", ""), TIMEFRAME_ENTRY, "SKIP_PREMIUM_FLOOR", "REJECTED",
                                   f"Premium ₹{benchmark_val:.2f} < ₹5.00 floor on DTE {dte_val}", entry=limit_price, sl=best.get("current_sl", 0.0), target=best.get("t1"),
                                   event_time=best.get("entry_time"))
                    continue

                # Gate 3: Safe Option Value Corridor (-5% to +15% VWAP) (ISSUE-071)
                # Trap A: Overstretched FOMO Chase (> +15% or > +2sigma) - wait for pullback/retest
                v_st = str(best.get("vwap_status", "")).upper()
                v_str = float(best.get("vwap_stretch", 0.0) or 0.0)
                if v_st == "STRETCHED" or v_str > 15.0:
                    logging.warning(f"[OPTION_VALUE_GUARD] Auto-execution skipped for {sym} ({contract}): "
                                    f"Option is overstretched ({v_str:.1f}% above VWAP, status={v_st}); wait for pullback/retest")
                    log_to_journal(sym, best.get("pattern", ""), TIMEFRAME_ENTRY, "SKIP_OVERSTRETCHED_VWAP", "REJECTED",
                                   f"Option stretched {v_str:.1f}% above VWAP", entry=limit_price, sl=best.get("current_sl", 0.0), target=best.get("t1"),
                                   event_time=best.get("entry_time"))
                    continue

                # Trap B: Falling Knife Breakdown (< -5.0% below Option VWAP)
                # Avoid buying rotting assets suffering from IV crush or delta bleed
                if v_str < -5.0:
                    logging.warning(f"[FALLING_KNIFE_GUARD] Auto-execution skipped for {sym} ({contract}): "
                                    f"Option is broken down ({v_str:.1f}% below VWAP); skipping decaying asset")
                    log_to_journal(sym, best.get("pattern", ""), TIMEFRAME_ENTRY, "SKIP_FALLING_KNIFE_VWAP", "REJECTED",
                                   f"Option broken down {v_str:.1f}% below VWAP", entry=limit_price, sl=best.get("current_sl", 0.0), target=best.get("t1"),
                                   event_time=best.get("entry_time"))
                    continue

                from liquidity_guard import check_bid_ask_spread_liquidity
                cfg_liq = cfg_eng.get("liquidity_gate", {})
                base_max_spread = float(cfg_liq.get("max_spread_pct", 0.02))
                cand_tier = c_tier
                is_high_conviction = (
                    cand_tier in [1, 2]
                    or "T1" in str(best.get("tier_badge", ""))
                    or "T2" in str(best.get("tier_badge", ""))
                    or "GOLD" in str(best.get("tier_label", ""))
                    or "CORE" in str(best.get("tier_label", ""))
                )
                if is_high_conviction:
                    # Adaptive Spread Tolerance for High-Conviction Setups:
                    # High-conviction setups utilize smart pegged limit order routing (passive mid-price peg).
                    # Allow up to 2.5% - 3.0% spread tolerance (default 0.03 / 3.0%) so leaders like TITAN (2.06%)
                    # are not starved over narrow basis points.
                    max_spread = float(cfg_liq.get("max_spread_pct_high_conviction", max(base_max_spread, 0.03)))
                else:
                    max_spread = base_max_spread

                liq_ok, spread_val, liq_msg, depth_details = check_bid_ask_spread_liquidity(
                    kite=kite,
                    exchange=kite.EXCHANGE_NFO,
                    contract=contract,
                    max_spread_pct=max_spread
                )
                if not liq_ok:
                    now_epoch = time.time()
                    if now_epoch - _LAST_LIQ_WARN.get(contract, 0) >= 60.0:
                        _LAST_LIQ_WARN[contract] = now_epoch
                        logging.warning(f"[LIQUIDITY_GATE] Auto-execution rejected for {sym} ({contract}): {liq_msg}; holding candidate in radar")
                        log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY, "SKIP_ILLIQUID_SPREAD", "REJECTED",
                                       liq_msg, entry=limit_price, sl=best["current_sl"], target=best["t1"],
                                       event_time=best.get("entry_time"))
                    else:
                        logging.debug(f"[LIQUIDITY_GATE] Re-evaluating {sym} ({contract}): spread still wide ({spread_val * 100:.2f}%); holding in radar")
                    continue

                # Stage 1: Smart Pegged Limit Order Routing (Passive Mid-Price Peg)
                # If spread >= 0.8%, peg limit order at Mid price between Best Bid and Best Ask to capture spread savings
                best_bid = float(depth_details.get("best_bid", 0.0))
                best_ask = float(depth_details.get("best_ask", 0.0))
                if best_bid > 0 and best_ask > 0 and depth_details.get("spread_pct", 0.0) >= 0.8:
                    mid_price = round((best_bid + best_ask) / 2.0, 1)
                    if mid_price > 0 and mid_price < limit_price:
                        logging.info(f"[PEGGED_LIMIT_ROUTING] {contract}: Pegging limit at Mid-Price {mid_price:.2f} (Bid={best_bid:.2f}, Ask={best_ask:.2f}, Spread={depth_details.get('spread_pct'):.2f}%) instead of marketable {limit_price:.2f}")
                        limit_price = mid_price

                # Kite Limit Price Protection (LPP) Safety Clamp:
                from position_monitor import clamp_lpp_buy_price
                clamped_limit = clamp_lpp_buy_price(limit_price, best_ask if best_ask > 0 else (best_bid if best_bid > 0 else cp))
                if clamped_limit < limit_price:
                    logging.info(f"[LPP_CLAMP] Clamped limit buy price for {contract} from {limit_price:.2f} to {clamped_limit:.2f} (LTP/Ask={best_ask or cp:.2f})")
                    limit_price = clamped_limit

                with position_lock:
                    if sym in ACTIVE_POSITIONS:
                        logging.info(f"{sym} already active; checking next candidate")
                        continue
                    pos = {
                        "contract": contract, "option_token": option_token,
                        "entry_spot": limit_price, "current_sl": best.get("current_sl", 0.0),
                        "t1": best.get("t1"), "t2": best.get("t2"), "t3": best.get("t3"),
                        "trailing_stage": 0, "lot_size": lot_sz, "position_size": pos_size,
                        "pattern": best["pattern"], "timeframe": TIMEFRAME_ENTRY,
                        "side": opt_type, "strike": target_strike,
                        "benchmark": benchmark_val, "anchor_floor": best.get("anchor_floor"),
                        "direction": best.get("direction", "BULL"),
                        "spot_token": best.get("spot_token"),
                        "spot_sl": best.get("spot_sl"),
                        "entry_time": dt.now().isoformat(),
                        "position_type": "option_spread" if spread_info else "option",
                        "tier": c_tier,
                        "tier_label": best.get("tier_label") or ("TIER_1_GOLD" if c_tier == 1 else "TIER_2_CORE"),
                        "tier_badge": best.get("tier_badge") or ("🥇 T1" if c_tier == 1 else "🥈 T2"),
                        "mfe_pct": 0.0,
                        "mae_pct": 0.0,
                        "trade_dna": {
                            "spot_vwap_dist_pct": round(((float(best.get("spot_ltp", 0.0) or 0.0) - float(best.get("spot_vwap", 0.0) or 0.0)) / float(best.get("spot_vwap", 1.0) or 1.0)) * 100, 2) if float(best.get("spot_vwap", 0.0) or 0.0) > 0 else 0.0,
                            "spot_rvol": round(float(best.get("rvol") or best.get("spot_rvol") or 1.0), 2),
                            "spot_ema_trend": "BULL" if best.get("is_bull", True) else "BEAR",
                            "spot_atr_ratio": round(float(best.get("spot_atr_ratio", 1.0) or 1.0), 2),
                            "opt_vcp_ratio": round(float(best.get("opt_atr_ratio", 1.0) or 1.0), 2),
                            "opt_spread_pct": round(float(best.get("spread_pct", 0.0) or 0.0), 2),
                            "opt_vwap_sigma": round(float(best.get("opt_vwap_sigma", 0.0) or 0.0), 2)
                        }
                    }
                    if spread_info:
                        pos["spread_type"] = spread_info["spread_type"]
                        pos["leg2_contract"] = spread_info["leg2"]["contract"]
                        pos["leg2_token"] = spread_info["leg2"]["token"]
                        pos["leg2_strike"] = spread_info["leg2"]["strike"]
                        pos["leg2_qty"] = lot_sz * pos_size

                    if trade_db.is_contract_active(contract, "nifty50"):
                        logging.info(f"[DUPLICATE_GUARD] Contract {contract} already active in trade_db; skipping candidate auto-execution")
                        continue

                    pos["trade_id"], _created = trade_db.create_trade("nifty50", sym, {k: v for k, v in pos.items() if k != "trade_id"})
                    if not _created:
                        logging.info(f"[DUPLICATE_GUARD] Active trade for {sym} ({contract}) already exists in trade_db (ID: {pos['trade_id']}); skipping candidate auto-execution")
                        continue
                    ACTIVE_POSITIONS[sym] = pos
                save_state()

            trade_db.record_executed_pattern("nifty50", key, {"contract": contract, "entry": limit_price})
            pattern_funnel.evict_item("nifty50", key)
            if contract:
                pattern_funnel.evict_item("nifty50", contract)
            clear_executed_exit(contract)
            clear_executed_exit(sym)

            if live_ok:
                from position_monitor import is_contract_held_on_broker
                is_held, held_qty = is_contract_held_on_broker(kite, contract)
                if is_held:
                    logging.info(f"[DUPLICATE_GUARD] Contract {contract} already held on broker (Qty: {held_qty}); skipping candidate auto-order placement")
                    continue
                try:
                    qty = lot_sz * pos_size
                    if qty <= 0:
                        logging.warning(f"[ZERO_QTY_GUARD] Skipping order placement for {sym} ({contract}): computed quantity {qty} <= 0")
                        with position_lock:
                            ACTIVE_POSITIONS.pop(sym, None)
                        if pos.get("trade_id"):
                            trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
                        save_state()
                        continue
                    qty_slices = slice_quantity_for_freeze(contract, qty)
                    placed_oids = []
                    for s_qty in qty_slices:
                        s_oid = kite.place_order(
                            variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                            exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_BUY,
                            quantity=s_qty, order_type=kite.ORDER_TYPE_LIMIT, price=limit_price,
                            product=kite.PRODUCT_NRML
                        )
                        placed_oids.append(str(s_oid))
                    oid = placed_oids[0]
                    c_badge = best.get("tier_badge") or ("🥇 T1" if c_tier == 1 else "🥈 T2")
                    c_label = best.get("tier_label") or ("TIER_1_GOLD" if c_tier == 1 else "TIER_2_CORE")
                    logging.info(f"{c_badge} AUTO-EXECUTE BUY LIMIT: {contract} TotalQty={qty} @ Benchmark Limit Price={limit_price} (Orders: {placed_oids})")
                    with position_lock:
                        if sym in ACTIVE_POSITIONS:
                            ACTIVE_POSITIONS[sym]["order_id"] = str(oid)
                            ACTIVE_POSITIONS[sym]["order_ids"] = placed_oids
                            ACTIVE_POSITIONS[sym]["order_status"] = "OPEN"
                    if pos.get("trade_id"):
                        trade_db.update_trade(pos["trade_id"], {"order_id": str(oid), "order_status": "OPEN"})
                    save_state()

                    if spread_info:
                        try:
                            leg2_c = spread_info["leg2"]["contract"]
                            leg2_q_key = f"NFO:{leg2_c}"
                            leg2_q = safe_kite_call(kite.quote, [leg2_q_key])
                            leg2_depth = leg2_q.get(leg2_q_key, {}).get("depth", {}).get("buy", [])
                            leg2_bid = float(leg2_depth[0]["price"]) if (leg2_depth and len(leg2_depth) > 0 and leg2_depth[0].get("price", 0) > 0) else float(leg2_q.get(leg2_q_key, {}).get("last_price", 0.0))
                            # Zerodha Kite strictly blocks MARKET orders for Stock Options. Always use LIMIT pegged at best bid (min 0.05).
                            leg2_limit = round(max(0.05, leg2_bid * 0.995), 2) if leg2_bid > 0 else 0.05
                            leg2_slices = slice_quantity_for_freeze(leg2_c, qty)
                            leg2_placed = []
                            for l2_s_qty in leg2_slices:
                                oid2 = kite.place_order(
                                    variety=kite.VARIETY_REGULAR, tradingsymbol=leg2_c,
                                    exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_SELL,
                                    quantity=l2_s_qty, order_type=kite.ORDER_TYPE_LIMIT, price=leg2_limit,
                                    product=kite.PRODUCT_NRML
                                )
                                leg2_placed.append(str(oid2))
                            pos["leg2_order_id"] = leg2_placed[0]
                            pos["leg2_order_ids"] = leg2_placed
                            with position_lock:
                                if sym in ACTIVE_POSITIONS:
                                    ACTIVE_POSITIONS[sym]["leg2_order_id"] = leg2_placed[0]
                                    ACTIVE_POSITIONS[sym]["leg2_order_ids"] = leg2_placed
                            if pos.get("trade_id"):
                                trade_db.update_trade(pos["trade_id"], {"leg2_order_id": leg2_placed[0], "leg2_order_ids": leg2_placed})
                            logging.info(f"[DEBIT SPREAD SHORT LEG] Placed {leg2_c} TotalQty={qty} @ Limit={leg2_limit} (Orders: {leg2_placed})")
                        except Exception as leg2_err:
                            logging.error(f"[DEBIT SPREAD SHORT LEG FAILED] {spread_info['leg2']['contract']}: {leg2_err}")
                            # ROLLBACK GUARD: Cancel Leg 1 order slices to prevent unhedged naked exposure
                            for o_to_cancel in placed_oids:
                                try:
                                    kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=o_to_cancel)
                                    logging.warning(f"[DEBIT SPREAD ROLLBACK] Cancelled Leg 1 order {o_to_cancel} because Leg 2 failed: {leg2_err}")
                                except Exception as c_err:
                                    logging.error(f"[DEBIT SPREAD ROLLBACK ERROR] Could not cancel Leg 1 order {o_to_cancel}: {c_err}")

                            # Check if Leg 1 was already filled/held on broker
                            from position_monitor import is_contract_held_on_broker
                            is_held, held_qty = is_contract_held_on_broker(kite, contract)
                            if is_held and held_qty > 0:
                                logging.warning(f"[DEBIT SPREAD EMERGENCY UNWIND] Leg 1 {contract} is held ({held_qty} qty) after Leg 2 failure. Executing emergency sell...")
                                try:
                                    q_unw = safe_kite_call(kite.quote, [f"NFO:{contract}"])
                                    u_bid = float(q_unw.get(f"NFO:{contract}", {}).get("depth", {}).get("buy", [{}])[0].get("price", 0.0) or q_unw.get(f"NFO:{contract}", {}).get("last_price", 0.0))
                                    u_limit = round(max(0.05, u_bid * 0.98), 2) if u_bid > 0 else limit_price
                                    kite.place_order(
                                        variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                                        exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_SELL,
                                        quantity=held_qty, order_type=kite.ORDER_TYPE_LIMIT, price=u_limit,
                                        product=kite.PRODUCT_NRML
                                    )
                                    logging.info(f"[DEBIT SPREAD EMERGENCY UNWIND SUCCESS] Sold {contract} Qty={held_qty} @ {u_limit}")
                                except Exception as unw_err:
                                    logging.critical(f"[DEBIT SPREAD EMERGENCY UNWIND FAILED] Failed emergency exit for {contract}: {unw_err}. Retaining in ACTIVE_POSITIONS for position monitor protection!")
                                    with position_lock:
                                        pos["position_type"] = "option"
                                        ACTIVE_POSITIONS[sym] = pos
                                    if pos.get("trade_id"):
                                        trade_db.update_trade(pos["trade_id"], {"status": "OPEN", "position_type": "option"})
                                    save_state()
                                    continue

                            with position_lock:
                                ACTIVE_POSITIONS.pop(sym, None)
                            if pos.get("trade_id"):
                                trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
                            save_state()
                            continue

                    log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY, "BUY", "SUCCESS",
                                   f"Order: {oid}, Qty: {qty}, {opt_type}@{target_strike} @ Benchmark Limit={limit_price} ({c_badge} {c_label})", entry=limit_price, sl=best["current_sl"], target=best["t1"], rr=avg_rr,
                                   event_time=best.get("entry_time"))
                except Exception as e:
                    for o_to_cancel in placed_oids:
                        try:
                            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=o_to_cancel)
                            logging.warning(f"[PARTIAL_SLICE_ROLLBACK] Cancelled placed slice {o_to_cancel} due to order failure: {e}")
                        except Exception as c_err:
                            logging.debug(f"Could not cancel slice {o_to_cancel}: {c_err}")
                    log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY, "BUY", "FAILED", str(e),
                                   entry=limit_price, sl=best["current_sl"], target=best["t1"],
                                   event_time=best.get("entry_time"))
                    with position_lock:
                        ACTIVE_POSITIONS.pop(sym, None)
                    if pos.get("trade_id"):
                        trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
                    save_state()
                    continue
            elif BACKTEST_DATE is not None:
                log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY, "BACKTEST_BEST", "SUCCESS",
                               f"Contract: {contract}, Size: {pos_size}, {opt_type}@{target_strike} @ Benchmark Limit={limit_price}", entry=limit_price, sl=best["current_sl"], target=best["t1"],
                               event_time=best.get("entry_time"))
                sim = simulate_trade_outcome(kite, best, BACKTEST_DATE)
                if sim["result"]:
                    log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY,
                                   sim["result"], "COMPLETED", sim["detail"],
                                   entry=limit_price, sl=best["current_sl"], target=best.get("t1",""), rr=avg_rr,
                                   event_time=sim.get("exit_time") or sim.get("entry_time"))
                    logging.info(f"[BACKTEST] Trade outcome: {sim['result']} | {sim['detail']} | P&L: {sim['pnl_pct']}%")
            else:
                log_to_journal(sym, best["pattern"], TIMEFRAME_ENTRY, "SCAN_READY", "SUCCESS",
                               f"Contract: {contract}, Size: {pos_size}, {opt_type}@{target_strike} | Manual entry pending @ Benchmark={limit_price}", entry=limit_price, sl=best["current_sl"], target=best["t1"],
                               event_time=best.get("entry_time"))
                logging.info(f"SCAN_READY best trade: {sym} {contract} | Entry Limit (Benchmark): {limit_price} | SL: {best['current_sl']} | T1: {best.get('t1','')}")

            targets = [t for t in [best.get("t1"), best.get("t2"), best.get("t3")] if t]
            avg_target = sum(targets) / len(targets) if targets else 0
            logging.info(f"EXECUTED cycle trade: {sym} | {best['pattern']} | avg-target={avg_target:.2f} | avg-RR={avg_rr}")
            break
        except Exception as cand_err:
            logging.error(f"[EXECUTE_CANDIDATE_FAILED] Error processing {best.get('symbol', 'UNKNOWN')}: {cand_err}", exc_info=True)
            continue


def run_fast_radar_check(kite):
    """
    Fast Surveillance Radar:
    Monitors Category A+ (Imminent Breakout) and Category A (Ready) setups in real-time.
    If latest price crosses or closes above Benchmark D trigger, immediately executes!
    """
    global _LAST_FUNNEL_CLEANUP_DATE
    now_ist = get_ist_now(naive=True)
    today_str = now_ist.strftime("%Y-%m-%d")
    t_str = now_ist.strftime("%H:%M")

    # Automated Morning Funnel Reset (Fix 4): Purge prior-day incubation setups once time >= "08:00" IST
    # Runs before is_new_entry_allowed() gate so radar is clean prior to 09:16 market open
    if _LAST_FUNNEL_CLEANUP_DATE != today_str and t_str >= "08:00":
        try:
            pattern_funnel.purge_stale_prior_day_setups("nifty50", today_str=today_str, purge_scan_display=True)
            _LAST_FUNNEL_CLEANUP_DATE = today_str
            logging.info(f"[RADAR MORNING PURGE] Successfully purged prior-day incubation setups at {t_str} IST for {today_str}")
        except Exception as p_err:
            logging.warning(f"Radar morning funnel purge error: {p_err}")

    if not is_new_entry_allowed(live_execution_active=True, is_option=True):
        return []

    _RADAR_ACTIVE.set()
    try:
        funnel_summary = pattern_funnel.get_funnel_summary("nifty50")
        radar_pool = list(funnel_summary.get("category_a_plus", []) + funnel_summary.get("category_a", []))

        # Ingest unexecuted high-conviction candidates directly from the Scan Tab (SCAN_DISPLAY_FILE)
        if os.path.exists(SCAN_DISPLAY_FILE):
            try:
                with open(SCAN_DISPLAY_FILE, "r", encoding="utf-8") as f:
                    scan_disp = json.load(f)
                staged_tab = scan_disp.get("staged_trades", [])
                existing_keys = {
                    (x.get("symbol"), x.get("contract")): True for x in radar_pool
                }
                for st in staged_tab:
                    s_key = (st.get("symbol"), st.get("contract"))
                    if s_key not in existing_keys:
                        bm = float(st.get("benchmark") or 0.0)
                        sl = float(st.get("current_sl") or 0.0)
                        # Filter: valid benchmark & SL, and not marked as active holding
                        if bm > 0 and sl > 0 and st.get("staged_tag") != "ACTIVE_HOLDING":
                            radar_pool.append(st)
                            existing_keys[s_key] = True
            except Exception as disp_err:
                logging.debug(f"Radar Scan Tab ingestion error: {disp_err}")

        if not radar_pool:
            return []

        # Prioritize: Tier 1 Gold first, then highest R:R
        def _radar_priority(x):
            tier_val = _parse_candidate_tier(x, default=2)
            rr_val = float(x.get("rr", 0.0) or 0.0)
            return (-tier_val, rr_val)

        radar_pool.sort(key=_radar_priority, reverse=True)

        # ── Item 8: Radar Quote-First Polling ──
        # Query bulk kite.quote() for candidate LTPs first; only fetch historical candle
        # data when LTP is near benchmark (LTP >= Benchmark * 0.995), cutting scan cycle latency.
        radar_quotes = {}
        quote_instruments = []
        for itm in radar_pool:
            c_name = itm.get("contract")
            if c_name:
                c_str = str(c_name).upper()
                exch_prefix = "BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO"
                quote_instruments.append(f"{exch_prefix}:{c_name}")
            else:
                s_name = itm.get("symbol")
                if s_name:
                    quote_instruments.append(f"NSE:{s_name}")

        if quote_instruments and kite:
            for ch_start in range(0, len(quote_instruments), 100):
                ch = quote_instruments[ch_start : ch_start + 100]
                try:
                    q_res = safe_kite_call(kite.quote, ch, priority=True)
                    if q_res and isinstance(q_res, dict):
                        radar_quotes.update(q_res)
                except Exception as qe:
                    logging.debug(f"Radar bulk quote fetch error: {qe}")

        triggered = []
        for item in radar_pool:
            sym = item.get("symbol")
            with position_lock:
                if sym in ACTIVE_POSITIONS:
                    continue

            # Evaluate item setup date against today's date, evicting stale prior-day setups cleanly before Kite API calls
            item_date = pattern_funnel._get_item_date_str(item)
            if item_date and item_date < today_str:
                logging.info(f"[RADAR EVICT: STALE PRIOR-DAY ITEM] {sym} ({item.get('contract')}) setup date {item_date} is prior to {today_str}. Evicting cleanly.")
                pattern_funnel.evict_item("nifty50", item)
                continue

            c_name = item.get("contract")
            c_str = str(c_name).upper() if c_name else ""
            exch_prefix = "BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO"
            q_k = f"{exch_prefix}:{c_name}" if c_name else f"NSE:{sym}"
            q_info = radar_quotes.get(q_k, {})
            live_ltp = float(q_info.get("last_price") or 0.0)
            bm = float(item.get("benchmark") or 0.0)
            sl = float(item.get("current_sl") or 0.0)
            t1 = float(item.get("t1") or 0.0)

            # Quote-First Trigger Polling:
            # If live LTP is known from bulk quote and not near benchmark (LTP < Benchmark * 0.995),
            # skip expensive historical candle fetch!
            if live_ltp > 0 and bm > 0:
                t1_80pct = round(bm + 0.80 * (t1 - bm), 2) if (bm > 0 and t1 > bm) else round(t1 * 0.80, 2) if t1 > 0 else 0.0
                if t1_80pct > 0 and live_ltp >= t1_80pct:
                    logging.info(f"[RADAR EVICT: 80% T1 HIT VIA QUOTE] {sym} ({item.get('contract')}) live LTP {live_ltp:.2f} >= {t1_80pct:.2f}. Evicting setup.")
                    pattern_funnel.evict_item("nifty50", item)
                    continue

                if sl > 0 and live_ltp <= sl:
                    logging.debug(f"[RADAR FAST SKIP: SL BREACH VIA QUOTE] {sym} ({item.get('contract')}) live LTP {live_ltp:.2f} <= SL {sl:.2f}. Skipping candle fetch.")
                    continue

                min_trigger_pct = 0.980 if (item.get("trigger_type") == "POST_D_RETEST" or (sl > 0 and t1 > 0)) else 0.995
                if live_ltp < (bm * min_trigger_pct):
                    logging.debug(f"[RADAR QUOTE-FIRST GATE] {sym} ({item.get('contract')}): LTP {live_ltp:.2f} < Benchmark threshold ({bm * min_trigger_pct:.2f}). Skipping candle fetch.")
                    continue

            tok = item.get("option_token") or item.get("spot_token")
            if not tok:
                continue
            try:
                from timeframe_utils import fetch_and_resample_candles
                # High priority Kite API fetch — ensures fast radar is NEVER delayed by background macro scan
                df_latest = safe_kite_call(
                    fetch_and_resample_candles,
                    kite, tok,
                    (dt.now() - timedelta(days=2)).strftime('%Y-%m-%d'),
                    dt.now().strftime('%Y-%m-%d'),
                    item.get("timeframe", TIMEFRAME_ENTRY),
                    priority=True
                )
                if df_latest is not None and not df_latest.empty:
                    last_candle = df_latest.iloc[-1]
                    candle_date_str = str(last_candle.get('date', ''))
                    c_dt = get_ist_now(naive=True)
                    try:
                        parsed_dt = pd.to_datetime(candle_date_str)
                        if hasattr(parsed_dt, 'tz') and parsed_dt.tz is not None:
                            parsed_dt = parsed_dt.tz_convert('Asia/Kolkata').tz_localize(None)
                        c_dt = parsed_dt
                    except Exception:
                        pass
                    c_now = float(last_candle['close'])
                    bm = float(item.get("benchmark") or 0.0)
                    sl = float(item.get("current_sl") or 0.0)
                    t1 = float(item.get("t1") or 0.0)

                    # Timeframe Maturity Guard (Calculated upfront for candle-close evaluation)
                    from timeframe_utils import is_live_candle_near_close, get_tf_minutes
                    item_tf = item.get("timeframe", TIMEFRAME_ENTRY)
                    tf_mins = get_tf_minutes(item_tf)
                    now_ist = get_ist_now(naive=True)
                    is_closed_bar = (now_ist - c_dt).total_seconds() >= (tf_mins * 60.0)
                    is_80pct_mature = is_live_candle_near_close(candle_date_str, item_tf, completion_pct=0.80)

                    # Historical candle from prior session check
                    if c_dt.date() < get_ist_now(naive=True).date():
                        # If prior session setup already hit T1, ran past BM, or breached SL, evict it now
                        if (t1 > 0 and c_now >= (t1 * 0.995)) or (bm > 0 and c_now >= bm) or (sl > 0 and c_now <= sl):
                            logging.info(f"[RADAR EVICT: STALE PRIOR-DAY SETUP] {sym} ({item.get('contract')}) from {c_dt.date()} already reached level (Close={c_now:.2f}, BM={bm:.2f}, T1={t1:.2f}, SL={sl:.2f}). Evicting setup.")
                            pattern_funnel.evict_item("nifty50", item)
                        continue

                    # Surveillance Guard 1: SL Breach Check
                    # IMPORTANT: Eviction must strictly be on Anchor Timeframe (15m) close with buffer (handled in audit_funnel_anchor_closures).
                    # During fast radar surveillance (3m/5m), price below SL simply skips entry execution without evicting the setup from the funnel.
                    if sl > 0 and c_now <= sl:
                        logging.debug(f"[RADAR SL HELD: AWAITING ANCHOR TF CLOSE] {sym} ({item.get('contract')}) price at {c_now:.2f} <= SL {sl:.2f} on {item_tf}. Skipping entry; awaiting Anchor TF close for eviction.")
                        continue

                    # Hard Eviction Rule 2: 80% T1 achieved pre-entry (Do Not Chase)
                    t1_80pct = round(bm + 0.80 * (t1 - bm), 2) if (bm > 0 and t1 > bm) else round(t1 * 0.80, 2) if t1 > 0 else 0.0
                    if t1_80pct > 0 and c_now >= t1_80pct:
                        logging.info(f"[RADAR EVICT: 80% T1 HIT] {sym} ({item.get('contract')}) reached 80% of T1 target ({c_now:.2f} >= {t1_80pct:.2f}, T1={t1:.2f}, BM={bm:.2f}) before entry. Evicting setup.")
                        pattern_funnel.evict_item("nifty50", item)
                        continue

                    # Trigger 1: Breakout / 80% Early D Trigger
                    is_breakout = (bm > 0 and c_now >= bm)

                    # Trigger 2: Post-D Retest Entry (D formed, pre-T1, SL intact, retesting Benchmark zone +/- 2.5%)
                    is_retest = False
                    if bm > 0 and sl > 0 and t1 > 0:
                        retest_lower = bm * 0.980
                        retest_upper = bm * 1.025
                        if retest_lower <= c_now <= retest_upper and c_now < t1 and c_now > sl:
                            is_retest = True

                    if is_breakout or is_retest:
                        time_now_str = now_ist.strftime("%H:%M")

                        # For initial breakouts, require 80% bar maturity or bar close to avoid premature wicks
                        if is_breakout and not is_retest:
                            if not (is_80pct_mature or is_closed_bar):
                                logging.debug(f"[RADAR COILING] {sym} ({item.get('contract')}) at {c_now} >= Benchmark {bm}, awaiting 80% candle maturity (Minute >= {int(tf_mins*0.8)}).")
                                continue

                        # Check 2: Option VWAP Support & Overpay Guard
                        from swing_detection import calculate_option_vwap
                        vwap_info = calculate_option_vwap(df_latest)
                        opt_vwap = float(vwap_info.get("vwap") or 0.0)
                        stretch_pct = float(vwap_info.get("stretch_pct") or 0.0)

                        if opt_vwap > 0 and c_now < opt_vwap:
                            logging.debug(f"[RADAR VWAP GATE] {sym} ({item.get('contract')}) at {c_now}, but lacks VWAP support (LTP {c_now} < VWAP {opt_vwap}).")
                            continue

                        if stretch_pct > 25.0:
                            logging.info(f"[RADAR OVERPAY GUARD] {sym} ({item.get('contract')}) stretched {stretch_pct:.1f}% > 25% above VWAP ({opt_vwap}). Skipping entry.")
                            continue

                        # Check 3: Spot Institutional Relative Volume (RVOL) & Morning VWAP Confluence
                        spot_tok = item.get("spot_token")
                        if not spot_tok:
                            from registries import STOCK_REGISTRY
                            reg = STOCK_REGISTRY.get(sym)
                            if isinstance(reg, dict):
                                spot_tok = reg.get("token")
                        
                        if spot_tok:
                            try:
                                # Fetch spot quote to check Intraday VWAP & turnover
                                spot_quote = safe_kite_call(kite.quote, [f"NSE:{sym}"]) or {}
                                q_data = spot_quote.get(f"NSE:{sym}", {}) if isinstance(spot_quote, dict) else {}
                                spot_ltp = float(q_data.get("last_price") or 0.0)
                                spot_vwap = float(q_data.get("average_price") or 0.0)

                                # ── ALL-DAY SPOT VWAP & TREND CONFLUENCE GATE ──
                                side_val = str(item.get("side", "CE")).upper()
                                dir_val = str(item.get("direction", "BULL")).upper()
                                c_str = str(item.get("contract", "")).upper()
                                is_pe = (side_val == "PE" or dir_val == "BEAR" or c_str.endswith("PE"))

                                if spot_vwap > 0 and spot_ltp > 0:
                                    if not is_pe and spot_ltp < (spot_vwap * 0.997):
                                        logging.info(f"🛡️ [SPOT VWAP REJECT] {sym}: Spot {spot_ltp:.2f} < VWAP {spot_vwap:.2f} (CE) "
                                                     f"at {time_now_str}. Lacks institutional buying support. Holding candidate.")
                                        continue
                                    elif is_pe and spot_ltp > (spot_vwap * 1.003):
                                        logging.info(f"🛡️ [SPOT VWAP REJECT] {sym}: Spot {spot_ltp:.2f} > VWAP {spot_vwap:.2f} (PE) "
                                                     f"at {time_now_str}. Lacks institutional selling pressure. Holding candidate.")
                                        continue

                                # ── SPOT MOVING AVERAGE GOLDEN / DEATH CROSS CONFLUENCE ──
                                # Protect against buying PEs in a strong Bullish Golden Cross or CEs in a Bearish Death Cross
                                try:
                                    df_spot_30m = safe_kite_call(
                                        fetch_and_resample_candles,
                                        kite, spot_tok,
                                        (dt.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
                                        dt.now().strftime('%Y-%m-%d'),
                                        "30minute",
                                        priority=True
                                    )
                                    if df_spot_30m is not None and len(df_spot_30m) >= 44:
                                        s_closes = df_spot_30m['close']
                                        s_ema13 = float(s_closes.ewm(span=13, adjust=False).mean().iloc[-1])
                                        s_ema44 = float(s_closes.ewm(span=44, adjust=False).mean().iloc[-1])
                                        s_last = float(s_closes.iloc[-1])

                                        # Golden Cross: Spot > EMA13 > EMA44 -> STRICTLY BLOCK PE TRIGGERS!
                                        if is_pe and (s_last > s_ema13 > s_ema44):
                                            logging.info(f"🛡️ [SPOT GOLDEN CROSS REJECT] {sym}: Spot ({s_last:.2f}) > EMA13 ({s_ema13:.2f}) > EMA44 ({s_ema44:.2f}) is in strong Bullish Golden Cross. Blocking counter-trend PE trigger!")
                                            continue
                                        # Death Cross: Spot < EMA13 < EMA44 -> STRICTLY BLOCK CE TRIGGERS!
                                        elif (not is_pe) and (s_last < s_ema13 < s_ema44):
                                            logging.info(f"🛡️ [SPOT DEATH CROSS REJECT] {sym}: Spot ({s_last:.2f}) < EMA13 ({s_ema13:.2f}) < EMA44 ({s_ema44:.2f}) is in strong Bearish Death Cross. Blocking counter-trend CE trigger!")
                                            continue
                                except Exception as ma_err:
                                    logging.debug(f"Spot MA confluence error for {sym}: {ma_err}")

                                df_spot_rvol = safe_kite_call(
                                    fetch_and_resample_candles,
                                    kite, spot_tok,
                                    (dt.now() - timedelta(days=35)).strftime('%Y-%m-%d'),
                                    dt.now().strftime('%Y-%m-%d'),
                                    "day",
                                    priority=True
                                )
                                if df_spot_rvol is not None and len(df_spot_rvol) >= 5:
                                    from rvol_calculator import calculate_rvol
                                    rvol_spot = calculate_rvol(df_spot_rvol, tf_is_daily=True, current_time=now_ist)
                                    proj_rvol = float(rvol_spot.get("rvol_projected", 1.0) or 1.0)
                                    item["spot_rvol_badge"] = rvol_spot.get("badge")
                                    item["spot_rvol_projected"] = proj_rvol

                                    # Institutional Volume Surge (RVOL >= 2.0x with Spot VWAP alignment) -> Promote to T1 Gold!
                                    vwap_aligned = (spot_vwap == 0 or (spot_ltp <= spot_vwap if is_pe else spot_ltp >= spot_vwap))
                                    if proj_rvol >= 2.0 and vwap_aligned:
                                        item["tier"] = 1
                                        item["tier_label"] = f"🥇 T1 Gold (Inst Surge {proj_rvol:.1f}x)"
                                        item["tier_badge"] = "🥇 T1"
                                        item["inst_surge"] = True
                                        op_str = "<=" if is_pe else ">="
                                        logging.info(f"🏛️ [INSTITUTIONAL OPENING SURGE CONFIRMED] {sym} ({item.get('contract')}): "
                                                     f"Spot {spot_ltp:.2f} {op_str} VWAP {spot_vwap:.2f} & RVOL {proj_rvol:.1f}x! Promoted to 🥇 T1 Gold!")
                                    elif rvol_spot.get("badge") != "NORMAL":
                                        logging.info(f"🔥 [SPOT RVOL CONFLUENCE] {sym}: Underlying has {rvol_spot.get('badge')} (Projected {proj_rvol:.1f}x) backing option breakout!")
                            except Exception as rvol_err:
                                logging.debug(f"Spot RVOL check error for {sym}: {rvol_err}")

                        # Check 4: Optional Synergy ADX/DMI Momentum Filter
                        enable_adx_synergy = bool(item.get("enable_adx_synergy", False))
                        if not enable_adx_synergy:
                            try:
                                opt_cfg = load_program_config_for_engine("nifty50")
                                enable_adx_synergy = bool(opt_cfg.get("ENABLE_ADX_SYNERGY_FILTER", False))
                            except Exception:
                                pass

                        if enable_adx_synergy:
                            from trap_adx_engine import calculate_dmi
                            plus_di, minus_di, adx_val = calculate_dmi(df_latest, period=14)
                            curr_plus_di = float(plus_di.iloc[-1]) if not plus_di.empty else 0.0
                            curr_minus_di = float(minus_di.iloc[-1]) if not minus_di.empty else 0.0

                            # Chop Guard: If +DI < 20.0, directional momentum is absent; hold candidate
                            if curr_plus_di < 20.0 and curr_plus_di <= curr_minus_di:
                                logging.info(f"🛡️ [SYNERGY ADX CHOP GUARD] {sym} ({item.get('contract')}): +DI {curr_plus_di:.1f} < 20.0 (-DI {curr_minus_di:.1f}). Market lacks directional momentum. Holding in Category A.")
                                continue

                            # Ignition Booster: If +DI >= 26.0 and +DI > -DI, promote to T1 Gold
                            if curr_plus_di >= 26.0 and curr_plus_di > curr_minus_di:
                                item["tier"] = 1
                                item["tier_label"] = "🥇 T1 Gold (ADX Ignition)"
                                logging.info(f"🔥 [SYNERGY ADX IGNITION] {sym} ({item.get('contract')}): +DI {curr_plus_di:.1f} >= 26.0! Promoted to 🥇 T1 Gold!")

                        # Check 5: Position Sizing & Risk Budget Sanity Gate
                        c_tier_val = _parse_candidate_tier(item, default=2)
                        lot_sz_val = int(item.get("lot_size") or (get_option_lot_size(item.get("contract")) if item.get("contract") else None) or STOCK_REGISTRY.get(sym, {}).get("lot_size", 1) or 1)
                        cfg_eng_radar = load_program_config_for_engine("nifty50")
                        cap_val_radar = float(cfg_eng_radar.get("capital") or 100000.0)
                        allow_conviction_r = bool(cfg_eng_radar.get("allow_single_lot_conviction", True))
                        max_single_risk_r = float(cfg_eng_radar.get("max_single_lot_risk_pct", 5.0))

                        calc_pos_sz = calculate_position_size(
                            spot_price=c_now,
                            stop_loss=sl,
                            capital=cap_val_radar,
                            risk_percent=float(cfg_eng_radar.get("MAX_RISK_PERCENT") or 1.0),
                            lot_size=lot_sz_val,
                            is_option=True,
                            tier=c_tier_val,
                            allow_zero=True,
                            allow_single_lot_conviction=allow_conviction_r,
                            max_single_lot_risk_pct=max_single_risk_r
                        )
                        if calc_pos_sz <= 0:
                            risk_amt = abs(c_now - sl) * lot_sz_val
                            logging.info(f"🛡️ [RADAR RISK BUDGET GATE] {sym} ({item.get('contract')}): Risk per lot (₹{risk_amt:.2f}) exceeds capital risk budget. Holding candidate from radar trigger.")
                            item["risk_exceeded"] = True
                            item["risk_msg"] = f"Risk per lot (₹{risk_amt:.0f}) exceeds capital risk budget"
                            continue

                        if is_retest and not is_breakout:
                            trigger_type = "POST_D_RETEST"
                        elif is_80pct_mature and not is_closed_bar:
                            trigger_type = "80%_EARLY_D"
                        else:
                            trigger_type = "COMPLETED_BAR_D"

                        logging.info(f"⚡ [RADAR TRIGGER: {trigger_type}] {sym} ({item.get('contract')}) LTP={c_now:.2f} vs Benchmark={bm:.2f} (VWAP={opt_vwap:.2f}, Stretch={stretch_pct:.1f}%)!")
                        item["entry_spot"] = c_now
                        item["entry_time"] = str(last_candle.get('date', dt.now().isoformat()))
                        item["trigger_type"] = trigger_type
                        item["risk_exceeded"] = False
                        # Recompute R:R based on exact retest entry price
                        risk_now = abs(c_now - sl)
                        if risk_now > 0 and t1 > 0:
                            item["rr"] = round(abs(t1 - c_now) / risk_now, 2)
                        triggered.append(item)
                        # NOTE: Candidate is retained in pattern_funnel so it remains in fast surveillance
                        # if gates (liquidity spread, overpay VWAP, portfolio caps) defer immediate execution.
                        # Eviction is handled cleanly in execute_highest_rr_trade() upon successful trade creation,
                        # or by hard eviction rules (80% T1 hit / Anchor SL close).
            except Exception as radar_err:
                logging.debug(f"Radar check error for {sym}: {radar_err}")

        if triggered:
            logging.info(f"⚡ [RADAR TRIGGERED] Executing {len(triggered)} setup(s) immediately!")
            execute_highest_rr_trade(kite, triggered)
        return triggered
    finally:
        _RADAR_ACTIVE.clear()


def fast_radar_loop(kite):
    """
    Dedicated background surveillance thread monitoring Category A+ (Imminent)
    and Category A (Ready) setups every 15 seconds.
    Ensures sub-15-second execution latency upon D-trigger breakout even while
    the main discovery scan cycle is processing other symbols.
    """
    logging.info("Fast surveillance radar loop started (surveillance interval: 15s).")
    while True:
        try:
            ensure_kite_session(kite)
            run_fast_radar_check(kite)
        except Exception as e:
            logging.error(f"Fast radar loop error: {e}", exc_info=True)
        time.sleep(15)

# ──────────────────────────────────────────────
#  ANCHOR SCAN — RUNS ON DEMAND VIA DASHBOARD
# ──────────────────────────────────────────────

def run_anchor_scan(kite):
    logging.info("On-demand scan requested: executing full A-B-C-D breakout scan across Nifty 50 option contracts...")
    staged = run_scan_cycle(kite)
    with position_lock:
        shared_write_display(staged or [], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
    logging.info(f"On-demand scan complete: found {len(staged or [])} full A-B-C-D breakout setup(s)")

# ──────────────────────────────────────────────
#  POSITION MONITORING — SL, TRAILING, TARGETS
# ──────────────────────────────────────────────

def monitor_active_positions(kite):
    return shared_monitor_positions(kite, STOCK_REGISTRY, ACTIVE_POSITIONS, position_lock,
                                     kite.PRODUCT_NRML, "nifty50", TIMEFRAME_ENTRY,
                                     trade_db, log_to_journal, save_state,
                                     live=LIVE_MARKET_DEPLOYMENT)

def position_monitor_loop(kite):
    """Background thread that checks stop-loss, trailing, and targets every 60s."""
    while True:
        try:
            ensure_kite_session(kite)
            monitor_active_positions(kite)
        except Exception as e:
            logging.error(f"Position monitor error: {e}")
        time.sleep(60)

# ──────────────────────────────────────────────
#  DISPLAY DATA WRITER + KITE SYNC
# ──────────────────────────────────────────────



def write_scan_display_data(staged, active, display_file=SCAN_DISPLAY_FILE, engine_name="nifty50"):
    return shared_write_display(staged, active, display_file, engine_name)

# ──────────────────────────────────────────────
#  MAIN LOOP — SCAN CYCLE + ANCHOR POLL
# ──────────────────────────────────────────────

def main_scan_loop(kite):
    global _LAST_FUNNEL_CLEANUP_DATE
    _sync_counter = 0
    _cycle_count = 0
    _pre_market_seeded = False
    while True:
        try:
            ensure_kite_session(kite)
            load_program_config()
            _sync_counter += 1
            now_ist = get_ist_now(naive=True)
            t_now = now_ist.time()
            today_str = now_ist.strftime("%Y-%m-%d")
            t_str = now_ist.strftime("%H:%M")
            is_pre_market = t_now < datetime_time(9, 15)

            # Morning pre-flight cleanup of stale runaway setups (runs once per day after 08:00 IST)
            if _LAST_FUNNEL_CLEANUP_DATE != today_str and t_str >= "08:00":
                try:
                    pattern_funnel.purge_stale_prior_day_setups("nifty50", today_str=today_str, purge_scan_display=True)
                    _LAST_FUNNEL_CLEANUP_DATE = today_str
                    logging.info(f"[MORNING PRE-FLIGHT PURGE] Cleaned stale runaway setups before morning scanning at {t_str} IST.")
                except Exception as p_err:
                    logging.warning(f"Morning pre-flight purge error: {p_err}")

            # Fast sync active trades from SQLite trade_db to catch manual/1-Click entries immediately
            try:
                db_active = trade_db.get_active_trades("nifty50")
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

            if _sync_counter % 5 == 0 and not BACKTEST_DATE:
                shared_sync_kite(kite, STOCK_REGISTRY, ACTIVE_POSITIONS, position_lock, "nifty50", TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR)
            if os.path.exists(SL_TARGET_OVERRIDES_FILE):
                try:
                    with open(SL_TARGET_OVERRIDES_FILE) as f:
                        overrides = json.load(f)
                    eng_overrides = overrides.get("nifty50", {})
                    if eng_overrides:
                        with position_lock:
                            for sym, vals in eng_overrides.items():
                                sym_clean = str(sym).replace(" ", "").upper()
                                target_pos = None
                                for k, p in ACTIVE_POSITIONS.items():
                                    p_contract = str(p.get("contract") or "").replace(" ", "").upper()
                                    k_clean = str(k).replace(" ", "").upper()
                                    if p_contract == sym_clean or k_clean == sym_clean:
                                        target_pos = p
                                        break
                                if target_pos:
                                    ep = float(target_pos.get("entry_spot", 0))
                                    ov_t1 = vals.get("t1")
                                    if ep > 0 and ov_t1 is not None and ov_t1 <= ep:
                                        logging.warning(f"[OVERRIDE REJECTED] Override T1 ({ov_t1}) <= Entry ({ep}) for {target_pos.get('contract')}. Skipping invalid override.")
                                        continue
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
                        save_state()
                except Exception as e:
                    logging.warning(f"Override apply failed: {e}")

            # 2-Tier Universe Scheduling & Pre-Market Seeding (FEATURE-042)
            if is_pre_market:
                universe_mode = "FULL"
                if not _pre_market_seeded:
                    logging.info(f"🌅 [PRE-MARKET LAUNCH] Engine started at {t_str} IST. Initiating full pre-market seeding sweep across F&O universe...")
            elif ENABLE_2TIER_SCHEDULING:
                # Every 5th cycle (~15 minutes) or Cycle 0 is FULL; other cycles are fast CORE (3 mins)
                if _cycle_count % 5 == 0:
                    universe_mode = "FULL"
                else:
                    universe_mode = "CORE"
            else:
                universe_mode = "FULL"

            logging.info(f"[BEAT] Starting Nifty 50 scan cycle {_cycle_count + 1} ({universe_mode})...")
            if os.path.exists(ANCHOR_SCAN_REQUEST_FILE):
                try:
                    with open(ANCHOR_SCAN_REQUEST_FILE) as f:
                        engine = f.read().strip()
                    os.remove(ANCHOR_SCAN_REQUEST_FILE)
                    if engine != "nifty50":
                        logging.info(f"Anchor scan flag not for nifty50, skipping (got {engine})")
                    else:
                        logging.info(f"Anchor scan requested via flag file (engine: {engine})")
                        run_anchor_scan(kite)
                except Exception:
                    pass

            start = time.time()
            staged = run_scan_cycle(kite, universe_mode=universe_mode)
            if staged:
                execute_highest_rr_trade(kite, staged)
            else:
                logging.info("[CYCLE] No trades staged this cycle.")
            trade_db.clear_cycle_trades("nifty50")
            with position_lock:
                shared_write_display(staged or [], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
            _cycle_count += 1
            elapsed = time.time() - start

            # Pre-Market Standby Countdown: Stay awake until 09:15:00 IST open
            if is_pre_market and ENABLE_PREMARKET_SEEDING:
                _pre_market_seeded = True
                funnel_st = pattern_funnel.get_funnel_summary("nifty50")
                total_seeded = funnel_st.get("count_a_plus", 0) + funnel_st.get("count_a", 0) + funnel_st.get("count_b", 0)
                market_open_dt = datetime.combine(now_ist.date(), datetime_time(9, 15))
                secs_to_open = (market_open_dt - get_ist_now(naive=True)).total_seconds()
                if secs_to_open > 0:
                    logging.info(f"🎯 [PRE-MARKET SEEDING COMPLETE] Sweep completed in {elapsed:.1f}s | {total_seeded} setups primed in Incubation Funnel (A+:{funnel_st.get('count_a_plus',0)}, A:{funnel_st.get('count_a',0)}, B:{funnel_st.get('count_b',0)}). Fast Surveillance Radar armed and standing by for 09:15:00 IST open ({secs_to_open:.0f}s countdown)...")
                    while secs_to_open > 5.0:
                        sleep_step = min(30.0, secs_to_open - 2.0)
                        time.sleep(sleep_step)
                        now_check = get_ist_now(naive=True)
                        secs_to_open = (market_open_dt - now_check).total_seconds()
                        if secs_to_open > 5.0:
                            logging.info(f"⏳ [PRE-MARKET COUNTDOWN] {secs_to_open:.0f}s until 09:15:00 IST market open. Radar armed with {total_seeded} setups.")
                    logging.info("🔔 [OPENING BELL] 09:15:00 IST reached! Transitioning to live market surveillance mode.")
                    continue

            # Standard / Live Market Sleep Handling
            target_interval = CORE_SCAN_INTERVAL_SECONDS if (ENABLE_2TIER_SCHEDULING and universe_mode == "CORE") else (FULL_SCAN_INTERVAL_SECONDS if ENABLE_2TIER_SCHEDULING else SCAN_INTERVAL_SECONDS)
            sleep = max(0, target_interval - elapsed)
            logging.info(f"[CYCLE COMPLETE] {_cycle_count} ({universe_mode}) cycle complete in {elapsed:.2f}s | Next scan in {sleep:.0f}s | Found {len(staged or [])} setup(s)")
            time.sleep(sleep)
        except Exception as e:
            logging.error(f"Main loop error: {e}")
            time.sleep(10)

def load_program_config():
    cfg_applied = load_program_config_for_engine(
        "nifty50",
        [
            ("strike_range", "STRIKE_RANGE"),
            ("target_universe", "TARGET_UNIVERSE"),
            ("core_scan_interval", "CORE_SCAN_INTERVAL_SECONDS"),
            ("full_scan_interval", "FULL_SCAN_INTERVAL_SECONDS"),
            ("enable_2tier_scheduling", "ENABLE_2TIER_SCHEDULING"),
            ("enable_premarket_seeding", "ENABLE_PREMARKET_SEEDING"),
        ]
    )
    for k, v in cfg_applied.items():
        if k == "STRIKE_RANGE": globals()["STRIKE_RANGE"] = int(v) if isinstance(v, (int, float)) else v
        elif k in ("TIMEFRAME_ENTRY", "TIMEFRAME_ANCHOR"): globals()[k] = v
        elif k == "TARGET_UNIVERSE": globals()["TARGET_UNIVERSE"] = str(v).upper()
        elif k == "LIVE_MARKET_DEPLOYMENT": globals()["LIVE_MARKET_DEPLOYMENT"] = v
        elif k == "LOOKBACK_DAYS": globals()["LOOKBACK_DAYS"] = int(v)
        elif k == "SCAN_INTERVAL_SECONDS": globals()["SCAN_INTERVAL_SECONDS"] = int(v)
        elif k == "CORE_SCAN_INTERVAL_SECONDS": globals()["CORE_SCAN_INTERVAL_SECONDS"] = int(v) if isinstance(v, (int, float)) else globals()["CORE_SCAN_INTERVAL_SECONDS"]
        elif k == "FULL_SCAN_INTERVAL_SECONDS": globals()["FULL_SCAN_INTERVAL_SECONDS"] = int(v) if isinstance(v, (int, float)) else globals()["FULL_SCAN_INTERVAL_SECONDS"]
        elif k == "ENABLE_2TIER_SCHEDULING": globals()["ENABLE_2TIER_SCHEDULING"] = bool(v)
        elif k == "ENABLE_PREMARKET_SEEDING": globals()["ENABLE_PREMARKET_SEEDING"] = bool(v)
        elif k == "MAX_RISK_PERCENT": globals()["MAX_RISK_PERCENT"] = float(v)
        elif k == "INITIAL_CAPITAL": globals()["INITIAL_CAPITAL"] = float(v)


def _resolve_option_token(contract_symbol):
    with instruments_lock:
        if NFO_INSTRUMENTS.empty:
            return None
        m = NFO_INSTRUMENTS[NFO_INSTRUMENTS['tradingsymbol'] == contract_symbol]
        if m.empty:
            return None
        return int(m.iloc[0]['instrument_token'])

def simulate_trade_outcome(kite, trade, target_date):
    return shared_simulate(kite, trade, target_date)

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
            if staged:
                results["days_with_trades"] += 1
                results["total_trades"] += 1
                best = max(staged, key=_avg_target_rank)
                sym = best["symbol"]
                if sym not in results["by_symbol"]:
                    results["by_symbol"][sym] = {"trades": 0, "wins": 0, "losses": 0, "no_exits": 0}
                results["by_symbol"][sym]["trades"] += 1
                key = f"{sym}|{best['pattern']}|{best.get('side', 'CE')}|{best.get('strike', '')}"
                if not trade_db.is_pattern_executed("nifty50", key):
                    trade_db.record_executed_pattern("nifty50", key, {"entry": best["entry_spot"]})
                strike_step = best.get("strike_step", 50)
                contract_display = resolve_option_contract(sym, best["entry_spot"], strike_step, best.get("side", "CE"), best.get("strike"))
                if not contract_display:
                    contract_display = sym
                log_to_journal(contract_display, best['pattern'], TIMEFRAME_ENTRY,
                               "BACKTEST_ENTRY", "ENTRY",
                               details=f"Symbol={sym} Strike={best.get('strike','')}",
                               entry=best['entry_spot'], sl=best['current_sl'],
                               target=best.get('t3') or best.get('t1') or "",
                               rr=best.get('rr'),
                               event_time=best.get("entry_time"))
                sim = simulate_trade_outcome(kite, best, day)
                sim_result = sim["result"]
                exit_action = ""
                pnl = 0.0
                if sim_result == "SL_HIT":
                    exit_action = "EXIT_SL"
                    pnl = sim["pnl_pct"] or 0.0
                    results["losses"] += 1
                    results["by_symbol"][sym]["losses"] += 1
                elif sim_result in ("T1_HIT", "T2_HIT", "T3_HIT"):
                    exit_action = sim_result.replace("_HIT", "")
                    pnl = sim["pnl_pct"] or 0.0
                    results["wins"] += 1
                    results["by_symbol"][sym]["wins"] += 1
                else:
                    exit_action = "EXIT_UNKNOWN"
                    results["no_exits"] += 1
                    results["by_symbol"][sym]["no_exits"] += 1
                if exit_action:
                    log_to_journal(contract_display, best['pattern'], TIMEFRAME_ENTRY,
                                   exit_action, sim_result or "NO_EXIT",
                                   details=f"Symbol={sym} Strike={best.get('strike','')}",
                                   entry=best['entry_spot'], sl=best['current_sl'],
                                   target=best.get('t3') or best.get('t1') or "",
                                   rr=best.get('rr'), pnl_pct=pnl,
                                   event_time=sim.get("exit_time") or sim.get("entry_time"))
                logging.info(f"  Trade: {contract_display} | {best['pattern']} | outcome={sim_result or 'unknown'} | P&L={pnl:.2f}%")
            trade_db.clear_cycle_trades("nifty50")
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
        logging.info("Starting Nifty 50 Stock Scanner + Executor")
    try:
        ak, at = load_kite_session()
        kite = KiteConnect(api_key=ak)
        kite.set_access_token(at)
        optimize_kite_session(kite)
        sync_instruments(kite)
        if BACKTEST_DATE is None:
            load_state()
            trade_db.run_db_housekeeping()
            try:
                pattern_funnel.purge_stale_prior_day_setups("nifty50")
            except Exception as funnel_init_err:
                logging.warning(f"Startup pattern funnel purge warning: {funnel_init_err}")
            active = trade_db.get_active_trades("nifty50")
            seen_symbols = set()
            for t in active:
                sym = t.get("symbol")
                if not sym or sym in seen_symbols:
                    continue
                seen_symbols.add(sym)
                pos = {k: v for k, v in t.items() if k not in ("id", "engine", "symbol", "status", "updated_at")}
                pos.setdefault("pattern", "DB_RECOVERED")
                pos.setdefault("lot_size", 1)
                pos.setdefault("entry_spot", 0)
                pos.setdefault("current_sl", 0)
                pos.setdefault("t1", 0)
                pos.setdefault("t2", 0)
                pos.setdefault("t3", 0)
                pos.setdefault("trailing_stage", 0)
                pos.setdefault("position_type", "option")
                pos["trade_id"] = t["id"]
                pos["entry_time"] = sanitize_entry_time(pos)
                with position_lock:
                    ACTIVE_POSITIONS[sym] = pos
                logging.info(f"Recovered position: {sym}")
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
                    if p["exchange"] not in ("NFO", "NSE") or int(p.get("quantity", 0)) <= 0:
                        continue
                    tsym = p["tradingsymbol"]
                    symbol = match_registry_symbol(STOCK_REGISTRY, tsym) or extract_underlying_symbol(tsym)
                    if not symbol:
                        continue
                    
                    avg_pr = float(p.get("average_price") or p.get("buy_price") or p.get("net_price") or 0.0)
                    nq = abs(int(p.get("quantity", 0)))
                    if nq == 0: continue

                    if symbol in ACTIVE_POSITIONS:
                        existing = ACTIVE_POSITIONS[symbol]
                        cnt_changed = existing.get("contract") and existing.get("contract") != tsym
                        old_entry = float(existing.get("entry_spot") or existing.get("entry_price") or 0.0)
                        entry_mismatch = (avg_pr > 0 and old_entry > 0 and abs(old_entry - avg_pr) / max(old_entry, 1.0) > 0.05)
                        curr_sl = float(existing.get("current_sl") or 0.0)
                        is_inverted_sl = (avg_pr > 0 and curr_sl >= avg_pr and int(existing.get("trailing_stage") or 0) == 0)

                        if cnt_changed or entry_mismatch or is_inverted_sl:
                            logging.info(f"[KITE SYNC] Correcting stale/mismatched state for {symbol} ({tsym}): old_entry={old_entry} -> avg_pr={avg_pr}, old_sl={curr_sl}")
                            existing["contract"] = tsym
                            existing["entry_spot"] = avg_pr if avg_pr > 0 else old_entry
                            existing["entry_price"] = existing["entry_spot"]
                            existing["option_token"] = int(p.get("instrument_token", 0))
                            if is_inverted_sl or cnt_changed:
                                scan_sl = lookup_scan_sl_target(tsym, symbol, "nifty50", kite, existing["entry_spot"], TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR)
                                if scan_sl:
                                    existing.update(scan_sl)
                                else:
                                    existing["current_sl"] = calculate_sl_buffer(existing["entry_spot"], side="BULL")
                                    existing["trailing_stage"] = 0
                            if existing.get("trade_id"):
                                trade_db.update_trade(existing["trade_id"], {
                                    "contract": tsym, "entry_spot": existing["entry_spot"],
                                    "entry_price": existing["entry_spot"], "current_sl": existing["current_sl"],
                                    "option_token": existing["option_token"], "trailing_stage": existing.get("trailing_stage", 0)
                                })
                        continue

                    if p["exchange"] == "NFO":
                        lot_sz = get_option_lot_size(tsym) or (STOCK_REGISTRY.get(symbol, {}).get("lot_size", 1))
                        lots = nq // lot_sz if lot_sz > 0 else 1
                        if lots == 0: lots = 1
                        pos = {
                            "contract": tsym, "option_token": int(p.get("instrument_token", 0)),
                            "entry_spot": float(p.get("net_price") or p.get("buy_price") or p.get("average_price") or 0),
                            "current_sl": 0, "t1": 0, "t2": 0, "t3": 0,
                            "trailing_stage": 0, "lot_size": lot_sz,
                            "position_size": lots, "pattern": "KITE_RECOVERED",
                            "timeframe": TIMEFRAME_ENTRY,
                            "entry_time": dt.now().isoformat(),
                            "position_type": "option"
                        }
                    else:
                        pos = {
                            "contract": tsym, "option_token": int(p.get("instrument_token", 0)),
                            "entry_spot": float(p.get("net_price") or p.get("buy_price") or p.get("average_price") or 0),
                            "current_sl": 0, "t1": 0, "t2": 0, "t3": 0,
                            "trailing_stage": 0, "lot_size": 1,
                            "position_size": nq, "pattern": "KITE_RECOVERED",
                            "timeframe": TIMEFRAME_ENTRY,
                            "entry_time": dt.now().isoformat(),
                            "position_type": "stock"
                        }
                    clear_executed_exit(tsym)
                    clear_executed_exit(symbol)
                    pos["trade_id"], _created = trade_db.create_trade("nifty50", symbol, {k: v for k, v in pos.items() if k != "trade_id"})
                    scan_sl = lookup_scan_sl_target(tsym, symbol, "nifty50", kite, pos["entry_spot"], TIMEFRAME_ENTRY, TIMEFRAME_ANCHOR)
                    if scan_sl:
                        pos.update(scan_sl)
                    else:
                        pos["current_sl"] = calculate_sl_buffer(pos["entry_spot"], side="BULL")
                    
                    # Sanitize recovered SL
                    from dashboard_sl_overrides import sanitize_sl_and_entry
                    _, safe_sl = sanitize_sl_and_entry(pos["entry_spot"], pos["current_sl"], pos.get("trailing_stage", 0), "BULL")
                    pos["current_sl"] = safe_sl
                    trade_db.update_trade(pos["trade_id"], {"current_sl": pos["current_sl"], "t1": pos.get("t1", 0), "t2": pos.get("t2", 0), "t3": pos.get("t3", 0)})
                    logging.info(f"[KITE_RECOVER] Applied scan SL/Target for {symbol}: SL={pos.get('current_sl')} T1={pos.get('t1')} T2={pos.get('t2')} T3={pos.get('t3')}")
                    ACTIVE_POSITIONS[symbol] = pos
                    logging.info(f"Recovered from Kite: {symbol} {tsym} qty={nq}")
            except Exception as e:
                logging.warning(f"Kite position recovery failed: {e}")
            reconcile_positions(kite)
            with position_lock:
                shared_write_display([], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
        if anchor_only:
            run_anchor_scan(kite)
            return
    except Exception as e:
        logging.error(f"Init: {e}")
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
            best = max(staged, key=_avg_target_rank)
            execute_highest_rr_trade(kite, staged)
            with position_lock:
                ACTIVE_POSITIONS.clear()
                write_scan_display_data(staged, dict(ACTIVE_POSITIONS))
            logging.info(f"\n{'='*100}")
            logging.info(f"{'TRADE LOG':^100}")
            logging.info(f"{'='*100}")
            hdr = f"{'#':<4} {'Symbol':<14} {'Contract':<24} {'Side':<4} {'Entry':>8} {'SL':>8} {'T1':>8} {'T2':>8} {'T3':>8} {'EntryTime':<24} {'ExitTime':<24} {'Result':<12} {'P&L%':>8}"
            logging.info(hdr)
            logging.info(f"{'-'*100}")
            for idx, t in enumerate(staged, 1):
                sim = simulate_trade_outcome(kite, t, BACKTEST_DATE)
                et = str(sim["entry_time"]) if sim["entry_time"] is not None else "-"
                ext = str(sim["exit_time"]) if sim["exit_time"] is not None else "-"
                r = sim["result"] or "FAIL"
                pnl = sim["pnl_pct"]
                pnl_s = f"{pnl:+.2f}%" if pnl is not None else "-"
                t1v = t.get("t1", "-")
                t2v = t.get("t2", "-")
                t3v = t.get("t3", "-")
                logging.info(f"{idx:<4} {t['symbol']:<14} {t.get('contract',''):<24} {t.get('side',''):<4} {t['entry_spot']:>8.2f} {t['current_sl']:>8.2f} {str(t1v):>8} {str(t2v):>8} {str(t3v):>8} {et:<24} {ext:<24} {r:<12} {pnl_s:>8}")
            logging.info(f"{'='*100}")
            logging.info(f"BEST TRADE: {best['symbol']} {best.get('contract','')} | avg-target RR={_avg_target_rank(best):.2f}")
        else:
            with position_lock:
                ACTIVE_POSITIONS.clear()
                write_scan_display_data([], dict(ACTIVE_POSITIONS), SCAN_DISPLAY_FILE, "nifty50")
            logging.info("[BACKTEST] No trades staged for this date.")
        trade_db.clear_cycle_trades("nifty50")
        return
    if not LIVE_MARKET_DEPLOYMENT:
        logging.error("Config has _backtest=true but no --date= or --backtest-range= flag. "
                      "Use --date=YYYY-MM-DD or --backtest-range=START,END to run backtest. Exiting.")
        return
    logging.info(f"TF: {TIMEFRAME_ENTRY} | Interval: {SCAN_INTERVAL_SECONDS}s | Risk: {MAX_RISK_PERCENT}%")
    t1 = threading.Thread(target=position_monitor_loop, args=(kite,), daemon=True)
    t1.start()
    t2 = threading.Thread(target=main_scan_loop, args=(kite,), daemon=True)
    t2.start()
    t3 = threading.Thread(target=fast_radar_loop, args=(kite,), daemon=True)
    t3.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Engine stopped.")

if __name__ == "__main__":
    main()
