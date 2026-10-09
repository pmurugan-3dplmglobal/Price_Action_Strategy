"""
Macro Market Regime Gate: Real-Time Index Direction Filter.
Evaluates live tick-level performance of NSE:NIFTY 50 and NSE:NIFTY BANK.

Features:
1. Directional Regime Filtering:
   - TREND_FOLLOWING (Default): Blocks Call (CE) purchases on crashes, blocks Put (PE) on rallies.
   - CONTRARIAN: Blocks Put (PE) on dips (anticipates bounce), blocks Call (CE) on surges (anticipates pullback).
   - OFF: Bypasses the macro gate entirely.
2. Institutional Relative Strength (RS) Alpha Bypass Exception (Option 3):
   - Allows independent "Decoupled Alpha Outperformers" (🥇 Tier 1 Gold, RVOL >= 2.0x, Spot >= 1.0% above VWAP for CE,
     or Spot <= -1.0% below VWAP for PE) to bypass macro index direction blocks.
3. Dynamic Configuration (Option 4):
   - Loads thresholds, modes, and bypass parameters from input/program_config.json with zero process restart.
4. Zerodha Kite API rate-limit preservation:
   - 20-second TTL cache for index quote fetches.
"""

import os
import json
import time
import logging
from datetime import datetime as dt, time as dtime
from typing import Tuple, Dict, Any

_MACRO_CACHE = {
    "timestamp": 0.0,
    "data": {}
}
_CACHE_TTL_SECONDS = 20.0
MAX_CACHE_AGE_SEC = 120.0


def is_auth_or_token_error(err: Exception) -> bool:
    """Detects if an exception is caused by an expired or invalid Kite access token / auth error."""
    if err is None:
        return False
    try:
        from kiteconnect.exceptions import TokenException, PermissionException
        if isinstance(err, (TokenException, PermissionException)):
            return True
    except ImportError:
        pass
    err_str = str(err).lower()
    return any(k in err_str for k in (
        "tokenexception", "access_token", "invalid token", "token is invalid",
        "token expired", "token has expired", "permissionexception", "incorrect `api_key`",
        "auth", "403", "forbidden"
    ))


def _get_ist_time() -> dtime:
    """Return current time of day in Indian Standard Time (IST)."""
    try:
        try:
            from common.timeframe_utils import get_ist_time
        except ImportError:
            from timeframe_utils import get_ist_time
        return get_ist_time()
    except Exception:
        import datetime
        return datetime.datetime.now().time()


_CONFIG_CACHE = {
    "mtime": 0.0,
    "data": {}
}

DEFAULT_MACRO_GATE_CONFIG = {
    "enable": True,
    "mode": "TREND_FOLLOWING",
    "nifty_drop_threshold_pct": -0.5,
    "nifty_surge_threshold_pct": 0.5,
    "banknifty_drop_threshold_pct": -0.75,
    "banknifty_surge_threshold_pct": 0.75,
    "nifty_drop_threshold": -0.5,
    "nifty_surge_threshold": 0.5,
    "banknifty_drop_threshold": -0.75,
    "banknifty_surge_threshold": 0.75,
    "allow_rs_alpha_bypass": True,
    "allow_rs_alpha_exception": True,
    "rs_min_tier": "GOLD",
    "rs_min_rvol": 2.0,
    "rs_vwap_distance_pct": 1.0,
    "rs_min_vwap_dist_pct": 1.0
}

BANKING_SYMBOLS = {
    "SBIN", "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "BANKBARODA", "PNB", "INDUSINDBK", "CANBK", "AUBANK",
    "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK", "RBLBANK"
}

INDEX_SYMBOLS = {
    "NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "BANKEX"
}


def is_index_symbol(sym: str) -> bool:
    """Returns True if the symbol is a broad market index."""
    s = str(sym or "").replace(" ", "").upper()
    if not s:
        return False
    if s in INDEX_SYMBOLS:
        return True
    return any(s.startswith(idx) for idx in INDEX_SYMBOLS)


def get_macro_gate_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Loads macro gate configuration from input/program_config.json.
    Supports both naming conventions (_pct and non-_pct, bypass and exception)
    and caches parsed config against file mtime for instant, zero-restart updates.
    """
    global _CONFIG_CACHE
    cfg = dict(DEFAULT_MACRO_GATE_CONFIG)

    possible_paths = []
    try:
        from common import paths
        if hasattr(paths, "PROGRAM_CONFIG_FILE"):
            possible_paths.append(paths.PROGRAM_CONFIG_FILE)
    except Exception:
        pass

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths.extend([
        os.path.join(base_dir, "input", "program_config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "input", "program_config.json"),
        os.path.join(os.getcwd(), "input", "program_config.json")
    ])

    cfg_file = next((p for p in possible_paths if os.path.exists(p)), None)
    if not cfg_file:
        return cfg

    try:
        mtime = os.path.getmtime(cfg_file)
        if not force_reload and _CONFIG_CACHE["mtime"] == mtime and _CONFIG_CACHE["data"]:
            return dict(_CONFIG_CACHE["data"])

        with open(cfg_file, "r", encoding="utf-8") as f:
            full = json.load(f)

        raw_gate = full.get("macro_market_gate", {})
        if isinstance(raw_gate, dict):
            # 1. NIFTY & BANKNIFTY drop / surge thresholds (support _pct and base keys)
            for pct_k, base_k, def_val in [
                ("nifty_drop_threshold_pct", "nifty_drop_threshold", -0.5),
                ("nifty_surge_threshold_pct", "nifty_surge_threshold", 0.5),
                ("banknifty_drop_threshold_pct", "banknifty_drop_threshold", -0.75),
                ("banknifty_surge_threshold_pct", "banknifty_surge_threshold", 0.75)
            ]:
                val = None
                if pct_k in raw_gate:
                    val = raw_gate[pct_k]
                elif base_k in raw_gate:
                    val = raw_gate[base_k]
                if val is not None:
                    try:
                        f_val = float(val)
                        cfg[pct_k] = f_val
                        cfg[base_k] = f_val
                    except (ValueError, TypeError):
                        pass

            # 2. VWAP distance threshold (support distance_pct and dist_pct)
            vwap_val = None
            if "rs_vwap_distance_pct" in raw_gate:
                vwap_val = raw_gate["rs_vwap_distance_pct"]
            elif "rs_min_vwap_dist_pct" in raw_gate:
                vwap_val = raw_gate["rs_min_vwap_dist_pct"]
            if vwap_val is not None:
                try:
                    f_vwap = float(vwap_val)
                    cfg["rs_vwap_distance_pct"] = f_vwap
                    cfg["rs_min_vwap_dist_pct"] = f_vwap
                except (ValueError, TypeError):
                    pass

            # 3. RVOL threshold
            if "rs_min_rvol" in raw_gate:
                try:
                    cfg["rs_min_rvol"] = float(raw_gate["rs_min_rvol"])
                except (ValueError, TypeError):
                    pass

            # 4. Enable boolean
            if "enable" in raw_gate:
                v = raw_gate["enable"]
                cfg["enable"] = bool(v) if not isinstance(v, str) else v.lower() == "true"

            # 5. RS Alpha bypass boolean (support allow_rs_alpha_bypass and allow_rs_alpha_exception)
            bypass_val = None
            if "allow_rs_alpha_bypass" in raw_gate:
                bypass_val = raw_gate["allow_rs_alpha_bypass"]
            elif "allow_rs_alpha_exception" in raw_gate:
                bypass_val = raw_gate["allow_rs_alpha_exception"]
            if bypass_val is not None:
                b_val = bool(bypass_val) if not isinstance(bypass_val, str) else bypass_val.lower() == "true"
                cfg["allow_rs_alpha_bypass"] = b_val
                cfg["allow_rs_alpha_exception"] = b_val

            # 6. Minimum Tier
            if "rs_min_tier" in raw_gate:
                cfg["rs_min_tier"] = str(raw_gate["rs_min_tier"]).upper()

            # 7. Mode
            if "mode" in raw_gate:
                cfg["mode"] = str(raw_gate["mode"]).upper()

        _CONFIG_CACHE["mtime"] = mtime
        _CONFIG_CACHE["data"] = dict(cfg)
        return cfg
    except Exception as e:
        logging.debug(f"[MACRO_GATE] Error loading macro_market_gate config: {e}")
        return cfg


def get_macro_index_deltas(kite) -> Dict[str, Any]:
    """
    Fetches real-time LTP and calculates % change from previous close for NIFTY 50 and NIFTY BANK.
    Uses 20-second TTL cache to prevent API rate-limit exhaustion, with a 120-second max staleness ceiling.
    Before 09:15 AM IST, forces index deltas to 0.0% with ok=True (pre-market protection).
    """
    global _MACRO_CACHE
    now = time.time()
    now_t = _get_ist_time()

    # Pre-market index delta zeroing (Fix 1 - ISSUE-127):
    # Before 09:15 AM IST, pre-market quotes compare yesterday's close to day-before-yesterday close,
    # which would poison the cache with yesterday's percentage return. Force deltas to 0.0% with ok=True.
    if now_t < dtime(9, 15):
        pre_market_res = {
            "NIFTY": 0.0,
            "NIFTY_LTP": 0.0,
            "NIFTY_CLOSE": 0.0,
            "BANKNIFTY": 0.0,
            "BANKNIFTY_LTP": 0.0,
            "BANKNIFTY_CLOSE": 0.0,
            "ok": True,
            "pre_market": True
        }
        _MACRO_CACHE["timestamp"] = now
        _MACRO_CACHE["data"] = pre_market_res
        return pre_market_res

    # Normal market hours (>= 09:15 AM):
    # If cache is fresh (< 20s) and not a pre-market placeholder, return cached data
    if (now - _MACRO_CACHE["timestamp"]) < _CACHE_TTL_SECONDS and _MACRO_CACHE["data"]:
        if not _MACRO_CACHE["data"].get("pre_market"):
            return _MACRO_CACHE["data"]

    # Helper function to evaluate cached fallback safely against MAX_CACHE_AGE_SEC (Fix 2 - ISSUE-127)
    def _safe_cached_or_fallback() -> Dict[str, Any]:
        cache_age = now - _MACRO_CACHE["timestamp"]
        # Only reuse cache if it is fresh (<= MAX_CACHE_AGE_SEC) AND it had ok=True AND not pre_market
        if _MACRO_CACHE["data"] and _MACRO_CACHE["data"].get("ok") and not _MACRO_CACHE["data"].get("pre_market") and cache_age <= MAX_CACHE_AGE_SEC:
            return _MACRO_CACHE["data"]
        # Stale cache (>120s) or no valid cache: NEVER use stale cache to assert market crashes! Return ok=False, delta=0.0%
        return {
            "NIFTY": 0.0,
            "NIFTY_LTP": 0.0,
            "NIFTY_CLOSE": 0.0,
            "BANKNIFTY": 0.0,
            "BANKNIFTY_LTP": 0.0,
            "BANKNIFTY_CLOSE": 0.0,
            "ok": False,
            "stale": True
        }

    if kite is None:
        return _safe_cached_or_fallback()

    try:
        try:
            from common.trading_core import safe_kite_call
        except ImportError:
            from trading_core import safe_kite_call

        instruments = ["NSE:NIFTY 50", "NSE:NIFTY BANK"]
        quotes = safe_kite_call(kite.quote, instruments)
        if not isinstance(quotes, dict):
            return _safe_cached_or_fallback()

        nifty_q = quotes.get("NSE:NIFTY 50", {})
        banknifty_q = quotes.get("NSE:NIFTY BANK", {})

        n_ltp = float(nifty_q.get("last_price") or 0.0)
        n_cp = float(nifty_q.get("ohlc", {}).get("close") or 0.0)
        n_delta = ((n_ltp - n_cp) / n_cp * 100.0) if n_cp > 0 else 0.0

        bn_ltp = float(banknifty_q.get("last_price") or 0.0)
        bn_cp = float(banknifty_q.get("ohlc", {}).get("close") or 0.0)
        bn_delta = ((bn_ltp - bn_cp) / bn_cp * 100.0) if bn_cp > 0 else 0.0

        res = {
            "NIFTY": round(n_delta, 2),
            "NIFTY_LTP": n_ltp,
            "NIFTY_CLOSE": n_cp,
            "BANKNIFTY": round(bn_delta, 2),
            "BANKNIFTY_LTP": bn_ltp,
            "BANKNIFTY_CLOSE": bn_cp,
            "ok": True,
            "pre_market": False
        }
        _MACRO_CACHE["timestamp"] = now
        _MACRO_CACHE["data"] = res
        return res
    except Exception as e:
        if is_auth_or_token_error(e):
            logging.warning(
                f"[MACRO_GATE_AUTH_FAILED] Kite access token expired or invalid in macro gate: {e}. "
                f"Daily token must be generated after 07:00 AM IST!"
            )
        else:
            logging.warning(f"[MACRO_GATE] Failed to query index quotes: {e}")
        return _safe_cached_or_fallback()



def check_rs_alpha_exception(
    candidate_meta: Dict[str, Any],
    side: str,
    symbol: str = "",
    rs_min_rvol: float = 2.0,
    rs_min_vwap_dist_pct: float = 1.0,
    kite = None,
    rs_min_tier: Any = "GOLD"
) -> Tuple[bool, str]:
    """
    Option 3: Evaluates whether an individual stock qualifies as an independent
    "Decoupled Alpha Outperformer":
    - Tier qualified (Default: 🥇 Tier 1 Gold; configurable via rs_min_tier)
    - RVOL >= rs_min_rvol (default 2.0x)
    - Spot is >= +rs_min_vwap_dist_pct above VWAP for CE, or <= -rs_min_vwap_dist_pct below VWAP for PE
    - Symbol is not a broad market index
    
    Returns:
        (qualified: bool, reason_description: str)
    """
    if not candidate_meta or not isinstance(candidate_meta, dict):
        return False, "NO_CANDIDATE_METADATA"

    sym_candidate = str(candidate_meta.get("symbol") or "").replace(" ", "").upper()
    sym_passed = str(symbol or "").replace(" ", "").upper()
    sym_clean = sym_candidate or sym_passed
    if is_index_symbol(sym_clean):
        return False, f"INDEX_SYMBOL_NOT_ELIGIBLE ({sym_clean})"

    # 1. Tier check (Dynamic based on rs_min_tier)
    tier_val = candidate_meta.get("tier")
    tier_label = str(candidate_meta.get("tier_label") or "").upper()
    tier_badge = str(candidate_meta.get("tier_badge") or "")

    tier_req = str(rs_min_tier or "GOLD").upper()
    if tier_req in ("GOLD", "TIER_1", "1", "T1"):
        is_tier_ok = (
            tier_val == 1 or
            str(tier_val) == "1" or
            "TIER_1" in tier_label or
            "GOLD" in tier_label or
            "🥇" in tier_badge
        )
        tier_desc = "🥇 T1 Gold"
    elif tier_req in ("SILVER", "TIER_2", "2", "T2"):
        is_tier_ok = (
            tier_val in (1, 2) or
            str(tier_val) in ("1", "2") or
            any(k in tier_label for k in ("TIER_1", "GOLD", "TIER_2", "SILVER")) or
            any(k in tier_badge for k in ("🥇", "🥈"))
        )
        tier_desc = "🥈 T2 Silver / 🥇 T1 Gold"
    else:
        is_tier_ok = True
        tier_desc = f"Tier {tier_val}"

    if not is_tier_ok:
        return False, f"TIER_NOT_GOLD (tier={tier_val}, label={tier_label}, required={tier_req})"

    # 2. RVOL check (must be >= rs_min_rvol)
    rvol = 0.0
    for k in ("rvol", "rvol_abs", "rvol_projected", "vol_d_ratio", "spot_rvol", "Spot_RVOL", "opt_rvol"):
        v = candidate_meta.get(k)
        if v is not None:
            try:
                rvol = max(rvol, float(v))
            except (ValueError, TypeError):
                pass

    if rvol == 0.0:
        badge_str = str(candidate_meta.get("opt_rvol_badge") or candidate_meta.get("rvol_badge") or candidate_meta.get("badge") or "")
        if "RVOL" in badge_str:
            import re
            m = re.search(r"(\d+(\.\d+)?)x", badge_str, re.IGNORECASE)
            if m:
                try:
                    rvol = float(m.group(1))
                except (ValueError, TypeError):
                    pass

    if rvol < rs_min_rvol:
        return False, f"RVOL_BELOW_THRESHOLD ({rvol:.2f}x < {rs_min_rvol:.2f}x)"

    # 3. Spot vs intraday VWAP clearance check
    vwap_dist = None
    for k in ("vwap_dist_pct", "spot_vwap_dist_pct", "vwap_dist", "vwap_distance_pct"):
        v = candidate_meta.get(k)
        if v is not None:
            try:
                vwap_dist = float(v)
                break
            except (ValueError, TypeError):
                pass

    if vwap_dist is None:
        spot = (
            candidate_meta.get("spot_entry") or
            candidate_meta.get("spot_ltp") or
            candidate_meta.get("entry_spot") or
            candidate_meta.get("spot_price") or
            candidate_meta.get("close") or
            candidate_meta.get("ltp")
        )
        vwap = (
            candidate_meta.get("spot_vwap") or
            candidate_meta.get("vwap")
        )
        try:
            s_num = float(spot or 0.0)
            v_num = float(vwap or 0.0)
            if s_num > 0 and v_num > 0:
                vwap_dist = ((s_num - v_num) / v_num) * 100.0
        except (ValueError, TypeError):
            pass

    # If still not found and live kite session available, query spot quote
    if vwap_dist is None and kite is not None and sym_clean:
        try:
            try:
                from common.trading_core import safe_kite_call
            except ImportError:
                from trading_core import safe_kite_call
            q = safe_kite_call(kite.quote, [f"NSE:{sym_clean}"])
            if isinstance(q, dict):
                q_item = q.get(f"NSE:{sym_clean}", {}) or q.get(sym_clean, {})
                ltp = float(q_item.get("last_price") or 0.0)
                avg_p = float(q_item.get("average_price") or 0.0)
                if ltp > 0 and avg_p > 0:
                    vwap_dist = ((ltp - avg_p) / avg_p) * 100.0
        except Exception as e:
            if is_auth_or_token_error(e):
                logging.warning(f"[MACRO_GATE_AUTH_FAILED] Live quote VWAP query failed for {sym_clean} due to token/auth error: {e}")
            else:
                logging.debug(f"[MACRO_GATE] Live quote VWAP query failed for {sym_clean}: {e}")

    if vwap_dist is None:
        return False, "VWAP_DATA_UNAVAILABLE"

    side_norm = str(side).upper()
    if side_norm in ("CE", "CALL"):
        if vwap_dist < rs_min_vwap_dist_pct:
            return False, f"CE_SPOT_VWAP_DIST_INSUFFICIENT ({vwap_dist:+.2f}% < +{rs_min_vwap_dist_pct:.2f}%)"
    elif side_norm in ("PE", "PUT"):
        if vwap_dist > -rs_min_vwap_dist_pct:
            return False, f"PE_SPOT_VWAP_DIST_INSUFFICIENT ({vwap_dist:+.2f}% > -{rs_min_vwap_dist_pct:.2f}%)"
    else:
        return False, f"UNKNOWN_SIDE ({side})"

    # All criteria met!
    return True, (
        f"RS_ALPHA_BYPASS (Decoupled Alpha Outperformer: {sym_clean} {tier_desc}, "
        f"RVOL {rvol:.2f}x >= {rs_min_rvol:.2f}x, VWAP dist {vwap_dist:+.2f}% vs {rs_min_vwap_dist_pct:.2f}%; "
        f"macro index direction bypassed)"
    )


def evaluate_macro_index_gate(
    kite,
    side: str,
    symbol: str = "",
    nifty_drop_threshold: float = None,
    nifty_surge_threshold: float = None,
    banknifty_drop_threshold: float = None,
    banknifty_surge_threshold: float = None,
    candidate_meta: Dict[str, Any] = None,
    mode: str = None,
    allow_rs_alpha_bypass: bool = None,
    rs_min_tier: Any = None
) -> Tuple[bool, str]:
    """
    Evaluates whether an option trade aligns with the macro market regime.
    
    Supports:
    - Option 4: Configurable modes (TREND_FOLLOWING, CONTRARIAN, OFF) & custom thresholds.
    - Option 3: Institutional Relative Strength (RS) Alpha Bypass Exception for decoupled outperformers.
    
    Modes:
    - TREND_FOLLOWING (Default): Blocks CE when NIFTY < drop_threshold, blocks PE when NIFTY > surge_threshold.
    - CONTRARIAN: Blocks PE on market dips (< drop_threshold), blocks CE on market surges (> surge_threshold).
    - OFF: Bypasses the gate entirely.
    
    Returns:
        (is_allowed: bool, reason: str)
    """
    # Auto-normalize if caller passed (kite, symbol, side) instead of (kite, side, symbol)
    if str(side).upper() not in ["CE", "PE", "CALL", "PUT"] and str(symbol).upper() in ["CE", "PE", "CALL", "PUT"]:
        side, symbol = symbol, side

    # Auto-detect if candidate_meta was passed as 4th positional argument
    if isinstance(nifty_drop_threshold, dict) and candidate_meta is None:
        candidate_meta = nifty_drop_threshold
        nifty_drop_threshold = None

    if not side:
        return True, "SIDE_NOT_SPECIFIED"

    cfg = get_macro_gate_config()

    # Gate Enabled check
    if not cfg.get("enable", True):
        return True, "MACRO_GATE_DISABLED (Gate is set to disabled in configuration)"

    active_mode = str(mode or cfg.get("mode", "TREND_FOLLOWING")).upper()
    if active_mode == "OFF":
        return True, "MACRO_GATE_DISABLED (Gate mode is OFF)"

    deltas = get_macro_index_deltas(kite)
    if not deltas.get("ok"):
        return True, "MACRO_DATA_UNAVAILABLE_PERMITTED"

    # Cache staleness guard (Fix 2 - ISSUE-127):
    cache_age = time.time() - _MACRO_CACHE.get("timestamp", 0.0)
    if cache_age > MAX_CACHE_AGE_SEC and not deltas.get("pre_market"):
        logging.warning(
            f"[MACRO_GATE_STALE_CACHE_EVICTED] Macro cache age ({cache_age:.1f}s) exceeded TTL ({MAX_CACHE_AGE_SEC}s). "
            f"Stale crash lockout prevented. Permitting trade."
        )
        return True, "MACRO_DATA_UNAVAILABLE_PERMITTED"

    side_upper = str(side).upper()
    if side_upper == "CALL":
        side_upper = "CE"
    elif side_upper == "PUT":
        side_upper = "PE"

    sym_upper = str(symbol).upper()
    is_banking = sym_upper in BANKING_SYMBOLS or any(b in sym_upper for b in ["BANK", "FINANCE", "CHOLA", "BAJAJFIN"])

    n_delta = deltas.get("NIFTY", 0.0)
    bn_delta = deltas.get("BANKNIFTY", 0.0)

    n_drop = nifty_drop_threshold if nifty_drop_threshold is not None else float(cfg.get("nifty_drop_threshold_pct", cfg.get("nifty_drop_threshold", -0.5)))
    n_surge = nifty_surge_threshold if nifty_surge_threshold is not None else float(cfg.get("nifty_surge_threshold_pct", cfg.get("nifty_surge_threshold", 0.5)))
    bn_drop = banknifty_drop_threshold if banknifty_drop_threshold is not None else float(cfg.get("banknifty_drop_threshold_pct", cfg.get("banknifty_drop_threshold", -0.75)))
    bn_surge = banknifty_surge_threshold if banknifty_surge_threshold is not None else float(cfg.get("banknifty_surge_threshold_pct", cfg.get("banknifty_surge_threshold", 0.75)))

    if allow_rs_alpha_bypass is not None:
        allow_rs = bool(allow_rs_alpha_bypass)
    else:
        allow_rs = bool(cfg.get("allow_rs_alpha_bypass", cfg.get("allow_rs_alpha_exception", True)))

    active_rs_tier = rs_min_tier or cfg.get("rs_min_tier", "GOLD")
    rs_min_rvol = float(cfg.get("rs_min_rvol", 2.0))
    rs_min_vwap_dist = float(cfg.get("rs_vwap_distance_pct", cfg.get("rs_min_vwap_dist_pct", 1.0)))

    blocked = False
    block_msg = ""

    if active_mode == "TREND_FOLLOWING":
        # 1. Bearish Market Crash -> Block Call (CE) Options
        if side_upper == "CE":
            if n_delta < n_drop:
                blocked = True
                block_msg = f"MACRO_NIFTY_CRASH_GATE (NIFTY 50 is down {n_delta:.2f}% < {n_drop:.2f}%; Call buys blocked)"
            elif is_banking and bn_delta < bn_drop:
                blocked = True
                block_msg = f"MACRO_BANKNIFTY_CRASH_GATE (NIFTY BANK is down {bn_delta:.2f}% < {bn_drop:.2f}%; Banking Call buys blocked)"

        # 2. Bullish Market Surge -> Block Put (PE) Options
        elif side_upper == "PE":
            if n_delta > n_surge:
                blocked = True
                block_msg = f"MACRO_NIFTY_SURGE_GATE (NIFTY 50 is up {n_delta:.2f}% > +{n_surge:.2f}%; Put buys blocked)"
            elif is_banking and bn_delta > bn_surge:
                blocked = True
                block_msg = f"MACRO_BANKNIFTY_SURGE_GATE (NIFTY BANK is up {bn_delta:.2f}% > +{bn_surge:.2f}%; Banking Put buys blocked)"

    elif active_mode == "CONTRARIAN":
        # Contrarian: blocks PE on drops (expects oversold rebound), blocks CE on surges (expects overbought pullback)
        if side_upper == "PE":
            if n_delta < n_drop:
                blocked = True
                block_msg = f"MACRO_CONTRARIAN_DIP_GATE (NIFTY 50 is down {n_delta:.2f}% < {n_drop:.2f}%; Put buys blocked for oversold mean-reversion)"
            elif is_banking and bn_delta < bn_drop:
                blocked = True
                block_msg = f"MACRO_CONTRARIAN_BANK_DIP_GATE (NIFTY BANK is down {bn_delta:.2f}% < {bn_drop:.2f}%; Banking Put buys blocked for oversold mean-reversion)"
        elif side_upper == "CE":
            if n_delta > n_surge:
                blocked = True
                block_msg = f"MACRO_CONTRARIAN_PEAK_GATE (NIFTY 50 is up {n_delta:.2f}% > +{n_surge:.2f}%; Call buys blocked for overbought mean-reversion)"
            elif is_banking and bn_delta > bn_surge:
                blocked = True
                block_msg = f"MACRO_CONTRARIAN_BANK_PEAK_GATE (NIFTY BANK is up {bn_delta:.2f}% > +{bn_surge:.2f}%; Banking Call buys blocked for overbought mean-reversion)"

    if blocked:
        # Check Option 3: Institutional Relative Strength (RS) Alpha Bypass Exception
        if allow_rs and candidate_meta:
            rs_ok, rs_msg = check_rs_alpha_exception(
                candidate_meta=candidate_meta,
                side=side_upper,
                symbol=symbol,
                rs_min_rvol=rs_min_rvol,
                rs_min_vwap_dist_pct=rs_min_vwap_dist,
                kite=kite,
                rs_min_tier=active_rs_tier
            )
            if rs_ok:
                logging.info(f"[MACRO_GATE] RS Alpha Exception granted for {symbol}: {rs_msg}")
                return True, rs_msg

        logging.info(f"[MACRO_GATE] Blocked {side_upper} trade for {symbol}: {block_msg}")
        return False, block_msg

    return True, "MACRO_GATE_PASSED"
