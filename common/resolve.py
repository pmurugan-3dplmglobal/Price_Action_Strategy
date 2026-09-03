"""
Option strike resolution, SL/target derivation, anchor validity checks,
scan_symbol dispatcher, position reconciliation, and trade simulation.
Extracted from trading_core.py (2026-08-11).
"""
import os
import sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import json
import logging
import time
from datetime import datetime as dt, timedelta, time as datetime_time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import paths

from swing_detection import detect_parabolic_multi_swings
from session import safe_kite_call, ensure_kite_session, load_kite_session
from timeframe_utils import (
    fetch_and_resample_candles,
    fetch_option_data,
    resample_timeframe,
    get_fetch_timeframe,
    get_ist_now,
    get_ist_date,
    get_ist_time,
    LOOKBACK_LIMITS
)
from display_writer import clean_timestamp
from targets import (
    find_profit_targets,
    find_profit_targets_bearish,
    check_left_side_rule,
    check_left_side_rule_bearish,
    calculate_position_size,
    calculate_sl_buffer
)
from patterns_bull import (
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout,
    scan_trend_continuation_reentry
)
from patterns_bear import (
    find_anchor_bearish_engulfing,
    find_anchor_hh_sweep,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_anchor_bcd_breakout_bearish,
    scan_trend_continuation_reentry_bearish,
    scan_anchor_bcd_breakout_generic
)
from vix_guard import evaluate_vix_regime
from portfolio_risk import check_portfolio_risk_caps

def _match_registry_symbol(registry, tradingsymbol):
    """Return the registry key that best matches a tradingsymbol, longest-match first.

    Fixes the mislabel bug where 'NIFTY' matched inside 'BANKNIFTY26AUG57700PE'
    before 'BANKNIFTY' was checked. Returns None when nothing matches.
    """
    if not registry or not tradingsymbol:
        return None
    raw = str(tradingsymbol).replace(" ", "").upper()
    for sym in sorted(registry.keys(), key=len, reverse=True):
        if sym.replace(" ", "").upper() in raw:
            return sym
    return None

def load_program_config_for_engine(cfg_section, extra_fields=None):
    """Load engine config from program_config.json. Returns dict of applied overrides."""
    applied = {}
    try:
        possible_paths = [
            paths.PROGRAM_CONFIG_FILE,
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "input", "program_config.json"),
            os.path.join(os.path.dirname(__file__), "input", "program_config.json")
        ]
        cfg_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if cfg_path:
            with open(cfg_path, encoding="utf-8") as f:
                full = json.load(f)
            if "_backtest" in full:
                applied["LIVE_MARKET_DEPLOYMENT"] = not bool(full["_backtest"])
            else:
                applied["LIVE_MARKET_DEPLOYMENT"] = True
            cfg = full.get(cfg_section, {})
            for k, v in cfg.items():
                applied[k.lower()] = v
                applied[k.upper()] = v
            for src_key, dst_key in [
                ("timeframe_entry", "TIMEFRAME_ENTRY"),
                ("timeframe_anchor", "TIMEFRAME_ANCHOR"),
                ("lookback_days", "LOOKBACK_DAYS"),
                ("scan_interval", "SCAN_INTERVAL_SECONDS"),
                ("risk_percent", "MAX_RISK_PERCENT"),
                ("capital", "INITIAL_CAPITAL"),
                ("enable_swing_filter", "ENABLE_SWING_FILTER"),
                ("swing_min_waves", "SWING_MIN_WAVES"),
                ("swing_min_r2", "SWING_MIN_R2"),
                ("strict_macro_gate", "STRICT_MACRO_GATE"),
                ("enable_spot_sl_guard", "ENABLE_SPOT_SL_GUARD"),
                ("strike_range", "STRIKE_RANGE"),
                ("tranche_mode", "TRANCHE_MODE"),
                ("prefer_itm_strikes", "PREFER_ITM_STRIKES"),
                ("max_daily_loss_pct", "MAX_DAILY_LOSS_PCT"),
            ]:
                if src_key in cfg:
                    applied[dst_key] = cfg[src_key]
                elif "portfolio_risk" in full and src_key in full["portfolio_risk"]:
                    applied[dst_key] = full["portfolio_risk"][src_key]
            if extra_fields:
                for src_key, dst_key in extra_fields:
                    if src_key in cfg:
                        applied[dst_key] = cfg[src_key]
                    elif src_key in full:
                        applied[dst_key] = full[src_key]
        else:
            applied["LIVE_MARKET_DEPLOYMENT"] = True
    except Exception as e:
        logging.warning(f"Config load ({cfg_section}): {e}")
        applied["LIVE_MARKET_DEPLOYMENT"] = True
    return applied

def sync_kite_positions(kite, registry, positions_dict, lock, engine, timeframe_entry, timeframe_anchor):
    try:
        kite_pos = kite.positions()
        for p in kite_pos.get("net", []):
            sym = _match_registry_symbol(registry, p.get("tradingsymbol", ""))
            if not sym:
                continue
            nq = int(p.get("quantity", 0))
            if nq <= 0:
                with lock:
                    if sym in positions_dict:
                        del positions_dict[sym]
                continue
            contract = p["tradingsymbol"]
            pos_key = contract
            entry = float(p.get("net_price") or p.get("buy_price") or p.get("average_price") or 0)
            import position_monitor
            lot_size = position_monitor.get_option_lot_size(contract) or registry.get(sym, {}).get("lot_size", 1)
            is_stock = p.get("exchange", "") == "NSE"
            
            position_monitor.clear_executed_exit(contract)
            with lock:
                target_key = pos_key if pos_key in positions_dict else (sym if sym in positions_dict and positions_dict[sym].get("contract") == contract else None)
                if target_key:
                    if not positions_dict[target_key].get("option_token"):
                        positions_dict[target_key]["option_token"] = int(p.get("instrument_token", 0))
                    positions_dict[target_key]["symbol"] = sym
                    positions_dict[target_key]["contract"] = contract
                    
                    if not positions_dict[target_key].get("user_edited"):
                        scan_sl = lookup_scan_sl_target(contract, sym, engine, kite, entry, timeframe_entry, timeframe_anchor)
                        if not scan_sl:
                            scan_sl = derive_sl_targets_for_contract(kite, contract, entry, timeframe_entry, timeframe_anchor)
                        if scan_sl:
                            for k, v in scan_sl.items():
                                positions_dict[target_key][k] = v
                            tid = positions_dict[target_key].get("trade_id")
                            if tid:
                                import trade_db
                                trade_db.update_trade(tid, scan_sl)
                    continue
                
                positions_dict[pos_key] = {
                    "contract": contract, "symbol": sym, "option_token": int(p.get("instrument_token", 0)),
                    "entry_spot": entry,
                    "current_sl": 0, "t1": 0, "t2": 0, "t3": 0,
                    "trailing_stage": 0, "lot_size": lot_size if not is_stock else 1,
                    "position_size": nq // lot_size if not is_stock else nq,
                    "pattern": "MANUAL_ENTRY",
                    "timeframe": timeframe_entry, "side": "PE" if "PE" in contract else "CE",
                    "entry_time": dt.now().isoformat(),
                    "position_type": "stock" if is_stock else "option"
                }
            import trade_db
            tid, _created = trade_db.create_trade(engine, sym, {"contract": contract, "entry_spot": entry, "current_sl": 0, "t1": 0, "t2": 0, "t3": 0, "lot_size": lot_size, "pattern": "MANUAL_ENTRY", "entry_time": dt.now().isoformat()})
            with lock:
                positions_dict[pos_key]["trade_id"] = tid
            logging.info(f"[KITE_SYNC] New manual position: {contract} entry={entry}")
            scan_sl = lookup_scan_sl_target(contract, sym, engine, kite, entry, timeframe_entry, timeframe_anchor)
            if not scan_sl:
                scan_sl = derive_sl_targets_for_contract(kite, contract, entry, timeframe_entry, timeframe_anchor)
            if scan_sl:
                with lock:
                    for k, v in scan_sl.items():
                        positions_dict[pos_key][k] = v
                trade_db.update_trade(tid, scan_sl)
                logging.info(f"[KITE_SYNC] Applied scan SL/Target for {contract}: SL={scan_sl.get('current_sl')} T1={scan_sl.get('t1')} T2={scan_sl.get('t2')} T3={scan_sl.get('t3')}")
    except Exception as e:
        logging.warning(f"Kite position sync failed: {e}")

def derive_sl_targets_for_contract(kite, contract, entry_price, timeframe_entry="30minute", timeframe_anchor="30minute"):
    """
    Derive SL and Targets for a specific contract.
    - Targets are derived strictly from Negation Theory (find_profit_targets non-negated swing high levels).
    - SL Exception for Manual Entries: If pattern SL is looser than 10% or missing, SL is set to Entry_Price * 0.90 (10% max loss).
    """
    try:
        ref_now = dt.now()
        from_d = (ref_now - timedelta(days=30)).strftime("%Y-%m-%d")
        to_d = ref_now.strftime("%Y-%m-%d")
        
        contract_str = str(contract).upper()
        if "SENSEX" in contract_str or "BSE" in contract_str:
            exch = "BFO"
        elif "CE" in contract_str or "PE" in contract_str or "NIFTY" in contract_str or "BANK" in contract_str:
            exch = "NFO"
        else:
            exch = "NSE"
            
        quote_key = f"{exch}:{contract}"
        ep = float(entry_price) if (entry_price and float(entry_price) > 0) else 0.0
        max_loss_sl = round(ep * 0.90, 2) if ep > 0 else 0.0

        token = None
        if kite:
            try:
                q = kite.quote([quote_key])
                token = q.get(quote_key, {}).get("instrument_token")
                if not ep:
                    ep = float(q.get(quote_key, {}).get("last_price", 0))
                    max_loss_sl = round(ep * 0.90, 2) if ep > 0 else 0.0
            except Exception as q_err:
                logging.warning(f"Kite quote error for {quote_key}: {q_err}")

        df_e, df_a = None, None
        if kite and token:
            try:
                df_e = fetch_and_resample_candles(kite, token, from_d, to_d, timeframe_entry)
                df_a = fetch_and_resample_candles(kite, token, from_d, to_d, timeframe_anchor)
            except Exception as fetch_err:
                logging.warning(f"Candle fetch error for {contract}: {fetch_err}")

        sl_val = None
        t1, t2, t3 = None, None, None
        pattern_name = "NEGATION_DERIVED_MANUAL"

        if df_a is not None and len(df_a) >= 5:
            res = scan_anchor_bcd_breakout(df_e if df_e is not None else df_a, df_a)
            if res:
                pattern_name = res.get("Pattern", "ABC_BREAKOUT")
                pattern_sl = float(res["SL"])
                if ep > 0:
                    sl_val = max(pattern_sl, max_loss_sl) if pattern_sl < ep else max_loss_sl
                else:
                    sl_val = pattern_sl
            else:
                anchor_low = float(df_a.iloc[-10:]['low'].min())
                swing_sl = round(anchor_low - max(0.50, anchor_low * 0.02), 2)
                if ep > 0:
                    sl_val = max(swing_sl, max_loss_sl) if (swing_sl > 0 and swing_sl < ep) else max_loss_sl
                else:
                    sl_val = swing_sl
                pattern_name = "TIMEFRAME_SWING_MANUAL"

            # Always derive Targets via Negation Theory on df_a!
            t1, t2, t3 = find_profit_targets(df_a, ep if ep > 0 else float(df_a.iloc[-1]['close']), stop_loss=sl_val)

        # Fallback for SL if missing
        if sl_val is None or sl_val <= 0 or (ep > 0 and sl_val >= ep):
            sl_val = max_loss_sl if max_loss_sl > 0 else (round(ep * 0.90, 2) if ep > 0 else 0.0)

        # Fallback for T1 only if Negation Theory target is missing or below entry
        if ep > 0 and sl_val > 0 and sl_val < ep:
            risk = round(ep - sl_val, 2)
            if t1 is None or t1 <= ep:
                t1 = round(ep + (1.88 * risk), 2)

        # Derive spot token & spot SL for Spot-Anchored SL Guard
        spot_tok = None
        spot_sl = None
        spot_entry = None
        if kite and contract_str:
            try:
                import re
                from registries import STOCK_REGISTRY, INDEX_REGISTRY
                m_sym = re.match(r"^([A-Za-z0-9_]+?)(?:\d{2}[A-Za-z]{3})", contract_str)
                base_s = m_sym.group(1).upper() if m_sym else contract_str.split("26")[0].upper()
                reg_entry = STOCK_REGISTRY.get(base_s) or INDEX_REGISTRY.get(base_s)
                if isinstance(reg_entry, dict):
                    spot_tok = reg_entry.get("token")
                elif isinstance(reg_entry, int):
                    spot_tok = reg_entry
                if spot_tok:
                    sq = kite.ltp([spot_tok])
                    if sq:
                        spot_entry = float(list(sq.values())[0]["last_price"])
                    df_spot = fetch_and_resample_candles(kite, spot_tok, from_d, to_d, timeframe_anchor)
                    if df_spot is not None and len(df_spot) >= 5:
                        if "PE" in contract_str:
                            spot_high_10 = float(df_spot['high'].iloc[-10:].max())
                            spot_sl = calculate_sl_buffer(spot_high_10, side="BEAR")
                        else:
                            spot_low_10 = float(df_spot['low'].iloc[-10:].min())
                            spot_sl = calculate_sl_buffer(spot_low_10, side="BULL")
            except Exception as s_derive_err:
                logging.debug(f"Spot derivation error for {contract}: {s_derive_err}")

        now_iso = dt.now().isoformat()
        return {
            "entry_price": round(ep, 2) if ep else 0.0,
            "current_sl": sl_val,
            "t1": t1,
            "t2": t2,
            "t3": t3,
            "pattern": pattern_name,
            "entry_time": now_iso,
            "spot_token": spot_tok,
            "spot_sl": spot_sl,
            "spot_entry": spot_entry
        }
    except Exception as e:
        logging.warning(f"Derive contract SL/Target failed for {contract}: {e}")
        if entry_price and float(entry_price) > 0:
            ep = float(entry_price)
            sl_val = round(ep * 0.90, 2)
            risk = round(ep - sl_val, 2)
            now_iso = dt.now().isoformat()
            return {
                "entry_price": round(ep, 2),
                "current_sl": sl_val,
                "t1": round(ep + 1.88 * risk, 2),
                "t2": round(ep + 2.50 * risk, 2),
                "t3": round(ep + 3.50 * risk, 2),
                "pattern": "FALLBACK_10PCT_MANUAL",
                "entry_time": now_iso
            }
        return None

def get_override_paths():
    """Return the canonical path for sl_target_overrides.json (ISSUE-038: no CWD-relative fallback)."""
    return [paths.SL_TARGET_OVERRIDES_FILE]


def lookup_scan_sl_target(contract, symbol, engine, kite=None, entry_price=0, timeframe_entry="15minute", timeframe_anchor="15minute", entry_date=None, is_stock=False):
    """
    Search trade_db and scan display files using:
    - Options: contract name as primary key (e.g. NIFTY26JUL23850CE)
    - Stocks: symbol + entry_date as primary key (e.g. RELIANCE_2026-07-23)
    If not found, fall back to Negation Theory derivation on contract/stock historical candles.
    """
    if not entry_date:
        entry_date = dt.now().strftime("%Y-%m-%d")
        
    stock_key = f"{symbol}_{entry_date}".replace(" ", "").upper()
    clean_c = stock_key if is_stock else str(contract or symbol).replace(" ", "").upper()

    # 0. Check sl_target_overrides.json first for any user overrides.
    #    Search ALL override paths (canonical project-root first), so a user
    #    edit saved under a different cwd is never missed and stale duplicates
    #    don't clobber the canonical value.
    try:
        best_match = None
        best_spec = -1
        clean_sym = str(symbol or "").replace(" ", "").upper()
        for ov_path in get_override_paths():
            if not os.path.exists(ov_path):
                continue
            with open(ov_path, encoding="utf-8") as f:
                overrides = json.load(f)
            for eng_k in (engine, "nifty50", "index"):
                eng_ov = overrides.get(eng_k, {})
                for sym_k, vals in eng_ov.items():
                    clean_k = str(sym_k).replace(" ", "").upper()
                    exact = (clean_k == clean_c) or (clean_sym and clean_k == clean_sym)
                    partial = bool(clean_k and clean_k in clean_c) or bool(clean_c and clean_c in clean_k)
                    if exact or partial:
                        ov_sl = vals.get("current_sl")
                        if ov_sl is not None and str(ov_sl).strip() != "":
                            spec = 2 if exact else 1
                            if spec > best_spec:
                                best_match = vals
                                best_spec = spec
        if best_match:
            ov_sl = best_match.get("current_sl")
            ov_t1 = best_match.get("t1")
            return {
                "current_sl": float(ov_sl),
                "t1": float(ov_t1) if (ov_t1 is not None and str(ov_t1).strip() != "") else 0.0,
                "t2": float(best_match.get("t2")) if (best_match.get("t2") is not None and str(best_match.get("t2")).strip() != "") else 0.0,
                "t3": float(best_match.get("t3")) if (best_match.get("t3") is not None and str(best_match.get("t3")).strip() != "") else 0.0,
                "pattern": "USER_OVERRIDE",
                "user_edited": True
            }
    except Exception:
        pass
    
    try:
        import trade_db
        all_trades = trade_db.get_all_trades(engine)
        best_db = None
        best_len = -1
        for t in all_trades:
            t_is_stock = t.get("position_type") == "stock"
            t_date = (t.get("created_at") or t.get("entry_time") or "")[:10]
            tc = f"{t.get('symbol')}_{t_date}".replace(" ", "").upper() if t_is_stock else str(t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()
            if not tc:
                continue
            if tc == clean_c:
                best_db = t
                break
            if clean_c in tc and len(tc) > best_len:
                best_db = t
                best_len = len(tc)
        if best_db:
            sl = best_db.get("current_sl")
            t1 = best_db.get("t1")
            if sl and t1:
                opt_tok = best_db.get("option_token") or best_db.get("token")
                if not opt_tok and (contract or symbol):
                    try:
                        from position_monitor import _get_nfo_cache
                        _df_cache = _get_nfo_cache()
                        if not _df_cache.empty and 'tradingsymbol' in _df_cache.columns:
                            _m = _df_cache[_df_cache['tradingsymbol'] == str(contract or symbol).strip().upper()]
                            if not _m.empty:
                                opt_tok = int(_m.iloc[0]['instrument_token'])
                    except Exception:
                        pass
                return {
                    "current_sl": sl, "t1": t1, "t2": best_db.get("t2"), "t3": best_db.get("t3"),
                    "pattern": best_db.get("pattern", "DB_SYNC"),
                    "option_token": opt_tok, "token": opt_tok,
                    "entry_spot": best_db.get("entry_spot") or best_db.get("entry_price"),
                    "timeframe": best_db.get("timeframe", "30minute"),
                    "lot_size": best_db.get("lot_size"),
                    "spot_token": best_db.get("spot_token") or best_db.get("index_token"),
                    "spot_sl": best_db.get("spot_sl"),
                    "spot_entry": best_db.get("spot_entry"),
                    "tier": best_db.get("tier", 2),
                    "tier_label": best_db.get("tier_label", "TIER_2_CORE"),
                    "tier_badge": best_db.get("tier_badge", "🥈 T2")
                }
    except Exception:
        pass

    display_paths = {"index": paths.SCAN_DISPLAY_INDEX_FILE, "nifty50": paths.SCAN_DISPLAY_FILE}
    display_path = display_paths.get(engine)
    if display_path and os.path.exists(display_path):
        try:
            with open(display_path) as f:
                data = json.load(f)
            for section in ("staged_trades", "carry_forward", "active_live"):
                for trade in data.get(section, []):
                    t_date = (trade.get("entry_time") or "")[:10]
                    tc = f"{trade.get('symbol')}_{t_date}".replace(" ", "").upper() if is_stock else str(trade.get("contract") or trade.get("symbol") or "").replace(" ", "").upper()
                    if not tc:
                        continue
                    if tc == clean_c:
                        sl = trade.get("current_sl")
                        t1 = trade.get("t1")
                        if sl and t1:
                            opt_tok = trade.get("option_token") or trade.get("token")
                            if not opt_tok and (contract or symbol):
                                try:
                                    from position_monitor import _get_nfo_cache
                                    _df_cache = _get_nfo_cache()
                                    if not _df_cache.empty and 'tradingsymbol' in _df_cache.columns:
                                        _m = _df_cache[_df_cache['tradingsymbol'] == str(contract or symbol).strip().upper()]
                                        if not _m.empty:
                                            opt_tok = int(_m.iloc[0]['instrument_token'])
                                except Exception:
                                    pass
                            return {
                                "current_sl": sl, "t1": t1, "t2": trade.get("t2"), "t3": trade.get("t3"),
                                "pattern": trade.get("pattern", "SCAN_SYNC"),
                                "option_token": opt_tok, "token": opt_tok,
                                "entry_spot": trade.get("entry_spot") or trade.get("entry_price"),
                                "timeframe": trade.get("timeframe", "30minute"),
                                "lot_size": trade.get("lot_size"),
                                "spot_token": trade.get("spot_token") or trade.get("index_token"),
                                "spot_sl": trade.get("spot_sl"),
                                "spot_entry": trade.get("spot_entry"),
                                "tier": trade.get("tier", 2),
                                "tier_label": trade.get("tier_label", "TIER_2_CORE"),
                                "tier_badge": trade.get("tier_badge", "🥈 T2")
                            }
                if clean_c:
                    best_t = None
                    best_len = -1
                    for trade in data.get(section, []):
                        t_date = (trade.get("entry_time") or "")[:10]
                        tc = f"{trade.get('symbol')}_{t_date}".replace(" ", "").upper() if is_stock else str(trade.get("contract") or trade.get("symbol") or "").replace(" ", "").upper()
                        if tc and clean_c in tc and len(tc) > best_len:
                            best_t = trade
                            best_len = len(tc)
                    if best_t:
                        sl = best_t.get("current_sl")
                        t1 = best_t.get("t1")
                        if sl and t1:
                            opt_tok = best_t.get("option_token") or best_t.get("token")
                            if not opt_tok and (contract or symbol):
                                try:
                                    from position_monitor import _get_nfo_cache
                                    _df_cache = _get_nfo_cache()
                                    if not _df_cache.empty and 'tradingsymbol' in _df_cache.columns:
                                        _m = _df_cache[_df_cache['tradingsymbol'] == str(contract or symbol).strip().upper()]
                                        if not _m.empty:
                                            opt_tok = int(_m.iloc[0]['instrument_token'])
                                except Exception:
                                    pass
                            return {
                                "current_sl": sl, "t1": t1, "t2": best_t.get("t2"), "t3": best_t.get("t3"),
                                "pattern": best_t.get("pattern", "SCAN_SYNC"),
                                "option_token": opt_tok, "token": opt_tok,
                                "entry_spot": best_t.get("entry_spot") or best_t.get("entry_price"),
                                "timeframe": best_t.get("timeframe", "30minute"),
                                "lot_size": best_t.get("lot_size"),
                                "spot_token": best_t.get("spot_token") or best_t.get("index_token"),
                                "spot_sl": best_t.get("spot_sl"),
                                "spot_entry": best_t.get("spot_entry"),
                                "tier": best_t.get("tier", 2),
                                "tier_label": best_t.get("tier_label", "TIER_2_CORE"),
                                "tier_badge": best_t.get("tier_badge", "🥈 T2")
                            }
        except Exception:
            pass

    if kite and (contract or symbol) and entry_price > 0:
        return derive_sl_targets_for_contract(kite, contract or symbol, entry_price, timeframe_entry, timeframe_anchor)

    return None

def write_scan_display_data(staged, active, display_file, engine_name=None):
    try:
        now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        today = dt.now().strftime("%Y-%m-%d")
        import trade_db
        db_trades = trade_db.get_all_trades(engine_name) if engine_name else []
        db_map = {}
        for dbt in db_trades:
            if dbt.get("status") in ["ACTIVE", "OPEN"]:
                c = str(dbt.get("contract") or dbt.get("symbol") or "").replace(" ", "").upper()
                if c: db_map[c] = dbt

        def build_trade(t, result, entry_time, exit_time, is_staged=False):
            contract = t.get("contract") or t.get("symbol") or ""
            c_clean = str(contract).replace(" ", "").upper()
            db_record = db_map.get(c_clean) if not is_staged else None
            entry = t.get("entry_spot") if (is_staged or not db_record or db_record.get("entry_spot") is None) else db_record.get("entry_spot")
            sl = t.get("current_sl") if (is_staged or not db_record or not db_record.get("current_sl")) else db_record.get("current_sl")
            t1 = t.get("t1") if (is_staged or not db_record or not db_record.get("t1")) else db_record.get("t1")
            t2 = t.get("t2") if (is_staged or not db_record or not db_record.get("t2")) else db_record.get("t2")
            t3 = t.get("t3") if (is_staged or not db_record or not db_record.get("t3")) else db_record.get("t3")
            pattern = t.get("pattern") if (is_staged or not db_record or not db_record.get("pattern")) else db_record.get("pattern", "")
            rr_val = t.get("rr") if t.get("rr") is not None else t.get("RR")
            if rr_val is None and entry is not None and sl is not None and t1 is not None:
                try:
                    risk = abs(float(entry) - float(sl))
                    risk_min = max(0.01, abs(float(entry)) * 0.005)
                    rr_val = (abs(float(t1) - float(entry)) / risk) if risk >= risk_min else 0.0
                except Exception:
                    rr_val = 0.0
            rr_num = float(rr_val) if (rr_val is not None and str(rr_val).strip() != "") else 0.0

            side_val = t.get("side", "")
            if not side_val:
                cnt = str(contract).upper()
                if "CE" in cnt:
                    side_val = "CE"
                elif "PE" in cnt:
                    side_val = "PE"

            ca_time = t.get("candle_a_time") or t.get("CandleATime")
            if not ca_time:
                try:
                    import trade_db
                    cnt_key = str(contract or t.get("symbol") or "").replace(" ", "").upper()
                    if cnt_key:
                        for db_tr in trade_db.get_all_trades():
                            db_cnt = str(db_tr.get("contract") or db_tr.get("symbol") or "").replace(" ", "").upper()
                            if db_cnt == cnt_key:
                                ca_time = db_tr.get("candle_a_time") or db_tr.get("CandleATime")
                                if ca_time: break
                except Exception:
                    pass

            opt_tok = t.get("option_token") or t.get("token") or t.get("instrument_token")
            if not opt_tok and contract:
                try:
                    from position_monitor import _get_nfo_cache
                    _df_cache = _get_nfo_cache()
                    if not _df_cache.empty and 'tradingsymbol' in _df_cache.columns:
                        _m = _df_cache[_df_cache['tradingsymbol'] == contract]
                        if not _m.empty:
                            opt_tok = int(_m.iloc[0]['instrument_token'])
                except Exception:
                    pass

            return {
                "symbol": t.get("symbol", ""),
                "contract": contract,
                "option_token": opt_tok,
                "token": opt_tok,
                "side": side_val,
                "entry_spot": entry,
                "current_sl": sl,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "pattern": pattern,
                "entry_time": clean_timestamp(entry_time),
                "exit_time": clean_timestamp(exit_time),
                "result": result,
                "carry_forward": False,
                "rr": round(rr_num, 2),
                "candle_a_time": clean_timestamp(ca_time or ""),
                "timeframe": t.get("timeframe", ""),
                "candle_tf_time": t.get("candle_tf_time", ""),
                "benchmark": t.get("benchmark"),
                "anchor_floor": t.get("anchor_floor"),
                "direction": t.get("direction", "BULL"),
                "swing_waves": t.get("swing_waves", t.get("valid_arch_count", 0)),
                "terminal_base": bool(t.get("terminal_base", t.get("has_terminal_base", False))),
                "tier": t.get("tier", 2),
                "tier_label": t.get("tier_label", "TIER_2_CORE"),
                "tier_badge": t.get("tier_badge", "🥈 T2"),
                "spot_token": t.get("spot_token") or t.get("index_token"),
                "spot_sl": t.get("spot_sl"),
                "spot_entry": t.get("spot_entry")
            }
        new_staged = [build_trade(t, t.get("pattern", "BE_ABCD"), t.get("entry_time", now_str), None, is_staged=True) for t in (staged or [])]
        carry_fwd = []
        active_live = []
        active_keys = set()
        active_iterable = active.items() if isinstance(active, dict) else [(p.get("symbol", ""), p) for p in (active or [])]
        for s, p in active_iterable:
            t = p.copy()
            t["symbol"] = s
            c_key = str(p.get("contract") or s or "").replace(" ", "").upper()

            # Validation check 1: Status must be ACTIVE or OPEN
            status_val = str(p.get("status") or "ACTIVE").upper()
            if status_val not in ["ACTIVE", "OPEN"]:
                continue

            # Validation check 2: Contract must NOT be expired
            if contract_is_expired(c_key):
                continue

            # Validation check 3: Must have valid SL & T1
            sl_val = float(p.get("current_sl") or p.get("sl") or 0)
            t1_val = float(p.get("t1") or 0)
            if sl_val <= 0 or t1_val <= 0:
                continue
            
            # Lookup original scanned trade from trade_db to get exact candle timestamps
            db_match = None
            try:
                import trade_db
                for db_tr in trade_db.get_all_trades():
                    db_c = str(db_tr.get("contract") or db_tr.get("symbol") or "").replace(" ", "").upper()
                    if db_c == c_key:
                        db_match = db_tr
                        break
            except Exception:
                pass

            if db_match:
                if not t.get("candle_a_time"):
                    t["candle_a_time"] = db_match.get("candle_a_time") or db_match.get("CandleATime")
                curr_et = str(t.get("entry_time") or "").replace("T", " ").split("+")[0].strip()
                curr_parts = curr_et.split(" ")
                curr_hr = 0
                if len(curr_parts) >= 2 and ":" in curr_parts[1]:
                    h_str = curr_parts[1].split(":")[0]
                    if h_str.isdigit():
                        curr_hr = int(h_str)
                if db_match.get("entry_time") and (not t.get("entry_time") or curr_hr >= 16 or curr_hr < 9):
                    t["entry_time"] = db_match.get("entry_time")

            et = t.get("entry_time", now_str)
            entry_date = et[:10] if isinstance(et, str) else today
            cf = entry_date < today
            entry_time_display = et if isinstance(et, str) else now_str
            trade = build_trade(t, "ACTIVE", entry_time_display, None)
            trade["carry_forward"] = cf
            if cf:
                carry_fwd.append(trade)
            else:
                active_live.append(trade)
            c = str(p.get("contract") or "").replace(" ", "").upper()
            if c: active_keys.add(c)

        def _trade_key(t):
            return str(t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()

        # Accumulate all staged trades for today's date from display_file
        existing_staged = []
        cleared_at_ts = None
        if display_file and os.path.exists(display_file):
            try:
                with open(display_file, "r", encoding="utf-8") as fh:
                    old_d = json.load(fh)
                cleared_at_ts = old_d.get("cleared_at")
                if old_d.get("date") == today:
                    raw_old = old_d.get("all_staged_today") or old_d.get("staged_trades") or []
                    if cleared_at_ts:
                        for tr in raw_old:
                            tr_time = str(tr.get("entry_time") or "")
                            if tr_time > cleared_at_ts:
                                existing_staged.append(tr)
                    else:
                        existing_staged = raw_old
            except Exception:
                pass

        combined_staged = existing_staged + (new_staged if new_staged else [])

        # Deduplicate staged trades by unique contract key: keep freshest entry_time & highest RR
        contract_map = {}
        for t in combined_staged:
            key = _trade_key(t)
            if not key or key in active_keys:
                continue
            if key not in contract_map:
                contract_map[key] = t
            else:
                prev = contract_map[key]
                prev_time = str(prev.get("entry_time") or "")
                curr_time = str(t.get("entry_time") or "")
                if curr_time > prev_time or (curr_time == prev_time and float(t.get("rr", 0)) > float(prev.get("rr", 0))):
                    contract_map[key] = t

        deduped_staged = list(contract_map.values())
        deduped_staged.sort(key=lambda x: float(x.get("rr", 0)), reverse=True)

        data = {
            "date": today,
            "timestamp": now_str,
            "staged_trades": deduped_staged,
            "all_staged_today": deduped_staged,
            "carry_forward": carry_fwd,
            "active_live": active_live
        }
        if engine_name:
            data["engine"] = engine_name
        os.makedirs(os.path.dirname(display_file), exist_ok=True)
        with open(display_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Display data write failed: {e}")

def derive_sl_targets_for_symbol(kite, symbol, entry_price, registry, timeframe_entry, timeframe_anchor, lookback_days, resolve_fn):
    """Run ABC reversal + anchor scanners on a single symbol to derive SL/T1/T2/T3."""
    try:
        config = registry.get(symbol)
        if not config:
            return None
        ref_now = dt.now()
        limits = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200, "60minute": 400, "75minute": 400, "75min": 400, "day": 2000}
        max_days = limits.get(timeframe_entry, 200)
        from_d = (ref_now - timedelta(days=min(lookback_days, max_days))).strftime("%Y-%m-%d")
        to_d = ref_now.strftime("%Y-%m-%d")
        spot_quote = kite.ltp([config["token"]])
        current_spot = float(list(spot_quote.values())[0]["last_price"])
        step = config["strike_step"]
        ce_opts = resolve_fn(symbol, current_spot, step, "CE", 0)
        pe_opts = resolve_fn(symbol, current_spot, step, "PE", 0)
        ce_map = {c["strike"]: c for c in ce_opts}
        pe_map = {p["strike"]: p for p in pe_opts}
        for strike in sorted(set(ce_map) & set(pe_map)):
            ce, pe = ce_map[strike], pe_map[strike]
            for side, opt in [("CE", ce), ("PE", pe)]:
                df_e = fetch_and_resample_candles(kite, opt["token"], from_d, to_d, timeframe_entry)
                df_a = fetch_and_resample_candles(kite, opt["token"], from_d, to_d, timeframe_anchor)
                if len(df_e) < 5 or len(df_a) < 5:
                    continue
                result = scan_anchor_bcd_breakout(df_e, df_a)
                if result:
                    return {"SL": result["SL"], "T1": result["T1"], "T2": result["T2"], "T3": result["T3"], "pattern": result["Pattern"], "side": side, "strike": strike}
                anchor_scanners = [find_anchor_bullish_engulfing, find_anchor_ll_sweep, find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs]
                for scanner in anchor_scanners:
                    res = scanner(df_a)
                    if res:
                        t1, t2, t3 = find_profit_targets(df_a, entry_price, stop_loss=res.get("SL"))
                        if t1:
                            return {"SL": res["SL"], "T1": t1, "T2": t2, "T3": t3, "pattern": res["Pattern"], "side": side, "strike": strike}
        return None
    except Exception as e:
        logging.warning(f"SL/Target derivation failed for {symbol}: {e}")
        return None

def reconcile_positions(kite, registry, positions_dict, lock, engine, timeframe_entry, timeframe_anchor, lookback_days, resolve_fn, save_state_fn=None):
    """Cross-reference ACTIVE_POSITIONS against Kite open positions and DB."""
    today = dt.now().strftime("%Y-%m-%d")
    kite_symbols = set()
    try:
        kite_pos = kite.positions()
        for plist in [kite_pos.get("day", []), kite_pos.get("net", [])]:
            for p in plist:
                sym = _match_registry_symbol(registry, p.get("tradingsymbol", ""))
                if sym and abs(int(p.get("quantity", 0))) > 0:
                    kite_symbols.add(sym)
    except Exception as e:
        logging.warning(f"Kite position fetch for reconciliation failed: {e}")
    import trade_db
    try:
        trade_db.reconcile_broker_live_positions(kite)
    except Exception as e:
        logging.warning(f"[RECONCILE] Live broker reconcile error: {e}")
    db_active = {t["symbol"] for t in trade_db.get_active_trades(engine) if t.get("symbol") in registry}
    with lock:
        stale_zero = [s for s, p in list(positions_dict.items())
                      if p.get("pattern") == "KITE_RECOVERED"
                      and p.get("position_type") != "stock"
                      and (p.get("entry_spot") or 0) == 0
                      and (p.get("current_sl") or 0) == 0]
        for s in stale_zero:
            logging.info(f"[RECONCILE] Removing stale KITE_RECOVERED ghost: {s}")
            tid = positions_dict[s].get("trade_id")
            if tid:
                try: trade_db.remove_trades([tid])
                except Exception: pass
            positions_dict.pop(s, None)
        if stale_zero:
            logging.info(f"[RECONCILE] Purged {len(stale_zero)} ghost positions")
        stale = [s for s in positions_dict if s not in registry] + \
                [s for s in positions_dict if s in registry and s not in kite_symbols and s not in db_active]
        for s in stale:
            pos = positions_dict[s]
            tid = pos.get("trade_id")
            logging.info(f"[RECONCILE] Removing stale position: {s}")
            if tid:
                trade_db.remove_trades([tid])
            positions_dict.pop(s, None)
        for s, pos in list(positions_dict.items()):
            now_str = dt.now().isoformat()
            if "entry_time" not in pos:
                pos["entry_time"] = now_str
            entry_date = pos["entry_time"][:10] if isinstance(pos["entry_time"], str) else today
            pos["carry_forward"] = entry_date < today
            if (pos.get("current_sl") or 0) == 0 or (pos.get("t1") or 0) == 0:
                db_found = False
                contract = pos.get("contract", "")
                if contract:
                    all_trades = trade_db.get_all_trades(engine)
                    for t in all_trades:
                        if t.get("contract") == contract and t.get("current_sl") and t.get("t1"):
                            pos["current_sl"] = t["current_sl"]
                            pos["t1"] = t["t1"]
                            pos["t2"] = t.get("t2")
                            pos["t3"] = t.get("t3")
                            pos["timeframe"] = t.get("timeframe", pos.get("timeframe", timeframe_entry))
                            pos["pattern"] = t.get("pattern", pos.get("pattern", "DB_RECOVERED"))
                            db_found = True
                            logging.info(f"[RECONCILE] Restored SL/Targets for {s} from DB: SL={pos['current_sl']} T1={pos['t1']} TF={pos['timeframe']}")
                            tid = pos.get("trade_id")
                            if tid:
                                trade_db.update_trade(tid, {"current_sl": pos["current_sl"], "t1": pos["t1"], "t2": pos["t2"], "t3": pos["t3"], "timeframe": pos["timeframe"]})
                            break
                if not db_found:
                    config = registry.get(s)
                    if config:
                        result = derive_sl_targets_for_symbol(kite, s, pos.get("entry_spot", 0), registry, timeframe_entry, timeframe_anchor, lookback_days, resolve_fn)
                        if result:
                            pos["current_sl"] = result["SL"]
                            pos["t1"] = result["T1"]
                            pos["t2"] = result["T2"]
                            pos["t3"] = result["T3"]
                            pos["pattern"] = result.get("pattern", pos.get("pattern", "DERIVED"))
                            pos["side"] = result.get("side", pos.get("side", "CE"))
                            pos["strike"] = result.get("strike", pos.get("strike", 0))
                            tid = pos.get("trade_id")
                            if tid:
                                trade_db.update_trade(tid, {"current_sl": result["SL"], "t1": result["T1"], "t2": result["T2"], "t3": result["T3"], "pattern": pos["pattern"]})
                            logging.info(f"[RECONCILE] Derived SL/Targets for {s}: SL={result['SL']} T1={result['T1']} T2={result['T2']} T3={result['T3']}")
                        else:
                            logging.info(f"[RECONCILE] No pattern match for {s}, leaving as passive tracking")
    SL_TARGET_OVERRIDES_FILE = get_override_paths()[0]
    if os.path.exists(SL_TARGET_OVERRIDES_FILE):
        try:
            from dashboard_sl_overrides import clean_stale_overrides, sanitize_sl_and_entry
            clean_stale_overrides()
            with open(SL_TARGET_OVERRIDES_FILE) as f:
                eng_overrides = json.load(f).get(engine, {})
            for sym, vals in eng_overrides.items():
                if sym in positions_dict:
                    e_s = float(positions_dict[sym].get("entry_spot") or positions_dict[sym].get("entry_price") or 0.0)
                    sl_override = float(vals.get("current_sl") or 0.0)
                    st_val = int(positions_dict[sym].get("trailing_stage") or 0)
                    side_val = positions_dict[sym].get("side", "CE")
                    
                    if e_s > 0 and sl_override > 0:
                        _, safe_sl = sanitize_sl_and_entry(e_s, sl_override, st_val, side_val)
                        if safe_sl != sl_override and st_val == 0:
                            logging.warning(f"[RECONCILE] Inverted SL override sanitized for {sym}: SL {sl_override} -> {safe_sl} (Entry: {e_s})")
                            vals["current_sl"] = safe_sl

                    for k in ("current_sl", "t1", "t2", "t3"):
                        if k in vals:
                            positions_dict[sym][k] = vals[k]
                    tid = positions_dict[sym].get("trade_id")
                    if tid:
                        trade_db.update_trade(tid, {k: positions_dict[sym][k] for k in ("current_sl", "t1", "t2", "t3") if k in positions_dict[sym]})
                    logging.info(f"[RECONCILE] Re-applied override for {sym}: SL={positions_dict[sym].get('current_sl')} T1={positions_dict[sym].get('t1')}")
        except Exception as e:
            logging.warning(f"Override re-apply failed: {e}")
    if save_state_fn:
        save_state_fn()

def is_anchor_valid_and_active(df_anchor, candle_a_time, sl_target, t1_target, t2_target=None, entry_price=None, side="BULL"):
    """
    Generic Universal Rule (Anchor TF Specific):
    For a given Anchor TF dataframe (`df_anchor`), verify that:
    1. Anchor is newest/valid.
    2. No subsequent candle on this Anchor TF closed below SL (closing basis for SL).
    3. No subsequent candle on this Anchor TF reached T1 / 80% T1 exhaustion:
       - If price achieves >= 80% of move to T1:
         * If T2 is not available -> Discard (T1 exhausted).
         * If T2 is available but gap between T1 and T2 is too small (< 5% expansion) -> Discard (T1/T2 compression).
         * If subsequent candle also reached T2 -> Discard (T2 exhausted).
    Returns True if Anchor is valid and active; False if invalidated or already completed.
    """
    if df_anchor is None or df_anchor.empty or not candle_a_time:
        return True
    try:
        c_time_clean = clean_timestamp(candle_a_time)
        if 'date' not in df_anchor.columns or not c_time_clean:
            return True
        
        # Normalize date strings using clean_timestamp to strip timezone offsets (+05:30) before comparison
        dates_clean = df_anchor['date'].astype(str).apply(clean_timestamp)
        subseq = df_anchor[dates_clean > c_time_clean]
        if subseq.empty:
            return True
        
        sl_val = float(sl_target) if sl_target else 0.0
        t1_val = float(t1_target) if t1_target else 0.0
        t2_val = float(t2_target) if (t2_target is not None and t2_target != "N/A" and float(t2_target or 0) > 0) else None
        ep_val = float(entry_price) if (entry_price is not None and float(entry_price or 0) > 0) else None
        is_bear = str(side or "").upper() in ["BEAR", "PE", "SELL"]
        
        # Rule 1: Discard if any subsequent Anchor TF candle closed below SL (Bull) or above SL (Bear)
        if sl_val > 0:
            if is_bear:
                if (subseq['close'].astype(float) >= sl_val).any():
                    return False
            else:
                if (subseq['close'].astype(float) <= sl_val).any():
                    return False
            
        # Rule 2: Check T1 and 80% T1 exhaustion
        if t1_val > 0:
            if not is_bear:
                # Bullish: 80% T1 threshold
                t1_80 = (ep_val + 0.80 * (t1_val - ep_val)) if (ep_val and t1_val > ep_val) else t1_val
                max_subseq_high = float(subseq['high'].astype(float).max())
                
                # Check if T1 or 80% of T1 was reached
                if max_subseq_high >= t1_80 or max_subseq_high >= t1_val:
                    # If no T2 available -> Invalidate (T1 hit / exhausted)
                    if t2_val is None or t2_val <= t1_val:
                        return False
                    # If T2 is available, check if T1 to T2 gap is too small (< 10% expansion)
                    gap_pct = (t2_val - t1_val) / t1_val
                    if gap_pct < 0.10:
                        return False  # Less gap with T2 (< 10%) -> Ignore scan
                    # If subsequent price already reached T2 as well -> Invalidate
                    if max_subseq_high >= t2_val:
                        return False
            else:
                # Bearish: 80% T1 threshold
                t1_80 = (ep_val - 0.80 * (ep_val - t1_val)) if (ep_val and ep_val > t1_val) else t1_val
                min_subseq_low = float(subseq['low'].astype(float).min())
                
                # Check if T1 or 80% of T1 was reached
                if min_subseq_low <= t1_80 or min_subseq_low <= t1_val:
                    # If no T2 available -> Invalidate
                    if t2_val is None or t2_val >= t1_val:
                        return False
                    # If T2 is available, check gap (< 10%)
                    gap_pct = (t1_val - t2_val) / t1_val
                    if gap_pct < 0.10:
                        return False  # Less gap with T2 (< 10%) -> Ignore scan
                    # If subsequent price already reached T2 as well -> Invalidate
                    if min_subseq_low <= t2_val:
                        return False
            
        return True
    except Exception as e:
        logging.warning(f"Error checking anchor validity: {e}")
        return True

def get_anchor_invalidation_reason(df_anchor, candle_a_time, sl_target, t1_target, t2_target=None, entry_price=None, side="BULL"):
    """
    Returns 'SL', 'T1 (80%+ Reached, No T2)', 'T1 (80%+ Reached, T2 Gap < 10%)', 'T2 (Reached)',
    or None if the anchor is still valid/active.
    """
    if df_anchor is None or df_anchor.empty or not candle_a_time:
        return None
    try:
        c_time_clean = clean_timestamp(candle_a_time)
        if 'date' not in df_anchor.columns or not c_time_clean:
            return None
        dates_clean = df_anchor['date'].astype(str).apply(clean_timestamp)
        subseq = df_anchor[dates_clean > c_time_clean]
        if subseq.empty:
            return None
        sl_val = float(sl_target) if sl_target else 0.0
        t1_val = float(t1_target) if t1_target else 0.0
        t2_val = float(t2_target) if (t2_target is not None and t2_target != "N/A" and float(t2_target or 0) > 0) else None
        ep_val = float(entry_price) if (entry_price is not None and float(entry_price or 0) > 0) else None
        is_bear = str(side or "").upper() in ["BEAR", "PE", "SELL"]

        if sl_val > 0:
            if is_bear and (subseq['close'].astype(float) >= sl_val).any():
                return "SL"
            elif not is_bear and (subseq['close'].astype(float) <= sl_val).any():
                return "SL"

        if t1_val > 0:
            if not is_bear:
                t1_80 = (ep_val + 0.80 * (t1_val - ep_val)) if (ep_val and t1_val > ep_val) else t1_val
                max_high = float(subseq['high'].astype(float).max())
                if max_high >= t1_80 or max_high >= t1_val:
                    if t2_val is None or t2_val <= t1_val:
                        return "T1 (80%+ Reached, No T2)"
                    gap_pct = (t2_val - t1_val) / t1_val
                    if gap_pct < 0.10:
                        return "T1 (80%+ Reached, T2 Gap < 10%)"
                    if max_high >= t2_val:
                        return "T2 (Reached)"
            else:
                t1_80 = (ep_val - 0.80 * (ep_val - t1_val)) if (ep_val and ep_val > t1_val) else t1_val
                min_low = float(subseq['low'].astype(float).min())
                if min_low <= t1_80 or min_low <= t1_val:
                    if t2_val is None or t2_val >= t1_val:
                        return "T1 (80%+ Reached, No T2)"
                    gap_pct = (t1_val - t2_val) / t1_val
                    if gap_pct < 0.10:
                        return "T1 (80%+ Reached, T2 Gap < 10%)"
                    if min_low <= t2_val:
                        return "T2 (Reached)"
        return None
    except Exception as e:
        logging.warning(f"Error checking anchor invalidation reason: {e}")
        return None

def is_setup_already_completed(df_candles, candle_time, t1_target, sl_target, t2_target=None, entry_price=None, side="BULL"):
    """Return True if setup was completed or invalidated."""
    return not is_anchor_valid_and_active(df_candles, candle_time, sl_target, t1_target, t2_target=t2_target, entry_price=entry_price, side=side)

def find_newest_valid_anchor(df):
    """
    Scans `df` (Anchor TF candles) starting from the NEWEST candle going backwards.
    Finds the first (newest) valid Anchor pattern where:
    1. Pattern detector matches an Anchor (LL Sweep, Engulfing, Baby Candle, Harami, Two HH).
    2. No subsequent candle in `df` closed below SL (closing basis).
    3. No subsequent candle in `df` touched T1 (high >= T1).
    Returns the newest valid anchor dict (with T1, T2, T3, RR), or None.
    """
    if df is None or len(df) < 5:
        return None

    scanners = [
        find_anchor_ll_sweep,
        find_anchor_bullish_engulfing,
        find_anchor_hammer_baby,
        find_anchor_bullish_harami,
        find_anchor_two_higher_highs,
    ]

    for end_idx in range(len(df), 4, -1):
        sub_df = df.iloc[:end_idx]
        for scanner_func in scanners:
            result = scanner_func(sub_df)
            if result:
                candle_a_time = str(result.get("CandleATime") or "")
                sl_val = result["SL"]
                t1, t2, t3 = find_profit_targets(df, result["Close"], stop_loss=sl_val)
                
                # Check validity on all subsequent candles in the full dataframe
                if is_anchor_valid_and_active(df, candle_a_time, sl_val, t1, t2_target=t2, entry_price=result["Close"], side="BULL"):
                    risk = round(result["Close"] - sl_val, 2) if (result["Close"] > sl_val) else 0.0
                    rr = round((t1 - result["Close"]) / risk, 2) if (t1 and risk > 0) else 0.0
                    return {
                        "Pattern": result["Pattern"],
                        "Close": result["Close"],
                        "SL": sl_val,
                        "T1": t1, "T2": t2, "T3": t3,
                        "RR": rr,
                        "CandleATime": candle_a_time
                    }
    return None


def scan_symbol(kite, symbol, config, from_entry, to_entry, from_anchor, to_anchor,
                entry_scanners, anchor_scanners, resolve_fn, engine_name,
                timeframe_entry, timeframe_anchor, timeframe_fallback,
                active_positions, position_lock, trade_db, strike_range,
                log_fn, spot_ltp=None):
    trades = []
    df_spot = None
    macro_bias = None  # 'CE' (Spot >= 13 EMA) or 'PE' (Spot < 13 EMA)
    current_spot = float(spot_ltp) if spot_ltp and float(spot_ltp) > 0 else 0.0
    token = config.get("token")
    if current_spot <= 0:
        try:
            spot_quote = safe_kite_call(kite.ltp, [f"NSE:{symbol}"])
            if f"NSE:{symbol}" in spot_quote:
                current_spot = float(spot_quote[f"NSE:{symbol}"]["last_price"])
                real_tok = spot_quote[f"NSE:{symbol}"].get("instrument_token")
                if real_tok and token != real_tok:
                    token = int(real_tok)
                    config["token"] = token
            else:
                spot_quote = safe_kite_call(kite.ltp, [token])
                current_spot = float(list(spot_quote.values())[0]["last_price"])
        except Exception:
            pass

    try:
        df_spot = safe_kite_call(fetch_and_resample_candles, kite, config["token"], from_entry, to_entry, timeframe_entry)
        if df_spot is not None and not df_spot.empty:
            if current_spot <= 0:
                current_spot = float(df_spot.iloc[-1]['close'])
        else:
            if current_spot <= 0:
                return []
    except Exception as e:
        err_str = str(e).lower()
        if "invalid token" in err_str or "not found" in err_str:
            try:
                q = kite.quote([f"NSE:{symbol}"])
                if f"NSE:{symbol}" in q:
                    real_tok = int(q[f"NSE:{symbol}"]["instrument_token"])
                    config["token"] = real_tok
                    from registries import STOCK_REGISTRY
                    if symbol in STOCK_REGISTRY:
                        STOCK_REGISTRY[symbol]["token"] = real_tok
                    df_spot = safe_kite_call(fetch_and_resample_candles, kite, real_tok, from_entry, to_entry, timeframe_entry)
                    if df_spot is not None and not df_spot.empty and current_spot <= 0:
                        current_spot = float(df_spot.iloc[-1]['close'])
            except Exception as auto_e:
                logging.warning(f"Spot auto-repair failed for {symbol}: {auto_e}")
                return []
        if current_spot <= 0 and (df_spot is None or df_spot.empty):
            logging.warning(f"Spot data failed for {symbol}: {e}")
            return []

    # Layer 1: Spot Macro Trend Calculation (13 EMA on Anchor / Entry Timeframe)
    try:
        if df_spot is None or len(df_spot) < 13:
            df_spot = safe_kite_call(fetch_and_resample_candles, kite, config["token"], from_anchor, to_anchor, timeframe_anchor)
        if df_spot is not None and len(df_spot) >= 13:
            ema_13 = float(df_spot['close'].ewm(span=13, adjust=False).mean().iloc[-1])
            spot_close = float(df_spot.iloc[-1]['close'])
            macro_bias = "CE" if spot_close >= ema_13 else "PE"
            logging.debug(f"[MACRO_TREND] {symbol}: Spot={spot_close:.2f} vs EMA13={ema_13:.2f} -> MacroBias={macro_bias}")
    except Exception as e:
        logging.debug(f"Spot EMA calculation error for {symbol}: {e}")

    # Layer 3: Mutual Exclusivity Guard — Check existing active position on this symbol
    existing_active_side = None
    with position_lock:
        if active_positions:
            for ak, av in active_positions.items():
                if av.get("symbol") == symbol or ak == symbol:
                    cntr = str(av.get("contract") or "").upper()
                    existing_active_side = "PE" if "PE" in cntr else "CE"
                    break

    ce_list = resolve_fn(symbol, current_spot, config['strike_step'], "CE", strike_range)
    pe_list = resolve_fn(symbol, current_spot, config['strike_step'], "PE", strike_range)
    ce_map = {c["strike"]: c for c in ce_list}
    pe_map = {p["strike"]: p for p in pe_list}

    symbol_candidates = []

    spot_low_10 = float(df_spot['low'].iloc[-10:].min()) if df_spot is not None and not df_spot.empty else (current_spot * 0.98 if current_spot > 0 else 0.0)
    spot_high_10 = float(df_spot['high'].iloc[-10:].max()) if df_spot is not None and not df_spot.empty else (current_spot * 1.02 if current_spot > 0 else 0.0)
    spot_sl_ce = calculate_sl_buffer(spot_low_10, side="BULL") if spot_low_10 > 0 else 0.0
    spot_sl_pe = calculate_sl_buffer(spot_high_10, side="BEAR") if spot_high_10 > 0 else 0.0

    for strike in sorted(set(ce_map) & set(pe_map)):
        ce = ce_map[strike]
        pe = pe_map[strike]
        same_tf = timeframe_entry == timeframe_anchor and from_entry == from_anchor and to_entry == to_anchor
        dfs = {}
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                tasks = {
                    pool.submit(fetch_and_resample_candles, kite, ce["token"], from_entry, to_entry, timeframe_entry): ("ce", "entry"),
                    pool.submit(fetch_and_resample_candles, kite, pe["token"], from_entry, to_entry, timeframe_entry): ("pe", "entry"),
                }
                if not same_tf:
                    tasks[pool.submit(fetch_and_resample_candles, kite, ce["token"], from_anchor, to_anchor, timeframe_anchor)] = ("ce", "anchor")
                    tasks[pool.submit(fetch_and_resample_candles, kite, pe["token"], from_anchor, to_anchor, timeframe_anchor)] = ("pe", "anchor")
                for f in as_completed(tasks):
                    tag, kind = tasks[f]
                    try:
                        dfs[(tag, kind)] = pd.DataFrame(f.result())
                    except Exception as e:
                        logging.warning(f"{tag} {kind} failed for {symbol} {strike}: {e}")
                        dfs[(tag, kind)] = pd.DataFrame()
        except Exception as e:
            logging.warning(f"Contract data failed for {symbol} {strike}: {e}")
            continue
        if same_tf:
            dfs[("ce", "anchor")] = dfs.get(("ce", "entry"), pd.DataFrame())
            dfs[("pe", "anchor")] = dfs.get(("pe", "entry"), pd.DataFrame())
        for tag_key, kind_key, from_d, to_d in [
            ("ce", "entry", from_entry, to_entry),
            ("pe", "entry", from_entry, to_entry),
            ("ce", "anchor", from_anchor, to_anchor),
            ("pe", "anchor", from_anchor, to_anchor),
        ]:
            if same_tf and kind_key == "anchor":
                continue
            df = dfs.get((tag_key, kind_key), pd.DataFrame())
            if len(df) < 5:
                tok = ce["token"] if tag_key == "ce" else pe["token"]
                tf = timeframe_entry if kind_key == "entry" else timeframe_anchor
                dfs[(tag_key, kind_key)] = fetch_option_data(kite, tok, from_d, to_d, tf, timeframe_fallback)
        if same_tf:
            dfs[("ce", "anchor")] = dfs.get(("ce", "entry"), pd.DataFrame())
            dfs[("pe", "anchor")] = dfs.get(("pe", "entry"), pd.DataFrame())
        df_ce_e = dfs.get(("ce", "entry"), pd.DataFrame())
        df_pe_e = dfs.get(("pe", "entry"), pd.DataFrame())
        df_ce_a = dfs.get(("ce", "anchor"), pd.DataFrame())
        df_pe_a = dfs.get(("pe", "anchor"), pd.DataFrame())
        if df_ce_e.empty or df_pe_e.empty:
            continue

        cfg_engine = load_program_config_for_engine(engine_name)
        enable_swing = bool(cfg_engine.get("ENABLE_SWING_FILTER", False))
        swing_min_w = int(cfg_engine.get("SWING_MIN_WAVES", 3))
        swing_r2 = float(cfg_engine.get("SWING_MIN_R2", 0.55))

        swing_meta_ce = {"swing_waves": 0, "terminal_base": False, "terminal_date": ""}
        swing_meta_pe = {"swing_waves": 0, "terminal_base": False, "terminal_date": ""}
        if enable_swing:
            if not df_ce_a.empty:
                sw_ce = detect_parabolic_multi_swings(df_ce_a, side="BULL", min_swings=swing_min_w, min_r2=swing_r2, max_bars_after_terminal=45, symbol=symbol, timeframe_str=timeframe_anchor)
                if sw_ce:
                    swing_meta_ce["swing_waves"] = sw_ce.get("valid_arch_count", 0)
                    swing_meta_ce["terminal_base"] = sw_ce.get("has_terminal_base", False)
                    swing_meta_ce["terminal_date"] = sw_ce.get("terminal_date", "")

            if not df_pe_a.empty:
                sw_pe = detect_parabolic_multi_swings(df_pe_a, side="BULL", min_swings=swing_min_w, min_r2=swing_r2, max_bars_after_terminal=45, symbol=symbol, timeframe_str=timeframe_anchor)
                if sw_pe:
                    swing_meta_pe["swing_waves"] = sw_pe.get("valid_arch_count", 0)
                    swing_meta_pe["terminal_base"] = sw_pe.get("has_terminal_base", False)
                    swing_meta_pe["terminal_date"] = sw_pe.get("terminal_date", "")

        if df_ce_e.empty and df_pe_e.empty:
            continue

        for name, scanner in entry_scanners:
            if not df_ce_e.empty:
                # Layer 3 Check: Skip CE if an active PE position already exists
                if existing_active_side == "PE":
                    logging.info(f"[MUTUAL_EXCLUSIVITY] Skipping CE scan for {symbol} ({ce['tradingsymbol']}) because active PE position exists.")
                else:
                    result_ce = scanner(df_ce_e, df_ce_a)
                    if result_ce:
                        candle_time = str(result_ce.get("CandleTime") or df_ce_e.iloc[-1]['date'])
                        candle_a_time = str(result_ce.get("CandleATime", ""))
                        if enable_swing and swing_meta_ce["terminal_date"] and candle_a_time:
                            a_dt_str = clean_timestamp(candle_a_time)
                            term_dt_str = clean_timestamp(swing_meta_ce["terminal_date"])
                            if a_dt_str and term_dt_str and a_dt_str[:10] < term_dt_str[:10]:
                                logging.info(f"CE SKIP {ce['tradingsymbol']}: Anchor A ({a_dt_str}) preceded terminal swing base ({term_dt_str})")
                                continue

                        if result_ce["Close"] < 300 and result_ce["T1"] > result_ce["Close"] * 5:
                            log_fn(ce['tradingsymbol'], result_ce["Pattern"], timeframe_entry,
                                   "SCAN_MATCH", "NO_TARGETS", "Stale ITM regime targets",
                                   entry=result_ce["Close"], sl=result_ce["SL"],
                                   target=0, rr=0, event_time=candle_time)
                            continue

                        if not is_anchor_valid_and_active(df_ce_a, candle_a_time or candle_time, result_ce.get("SL"), result_ce.get("T1"), t2_target=result_ce.get("T2"), entry_price=result_ce.get("Close"), side="BULL"):
                            invalid_reason = get_anchor_invalidation_reason(df_ce_a, candle_a_time or candle_time, result_ce.get("SL"), result_ce.get("T1"), t2_target=result_ce.get("T2"), entry_price=result_ce.get("Close"), side="BULL")
                            skip_reason = f"already completed {invalid_reason} (skip)" if invalid_reason else "already completed (skip)"
                            logging.info(f"CE MATCH {skip_reason}: {ce['tradingsymbol']} | {result_ce['Pattern']}")
                            continue

                        ce_lot = int(ce.get("lot_size") or config.get("lot_size", 1))
                        pos_size = calculate_position_size(
                            spot_price=result_ce["Close"],
                            stop_loss=result_ce["SL"],
                            capital=float(cfg_engine.get("capital") or 100000.0),
                            risk_percent=float(cfg_engine.get("MAX_RISK_PERCENT") or 1.0),
                            lot_size=ce_lot,
                            is_option=True
                        )
                        trade_data = {
                            "symbol": symbol, "contract": ce['tradingsymbol'], "option_token": ce['token'],
                            "index_token": config["token"], "spot_token": config["token"], "spot_entry": current_spot,
                            "spot_sl": spot_sl_ce, "strike": strike, "entry_spot": result_ce["Close"],
                            "current_sl": result_ce["SL"], "t1": result_ce["T1"], "t2": result_ce["T2"],
                            "t3": result_ce["T3"], "rr": result_ce.get("RR"), "trailing_stage": 0,
                            "lot_size": ce_lot, "position_size": pos_size,
                            "pattern": result_ce["Pattern"], "timeframe": timeframe_entry, "side": "CE",
                            "strike_step": config["strike_step"], "entry_time": candle_time,
                            "candle_a_time": candle_a_time,
                            "benchmark": result_ce.get("Benchmark"), "anchor_floor": result_ce.get("AnchorFloor"),
                            "direction": result_ce.get("Direction", "BULL"),
                            "swing_waves": swing_meta_ce["swing_waves"],
                            "terminal_base": swing_meta_ce["terminal_base"],
                            "tier": result_ce.get("tier", 2),
                            "tier_label": result_ce.get("tier_label", "TIER_2_CORE"),
                            "tier_badge": result_ce.get("tier_badge", "🥈 T2")
                        }
                        symbol_candidates.append(trade_data)

            if not df_pe_e.empty:
                # Layer 3 Check: Skip PE if an active CE position already exists
                if existing_active_side == "CE":
                    logging.info(f"[MUTUAL_EXCLUSIVITY] Skipping PE scan for {symbol} ({pe['tradingsymbol']}) because active CE position exists.")
                else:
                    result_pe = scanner(df_pe_e, df_pe_a)
                    if result_pe:
                        candle_time = str(result_pe.get("CandleTime") or df_pe_e.iloc[-1]['date'])
                        candle_a_time = str(result_pe.get("CandleATime", ""))
                        if enable_swing and swing_meta_pe["terminal_date"] and candle_a_time:
                            a_dt_str = clean_timestamp(candle_a_time)
                            term_dt_str = clean_timestamp(swing_meta_pe["terminal_date"])
                            if a_dt_str and term_dt_str and a_dt_str[:10] < term_dt_str[:10]:
                                logging.info(f"PE SKIP {pe['tradingsymbol']}: Anchor A ({a_dt_str}) preceded terminal swing base ({term_dt_str})")
                                continue

                        if result_pe["Close"] < 300 and result_pe["T1"] > result_pe["Close"] * 5:
                            log_fn(pe['tradingsymbol'], result_pe["Pattern"], timeframe_entry,
                                   "SCAN_MATCH", "NO_TARGETS", "Stale ITM regime targets",
                                   entry=result_pe["Close"], sl=result_pe["SL"],
                                   target=0, rr=0, event_time=candle_time)
                            continue

                        if not is_anchor_valid_and_active(df_pe_a, candle_a_time or candle_time, result_pe.get("SL"), result_pe.get("T1"), t2_target=result_pe.get("T2"), entry_price=result_pe.get("Close"), side="BEAR"):
                            invalid_reason = get_anchor_invalidation_reason(df_pe_a, candle_a_time or candle_time, result_pe.get("SL"), result_pe.get("T1"), t2_target=result_pe.get("T2"), entry_price=result_pe.get("Close"), side="BEAR")
                            skip_reason = f"already completed {invalid_reason} (skip)" if invalid_reason else "already completed (skip)"
                            logging.info(f"PE MATCH {skip_reason}: {pe['tradingsymbol']} | {result_pe['Pattern']}")
                            continue

                        pe_lot = int(pe.get("lot_size") or config.get("lot_size", 1))
                        pos_size = calculate_position_size(
                            spot_price=result_pe["Close"],
                            stop_loss=result_pe["SL"],
                            capital=float(cfg_engine.get("capital") or 100000.0),
                            risk_percent=float(cfg_engine.get("MAX_RISK_PERCENT") or 1.0),
                            lot_size=pe_lot,
                            is_option=True
                        )
                        trade_data = {
                            "symbol": symbol, "contract": pe['tradingsymbol'], "option_token": pe['token'],
                            "index_token": config["token"], "spot_token": config["token"], "spot_entry": current_spot,
                            "spot_sl": spot_sl_pe, "strike": strike, "entry_spot": result_pe["Close"],
                            "current_sl": result_pe["SL"], "t1": result_pe["T1"], "t2": result_pe["T2"],
                            "t3": result_pe["T3"], "rr": result_pe.get("RR"), "trailing_stage": 0,
                            "lot_size": pe_lot, "position_size": pos_size,
                            "pattern": result_pe["Pattern"], "timeframe": timeframe_entry, "side": "PE",
                            "strike_step": config["strike_step"], "entry_time": candle_time,
                            "candle_a_time": candle_a_time,
                            "benchmark": result_pe.get("Benchmark"), "anchor_floor": result_pe.get("AnchorFloor"),
                            "direction": result_pe.get("Direction", "BULL"),
                            "swing_waves": swing_meta_pe["swing_waves"],
                            "terminal_base": swing_meta_pe["terminal_base"],
                            "tier": result_pe.get("tier", 2),
                            "tier_label": result_pe.get("tier_label", "TIER_2_CORE"),
                            "tier_badge": result_pe.get("tier_badge", "🥈 T2")
                        }
                        symbol_candidates.append(trade_data)

        for name, scanner in anchor_scanners:
            res_ce = scanner(df_ce_a) if not df_ce_a.empty else None
            if res_ce:
                logging.info(f"ANCHOR FORMED: {ce['tradingsymbol']} | {res_ce['Pattern']} | Close: {res_ce['Close']:.2f} | SL: {res_ce['SL']:.2f}")
                continue
            res_pe = scanner(df_pe_a) if not df_pe_a.empty else None
            if res_pe:
                logging.info(f"ANCHOR FORMED: {pe['tradingsymbol']} | {res_pe['Pattern']} | Close: {res_pe['Close']:.2f} | SL: {res_pe['SL']:.2f}")

    # Layer 2: Dominant Conviction Arbitrage — Select Single Best Setup per Symbol
    if symbol_candidates:
        strict_gate = cfg_engine.get("STRICT_MACRO_GATE", False) or cfg_engine.get("strict_macro_gate", False)
        strict_gate = True if str(strict_gate).lower() == "true" else bool(strict_gate)

        # Step 1: Filter candidates by Spot Macro Trend Bias if available
        preferred_candidates = [c for c in symbol_candidates if c.get("side") == macro_bias] if macro_bias else []
        if strict_gate and macro_bias:
            if not preferred_candidates:
                logging.info(f"[STRICT_MACRO_GATE] Suppressed {symbol} counter-trend candidates because Spot is {macro_bias}-biased and Strict Gate is ON.")
                pool = []
            else:
                pool = preferred_candidates
        else:
            # Mode 1 (Default): Soft Conflict Arbiter — Prefer aligned candidates, fallback if only one side formed
            pool = preferred_candidates if preferred_candidates else symbol_candidates

        if pool:
            # Step 2: Moneyness Classification & Far OTM Filtering
            # Moneyness classification:
            #   0: 1-Step ITM or ATM (Highest Priority: resilient Delta ~0.50-0.60, narrowest spread)
            #   1: 1-Step OTM (Permissible for high-velocity momentum)
            #   2: Deep ITM
            #   3: Far OTM (Distance > 1.25 * strike_step -> Strictly Rejected by Moneyness Guard)
            def _calc_moneyness_rank(c):
                strike_val = float(c.get("strike", 0))
                side_val = str(c.get("side", "CE")).upper()
                step_val = float(c.get("strike_step") or 50.0)
                dist = abs(strike_val - current_spot)
                # True ATM (closest strike within half step) always qualifies as Rank 0
                is_atm = dist <= (step_val * 0.55)
                if side_val == "CE":
                    if is_atm or (strike_val < current_spot and (current_spot - strike_val) <= (step_val * 1.25)):
                        return 0  # ATM or 1-Step ITM
                    elif strike_val > current_spot and (strike_val - current_spot) <= (step_val * 1.25):
                        return 1  # 1-Step OTM
                    elif strike_val < current_spot:
                        return 2  # Deep ITM
                    else:
                        return 3  # Far OTM (> 1.25 steps away)
                else: # PE
                    if is_atm or (strike_val > current_spot and (strike_val - current_spot) <= (step_val * 1.25)):
                        return 0  # ATM or 1-Step ITM
                    elif strike_val < current_spot and (current_spot - strike_val) <= (step_val * 1.25):
                        return 1  # 1-Step OTM
                    elif strike_val > current_spot:
                        return 2  # Deep ITM
                    else:
                        return 3  # Far OTM (> 1.25 steps away)

            # Hard Moneyness Guard: Strictly reject Far OTM strikes (Rank 3) to protect against Delta collapse & Theta decay
            non_far_otm = [c for c in pool if _calc_moneyness_rank(c) < 3]
            if non_far_otm:
                pool = non_far_otm
            else:
                logging.info(f"[MONEYNESS_GUARD] Suppressed {symbol} options: All candidates are far OTM (> 1 strike step from spot {current_spot:.2f}).")
                pool = []

            if pool:
                def _candidate_rank(c):
                    m_rank = _calc_moneyness_rank(c)
                    tier_val = int(c.get("tier", 2))
                    rr_val = float(c.get("rr") or 0.0)
                    ep = float(c.get("entry_spot") or 0.0)
                    t1 = float(c.get("t1") or 0.0)
                    net_profit = max(0.0, t1 - ep)
                    strike_val = float(c.get("strike", 0))
                    strike_dist = abs(strike_val - current_spot)
                    # Priority: 1. Moneyness (ATM/1-ITM first) -> 2. Tier (Gold/Core) -> 3. Profit -> 4. RR -> 5. Distance
                    return (m_rank, tier_val, -net_profit, -rr_val, strike_dist)

                pool.sort(key=_candidate_rank)
                best_trade = pool[0]

            logging.info(f"[ARBITRAGE WINNER] {symbol}: Selected {best_trade['contract']} ({best_trade['side']} | Strike {best_trade.get('strike')}) | Tier: {best_trade.get('tier_label')} | Profit: {float(best_trade.get('t1',0))-float(best_trade.get('entry_spot',0)):.2f} pts | RR: {best_trade.get('rr')} | MacroBias: {macro_bias} | StrictGate: {strict_gate}")

            # ── VIX Regime Gate Check ──
            vix_allowed, vix_reason, vix_val = evaluate_vix_regime(kite, tier_val=best_trade.get("tier", 2))
            best_trade["vix_allowed"] = vix_allowed
            best_trade["vix_reason"] = vix_reason
            best_trade["vix_val"] = vix_val
            if not vix_allowed:
                logging.info(f"[VIX_REGIME_GATE] Execution capped for {symbol} ({best_trade['contract']}): {vix_reason} (loaded for scan display)")

            # ── Portfolio Risk & Sector Caps Check ──
            cap_amount = float(cfg_engine.get("capital") or 100000.0)
            p_allowed, p_reason, p_details = check_portfolio_risk_caps(
                engine=engine_name,
                symbol=symbol,
                candidate_tier=best_trade.get("tier", 2),
                capital=cap_amount,
                live_positions=active_positions
            )
            best_trade["portfolio_risk_allowed"] = p_allowed
            best_trade["portfolio_risk_reason"] = p_reason
            if not p_allowed:
                logging.info(f"[PORTFOLIO_RISK_CAP] Execution capped for {symbol} ({best_trade['contract']}): {p_reason} (loaded for scan display)")
            
            live_flag = paths.INDEX_LIVE_FLAG if engine_name == "index" else paths.NIFTY50_LIVE_FLAG
            is_live = False
            try:
                if os.path.exists(live_flag):
                    with open(live_flag, "r") as f:
                        is_live = (f.read().strip() == "1")
            except Exception:
                is_live = False

            now_dt = get_ist_now()
            now_t = now_dt.time()
            is_weekday = now_dt.weekday() < 5
            if is_live and is_weekday and datetime_time(15, 20) < now_t <= datetime_time(15, 30):
                logging.info(f"[MARKET_CLOSE_LOCK] New trade staging suppressed for {symbol} ({best_trade['contract']}): Live execution is ON and current time {now_t.strftime('%H:%M:%S')} is past 15:20 IST entry cutoff.")
            else:
                trade_db.stage_cycle_trade(engine_name, best_trade)
                trades.append(best_trade)
                log_fn(best_trade['contract'], best_trade['pattern'], timeframe_entry,
                       "SCAN_MATCH", "STAGED",
                       f"Side={best_trade.get('side')} Strike={best_trade.get('strike')} RR={best_trade.get('rr','')} Tier={best_trade.get('tier_label','')} MacroBias={macro_bias}",
                       entry=best_trade['entry_spot'], sl=best_trade['current_sl'],
                       target=best_trade.get('t3',''), rr=best_trade.get('rr',''),
                       event_time=best_trade.get('entry_time',''))

    return trades



def simulate_trade_outcome(kite, trade, target_date, resolve_token_fn=None):
    try:
        if isinstance(target_date, str):
            try:
                target_date = dt.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                target_date = get_ist_date()
        elif target_date is None:
            target_date = get_ist_date()
        if isinstance(target_date, dt):
            target_date = target_date.date()
        sym = trade["symbol"]
        cp = trade["entry_spot"]
        side = trade.get("side", "CE")
        strike = trade.get("strike")
        strike_step = trade.get("strike_step", 50)
        token = trade.get("option_token")
        if not token and resolve_token_fn:
            target_strike = strike or int(round(cp / strike_step) * strike_step)
            opt_type = "CE" if side == "CE" else "PE"
            contract = resolve_token_fn(sym, cp, strike_step, opt_type, target_strike)
            if not contract:
                return {"result": None, "detail": "option_resolve_failed", "entry_time": None, "exit_time": None, "pnl_pct": None}
            token = contract
        if not token:
            return {"result": None, "detail": "no_token", "entry_time": None, "exit_time": None, "pnl_pct": None}
        entry = cp
        sl_val = trade["current_sl"]
        t1 = trade.get("t1")
        t2 = trade.get("t2")
        t3 = trade.get("t3")
        expiry_limit = target_date + timedelta(days=14)
        tf = trade.get("timeframe", "15minute") or "15minute"
        from_str = target_date.strftime("%Y-%m-%d")
        to_str = expiry_limit.strftime("%Y-%m-%d")
        for attempt in range(3):
            try:
                df = fetch_and_resample_candles(kite, token, from_str, to_str, tf)
                break
            except Exception as e:
                if "Too many requests" in str(e) and attempt < 2:
                    time.sleep(5)
                    continue
                raise
        if df.empty:
            return {"result": None, "detail": "no_data", "entry_time": None, "exit_time": None, "pnl_pct": None}
        entry_idx = None
        best_diff = float('inf')
        for i in range(len(df)):
            cclose = float(df.iloc[i]['close'])
            diff = abs(cclose - entry)
            if diff < best_diff:
                best_diff = diff
                entry_idx = i
        if entry_idx is None:
            return {"result": None, "detail": "entry_candle_not_found", "entry_time": None, "exit_time": None, "pnl_pct": None}
        if entry_idx >= len(df) - 1:
            return {"result": None, "detail": "no_subsequent_candles", "entry_time": None, "exit_time": None, "pnl_pct": None}
        entry_time = df.iloc[entry_idx]['date']
        for i in range(entry_idx + 1, len(df)):
            candle = df.iloc[i]
            low = float(candle['low'])
            high = float(candle['high'])
            if low <= sl_val:
                exit_time = candle['date']
                pnl = (sl_val - entry) / entry * 100
                return {"result": "SL_HIT", "detail": f"SL_HIT at {exit_time}", "entry_time": str(entry_time), "exit_time": str(exit_time), "pnl_pct": round(pnl, 2)}
            if t1 and high >= t1:
                exit_t = candle['date']
                if t3 and high >= t3:
                    pnl = (t3 - entry) / entry * 100
                    return {"result": "T3_HIT", "detail": f"T3_HIT at {exit_t}", "entry_time": str(entry_time), "exit_time": str(exit_t), "pnl_pct": round(pnl, 2)}
                if t2 and high >= t2:
                    pnl = (t2 - entry) / entry * 100
                    return {"result": "T2_HIT", "detail": f"T2_HIT at {exit_t}", "entry_time": str(entry_time), "exit_time": str(exit_t), "pnl_pct": round(pnl, 2)}
                pnl = (t1 - entry) / entry * 100
                return {"result": "T1_HIT", "detail": f"T1_HIT at {exit_t}", "entry_time": str(entry_time), "exit_time": str(exit_t), "pnl_pct": round(pnl, 2)}
        return {"result": "NO_EXIT", "detail": "No SL or target hit before expiry", "entry_time": str(entry_time), "exit_time": None, "pnl_pct": None}
    except Exception as e:
        logging.error(f"[SIM] Exception: {e}")
        return {"result": None, "detail": str(e), "entry_time": None, "exit_time": None, "pnl_pct": None}


def resolve_option_strikes(nfo_instruments, base_symbol, spot_price, step_size, option_type, n_range=0):
    """Return ATM strike plus n_range strikes ITM/OTM. nfo_instruments can be None for derived calls."""
    if nfo_instruments is None:
        return []
    if nfo_instruments is None or nfo_instruments.empty or 'name' not in nfo_instruments.columns:
        return []
    atm = int(round(spot_price / step_size) * step_size)
    out = []
    seen = set()
    for offset in range(-n_range, n_range + 1):
        strike = atm + offset * step_size
        if strike in seen:
            continue
        seen.add(strike)
        try:
            df = nfo_instruments[
                (nfo_instruments['name'] == base_symbol.strip().upper()) &
                (nfo_instruments['instrument_type'] == option_type.upper()) &
                (nfo_instruments['strike'] == float(strike))
            ].copy()
            if df.empty:
                continue
            df['expiry_dt'] = pd.to_datetime(df['expiry']).dt.date
            today = get_ist_date()
            future = df[df['expiry_dt'] >= today].sort_values(by='expiry_dt')
            if not future.empty:
                expiries = future['expiry_dt'].unique()
                curr_exp = expiries[0]
                days_rem = (curr_exp - today).days
                is_index_contract = base_symbol.strip().upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"]
                
                # Expiry Rollover Protection:
                # 1) Stock Options: In monthly expiry week (days_rem <= 6), roll over to next month's series to prevent severe theta crush.
                # 2) Index Options: Weekly expiries supported — provide current weekly expiry (or next week if expiring today late in session).
                if not is_index_contract:
                    if days_rem <= 6 and len(expiries) > 1:
                        target_exp = expiries[1]
                        sub = future[future['expiry_dt'] == target_exp]
                        c = sub.iloc[0] if not sub.empty else future.iloc[0]
                    else:
                        c = future.iloc[0]
                else:
                    if days_rem == 0 and get_ist_now().time() >= datetime_time(14, 0) and len(expiries) > 1:
                        target_exp = expiries[1]
                        sub = future[future['expiry_dt'] == target_exp]
                        c = sub.iloc[0] if not sub.empty else future.iloc[0]
                    else:
                        c = future.iloc[0]
            elif not df.empty:
                c = df.iloc[0]
            else:
                continue
            c_lot = int(c['lot_size']) if 'lot_size' in c and pd.notna(c['lot_size']) else None
            out.append({"strike": strike, "token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol'], "lot_size": c_lot})
        except Exception as e:
            logging.error(f"Strike resolution error for {base_symbol} {option_type} @ {strike}: {e}")
            continue
    return out


def resolve_option_spread(nfo_instruments, base_symbol, spot_price, step_size, direction="BULL", target_price=None, spread_width_steps=2):
    """
    Resolve a 2-leg Debit Spread to neutralize theta decay during intraday consolidation:
    - BULL (Bull Call Spread): Buy ATM CE (Leg 1) + Sell OTM CE (Leg 2 at/near Target T1)
    - BEAR (Bear Put Spread):  Buy ATM PE (Leg 1) + Sell OTM PE (Leg 2 at/near Target T1)
    """
    if nfo_instruments is None or (hasattr(nfo_instruments, "empty") and nfo_instruments.empty):
        return None

    is_bull = str(direction).upper().startswith("BULL")
    opt_type = "CE" if is_bull else "PE"
    atm_strike = int(round(spot_price / step_size) * step_size)

    # Determine desired short leg strike
    if is_bull:
        if target_price and target_price > atm_strike:
            target_strike = int(round(target_price / step_size) * step_size)
            if target_strike <= atm_strike:
                target_strike = atm_strike + spread_width_steps * step_size
        else:
            target_strike = atm_strike + spread_width_steps * step_size
    else:
        if target_price and target_price < atm_strike:
            target_strike = int(round(target_price / step_size) * step_size)
            if target_strike >= atm_strike:
                target_strike = atm_strike - spread_width_steps * step_size
        else:
            target_strike = atm_strike - spread_width_steps * step_size

    step_offset = abs(int(round((target_strike - atm_strike) / step_size)))
    n_range = max(3, step_offset + 1)

    strikes_pool = resolve_option_strikes(nfo_instruments, base_symbol, spot_price, step_size, opt_type, n_range=n_range)
    if not strikes_pool:
        return None

    strike_map = {int(s["strike"]): s for s in strikes_pool}
    leg1 = strike_map.get(atm_strike)
    if not leg1:
        closest_strike = min(strike_map.keys(), key=lambda k: abs(k - atm_strike))
        leg1 = strike_map[closest_strike]

    leg2 = strike_map.get(target_strike)
    if not leg2:
        if is_bull:
            otm_candidates = [k for k in strike_map.keys() if k > leg1["strike"]]
            if otm_candidates:
                best_otm = min(otm_candidates, key=lambda k: abs(k - target_strike))
                leg2 = strike_map[best_otm]
        else:
            otm_candidates = [k for k in strike_map.keys() if k < leg1["strike"]]
            if otm_candidates:
                best_otm = min(otm_candidates, key=lambda k: abs(k - target_strike))
                leg2 = strike_map[best_otm]

    if not leg1 or not leg2 or leg1["strike"] == leg2["strike"]:
        return None

    return {
        "spread_type": "BULL_CALL_SPREAD" if is_bull else "BEAR_PUT_SPREAD",
        "direction": "BULL" if is_bull else "BEAR",
        "base_symbol": base_symbol.strip().upper(),
        "spot_price": spot_price,
        "leg1": {
            "action": "BUY",
            "contract": leg1["tradingsymbol"],
            "token": leg1["token"],
            "strike": leg1["strike"],
            "option_type": opt_type,
            "lot_size": leg1.get("lot_size")
        },
        "leg2": {
            "action": "SELL",
            "contract": leg2["tradingsymbol"],
            "token": leg2["token"],
            "strike": leg2["strike"],
            "option_type": opt_type,
            "lot_size": leg2.get("lot_size")
        },
        "strike_diff": abs(leg2["strike"] - leg1["strike"]),
        "lot_size": leg1.get("lot_size") or leg2.get("lot_size")
    }



# ──────────────────────────────────────────────
#  BEARISH REVERSAL PATTERNS & NEGATION TARGETS
# ──────────────────────────────────────────────

