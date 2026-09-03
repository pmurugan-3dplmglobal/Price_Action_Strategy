import json
import sys
import os
from datetime import datetime as dt, timedelta, time as datetime_time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "common"))

from kiteconnect import KiteConnect
import paths
import session
from position_monitor import (
    _load_program_config_file,
    get_sl_floor_time,
    is_candle_before_entry,
    sanitize_entry_time,
    fetch_and_resample_candles,
    live_execution_enabled
)

def diagnose():
    api_key, access_token = session.load_kite_session()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    pos_db_file = paths.ACTIVE_POSITIONS_DB
    pos_data = json.load(open(pos_db_file, "r", encoding="utf-8"))
    positions = pos_data.get("positions", [])

    cfg = _load_program_config_file()
    sl_mode = cfg.get("sl_mode", "hybrid")
    emergency_buffer_pct = float(cfg.get("emergency_buffer_pct", 0.15))
    failsafe_start_str = cfg.get("failsafe_start_time", "09:45")
    enable_spot_guard = cfg.get("enable_spot_sl_guard", True)
    
    print(f"=== Config: sl_mode={sl_mode}, emergency_buffer_pct={emergency_buffer_pct}, failsafe_start={failsafe_start_str}, enable_spot_sl_guard={enable_spot_guard} ===")
    
    # Check live flags
    print(f"nifty50_live.flag exists: {os.path.exists(paths.NIFTY50_LIVE_FLAG)}")
    print(f"index_live.flag exists: {os.path.exists(paths.INDEX_LIVE_FLAG)}")
    
    from timeframe_utils import get_ist_now
    now_dt = get_ist_now().replace(tzinfo=None)
    now_time_str = now_dt.strftime("%H:%M")
    is_before_0945 = now_time_str < "09:45"
    is_start_0945 = "09:45" <= now_time_str <= "09:47"
    print(f"Current Time: {now_time_str} | is_before_0945={is_before_0945} | is_start_0945={is_start_0945}")

    from_date = (dt.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = dt.now().strftime("%Y-%m-%d")

    for pos in positions:
        sym = pos.get("symbol")
        contract = pos.get("contract") or sym
        engine = pos.get("engine")
        token = pos.get("option_token") or pos.get("token")
        entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
        current_sl = float(pos.get("current_sl") or 0.0)
        pos_tf = pos.get("timeframe") or ("5minute" if engine == "index" else "30minute")
        trailing_stg = int(pos.get("trailing_stage") or 0)
        user_edited = pos.get("user_edited", False)

        print(f"\n==========================================")
        print(f"Diagnosing {sym} ({contract}) | Engine: {engine} | TF: {pos_tf}")
        print(f"  Entry: {entry_s}, Current SL: {current_sl}, Stage: {trailing_stg}, UserEdited: {user_edited}")

        # Fetch quote
        live_ltp = 0.0
        try:
            q = kite.ltp([token])
            live_ltp = float(q.get(str(token), {}).get("last_price", 0.0))
        except Exception as e:
            print(f"  [ERROR] LTP fetch failed: {e}")

        print(f"  Live LTP: {live_ltp:.2f}")

        # Fetch candles
        df = fetch_and_resample_candles(kite, token, from_date, to_date, pos_tf)
        if df is None or df.empty:
            print("  [ERROR] Candle DF is empty!")
            continue

        print(f"  Fetched {len(df)} candles for {pos_tf}. Last candle: {df.iloc[-1].to_dict()}")

        sl_floor = get_sl_floor_time(pos)
        entry_time_str = sanitize_entry_time(pos)
        print(f"  sl_floor: {sl_floor} | entry_time_str: {entry_time_str}")

        sl_hit = False
        sl_reason = ""
        cp = live_ltp

        # 1) SL Candle Close Check
        if current_sl > 0:
            if is_before_0945:
                print("  -> Skipped candle close SL check because is_before_0945 is True.")
            elif is_start_0945:
                prev_date = str(df.iloc[-2]['date']) if len(df) >= 2 else ""
                prev_closed_below = (len(df) >= 2 and float(df.iloc[-2]['close']) <= current_sl
                                     and not is_candle_before_entry(prev_date, sl_floor))
                curr_below = (live_ltp > 0 and live_ltp <= current_sl) or (float(df.iloc[-1]['close']) <= current_sl)
                print(f"  -> 0945 Failsafe Check: prev_closed_below={prev_closed_below} (prev close={df.iloc[-2]['close'] if len(df)>=2 else 'N/A'}), curr_below={curr_below}")
                if curr_below and prev_closed_below:
                    sl_hit = True
                    sl_reason = f"SL_FAILSAFE_0945_TRIGGER (LTP {live_ltp:.2f} <= {current_sl:.2f})"
            else:
                for idx in range(len(df)):
                    c_row = df.iloc[idx]
                    c_date = str(c_row.get('date', ''))
                    if is_candle_before_entry(c_date, entry_time_str):
                        continue
                    if is_candle_before_entry(c_date, sl_floor):
                        continue
                    if float(c_row['close']) <= current_sl:
                        sl_hit = True
                        sl_reason = f"CANDLE_CLOSE_SL ({pos_tf} Bar @ {c_date} Close {c_row['close']})"
                        cp = float(c_row['close'])
                        print(f"  -> Candle close breached SL at {c_date}: Close={c_row['close']} <= SL={current_sl}")
                        break

        print(f"  After Candle Close check: sl_hit={sl_hit}, reason='{sl_reason}'")

        # Live Reclaim Guard Check
        if sl_hit and "CANDLE_CLOSE_SL" in sl_reason:
            latest_completed_close = float(df.iloc[-2]['close']) if len(df) >= 2 else 0.0
            reclaimed = (entry_s > 0 and live_ltp >= entry_s and latest_completed_close > current_sl)
            print(f"  Live Reclaim Guard: entry_s={entry_s}, live_ltp={live_ltp}, latest_completed_close={latest_completed_close} -> Reclaimed={reclaimed}")
            if reclaimed:
                print("  -> RECLAIM GUARD SUPPRESSED SL!")
                sl_hit = False
                sl_reason = ""

        # Outlier Entry Guard Check
        is_outlier_entry = False
        if entry_s > 0 and live_ltp > 0:
            if (entry_s / live_ltp > 3.0 or live_ltp / entry_s > 3.0) and pos.get("user_edited"):
                is_outlier_entry = True
                print(f"  -> Outlier Entry Guard TRIGGERED! entry={entry_s} vs ltp={live_ltp} (ratio > 3.0)")

        # 2) Emergency Hard Stop
        if not sl_hit and current_sl > 0 and live_ltp > 0 and not is_before_0945 and not is_outlier_entry:
            if sl_mode == "tick_ltp" and live_ltp <= current_sl:
                sl_hit = True
                sl_reason = f"TICK_LTP_SL ({live_ltp})"
                print(f"  -> TICK_LTP_SL Hit: LTP {live_ltp} <= SL {current_sl}")
            elif sl_mode == "hybrid":
                emergency_cushion = max(0.30, current_sl * 0.05) if current_sl < 10 else max(1.00, current_sl * emergency_buffer_pct)
                emergency_threshold = round(current_sl - emergency_cushion, 2)
                print(f"  -> Hybrid Emergency Check: threshold = {emergency_threshold:.2f} (current_sl={current_sl}, cushion={emergency_cushion:.2f}), live_ltp={live_ltp:.2f}")
                if live_ltp <= emergency_threshold:
                    sl_hit = True
                    sl_reason = f"EMERGENCY_HARD_SL (LTP {live_ltp:.2f} <= {emergency_threshold:.2f})"
                    print(f"  -> EMERGENCY_HARD_SL Hit!")

        # 2b) Hard Max Loss Circuit
        max_loss_pct = float(cfg.get("max_option_loss_pct", 15)) / 100.0
        hard_max_sl_threshold = round(entry_s * (1.0 - max_loss_pct), 2) if entry_s > 0 else 0.0
        print(f"  Hard Max Loss Check: max_loss_pct={max_loss_pct}, hard_max_sl_threshold={hard_max_sl_threshold}, live_ltp={live_ltp}")
        if not sl_hit and hard_max_sl_threshold > 0 and live_ltp > 0 and live_ltp <= hard_max_sl_threshold and not is_before_0945 and not is_outlier_entry:
            sl_hit = True
            sl_reason = f"HARD_MAX_{int(max_loss_pct*100)}PCT_SL (LTP {live_ltp:.2f} <= {hard_max_sl_threshold:.2f})"
            print(f"  -> HARD_MAX_LOSS Hit!")

        # 2c) Spot Guard Check
        is_trailed_stop = (trailing_stg >= 1) or (entry_s > 0 and current_sl >= (entry_s * 0.99))
        print(f"  Spot Guard Check: enable_spot_guard={enable_spot_guard}, is_trailed_stop={is_trailed_stop}")
        if sl_hit and enable_spot_guard and not is_trailed_stop:
            spot_tok = pos.get("spot_token") or pos.get("index_token") or pos.get("underlying_token")
            if not spot_tok:
                from registries import STOCK_REGISTRY, INDEX_REGISTRY
                reg_entry = STOCK_REGISTRY.get(sym) or INDEX_REGISTRY.get(sym)
                if isinstance(reg_entry, dict):
                    spot_tok = reg_entry.get("token")
                elif isinstance(reg_entry, int):
                    spot_tok = reg_entry
            spot_sl = float(pos.get("spot_sl") or 0.0)
            print(f"  Spot token={spot_tok}, spot_sl={spot_sl}")
            if spot_tok:
                sq = kite.ltp([spot_tok])
                live_spot = float(list(sq.values())[0]["last_price"]) if sq else 0.0
                side_str = str(pos.get("side", "CE")).upper()
                is_bull = side_str in ["CE", "BUY", "BULL"]
                is_catastrophic_opt = (entry_s > 0 and live_ltp > 0 and live_ltp < (entry_s * 0.65))
                print(f"  live_spot={live_spot}, spot_sl={spot_sl}, is_bull={is_bull}, is_catastrophic_opt={is_catastrophic_opt}")
                if is_bull and live_spot > spot_sl and not is_catastrophic_opt:
                    print(f"  -> SPOT_SL_GUARD SUPPRESSED SL for {sym}! live_spot ({live_spot}) > spot_sl ({spot_sl})")
                    sl_hit = False
                elif (not is_bull) and live_spot < spot_sl and not is_catastrophic_opt:
                    print(f"  -> SPOT_SL_GUARD SUPPRESSED PE SL for {sym}! live_spot ({live_spot}) < spot_sl ({spot_sl})")
                    sl_hit = False

        print(f"  FINAL SL DECISION: sl_hit={sl_hit}, reason='{sl_reason}'")

if __name__ == "__main__":
    diagnose()
