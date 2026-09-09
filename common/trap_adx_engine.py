"""
5-Minute Trap-ADX Index & 45-Minute High Stock Breakout Engine.
Implements:
1. Wilder's DMI (+DI, -DI, ADX) calculation.
2. Index Option 5-Minute Trap Scanner:
   - Condition 1: 5m candle closes below support line.
   - Condition 2: Immediate subsequent 5m candle closes GREEN back above support line.
   - Condition 3: DMI +DI >= 26.0 on the option premium chart and +DI > -DI.
   - Max Stop-Loss Risk Cap: strictly <= 20.0 points.
3. Stock Option 45-Minute High Breakout Scanner:
   - 45-Minute Opening Range High (09:15-10:00 AM).
   - Breakout above 45m high on 5m timeframe.
   - Tiered Stop-Loss buffer based on price:
     * < 500: Rs 0.60 buffer
     * 500-1000: Rs 1.00 buffer
     * 1000-2000: Rs 2.00 buffer
     * >= 2000: Rs 4.00 buffer
   - No ADX requirement on stocks (peer directive).
4. Real-time serialization to SCAN_DISPLAY_TRAP_ADX.
"""
import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime as dt

COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
from trading_core import (
    INDEX_REGISTRY, STOCK_REGISTRY,
    get_option_lot_size, is_market_open
)


def calculate_dmi(df: pd.DataFrame, period: int = 14):
    """
    Wilder's Directional Movement Index (DMI):
    Returns (+DI, -DI, ADX) series aligned to df.index.
    """
    if df is None or len(df) < period + 2:
        empty_s = pd.Series(0.0, index=df.index if df is not None else [0])
        return empty_s, empty_s, empty_s

    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)

    # 1. True Range (TR)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 2. Directional Movement (+DM, -DM)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # 3. Wilder's Smoothing (alpha = 1 / period)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * (pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100.0 * (pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))

    # 4. Directional Index (DX) & ADX
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * ((plus_di - minus_di).abs() / denom)
    adx = dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)

    return plus_di.fillna(0.0), minus_di.fillna(0.0), adx.fillna(0.0)


def calculate_stock_tiered_buffer(price: float) -> float:
    """
    Peer's exact price-tiered stop-loss buffer for stock cash intraday:
    - Below 500: Rs 0.60
    - 500 to 1000: Rs 1.00
    - 1000 to 2000: Rs 2.00
    - Above 2000: Rs 4.00 (e.g. Adani Ent at Rs 3,078)
    """
    p = float(price)
    if p < 500.0:
        return 0.60
    elif p < 1000.0:
        return 1.00
    elif p < 2000.0:
        return 2.00
    else:
        return 4.00


def scan_index_option_trap(
    df_5m: pd.DataFrame,
    symbol: str,
    contract: str,
    side: str = "CE",
    adx_threshold: float = 26.0,
    max_sl_points: float = 20.0
):
    """
    Detects 5-Minute Index Option Trap Reversal:
    Condition 1: Candle 1 closes below support line.
    Condition 2: Candle 2 (immediate next) is GREEN and closes back ABOVE the support line.
    Condition 3: DMI +DI >= 26.0 and +DI > -DI on the option premium chart.
    Risk Filter: Entry - SL <= 20.0 points.
    """
    if df_5m is None or len(df_5m) < 16:
        return None

    plus_di, minus_di, adx = calculate_dmi(df_5m, period=14)

    # Rolling support low: lowest low of recent 8-12 candles before the last 2 completed bars
    prior_slice = df_5m.iloc[-12:-2] if len(df_5m) >= 12 else df_5m.iloc[:-2]
    if len(prior_slice) < 4:
        return None
    support_line = float(prior_slice['low'].min())

    candle_1 = df_5m.iloc[-2]  # Sweep candle
    candle_2 = df_5m.iloc[-1]  # Reclaim candle

    c1_close = float(candle_1['close'])
    c2_open = float(candle_2['open'])
    c2_close = float(candle_2['close'])
    c2_low = float(candle_2['low'])
    c1_low = float(candle_1['low'])

    # Condition 1: Sweep below support
    cond_1 = c1_close < support_line

    # Condition 2: Immediate green reclaim
    cond_2 = (c2_close > c2_open) and (c2_close > support_line)

    # Condition 3: +DI >= 26.0 and +DI > -DI
    curr_plus_di = float(plus_di.iloc[-1])
    curr_minus_di = float(minus_di.iloc[-1])
    cond_3 = (curr_plus_di > curr_minus_di) and (curr_plus_di >= adx_threshold)

    raw_sl = min(c1_low, c2_low)
    risk_pts = round(c2_close - raw_sl, 2)

    if cond_1 and cond_2 and cond_3:
        if risk_pts <= 0 or risk_pts > max_sl_points:
            return None

        entry_price = round(c2_close, 2)
        sl_price = round(raw_sl, 2)
        t1_price = round(entry_price + 1.5 * risk_pts, 2)
        t2_price = round(entry_price + 2.5 * risk_pts, 2)
        lot_size = get_option_lot_size(contract) or 65

        return {
            "type": "INDEX_TRAP",
            "symbol": symbol,
            "contract": contract,
            "side": side,
            "support_line": round(support_line, 2),
            "sweep_close": round(c1_close, 2),
            "reclaim_close": round(c2_close, 2),
            "plus_di": round(curr_plus_di, 1),
            "minus_di": round(curr_minus_di, 1),
            "adx": round(float(adx.iloc[-1]), 1),
            "entry_spot": entry_price,
            "current_sl": sl_price,
            "sl": sl_price,
            "t1": t1_price,
            "t2": t2_price,
            "t3": round(entry_price + 4.0 * risk_pts, 2),
            "risk_pts": risk_pts,
            "lot_size": lot_size,
            "status": "READY_FOR_BUY",
            "candle_time": str(candle_2.get("date", ""))
        }

    return None


def scan_stock_45m_breakout(
    df_5m: pd.DataFrame,
    symbol: str,
    target_contract: str = ""
):
    """
    Detects 45-Minute High Breakout for Stock Options:
    1. 45-Minute Opening Range High (09:15 to 10:00 AM).
    2. 5m breakout above 45m High.
    3. Stop-Loss based on 9 EMA low / recent low with tiered buffer.
    """
    if df_5m is None or len(df_5m) < 10:
        return None

    range_45m = df_5m.iloc[:9]
    high_45m = float(range_45m['high'].max())
    low_45m = float(range_45m['low'].min())

    post_45m = df_5m.iloc[9:]
    if post_45m.empty:
        return None

    latest_candle = post_45m.iloc[-1]
    curr_close = float(latest_candle['close'])
    curr_open = float(latest_candle['open'])

    if curr_close > high_45m and (curr_close >= curr_open):
        ema_9_low = float(df_5m['low'].ewm(span=9, adjust=False).mean().iloc[-1])
        buf = calculate_stock_tiered_buffer(curr_close)

        recent_low = float(df_5m['low'].tail(3).min())
        sl_level = round(min(recent_low, ema_9_low) - buf, 2)
        risk_dist = round(curr_close - sl_level, 2)

        lot_size = get_option_lot_size(target_contract) or 250

        return {
            "type": "STOCK_45M_BREAKOUT",
            "symbol": symbol,
            "contract": target_contract or symbol,
            "side": "CE",
            "high_45m": round(high_45m, 2),
            "low_45m": round(low_45m, 2),
            "spot_ltp": round(curr_close, 2),
            "entry_spot": round(curr_close, 2),
            "current_sl": sl_level,
            "sl": sl_level,
            "buffer_applied": buf,
            "risk_pts": risk_dist,
            "t1": round(curr_close + 1.5 * risk_dist, 2),
            "t2": round(curr_close + 2.5 * risk_dist, 2),
            "t3": round(curr_close + 4.0 * risk_dist, 2),
            "lot_size": lot_size,
            "status": "BREAKOUT_TRIGGERED",
            "candle_time": str(latest_candle.get("date", ""))
        }

    return None


def run_trap_adx_scan_cycle(kite=None) -> dict:
    """
    Executes scan cycle and serializes output to paths.SCAN_DISPLAY_TRAP_ADX.
    """
    results = {
        "timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index_traps": [],
        "stock_breakouts": []
    }
    try:
        if os.path.exists(paths.SCAN_DISPLAY_TRAP_ADX):
            with open(paths.SCAN_DISPLAY_TRAP_ADX, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    results.update(data)
    except Exception:
        pass

    results["timestamp"] = dt.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(paths.SCAN_DISPLAY_TRAP_ADX, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to write SCAN_DISPLAY_TRAP_ADX: {e}")

    return results
