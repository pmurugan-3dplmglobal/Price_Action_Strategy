"""
common/rvol_calculator.py

Institutional Relative Volume (RVOL) & Daily Breakout Engine.
Calculates 20-day historical average volume, time-of-day adjusted pacing,
and flags high trading volume surges and daily breakouts as seen in institutional scanners.
"""

import pandas as pd
import numpy as np
from datetime import datetime as dt, time as dtime
try:
    from pytz import timezone
    IST = timezone("Asia/Kolkata")
except Exception:
    IST = None


def get_market_elapsed_minutes(current_time=None):
    """
    Computes elapsed trading minutes in the NSE regular trading session (09:15 to 15:30 IST).
    Total session duration = 375 minutes.
    """
    if current_time is None:
        if IST:
            now = dt.now(IST)
        else:
            now = dt.now()
    elif isinstance(current_time, str):
        try:
            now = pd.to_datetime(current_time)
        except Exception:
            now = dt.now()
    else:
        now = current_time

    market_open = dtime(9, 15)
    market_close = dtime(15, 30)

    cur_time = now.time() if hasattr(now, "time") else dtime(12, 0)

    if cur_time < market_open:
        # Pre-market: clamp to minimum 15 mins for conservative projections
        return 15.0
    elif cur_time >= market_close:
        # Post-market: full trading session completed
        return 375.0
    else:
        elapsed = (cur_time.hour - 9) * 60 + (cur_time.minute - 15) + (cur_time.second / 60.0)
        return max(15.0, min(375.0, float(elapsed)))


def calculate_rvol(df, current_time=None, lookback_days=20, tf_is_daily=False, is_live_intraday=False):
    """
    Calculates Relative Volume (RVOL) metrics:
    1. avg_vol_20: 20-day baseline average daily volume.
    2. current_vol: Current cumulative intraday or bar volume.
    3. rvol_abs: Absolute ratio of today's volume to 20-day daily average.
    4. rvol_projected: Time-of-day pacing projected to full session vs 20-day avg.

    Returns dict with structured metrics and visual badges.
    """
    default_res = {
        "avg_vol_20": 0.0,
        "current_vol": 0.0,
        "rvol_abs": 1.0,
        "rvol_projected": 1.0,
        "is_surge": False,
        "is_momentum": False,
        "badge": "NORMAL",
        "alert_title": "",
        "alert_desc": ""
    }

    if df is None or df.empty or 'volume' not in df.columns:
        return default_res

    try:
        elapsed_mins = get_market_elapsed_minutes(current_time)
        if tf_is_daily and not is_live_intraday and current_time is None:
            # Completed historical daily bars without active intraday timing
            pacing_factor = 1.0
        else:
            pacing_factor = max(0.04, elapsed_mins / 375.0)  # Min 4% (15m into day)

        if tf_is_daily or len(df) < 50:
            # Daily candles dataframe
            if len(df) < 2:
                return default_res
            # Exclude current forming candle to calculate baseline
            prior_candles = df.iloc[:-1]
            lookback_slice = prior_candles['volume'].tail(lookback_days)
            avg_vol_20 = float(lookback_slice.mean()) if not lookback_slice.empty else 0.0
            current_vol = float(df['volume'].iloc[-1])
        else:
            # Intraday candles dataframe: group by date to get daily totals
            df_work = df.copy()
            if 'date' in df_work.columns:
                df_work['date_dt'] = pd.to_datetime(df_work['date'])
                daily_vols = df_work.groupby(df_work['date_dt'].dt.date)['volume'].sum()
            else:
                daily_vols = pd.Series([float(df_work['volume'].sum())])

            if len(daily_vols) > 1:
                current_vol = float(daily_vols.iloc[-1])
                prior_daily = daily_vols.iloc[:-1].tail(lookback_days)
                avg_vol_20 = float(prior_daily.mean()) if not prior_daily.empty else 0.0
            else:
                # Only 1 day in df, fallback to historical estimation
                current_vol = float(df_work['volume'].sum())
                avg_vol_20 = current_vol / pacing_factor

        if avg_vol_20 <= 0:
            avg_vol_20 = max(1.0, current_vol)

        rvol_abs = round(current_vol / avg_vol_20, 2)
        projected_vol = current_vol / pacing_factor
        rvol_projected = round(projected_vol / avg_vol_20, 2)

        # An institutional volume surge occurs if:
        # 1. Projected daily volume is >= 2.0x 20-day average, OR
        # 2. Intraday volume already exceeds the full 20-day daily average mid-day (pacing_factor <= 0.85), OR
        # 3. For a completed day, volume is >= 1.25x 20-day average.
        is_surge = bool(rvol_projected >= 2.0 or (rvol_abs >= 1.0 and pacing_factor <= 0.85) or rvol_abs >= 1.25)
        is_momentum = bool(rvol_projected >= 1.4 or rvol_abs >= 1.10)

        badge = "NORMAL"
        alert_title = ""
        alert_desc = ""

        if rvol_abs >= 1.0 and pacing_factor <= 0.85:
            badge = f"🔥 RVOL {rvol_abs}x > 20D"
            alert_title = "High trading volume alert!"
            alert_desc = f"Trading volume ({current_vol:,.0f}) greater than 20-day average ({avg_vol_20:,.0f}). Indicating increased institutional interest."
        elif rvol_abs >= 1.25:
            badge = f"🔥 RVOL {rvol_abs}x > 20D"
            alert_title = "High trading volume alert!"
            alert_desc = f"Trading volume ({current_vol:,.0f}) greater than 20-day average ({avg_vol_20:,.0f})."
        elif rvol_projected >= 2.0:
            badge = f"⚡ RVOL {rvol_projected}x PACE"
            alert_title = "Institutional volume surge!"
            alert_desc = f"Pacing at {rvol_projected:.1f}x of 20-day average volume with potential expansion."
        elif rvol_projected >= 1.4 or rvol_abs >= 1.10:
            badge = f"📈 RVOL {rvol_projected}x"
            alert_title = "Above average volume"
            alert_desc = f"Volume tracking {rvol_projected:.1f}x normal daily pace."

        return {
            "avg_vol_20": round(avg_vol_20, 1),
            "current_vol": round(current_vol, 1),
            "rvol_abs": rvol_abs,
            "rvol_projected": rvol_projected,
            "is_surge": is_surge,
            "is_momentum": is_momentum,
            "badge": badge,
            "alert_title": alert_title,
            "alert_desc": alert_desc
        }
    except Exception as e:
        return default_res


def detect_daily_breakout(df, lookback_bars=20):
    """
    Detects if the latest candle is breaking out of the 20-bar high (Bullish)
    or breaking down below the 20-bar low (Bearish).
    """
    default_res = {
        "is_breakout": False,
        "side": "NONE",
        "breakout_level": 0.0,
        "badge": ""
    }
    if df is None or len(df) < lookback_bars + 1:
        return default_res

    try:
        prior_bars = df.iloc[-lookback_bars - 1 : -1]
        latest = df.iloc[-1]
        c_close = float(latest['close'])
        prior_high = float(prior_bars['high'].max())
        prior_low = float(prior_bars['low'].min())

        if c_close > prior_high:
            return {
                "is_breakout": True,
                "side": "BULL",
                "breakout_level": prior_high,
                "badge": "🚀 DAILY BREAKOUT"
            }
        elif c_close < prior_low:
            return {
                "is_breakout": True,
                "side": "BEAR",
                "breakout_level": prior_low,
                "badge": "🔻 DAILY BREAKDOWN"
            }
        return default_res
    except Exception:
        return default_res
