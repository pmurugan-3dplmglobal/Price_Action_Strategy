"""
Macro Market Regime Gate: Real-Time Index Direction Filter.
Evaluates live tick-level performance of NSE:NIFTY 50 and NSE:NIFTY BANK.
Blocks Call (CE) option purchases during confirmed market drops (prevents buying into crashes).
Blocks Put (PE) option purchases during confirmed market rallies (prevents buying into surges).
Includes 20-second TTL caching to preserve Zerodha Kite API rate limits.
"""

import time
import logging
from typing import Tuple, Dict, Any

_MACRO_CACHE = {
    "timestamp": 0.0,
    "data": {}
}
_CACHE_TTL_SECONDS = 20.0

BANKING_SYMBOLS = {
    "SBIN", "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "BANKBARODA", "PNB", "INDUSINDBK", "CANBK", "AUBANK",
    "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK", "RBLBANK"
}


def get_macro_index_deltas(kite) -> Dict[str, Any]:
    """
    Fetches real-time LTP and calculates % change from previous close for NIFTY 50 and NIFTY BANK.
    Uses 20-second TTL cache to prevent API rate-limit exhaustion.
    """
    global _MACRO_CACHE
    now = time.time()
    if (now - _MACRO_CACHE["timestamp"]) < _CACHE_TTL_SECONDS and _MACRO_CACHE["data"]:
        return _MACRO_CACHE["data"]

    if kite is None:
        return _MACRO_CACHE["data"] or {"NIFTY": 0.0, "BANKNIFTY": 0.0, "ok": False}

    try:
        try:
            from common.trading_core import safe_kite_call
        except ImportError:
            from trading_core import safe_kite_call

        instruments = ["NSE:NIFTY 50", "NSE:NIFTY BANK"]
        quotes = safe_kite_call(kite.quote, instruments)
        if not isinstance(quotes, dict):
            return _MACRO_CACHE["data"] or {"NIFTY": 0.0, "BANKNIFTY": 0.0, "ok": False}

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
            "ok": True
        }
        _MACRO_CACHE["timestamp"] = now
        _MACRO_CACHE["data"] = res
        return res
    except Exception as e:
        logging.debug(f"[MACRO_GATE] Failed to query index quotes: {e}")
        return _MACRO_CACHE["data"] or {"NIFTY": 0.0, "BANKNIFTY": 0.0, "ok": False}


def evaluate_macro_index_gate(
    kite,
    side: str,
    symbol: str = "",
    nifty_drop_threshold: float = -0.25,
    nifty_surge_threshold: float = 0.25,
    banknifty_drop_threshold: float = -0.35,
    banknifty_surge_threshold: float = 0.35
) -> Tuple[bool, str]:
    """
    Evaluates whether an option trade aligns with the macro market regime.
    
    Rules:
    - If side == 'CE' and NIFTY 50 is down more than nifty_drop_threshold (default -0.25%), REJECT.
    - If side == 'CE' and symbol is banking stock and BANKNIFTY is down more than banknifty_drop_threshold (-0.35%), REJECT.
    - If side == 'PE' and NIFTY 50 is up more than nifty_surge_threshold (default +0.25%), REJECT.
    - If side == 'PE' and symbol is banking stock and BANKNIFTY is up more than banknifty_surge_threshold (+0.35%), REJECT.
    
    Returns:
        (is_allowed: bool, reason: str)
    """
    # Auto-normalize if caller passed (kite, symbol, side) instead of (kite, side, symbol)
    if str(side).upper() not in ["CE", "PE", "CALL", "PUT"] and str(symbol).upper() in ["CE", "PE", "CALL", "PUT"]:
        side, symbol = symbol, side

    if not side:
        return True, "SIDE_NOT_SPECIFIED"

    deltas = get_macro_index_deltas(kite)
    if not deltas.get("ok"):
        # If market quote fetch fails or offline test, do not block execution
        return True, "MACRO_DATA_UNAVAILABLE_PERMITTED"

    side_upper = str(side).upper()
    sym_upper = str(symbol).upper()
    is_banking = sym_upper in BANKING_SYMBOLS or any(b in sym_upper for b in ["BANK", "FINANCE", "CHOLA", "BAJAJFIN"])

    n_delta = deltas.get("NIFTY", 0.0)
    bn_delta = deltas.get("BANKNIFTY", 0.0)

    # 1. Bearish Market Crash -> Block Call (CE) Options
    if side_upper == "CE":
        if n_delta < nifty_drop_threshold:
            msg = f"MACRO_NIFTY_CRASH_GATE (NIFTY 50 is down {n_delta:.2f}% < {nifty_drop_threshold:.2f}%; Call buys blocked)"
            logging.info(f"[MACRO_GATE] Blocked CE trade for {symbol}: {msg}")
            return False, msg

        if is_banking and bn_delta < banknifty_drop_threshold:
            msg = f"MACRO_BANKNIFTY_CRASH_GATE (NIFTY BANK is down {bn_delta:.2f}% < {banknifty_drop_threshold:.2f}%; Banking Call buys blocked)"
            logging.info(f"[MACRO_GATE] Blocked Banking CE trade for {symbol}: {msg}")
            return False, msg

    # 2. Bullish Market Surge -> Block Put (PE) Options
    elif side_upper == "PE":
        if n_delta > nifty_surge_threshold:
            msg = f"MACRO_NIFTY_SURGE_GATE (NIFTY 50 is up {n_delta:.2f}% > +{nifty_surge_threshold:.2f}%; Put buys blocked)"
            logging.info(f"[MACRO_GATE] Blocked PE trade for {symbol}: {msg}")
            return False, msg

        if is_banking and bn_delta > banknifty_surge_threshold:
            msg = f"MACRO_BANKNIFTY_SURGE_GATE (NIFTY BANK is up {bn_delta:.2f}% > +{banknifty_surge_threshold:.2f}%; Banking Put buys blocked)"
            logging.info(f"[MACRO_GATE] Blocked Banking PE trade for {symbol}: {msg}")
            return False, msg

    return True, "MACRO_GATE_PASSED"
