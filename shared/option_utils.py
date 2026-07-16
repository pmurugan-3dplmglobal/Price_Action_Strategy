import os
import math
import logging
import calendar
import pandas as pd
from datetime import datetime as dt, timedelta, date as date_type

from shared.config import (
    BACKTEST_DATE, INDEX_REGISTRY, STOCK_REGISTRY,
    INDEX_STRIKE_RANGE, NIFTY50_STRIKE_RANGE,
    BEAR_INDEX_STRIKE_RANGE, BEAR_NIFTY50_STRIKE_RANGE
)
import shared.kite_utils as kite_utils


def get_expiry_date(base_symbol, backtest_date=None):
    """Get expiry date for option contracts.
    Index (NIFTY/BANKNIFTY): weekly — next Thursday.
    Stock: monthly — last Thursday of the month.
    """
    ref = backtest_date or (BACKTEST_DATE if BACKTEST_DATE else dt.now().date())
    if isinstance(ref, dt):
        ref = ref.date()

    is_stock = base_symbol not in INDEX_REGISTRY
    if is_stock:
        last_day = calendar.monthrange(ref.year, ref.month)[1]
        last_date = date_type(ref.year, ref.month, last_day)
        while last_date.weekday() != 3:
            last_date -= timedelta(days=1)
        return last_date
    else:
        days_ahead = (3 - ref.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return ref + timedelta(days=days_ahead)


def approximate_delta(spot, strike, option_type, days_to_expiry):
    """Approximate option delta using sigmoid of moneyness.
    ATM ~ ±0.5, ITM → ±1, OTM → 0.
    Time adjustment: delta flattens for far-expiry, sharpens near expiry.
    """
    if days_to_expiry <= 0:
        days_to_expiry = 1
    moneyness = (spot - strike) / strike
    sharpness = 3.0 * (30 / max(days_to_expiry, 1)) ** 0.5  # sharper near expiry
    if option_type == 'CE':
        return 1 / (1 + math.exp(-sharpness * moneyness))
    else:
        return -1 / (1 + math.exp(sharpness * moneyness))

def _get_strike_range(engine_type, config=None):
    """Get strike range for engine type."""
    ranges = {
        'bull_index': INDEX_STRIKE_RANGE,
        'bear_index': BEAR_INDEX_STRIKE_RANGE,
        'bull_nifty50': NIFTY50_STRIKE_RANGE,
        'bear_nifty50': BEAR_NIFTY50_STRIKE_RANGE,
    }
    if config and 'strike_range' in config:
        return config['strike_range']
    return ranges.get(engine_type, 1)

def get_weekly_expiry(target_weekday=1):
    """Get weekly expiry date (Thursday=3, but NFO weekly is Thursday)."""
    ref = BACKTEST_DATE if BACKTEST_DATE else dt.now().date()
    days_ahead = (target_weekday - ref.weekday()) % 7
    if days_ahead == 0 and not BACKTEST_DATE and dt.now().hour >= 15:
        days_ahead = 7
    return ref + timedelta(days=days_ahead)

def resolve_option_strikes(base_symbol, spot_price, step_size, option_type, n_range=0, engine_type='bull_nifty50'):
    """
    Resolve option contracts for a symbol around ATM strike.
    
    Args:
        base_symbol: e.g., "NIFTY", "RELIANCE"
        spot_price: current spot price
        step_size: strike step (50 for NIFTY, 100 for BANKNIFTY, etc.)
        option_type: "CE" or "PE"
        n_range: number of strikes ITM/OTM to include (0 = ATM only)
        engine_type: engine identifier for strike range config
    
    Returns:
        List of dicts: {"strike": int, "token": int, "tradingsymbol": str}
    """
    nfo = kite_utils.NFO_INSTRUMENTS
    if nfo is None or nfo.empty:
        logging.warning("NFO_INSTRUMENTS not loaded, cannot resolve options")
        return []
    
    strike_range = _get_strike_range(engine_type)
    total_range = max(n_range, strike_range)
    
    atm = int(round(spot_price / step_size) * step_size)
    target_expiry = get_weekly_expiry()
    
    out = []
    seen = set()
    
    for offset in range(-total_range, total_range + 1):
        strike = atm + offset * step_size
        if strike in seen:
            continue
        seen.add(strike)
        
        try:
            df = nfo[
                (nfo['name'] == base_symbol.strip().upper()) &
                (nfo['instrument_type'] == option_type.upper()) &
                (nfo['strike'] == float(strike))
            ].copy()
            
            if df.empty:
                continue
            
            df['expiry'] = pd.to_datetime(df['expiry']).dt.date
            weekly = df[df['expiry'] == target_expiry].sort_values(by='expiry')
            
            if not weekly.empty:
                c = weekly.iloc[0]
                out.append({"strike": strike, "token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol']})
                continue
            
            ref_date = BACKTEST_DATE if BACKTEST_DATE else dt.now().date()
            df = df[df['expiry'] >= ref_date].sort_values(by='expiry')
            if df.empty:
                continue
            c = df.iloc[0]
            out.append({"strike": strike, "token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol']})
            
        except Exception as e:
            logging.error(f"Strike resolution error for {base_symbol} {strike}{option_type}: {e}")
            continue
    
    return out

def resolve_option_contract(base_symbol, spot_price, step_size, option_type, target_strike=None, engine_type='bull_nifty50'):
    """
    Resolve a single option contract (ATM or specific strike).
    
    Args:
        base_symbol: e.g., "NIFTY", "RELIANCE"
        spot_price: current spot price
        step_size: strike step
        option_type: "CE" or "PE"
        target_strike: specific strike to resolve (optional)
        engine_type: engine identifier for config
    
    Returns:
        Dict with token and tradingsymbol, or None
    """
    nfo = kite_utils.NFO_INSTRUMENTS
    if nfo is None or nfo.empty:
        return None
    
    strike = target_strike or int(round(spot_price / step_size) * step_size)
    target_expiry = get_weekly_expiry()
    
    try:
        df = nfo[
            (nfo['name'] == base_symbol.strip().upper()) &
            (nfo['instrument_type'] == option_type.upper()) &
            (nfo['strike'] == float(strike))
        ].copy()
        if df.empty:
            return None

        
        df['expiry'] = pd.to_datetime(df['expiry']).dt.date
        weekly = df[df['expiry'] == target_expiry].sort_values(by='expiry')
        
        if not weekly.empty:
            c = weekly.iloc[0]
            return {"token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol'], "strike": strike}
        
        ref_date = BACKTEST_DATE if BACKTEST_DATE else dt.now().date()
        df = df[df['expiry'] >= ref_date].sort_values(by='expiry')
        if df.empty:
            return None
        c = df.iloc[0]
        return {"token": int(c['instrument_token']), "tradingsymbol": c['tradingsymbol'], "strike": strike}
        
    except Exception as e:
        logging.error(f"Contract resolution error for {base_symbol}: {e}")
        return None

def reresolve_token(base_symbol, spot_price, option_type, engine_type=None):
    """Best-effort re-resolution of a contract token from cached NFO instruments.

    Used to repair live positions whose stored token was lost/stale (e.g. 0/None)
    so that SL/target monitoring can resume. Returns (token, tradingsymbol) or (None, None).
    """
    nfo = kite_utils.NFO_INSTRUMENTS
    if nfo is None or nfo.empty:
        return None, None
    if base_symbol in INDEX_REGISTRY:
        step = INDEX_REGISTRY[base_symbol].get("strike_step", 50)
    elif base_symbol in STOCK_REGISTRY:
        step = STOCK_REGISTRY[base_symbol].get("strike_step", 50)
    else:
        step = 50
    try:
        contract = resolve_option_contract(base_symbol, spot_price, step, option_type, engine_type=engine_type)
    except Exception:
        contract = None
    if contract:
        return contract["token"], contract["tradingsymbol"]
    return None, None

def get_spot_symbol_tradingsymbol(base_symbol):
    """Get spot tradingsymbol for index/stock."""
    if base_symbol in INDEX_REGISTRY:
        return INDEX_REGISTRY[base_symbol]['tradingsymbol']
    if base_symbol in STOCK_REGISTRY:
        return base_symbol
    return base_symbol

def get_lot_size(base_symbol):
    """Get lot size for a symbol."""
    if base_symbol in INDEX_REGISTRY:
        return INDEX_REGISTRY[base_symbol]['lot_size']
    if base_symbol in STOCK_REGISTRY:
        return STOCK_REGISTRY[base_symbol]['lot_size']
    return 1

def sync_instruments(kite):
    return kite_utils.sync_instruments(kite)

def get_strike_step(base_symbol):
    """Get strike step for a symbol."""
    if base_symbol in INDEX_REGISTRY:
        return INDEX_REGISTRY[base_symbol]['strike_step']
    if base_symbol in STOCK_REGISTRY:
        return STOCK_REGISTRY[base_symbol]['strike_step']
    return 50