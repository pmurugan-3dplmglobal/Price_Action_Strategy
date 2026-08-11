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
    STOCK_REGISTRY, load_kite_session, fetch_and_resample_candles, sync_stock_tokens
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

def _save_ema_status():
    try:
        os.makedirs(os.path.dirname(EMA_STATUS_FILE), exist_ok=True)
        with open(EMA_STATUS_FILE, "w") as f:
            json.dump(_ema_engine_running, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save EMA status file: {e}")

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

def get_option_contract_symbol(symbol, strike, side="CE"):
    now = datetime.datetime.now()
    month_str = now.strftime("%b").upper()
    yr_str = now.strftime("%y")
    strike_val = int(strike) if int(strike) == strike else strike
    return f"{symbol}{yr_str}{month_str}{strike_val}{side}"

def calculate_ema(df, period):
    if df is None or df.empty or len(df) < period:
        return pd.Series([0] * len(df) if df is not None else [])
    return df['close'].ewm(span=period, adjust=False).mean()

def run_ema_scan_symbol(kite, symbol, info, timeframe="1d", fast_period=13, slow_period=44):
    try:
        token = info.get("token", 0)
        if not token:
            return None

        # Fetch candles (days based on timeframe)
        days = 60 if timeframe in ['1d', 'day'] else 15
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
        c_ema13 = float(curr['ema13'])
        c_ema44 = float(curr['ema44'])

        p_close = float(prev['close'])
        p_ema13 = float(prev['ema13'])
        p_ema44 = float(prev['ema44'])

        # Bullish Condition: Trading above both EMAs AND fresh crossover from previous candle
        is_above = (c_close > c_ema13) and (c_close > c_ema44)
        is_fresh_cross = (p_close <= p_ema13) or (p_close <= p_ema44)

        if not (is_above and is_fresh_cross):
            return None

        # SL at 44 EMA (or recent 3-candle low if lower)
        sl_price = min(c_ema44, float(df['low'].iloc[-3:].min()))
        if sl_price >= c_close:
            sl_price = c_close * 0.98  # Fallback 2% SL buffer

        risk = c_close - sl_price
        t1 = c_close + (1.5 * risk)
        t2 = c_close + (2.5 * risk)
        t3 = c_close + (3.5 * risk)

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
            "pattern": "BULL_EMA_CROSS",
            "timeframe": timeframe
        }
    except Exception as e:
        logger.warning(f"EMA Scan skipped for {symbol}: {e}")
        return None

def execute_ema_scan_cycle(timeframe="1d", is_options_mode=True, target_universe="ALL"):
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

        if target_universe and target_universe.upper() != "ALL":
            symbols, token_map = get_universe_symbols_and_tokens(kite, target_universe)
            target_registry = {}
            for sym in symbols:
                if sym in STOCK_REGISTRY:
                    target_registry[sym] = STOCK_REGISTRY[sym]
                else:
                    target_registry[sym] = {"token": token_map.get(sym, 0), "strike_step": 10, "lot_size": 100}
        else:
            target_registry = STOCK_REGISTRY

        results = []
        for symbol, info in target_registry.items():
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
                    "pattern": "BULL_EMA_CROSS",
                    "carry_forward": False,
                    "lot_size": lot_size,
                    "engine": "ema_engine",
                    "timeframe": timeframe
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
                    "pattern": "BULL_EMA_CROSS",
                    "carry_forward": False,
                    "engine": "ema_engine",
                    "timeframe": timeframe
                })

        # Save scan display file
        out_file = EMA_DISPLAY_FILE_OPTION if is_options_mode else EMA_DISPLAY_FILE_STOCK
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        payload = {
            "ema_engine": {
                "staged_trades": results,
                "all_staged_today": results,
                "carry_forward": [],
                "active_live": []
            },
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(out_file, "w") as f:
            json.dump(payload, f, indent=2)

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
        time.sleep(scan_interval)
    logger.info(f"Stock EMA Engine worker loop stopped for mode={mode_key}")

def start_ema_engine(timeframe="1d", is_options_mode=True, scan_interval=300, target_universe="ALL"):
    mode_key = "option" if is_options_mode else "stock"
    if _ema_engine_running.get(mode_key, False):
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
    _load_ema_status()
    return _ema_engine_running.get(mode_key, False)

def get_ema_scan_data(is_options_mode=True):
    out_file = EMA_DISPLAY_FILE_OPTION if is_options_mode else EMA_DISPLAY_FILE_STOCK
    if os.path.exists(out_file):
        try:
            with open(out_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {"ema_engine": {"staged_trades": [], "all_staged_today": [], "carry_forward": [], "active_live": []}}
