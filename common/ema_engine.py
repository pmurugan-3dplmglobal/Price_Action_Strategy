import os
import json
import logging
import time
import datetime
import threading
import pandas as pd
from kiteconnect import KiteConnect

import paths

from trading_core import (
    STOCK_REGISTRY, INDEX_REGISTRY, load_kite_session, fetch_and_resample_candles, sync_stock_tokens,
    STOCK_EXPIRY_ROLLOVER_DAYS
)
from equity_universe import get_universe_symbols_and_tokens

BASE_DIR = paths.PROJECT_ROOT

# Output persistence files for EMA scans
EMA_DISPLAY_FILE_OPTION = paths.SCAN_DISPLAY_EMA_FILE
EMA_DISPLAY_FILE_STOCK = paths.SCAN_DISPLAY_EMA_STOCK_FILE
EMA_STATUS_FILE = os.path.join(BASE_DIR, "output", "monitor", "ema_engine_status.json")

# Engine state trackers
_ema_engine_threads = {}
_ema_engine_running = {}

def _setup_ema_logger():
    os.makedirs(os.path.dirname(paths.EMA_LOG_FILE), exist_ok=True)
    log_file = paths.EMA_LOG_FILE
    logger = logging.getLogger("ema_engine_module")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

logger = _setup_ema_logger()

def _atomic_write_json(file_path, data):
    tmp = f"{file_path}.tmp.{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        for attempt in range(5):
            try:
                os.replace(tmp, file_path)
                return True
            except (PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.warning(f"Atomic write failed for {file_path}: {e}")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

def _save_ema_status():
    _atomic_write_json(EMA_STATUS_FILE, _ema_engine_running)

def _load_ema_status():
    if os.path.exists(EMA_STATUS_FILE):
        try:
            with open(EMA_STATUS_FILE, "r") as f:
                data = json.load(f)
                _ema_engine_running.update(data)
        except Exception:
            pass

_load_ema_status()

def get_atm_strike(spot_price, strike_step):
    if not strike_step or strike_step <= 0:
        return round(spot_price)
    return round(spot_price / strike_step) * strike_step


def _get_monthly_expiry_month_str(now=None):
    """
    Determine the appropriate contract month string for monthly options.
    If <= 6 days remain to the last Thursday of the current month (monthly expiry),
    automatically rolls over to the next month's series to avoid extreme theta decay.
    """
    if now is None:
        now = datetime.datetime.now()
    import calendar
    year = now.year
    month = now.month
    last_day = calendar.monthrange(year, month)[1]
    last_date = datetime.date(year, month, last_day)
    # Find last Thursday of current month (weekday 3)
    offset = (last_date.weekday() - 3) % 7
    last_thursday = last_date - datetime.timedelta(days=offset)
    today = now.date() if isinstance(now, datetime.datetime) else now
    days_to_expiry = (last_thursday - today).days

    # 6-Day Monthly Rollover Rule: If <= STOCK_EXPIRY_ROLLOVER_DAYS to expiry, roll to next month
    if days_to_expiry <= STOCK_EXPIRY_ROLLOVER_DAYS:
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        next_dt = datetime.date(next_year, next_month, 1)
        return next_dt.strftime("%y"), next_dt.strftime("%b").upper()
    else:
        return now.strftime("%y"), now.strftime("%b").upper()

def get_option_contract_symbol(symbol, strike, side="CE"):
    now = datetime.datetime.now()
    yr_str, month_str = _get_monthly_expiry_month_str(now)
    strike_val = int(strike) if int(strike) == strike else strike
    return f"{symbol}{yr_str}{month_str}{strike_val}{side}"

def calculate_ema(df, period):
    if df is None or df.empty or len(df) < period:
        return pd.Series([0] * len(df) if df is not None else [])
    return df['close'].ewm(span=period, adjust=False).mean()

def detect_datta_dual_tf_ema_pattern(kite, symbol, info, fast_period=13, slow_period=44):
    """
    Datta Harale Dual-Timeframe Hierarchical EMA Strategy Engine:
      1. Step 1 (Daily 1d): 'Firstly close ABV ema On day basis'
         - Must close ABOVE EMA (d_close > d_ema13 or d_close > d_ema44).
         - If false: Disqualified immediately (zero 1-hour API calls, fail-fast protection).
      2. Step 2 (1-Hour 60m): 'Then close ABV 1 hrs That is criteria'
         - Must also close ABOVE EMA (h_close > h_ema13 or h_close > h_ema44).
         - If false: Disqualified.
      3. Classify Setup Trigger on 1-Hour:
         - BULL_13_44_CROSS: 1-hour 13 EMA crossed above 44 EMA (Day confirmed)
         - BULL_EMA_CROSS: 1-hour candle freshly crossed above 13/44 EMA (Day confirmed)
         - BULL_EMA_ON_13: 1-hour pullback bounced & held 13 EMA support (Day confirmed)
         - BULL_EMA_ON_44: 1-hour pullback bounced & held 44 EMA support (Day confirmed)
         - BULL_DAY_1H_EMA_CONFIRMED: Dual Day & 1-Hr close above EMA
    """
    try:
        token = info.get("token", 0) if isinstance(info, dict) else 0
        if not token:
            return None

        to_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Step 1: Daily Timeframe Check ("Firstly close ABV ema On day basis")
        from_date_day = (datetime.datetime.now() - datetime.timedelta(days=75)).strftime("%Y-%m-%d 09:15:00")
        df_day = fetch_and_resample_candles(kite, token, from_date_day, to_date, "1d")
        if df_day is None or df_day.empty or len(df_day) < slow_period + 2:
            return None

        df_day['ema13'] = calculate_ema(df_day, fast_period)
        df_day['ema44'] = calculate_ema(df_day, slow_period)

        d_curr = df_day.iloc[-1]
        d_close = float(d_curr['close'])
        d_ema13 = float(d_curr['ema13'])
        d_ema44 = float(d_curr['ema44'])

        # Daily Criteria: Must close above EMA (13 or 44)
        day_above_ema = (d_close > d_ema13) or (d_close > d_ema44)
        if not day_above_ema:
            return None  # Disqualified: Failed Step 1 (Day close ABV EMA) - zero 1H API calls

        # Step 2: 1-Hour Timeframe Check ("Then close ABV 1 hrs That is criteria")
        from_date_1h = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d 09:15:00")
        df_1h = fetch_and_resample_candles(kite, token, from_date_1h, to_date, "60minute")
        if df_1h is None or df_1h.empty or len(df_1h) < slow_period + 2:
            return None

        df_1h['ema13'] = calculate_ema(df_1h, fast_period)
        df_1h['ema44'] = calculate_ema(df_1h, slow_period)

        h_curr = df_1h.iloc[-1]
        h_prev = df_1h.iloc[-2]

        h_close = float(h_curr['close'])
        h_open = float(h_curr['open'])
        h_high = float(h_curr['high'])
        h_low = float(h_curr['low'])
        h_ema13 = float(h_curr['ema13'])
        h_ema44 = float(h_curr['ema44'])

        p_close = float(h_prev['close'])
        p_ema13 = float(h_prev['ema13'])
        p_ema44 = float(h_prev['ema44'])

        # 1-Hour Criteria: Must close above EMA
        h1_above_ema = (h_close > h_ema13) or (h_close > h_ema44)
        if not h1_above_ema:
            return None  # Disqualified: Failed Step 2 (1-Hr close ABV EMA)

        # Classify Setup Trigger on 1-Hour
        pattern = None
        is_13_44_cross = (h_ema13 > h_ema44) and (p_ema13 <= p_ema44)
        if is_13_44_cross and h_close >= h_ema44:
            pattern = "BULL_13_44_CROSS"
        elif (h_close > h_ema13) and (h_close > h_ema44) and ((p_close <= p_ema13) or (p_close <= p_ema44)):
            pattern = "BULL_EMA_CROSS"
        elif h_close >= h_ema44 and (h_low <= h_ema13 * 1.003) and (h_close >= h_ema13 * 0.997):
            rng = max(0.01, h_high - h_low)
            lower_wick = min(h_open, h_close) - h_low
            if h_close >= h_open or (lower_wick / rng) >= 0.40:
                pattern = "BULL_EMA_ON_13"
        elif (h_low <= h_ema44 * 1.003) and (h_close >= h_ema44 * 0.997):
            rng = max(0.01, h_high - h_low)
            lower_wick = min(h_open, h_close) - h_low
            if h_close >= h_open or (lower_wick / rng) >= 0.40:
                pattern = "BULL_EMA_ON_44"
        else:
            pattern = "BULL_DAY_1H_EMA_CONFIRMED"

        # Stop Loss: min(44 EMA on 1H, lowest low of last 3 1H candles)
        sl_price = min(h_ema44, float(df_1h['low'].iloc[-3:].min()))
        if sl_price >= h_close:
            sl_price = round(h_close * 0.98, 2)

        risk = h_close - sl_price
        t1 = round(h_close + (1.5 * risk), 2)
        t2 = round(h_close + (2.5 * risk), 2)
        t3 = round(h_close + (3.5 * risk), 2)

        ts_val = h_curr.get('date') if isinstance(h_curr, pd.Series) and 'date' in h_curr else getattr(h_curr, 'name', None)
        ts_str = str(ts_val) if ts_val is not None else time.strftime("%Y-%m-%d %H:%M:%S")
        ts_clean = ts_str.replace("T", " ").split("+")[0]

        return {
            "symbol": symbol,
            "spot_price": round(h_close, 2),
            "sl": round(sl_price, 2),
            "t1": round(t1, 2),
            "t2": round(t2, 2),
            "t3": round(t3, 2),
            "rr": 1.5,
            "ema13": round(h_ema13, 2),
            "ema44": round(h_ema44, 2),
            "day_close": round(d_close, 2),
            "day_ema13": round(d_ema13, 2),
            "day_ema44": round(d_ema44, 2),
            "entry_time": ts_clean,
            "candle_a_time": ts_clean,
            "pattern": pattern,
            "timeframe": "BOTH_1D_1HR"
        }
    except Exception as e:
        logger.warning(f"Datta Dual-TF EMA Scan skipped for {symbol}: {e}")
        return None

def run_ema_scan_symbol(kite, symbol, info, timeframe="1d", fast_period=13, slow_period=44):
    """
    Evaluates 13 EMA & 44 EMA setups for a given equity symbol via Zerodha Kite Connect.
    Supports single-timeframe and Datta Dual-Timeframe (Day close ABV EMA -> 1Hr close ABV EMA).
    """
    clean_tf = str(timeframe).strip().upper()
    if clean_tf in ["1D", "DAY", "DAILY", "D", "BOTH_1D_1HR", "1D_AND_60M", "ALL_TF", "DATTA_DAY_1HR"]:
        return detect_datta_dual_tf_ema_pattern(kite, symbol, info, fast_period=fast_period, slow_period=slow_period)

    try:
        token = info.get("token", 0) if isinstance(info, dict) else 0
        if not token:
            return None

        tf_lower = str(timeframe).lower()
        days = 30 if tf_lower in ['60minute', '60min', '1hr', '1h', '60m', '4hr', '4h'] else 15
        to_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        from_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d 09:15:00")
        
        df = fetch_and_resample_candles(kite, token, from_date, to_date, timeframe)
        if df is None or df.empty or len(df) < slow_period + 2:
            return None

        df['ema13'] = calculate_ema(df, fast_period)
        df['ema44'] = calculate_ema(df, slow_period)

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        c_close = float(curr['close'])
        c_open = float(curr['open'])
        c_high = float(curr['high'])
        c_low = float(curr['low'])
        c_ema13 = float(curr['ema13'])
        c_ema44 = float(curr['ema44'])

        p_close = float(prev['close'])
        p_ema13 = float(prev['ema13'])
        p_ema44 = float(prev['ema44'])

        pattern = None
        is_13_44_cross = (c_ema13 > c_ema44) and (p_ema13 <= p_ema44)
        if is_13_44_cross and c_close >= c_ema44:
            pattern = "BULL_13_44_CROSS"
        elif (c_close > c_ema13) and (c_close > c_ema44) and ((p_close <= p_ema13) or (p_close <= p_ema44)):
            pattern = "BULL_EMA_CROSS"
        elif c_close >= c_ema44 and (c_low <= c_ema13 * 1.003) and (c_close >= c_ema13 * 0.997):
            rng = max(0.01, c_high - c_low)
            lower_wick = min(c_open, c_close) - c_low
            if c_close >= c_open or (lower_wick / rng) >= 0.40:
                pattern = "BULL_EMA_ON_13"
        elif (c_low <= c_ema44 * 1.003) and (c_close >= c_ema44 * 0.997):
            rng = max(0.01, c_high - c_low)
            lower_wick = min(c_open, c_close) - c_low
            if c_close >= c_open or (lower_wick / rng) >= 0.40:
                pattern = "BULL_EMA_ON_44"

        if not pattern:
            return None

        # SL at 44 EMA (or recent 3-candle low if lower)
        sl_price = min(c_ema44, float(df['low'].iloc[-3:].min()))
        if sl_price >= c_close:
            sl_price = round(c_close * 0.98, 2)  # Fallback 2% SL buffer

        risk = c_close - sl_price
        t1 = round(c_close + (1.5 * risk), 2)
        t2 = round(c_close + (2.5 * risk), 2)
        t3 = round(c_close + (3.5 * risk), 2)

        ts_val = curr.get('date') if isinstance(curr, pd.Series) and 'date' in curr else getattr(curr, 'name', None)
        ts_str = str(ts_val) if ts_val is not None else time.strftime("%Y-%m-%d %H:%M:%S")
        ts_clean = ts_str.replace("T", " ").split("+")[0]

        return {
            "symbol": symbol,
            "spot_price": round(c_close, 2),
            "sl": round(sl_price, 2),
            "t1": round(t1, 2),
            "t2": round(t2, 2),
            "t3": round(t3, 2),
            "rr": 1.5,
            "ema13": round(c_ema13, 2),
            "ema44": round(c_ema44, 2),
            "entry_time": ts_clean,
            "candle_a_time": ts_clean,
            "pattern": pattern,
            "timeframe": timeframe
        }
    except Exception as e:
        logger.warning(f"EMA Scan skipped for {symbol}: {e}")
        return None

def _accumulate_today_setups(prev_payload, results, today_str):
    accumulated = {}
    if isinstance(prev_payload, dict):
        for t in prev_payload.get("ema_engine", {}).get("all_staged_today", []):
            if isinstance(t, dict) and str(t.get("entry_time") or t.get("candle_a_time") or "").startswith(today_str):
                accumulated[t.get("symbol")] = t
    for r in results:
        if isinstance(r, dict) and r.get("symbol"):
            accumulated[r.get("symbol")] = r
    return list(accumulated.values())

def execute_ema_scan_cycle(timeframe="1d", is_options_mode=True, target_universe="ALL"):
    mode_key = "option" if is_options_mode else "stock"
    try:
        ak, at = load_kite_session()
        if not ak or not at:
            logger.error("Kite instance unavailable for EMA scan cycle: missing token.")
            return []
        kite = KiteConnect(api_key=ak)
        kite.set_access_token(at)
        try:
            sync_stock_tokens(kite)
        except Exception as e:
            logger.warning(f"Stock token sync warning: {e}")

        symbols, token_map = get_universe_symbols_and_tokens(kite, target_universe)
        target_registry = {}
        for sym in symbols:
            if sym in STOCK_REGISTRY and STOCK_REGISTRY[sym].get("token"):
                target_registry[sym] = STOCK_REGISTRY[sym]
            elif sym in INDEX_REGISTRY and INDEX_REGISTRY[sym].get("token"):
                target_registry[sym] = INDEX_REGISTRY[sym]
            else:
                target_registry[sym] = {
                    "token": token_map.get(sym, 0),
                    "strike_step": STOCK_REGISTRY.get(sym, {}).get("strike_step", 10),
                    "lot_size": STOCK_REGISTRY.get(sym, {}).get("lot_size", 100)
                }

        results = []
        for symbol, info in target_registry.items():
            if not _ema_engine_running.get(mode_key, False):
                logger.info(f"EMA scan cycle aborted (engine stopped) for mode={mode_key}")
                break
            setup = run_ema_scan_symbol(kite, symbol, info, timeframe=timeframe)
            if not setup:
                continue

            if is_options_mode:
                strike_step = info.get("strike_step", 10)
                lot_size = info.get("lot_size", 100)
                spot = setup["spot_price"]
                strike = get_atm_strike(spot, strike_step)
                contract = get_option_contract_symbol(symbol, strike, "CE")

                # Derive option contract setup levels (simulated ratio based on spot movement)
                opt_entry = round(spot * 0.03, 2)
                opt_sl = round(max(0.5, opt_entry - (setup["spot_price"] - setup["sl"]) * 0.5), 2)
                opt_risk = opt_entry - opt_sl
                opt_t1 = round(opt_entry + (1.5 * opt_risk), 2)
                opt_t2 = round(opt_entry + (2.5 * opt_risk), 2)
                opt_t3 = round(opt_entry + (3.5 * opt_risk), 2)

                results.append({
                    "symbol": symbol,
                    "contract": contract,
                    "side": "CE",
                    "entry_spot": setup["spot_price"],
                    "entry": opt_entry,
                    "sl": opt_sl,
                    "t1": opt_t1,
                    "t2": opt_t2,
                    "t3": opt_t3,
                    "rr": 1.5,
                    "candle_a_time": setup["candle_a_time"],
                    "entry_time": setup["entry_time"],
                    "pattern": setup.get("pattern", "BULL_EMA_CROSS"),
                    "day_close": setup.get("day_close"),
                    "day_ema13": setup.get("day_ema13"),
                    "day_ema44": setup.get("day_ema44"),
                    "ema13": setup.get("ema13"),
                    "ema44": setup.get("ema44"),
                    "carry_forward": False,
                    "lot_size": lot_size,
                    "engine": "ema_engine",
                    "timeframe": setup.get("timeframe", timeframe)
                })
            else:
                results.append({
                    "symbol": symbol,
                    "contract": symbol,
                    "side": "EQUITY",
                    "entry_spot": setup["spot_price"],
                    "entry": setup["spot_price"],
                    "sl": setup["sl"],
                    "t1": setup["t1"],
                    "t2": setup["t2"],
                    "t3": setup["t3"],
                    "rr": setup["rr"],
                    "candle_a_time": setup["candle_a_time"],
                    "entry_time": setup["entry_time"],
                    "pattern": setup.get("pattern", "BULL_EMA_CROSS"),
                    "day_close": setup.get("day_close"),
                    "day_ema13": setup.get("day_ema13"),
                    "day_ema44": setup.get("day_ema44"),
                    "ema13": setup.get("ema13"),
                    "ema44": setup.get("ema44"),
                    "carry_forward": False,
                    "engine": "ema_engine",
                    "timeframe": setup.get("timeframe", timeframe)
                })

        # Save scan display file (accumulate today's setups across cycles so the scan
        # tab is not wiped empty once a crossover candle ages out of the fresh-cross window)
        out_file = EMA_DISPLAY_FILE_OPTION if is_options_mode else EMA_DISPLAY_FILE_STOCK
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        today_str = time.strftime("%Y-%m-%d")
        prev_payload = {}
        if os.path.exists(out_file):
            try:
                with open(out_file, encoding="utf-8") as f:
                    prev_payload = json.load(f)
            except Exception:
                pass
        accumulated_list = _accumulate_today_setups(prev_payload, results, today_str)
        payload = {
            "ema_engine": {
                "staged_trades": accumulated_list,
                "all_staged_today": accumulated_list,
                "carry_forward": [],
                "active_live": []
            },
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        _atomic_write_json(out_file, payload)

        logger.info(f"EMA Scan cycle completed for universe='{target_universe}': {len(results)} setups found.")
        return results
    except Exception as e:
        logger.error(f"EMA scan cycle failed: {e}")
        return []

def _ema_worker_loop(mode_key, timeframe, is_options_mode, scan_interval=300, target_universe="ALL"):
    logger.info(f"Started Stock EMA Engine worker loop for mode={mode_key}, timeframe={timeframe}, universe={target_universe}")
    while _ema_engine_running.get(mode_key, False):
        try:
            execute_ema_scan_cycle(timeframe=timeframe, is_options_mode=is_options_mode, target_universe=target_universe)
        except Exception as e:
            logger.error(f"EMA worker loop error: {e}")
        # Poll the running flag in small increments so Stop takes effect promptly
        # instead of blocking on a single long sleep for the full scan_interval.
        wait_until = time.time() + scan_interval
        while time.time() < wait_until and _ema_engine_running.get(mode_key, False):
            time.sleep(1)
    logger.info(f"Stock EMA Engine worker loop stopped for mode={mode_key}")

def start_ema_engine(timeframe="1d", is_options_mode=True, scan_interval=300, target_universe="ALL"):
    mode_key = "option" if is_options_mode else "stock"
    existing = _ema_engine_threads.get(mode_key)
    if existing is not None and existing.is_alive():
        return True, "EMA Engine is already running"

    _ema_engine_running[mode_key] = True
    _save_ema_status()
    t = threading.Thread(target=_ema_worker_loop, args=(mode_key, timeframe, is_options_mode, scan_interval, target_universe), daemon=True)
    _ema_engine_threads[mode_key] = t
    t.start()
    logger.info(f"Stock EMA Engine started on {timeframe} timeframe, universe={target_universe} (options_mode={is_options_mode})")
    return True, f"Stock EMA Engine started successfully on {timeframe} timeframe ({target_universe})"

def stop_ema_engine(is_options_mode=True):
    mode_key = "option" if is_options_mode else "stock"
    _ema_engine_running[mode_key] = False
    _save_ema_status()
    logger.info(f"Stock EMA Engine stopped (options_mode={is_options_mode})")
    return True, "Stock EMA Engine stopped successfully"

def get_ema_engine_status(is_options_mode=True):
    mode_key = "option" if is_options_mode else "stock"
    existing = _ema_engine_threads.get(mode_key)
    if existing is not None and existing.is_alive():
        return True
    _ema_engine_running[mode_key] = False
    return False

def get_ema_scan_data(is_options_mode=True):
    out_file = EMA_DISPLAY_FILE_OPTION if is_options_mode else EMA_DISPLAY_FILE_STOCK
    if os.path.exists(out_file):
        try:
            with open(out_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {"ema_engine": {"staged_trades": [], "all_staged_today": [], "carry_forward": [], "active_live": []}}
