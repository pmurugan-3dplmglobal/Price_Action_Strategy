"""
Timeframe utilities — canonical source for all timeframe string parsing,
lookback calculation, resampling, and candle timing helpers.
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
from datetime import datetime as dt, timedelta

LOOKBACK_LIMITS = {
    "minute": 60, "1min": 60, "1minute": 60, "1m": 60,
    "3minute": 100, "3min": 100, "3mins": 100, "3m": 100, "3minutes": 100,
    "5minute": 100, "5min": 100, "5mins": 100, "5m": 100, "5minutes": 100,
    "10minute": 100, "10min": 100, "10mins": 100, "10m": 100, "10minutes": 100,
    "15minute": 200, "15min": 200, "15mins": 200, "15m": 200, "15minutes": 200,
    "30minute": 200, "30min": 200, "30mins": 200, "30m": 200, "30minutes": 200,
    "60minute": 400, "60min": 400, "60mins": 400, "60m": 400, "60minutes": 400, "1hr": 400, "1h": 400, "1hour": 400,
    "75min": 400, "75mins": 400, "75m": 400, "75minute": 400, "75minutes": 400,
    "3hr": 400, "3h": 400, "180min": 400,
    "4hr": 400, "4h": 400, "240min": 400, "4hour": 400,
    "day": 2000, "d": 2000, "1d": 2000, "daily": 2000,
    "week": 2000, "w": 2000, "1w": 2000, "weekly": 2000
}

def get_next_candle_start_time(candle_date, timeframe_str):
    try:
        dt_val = pd.to_datetime(candle_date)
        tf_s = str(timeframe_str).lower()
        if "week" in tf_s or tf_s in ["w", "1w"]: tf_minutes = 10080
        elif "4h" in tf_s or "240min" in tf_s: tf_minutes = 240
        elif "3h" in tf_s or "180min" in tf_s: tf_minutes = 180
        elif "75min" in tf_s or tf_s == "75minute" or "75m" in tf_s: tf_minutes = 75
        elif "60min" in tf_s or tf_s == "60minute" or "1hour" in tf_s or "1hr" in tf_s or "1h" in tf_s: tf_minutes = 60
        elif "30min" in tf_s or tf_s == "30minute": tf_minutes = 30
        elif "15min" in tf_s or tf_s == "15minute": tf_minutes = 15
        elif "10min" in tf_s or tf_s == "10minute": tf_minutes = 10
        elif "5min" in tf_s or tf_s == "5minute": tf_minutes = 5
        elif "3min" in tf_s or tf_s == "3minute": tf_minutes = 3
        elif "day" in tf_s or tf_s in ["d", "1d"]: tf_minutes = 1440
        else: tf_minutes = 1440
        next_dt = dt_val + pd.Timedelta(minutes=tf_minutes)
        return str(next_dt)
    except Exception:
        return str(candle_date)

def get_tf_minutes(timeframe_str):
    """Return timeframe duration in minutes."""
    tf_s = str(timeframe_str).lower()
    if "week" in tf_s or tf_s in ["w", "1w"]: return 10080
    elif "4h" in tf_s or "240min" in tf_s: return 240
    elif "3h" in tf_s or "180min" in tf_s: return 180
    elif "75min" in tf_s or tf_s in ["75minute", "75m", "75minutes"]: return 75
    elif "60min" in tf_s or tf_s in ["60minute", "1hour", "1hr", "1h"]: return 60
    elif "30min" in tf_s or tf_s in ["30minute", "30m"]: return 30
    elif "15min" in tf_s or tf_s in ["15minute", "15m"]: return 15
    elif "10min" in tf_s or tf_s in ["10minute", "10m"]: return 10
    elif "5min" in tf_s or tf_s in ["5minute", "5m"]: return 5
    elif "3min" in tf_s or tf_s in ["3minute", "3m"]: return 3
    elif "day" in tf_s or tf_s in ["d", "1d"]: return 1440
    return 1440

def is_live_candle_near_close(candle_date, timeframe_str, completion_pct=0.90):
    """
    Check if the active forming candle is currently within the last 10% (or completion_pct)
    of its duration during live market hours.
    Returns True if elapsed time >= completion_pct * tf_minutes.
    """
    if not candle_date or str(candle_date).strip() == "":
        return False
    try:
        now = dt.now()
        c_dt = pd.to_datetime(candle_date)
        if hasattr(c_dt, 'tz') and c_dt.tz is not None:
            c_dt = c_dt.tz_localize(None)
        tf_mins = get_tf_minutes(timeframe_str)
        if tf_mins >= 1440:
            sess_start = c_dt.replace(hour=9, minute=15, second=0)
            elapsed_sec = (now - sess_start).total_seconds()
            total_sec = 375.0 * 60.0 # 09:15 to 15:30 IST = 375 mins
            if elapsed_sec <= 0:
                return False
            return (elapsed_sec / total_sec) >= completion_pct
        else:
            elapsed_sec = (now - c_dt).total_seconds()
            total_sec = tf_mins * 60.0
            if elapsed_sec <= 0:
                return False
            return (elapsed_sec / total_sec) >= completion_pct
    except Exception:
        return False


INDEX_REGISTRY = {
    "NIFTY": {"token": 256265, "lot_size": 65, "strike_step": 50, "tradingsymbol": "NIFTY 50", "exchange": "NFO"},
    "BANKNIFTY": {"token": 260105, "lot_size": 30, "strike_step": 100, "tradingsymbol": "NIFTY BANK", "exchange": "NFO"},
    "SENSEX": {"token": 265, "lot_size": 20, "strike_step": 100, "tradingsymbol": "BSE SENSEX", "exchange": "BFO"}
}

def get_adaptive_lookback(timeframe_str, asset_class="STOCK_SPOT", user_lookback=None):
    """
    Priority Hierarchy:
      1. User-configured lookback_days (if > 0)
      2. Adaptive lookup based on Timeframe & Asset Class
    """
    if user_lookback is not None and isinstance(user_lookback, (int, float)) and user_lookback > 0:
        return int(user_lookback)

    tf_s = str(timeframe_str).lower()
    if "week" in tf_s or tf_s in ["w", "1w"] or "day" in tf_s or tf_s in ["d", "1d"]:
        return 2000
    elif "4h" in tf_s or "3h" in tf_s or "180min" in tf_s or "240min" in tf_s or "75min" in tf_s or "75m" in tf_s or "60min" in tf_s or "1hour" in tf_s or "1hr" in tf_s or "1h" in tf_s:
        return 365
    else:
        return 60

def resample_timeframe(df, timeframe_str):
    """
    Resample dataframe candles for custom non-native timeframes (e.g. 75min, 3h, 4h, week).
    Native Kite TFs (3m, 5m, 10m, 15m, 30m, 60m, day) are returned as is.
    """
    if df is None or df.empty:
        return df

    tf_s = str(timeframe_str).lower()
    if tf_s in ["75min", "75mins", "75m", "75minute", "75minutes"]:
        rule = '75min'
    elif tf_s in ["3hr", "3h", "180min", "180minute"]:
        rule = '180min'
    elif tf_s in ["4hr", "4h", "4hour", "240min", "240minute"]:
        rule = '240min'
    elif tf_s in ["week", "weekly", "w", "1w"]:
        rule = 'W-FRI'
    else:
        return df

    try:
        hist = df.copy()
        time_col = None
        for col in ['date', 'datetime', 'timestamp', 'time']:
            if col in hist.columns:
                time_col = col
                break
        if not time_col:
            return df

        hist[time_col] = pd.to_datetime(hist[time_col])
        if tf_s in ["75min", "75mins", "75m", "75minute", "75minutes"]:
            hist['trade_date'] = hist[time_col].dt.date
            groups = []
            for d, g in hist.groupby('trade_date'):
                g_res = g.set_index(time_col).resample('75min', origin='start').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
                groups.append(g_res)
            if groups:
                return pd.concat(groups, ignore_index=True)

        if tf_s in ["4hr", "4hrs", "4h", "4hour", "240min", "240minute"]:
            hist['trade_date'] = hist[time_col].dt.date
            groups = []
            for d, g in hist.groupby('trade_date'):
                g_res = g.set_index(time_col).resample('240min', origin='start').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna().reset_index()
                groups.append(g_res)
            if groups:
                return pd.concat(groups, ignore_index=True)

        hist = hist.set_index(time_col)
        resampled = hist.resample(rule, origin='start').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        return resampled
    except Exception as e:
        logging.warning(f"Resampling failed for {timeframe_str}: {e}")
        return df

def cap_lookback_days(timeframe, requested_days):
    limit = LOOKBACK_LIMITS.get(timeframe, 200)
    return min(requested_days, limit)


def get_fetch_timeframe(timeframe_str):
    """
    Translates any timeframe string (native or custom resampled like 75min, 4hr, 3hr, week)
    into a valid native Zerodha Kite interval string.
    Native Kite intervals: ["minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute", "day"]
    """
    tf_clean = str(timeframe_str).lower()
    if tf_clean in ["week", "weekly", "w", "1w", "day", "d", "1d"]:
        return "day"
    elif tf_clean in ["3hr", "3hrs", "3h", "180min", "180minute", "4hr", "4hrs", "4h", "4hour", "240min", "240minute", "1hr", "1hrs", "1h", "60min", "60minute"]:
        return "60minute"
    elif tf_clean in ["75min", "75mins", "75m", "75minute", "75minutes"]:
        return "15minute"
    elif tf_clean in ["30min", "30mins", "30m", "30minute", "30minutes"]:
        return "30minute"
    elif tf_clean in ["15min", "15mins", "15m", "15minute", "15minutes"]:
        return "15minute"
    elif tf_clean in ["10min", "10mins", "10m", "10minute", "10minutes"]:
        return "10minute"
    elif tf_clean in ["5min", "5mins", "5m", "5minute", "5minutes"]:
        return "5minute"
    elif tf_clean in ["3min", "3mins", "3m", "3minute", "3minutes"]:
        return "3minute"
    elif tf_clean in ["minute", "1min", "1m", "1minute"]:
        return "minute"
    else:
        return "day"

_HISTORICAL_CANDLE_CACHE = {}
_CACHE_TTL_SECONDS = 45.0


def trading_days_between(start, end):
    if isinstance(start, str):
        start = dt.strptime(start, "%Y-%m-%d")
    if isinstance(end, str):
        end = dt.strptime(end, "%Y-%m-%d")
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def fetch_and_resample_candles(kite, token, from_date, to_date, timeframe_str):
    import time
    fetch_tf = get_fetch_timeframe(timeframe_str)
    cache_key = (token, str(from_date), str(to_date), fetch_tf)
    now = time.time()

    if len(_HISTORICAL_CANDLE_CACHE) > 500:
        stale = [k for k, (_, ts) in _HISTORICAL_CANDLE_CACHE.items() if now - ts > _CACHE_TTL_SECONDS]
        for k in stale:
            del _HISTORICAL_CANDLE_CACHE[k]

    if cache_key in _HISTORICAL_CANDLE_CACHE:
        cached_df, timestamp = _HISTORICAL_CANDLE_CACHE[cache_key]
        if now - timestamp < _CACHE_TTL_SECONDS:
            return resample_timeframe(cached_df.copy(), timeframe_str)

    if hasattr(kite, "timeout") and not kite.timeout:
        kite.timeout = 10
    raw = None
    for attempt in range(4):
        try:
            raw = kite.historical_data(token, from_date, to_date, fetch_tf)
            break
        except Exception as e:
            err_msg = str(e).lower()
            if "too many requests" in err_msg or "429" in err_msg or "timeout" in err_msg or "connection" in err_msg:
                time.sleep(0.3 * (attempt + 1))
            else:
                raise e

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    _HISTORICAL_CANDLE_CACHE[cache_key] = (df.copy(), now)
    return resample_timeframe(df, timeframe_str)


def fetch_option_data(kite, token, from_date, to_date, primary_tf, fallback_tf, min_candles=5):
    """Fetch option data with primary timeframe, falling back if insufficient candles."""
    df = fetch_and_resample_candles(kite, token, from_date, to_date, primary_tf)
    if len(df) >= min_candles:
        return df
    df = fetch_and_resample_candles(kite, token, from_date, to_date, fallback_tf)
    if len(df) >= min_candles:
        logging.info(f"Fallback to {fallback_tf} for token {token} (only {len(df)} candles on {primary_tf})")
    return df


