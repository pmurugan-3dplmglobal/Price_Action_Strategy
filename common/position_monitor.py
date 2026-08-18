"""
Active position monitoring, SL/target evaluation, trailing stops,
and position close execution (both options and stock spot).
Extracted from trading_core.py (2026-08-11).
"""
import os
import json
import logging
import time
from datetime import datetime as dt, timedelta, time as datetime_time
import pandas as pd
import paths

NFO_CACHE_FILE = paths.NFO_CACHE_FILE
EXECUTED_EXITS_FILE = paths.EXECUTED_EXITS_FILE

def live_execution_enabled(flag_path):
    return os.path.exists(flag_path)

# ──────────────────────────────────────────────
#  SHARED POSITION MANAGEMENT
# ──────────────────────────────────────────────

NFO_CACHE_FILE = paths.NFO_CACHE_FILE

_nfo_cache_df = None
_nfo_cache_mtime = 0

def _get_nfo_cache():
    """Load NFO instruments cache CSV once, re-read only when file changes on disk."""
    global _nfo_cache_df, _nfo_cache_mtime
    if not os.path.exists(NFO_CACHE_FILE):
        return pd.DataFrame()
    try:
        mtime = os.path.getmtime(NFO_CACHE_FILE)
        if _nfo_cache_df is None or mtime != _nfo_cache_mtime:
            _nfo_cache_df = pd.read_csv(NFO_CACHE_FILE)
            _nfo_cache_mtime = mtime
        return _nfo_cache_df
    except Exception:
        return pd.DataFrame()

def get_option_lot_size(contract):
    """Look up actual lot size from NFO instruments cache, not from registry."""
    try:
        df = _get_nfo_cache()
        if df.empty:
            return None
        row = df[df['tradingsymbol'] == contract]
        if not row.empty:
            return int(row.iloc[0]['lot_size'])
    except Exception as e:
        logging.warning(f"Lot size lookup failed for {contract}: {e}")
    return None

_CONTRACT_EXPIRY_RE = None

def contract_is_expired(contract):
    """Return True if the option contract has already expired.

    Uses the NFO instruments cache (authoritative expiry) when available;
    falls back to parsing the embedded expiry from the contract name.
    """
    import re
    global _CONTRACT_EXPIRY_RE
    if not contract:
        return False
    c = str(contract).strip().upper()
    try:
        df = _get_nfo_cache()
        if not df.empty:
            row = df[df['tradingsymbol'] == c]
            if not row.empty:
                exp_str = str(row.iloc[0]['expiry'])
                exp_date = pd.to_datetime(exp_str).date()
                return exp_date < dt.now().date()
    except Exception as e:
        logging.warning(f"Expiry cache lookup failed for {c}: {e}")
    if _CONTRACT_EXPIRY_RE is None:
        _CONTRACT_EXPIRY_RE = re.compile(r"(\d+)(CE|PE)$")
    m = _CONTRACT_EXPIRY_RE.search(c)
    if m:
        num_part = m.group(1)
        for strike_len in range(6, 2, -1):
            if len(num_part) <= strike_len:
                continue
            date_part = num_part[:len(num_part) - strike_len]
            if len(date_part) < 5:
                continue
            for mm_width in (2, 1):
                if len(date_part) != 2 + mm_width + 2:
                    continue
                yy = int(date_part[:2])
                mm = int(date_part[2:2 + mm_width])
                dd = int(date_part[2 + mm_width:])
                if 1 <= mm <= 12 and 1 <= dd <= 31:
                    try:
                        exp_date = dt.strptime("20%02d-%02d-%02d" % (yy, mm, dd), "%Y-%m-%d").date()
                        return exp_date < dt.now().date()
                    except Exception:
                        continue
    return False

def close_stock_position(kite, pos, live_market=True, product=None):
    if not kite:
        logging.info(f"[BACKTEST EXIT] Closed stock {pos.get('contract','')}")
        return
    contract = pos.get("contract") or pos.get("symbol")
    if not contract:
        logging.error("close_stock_position failed: missing contract/symbol name")
        return
    if is_contract_exit_executed(contract):
        prev = EXECUTED_EXITS.get(contract, {})
        oid = prev.get("order_id")
        prev_ts = prev.get("timestamp")
        
        is_reentry = False
        pos_entry_time = pos.get("entry_time") or ""
        if pos_entry_time and prev_ts:
            try:
                p_dt = dt.fromisoformat(pos_entry_time.split("+")[0])
                e_dt = dt.fromisoformat(prev_ts.split("+")[0])
                if p_dt > e_dt:
                    is_reentry = True
            except Exception:
                pass

        has_live_qty = False
        if kite and live_market:
            try:
                for kp in kite.positions().get("net", []):
                    if kp.get("tradingsymbol") == contract and int(kp.get("quantity", 0)) > 0:
                        has_live_qty = True
                        break
            except Exception:
                pass

        if is_reentry or has_live_qty:
            logging.info(f"[EXIT GUARD RESET] Stock {contract} is an active position / re-entry (entry_time={pos_entry_time} vs exit_ts={prev_ts}, live_qty={has_live_qty}). Resetting stale exit guard order {oid}.")
            clear_executed_exit(contract)
        else:
            logging.info(f"[EXIT GUARD BLOCK] {contract} stock exit order already submitted (Order ID: {prev.get('order_id')}). Skipping duplicate exit call.")
            return
    target_product = product
    try:
        if kite:
            net_positions = kite.positions().get("net", [])
            for p in net_positions:
                if p.get("tradingsymbol") == contract and int(p.get("quantity", 0)) > 0:
                    prod = p.get("product")
                    if prod:
                        target_product = prod
                        break
    except Exception as e:
        logging.warning(f"Could not fetch Kite stock position product for {contract}: {e}")
    if not target_product:
        target_product = pos.get("product") or kite.PRODUCT_CNC
    try:
        q = kite.quote(f"{kite.EXCHANGE_NSE}:{contract}")
        ltp = q[f"{kite.EXCHANGE_NSE}:{contract}"]["last_price"]
        bid = q[f"{kite.EXCHANGE_NSE}:{contract}"]["depth"]["buy"][0]["price"]
        price = round((bid if bid > 0 else ltp) * 0.995, 1)
        qty = pos.get("position_size", pos.get("quantity", 1))
        try:
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                exchange=kite.EXCHANGE_NSE, transaction_type=kite.TRANSACTION_TYPE_SELL,
                quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=price, product=target_product
            )
            save_executed_exit(contract, oid, {"type": "LIMIT", "price": price, "qty": qty})
            logging.info(f"Closed stock {contract} with product {target_product} (Order ID: {oid})")
        except Exception as primary_err:
            logging.warning(f"Primary stock exit with {target_product} failed for {contract}: {primary_err}. Retrying with fallback...")
            alt_product = kite.PRODUCT_MIS if target_product == kite.PRODUCT_CNC else kite.PRODUCT_CNC
            try:
                oid = kite.place_order(
                    variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                    exchange=kite.EXCHANGE_NSE, transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                    price=price, product=alt_product
                )
                save_executed_exit(contract, oid, {"type": "LIMIT_ALT", "price": price, "qty": qty})
                logging.info(f"Fallback stock exit SUCCESS for {contract} with product {alt_product} (Order ID: {oid})")
            except Exception as alt_err:
                logging.error(f"Fallback stock exit failed for {contract}: {alt_err}")
    except Exception as e:
        logging.error(f"Stock exit failed for {contract}: {e}")

EXECUTED_EXITS_FILE = paths.EXECUTED_EXITS_FILE
EXECUTED_EXITS = {}
_EXECUTED_EXITS_MTIME = 0

def load_executed_exits():
    """Load executed exits from disk, using mtime to skip re-reads when file hasn't changed."""
    global EXECUTED_EXITS, _EXECUTED_EXITS_MTIME
    if not os.path.exists(EXECUTED_EXITS_FILE):
        return
    try:
        mtime = os.path.getmtime(EXECUTED_EXITS_FILE)
        if mtime != _EXECUTED_EXITS_MTIME:
            with open(EXECUTED_EXITS_FILE, "r", encoding="utf-8") as f:
                EXECUTED_EXITS = json.load(f)
            _EXECUTED_EXITS_MTIME = mtime
    except Exception:
        EXECUTED_EXITS = {}

def save_executed_exit(contract, order_id, details=None):
    global EXECUTED_EXITS
    load_executed_exits()
    EXECUTED_EXITS[contract] = {
        "order_id": str(order_id),
        "timestamp": dt.now().isoformat(),
        "details": details or {}
    }
    try:
        os.makedirs(os.path.dirname(EXECUTED_EXITS_FILE), exist_ok=True)
        with open(EXECUTED_EXITS_FILE, "w", encoding="utf-8") as f:
            json.dump(EXECUTED_EXITS, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save executed exit order file: {e}")

def is_contract_exit_executed(contract):
    load_executed_exits()
    return contract in EXECUTED_EXITS

def clear_executed_exit(contract):
    global EXECUTED_EXITS
    load_executed_exits()
    if contract in EXECUTED_EXITS:
        del EXECUTED_EXITS[contract]
        try:
            os.makedirs(os.path.dirname(EXECUTED_EXITS_FILE), exist_ok=True)
            with open(EXECUTED_EXITS_FILE, "w", encoding="utf-8") as f:
                json.dump(EXECUTED_EXITS, f, indent=4)
            logging.info(f"[EXIT GUARD RESET] Reset exit guard for {contract} due to new trade re-entry.")
        except Exception as e:
            logging.error(f"Failed to clear executed exit for {contract}: {e}")

def is_market_open():
    """Check if Indian markets (NSE/NFO/BSE/BFO) are currently open (Mon-Fri 09:15 to 15:30 IST)."""
    now = dt.now()
    if now.weekday() >= 5:
        return False
    t_now = now.time()
    return datetime_time(9, 15) <= t_now <= datetime_time(15, 30)

def close_position(kite, pos, live_market=True, product=None):
    contract = pos.get("contract") or pos.get("tradingsymbol")
    if not contract:
        return
    
    target_product = product
    try:
        if not target_product and kite:
            kp = kite.positions()
            for p in (kp.get("day", []) + kp.get("net", [])):
                if p.get("tradingsymbol") == contract:
                    target_product = p.get("product")
                    break
    except Exception as e:
        logging.warning(f"Could not fetch Kite position product for {contract}: {e}")
    if not target_product:
        target_product = pos.get("product") or (kite.PRODUCT_NRML if kite else "NRML")

    c_str = str(contract).upper()
    is_option = "CE" in c_str or "PE" in c_str or "NIFTY" in c_str or "BANK" in c_str or "SENSEX" in c_str or "BSE" in c_str
    if "SENSEX" in c_str or "BSE" in c_str:
        target_exch = "BFO"
    elif is_option:
        target_exch = "NFO"
    else:
        target_exch = "NSE"

    qty = pos.get("quantity") or (get_option_lot_size(contract) or pos.get("lot_size", 1)) * pos.get("position_size", 1)

    if kite and live_market and not is_market_open():
        logging.info(f"[MARKET CLOSED] Skipping live Zerodha exit order for {contract} outside market hours (09:15-15:30 IST). Position status logged.")
        return

    # Fetch live quote for LTP & Bid price
    ltp = 0.0
    bid = 0.0
    if kite and live_market:
        try:
            q_key = f"{target_exch}:{contract}"
            q = kite.quote([q_key])
            if q_key in q:
                ltp = float(q[q_key].get("last_price", 0))
                depth = q[q_key].get("depth", {}).get("buy", [])
                if depth and len(depth) > 0:
                    bid = float(depth[0].get("price", 0))
        except Exception as q_err:
            logging.warning(f"Could not fetch quote for exit {contract}: {q_err}")

    ref_price = bid if bid > 0 else ltp
    if ref_price <= 0:
        ref_price = float(pos.get("entry_spot", 1.0))
    
    # Calculate marketable limit price (0.995 * ref_price rounded to 0.05 tick)
    price = max(0.05, round(round((ref_price * 0.995) / 0.05) * 0.05, 2))

    if is_contract_exit_executed(contract):
        prev = EXECUTED_EXITS.get(contract, {})
        oid = prev.get("order_id")
        prev_ts = prev.get("timestamp")
        
        # Check if current position entry_time is newer than the saved exit order timestamp
        is_reentry = False
        pos_entry_time = pos.get("entry_time") or ""
        if pos_entry_time and prev_ts:
            try:
                p_dt = dt.fromisoformat(pos_entry_time.split("+")[0])
                e_dt = dt.fromisoformat(prev_ts.split("+")[0])
                if p_dt > e_dt:
                    is_reentry = True
            except Exception:
                pass

        # Also check if kite positions confirm we still hold an active long position (quantity > 0)
        has_live_qty = False
        if kite and live_market:
            try:
                for kp in kite.positions().get("net", []):
                    if kp.get("tradingsymbol") == contract and int(kp.get("quantity", 0)) > 0:
                        has_live_qty = True
                        break
            except Exception:
                pass

        if is_reentry or has_live_qty:
            logging.info(f"[EXIT GUARD RESET] Contract {contract} is an active position / re-entry (entry_time={pos_entry_time} vs exit_ts={prev_ts}, live_qty={has_live_qty}). Resetting stale exit guard {oid}.")
            clear_executed_exit(contract)
        elif oid and kite and live_market:
            o_status = None
            try:
                orders = kite.orders()
                for o in orders:
                    if str(o.get("order_id")) == str(oid):
                        o_status = o.get("status")
                        break
                if o_status in ["OPEN", "TRIGGER PENDING"]:
                    logging.warning(f"[PENDING LIMIT EXIT DETECTED] Order {oid} for {contract} is OPEN/UNFILLED. Cancelling order and executing aggressive Marketable LIMIT exit fallback...")
                    try:
                        kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=oid)
                    except Exception as c_err:
                        logging.warning(f"Could not cancel pending order {oid}: {c_err}")
                    
                    fallback_price = max(0.05, round(round((ref_price * 0.98) / 0.05) * 0.05, 2))
                    m_oid = kite.place_order(
                        variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                        exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                        price=fallback_price, product=target_product
                    )
                    save_executed_exit(contract, m_oid, {"type": "MARKETABLE_LIMIT_FALLBACK", "price": fallback_price, "qty": qty})
                    logging.info(f"Fallback Marketable LIMIT exit SUCCESS for {contract} at price {fallback_price} on exchange {target_exch} (Order ID: {m_oid})")
                    return
                elif o_status in ["CANCELLED", "REJECTED", "EXPIRED", "CANCELLED ALL"]:
                    logging.warning(f"[EXIT GUARD RESET] Order {oid} for {contract} is {o_status}. Clearing exit guard and retrying exit.")
                    clear_executed_exit(contract)
                else:
                    logging.info(f"[EXIT GUARD BLOCK] {contract} exit order {oid} is {o_status or 'UNKNOWN'}. Skipping duplicate exit call.")
                    return
            except Exception as check_err:
                logging.debug(f"Could not verify exit order status for {contract}: {check_err}")
                logging.info(f"[EXIT GUARD BLOCK] {contract} exit order {oid} status could not be verified. Skipping duplicate exit call.")
                return
        else:
            logging.info(f"[EXIT GUARD BLOCK] {contract} exit order already submitted (Order ID: {prev.get('order_id')}). Skipping duplicate exit call.")
            return

    if not live_market:
        logging.info(f"[BACKTEST EXIT] {contract}")
        return

    try:
        oid = kite.place_order(
            variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
            exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
            price=price, product=target_product
        )
        save_executed_exit(contract, oid, {"type": "LIMIT", "price": price, "qty": qty})
        logging.info(f"Closed {contract} with Marketable LIMIT order price {price} on exchange {target_exch} (Order ID: {oid})")
    except Exception as primary_err:
        logging.warning(f"Primary LIMIT exit with {target_product} on {target_exch} failed for {contract}: {primary_err}. Retrying with aggressive limit fallback...")
        try:
            fallback_price = max(0.05, round(round((ref_price * 0.98) / 0.05) * 0.05, 2))
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=fallback_price, product=target_product
            )
            save_executed_exit(contract, oid, {"type": "LIMIT_FALLBACK", "price": fallback_price, "qty": qty})
            logging.info(f"Fallback Marketable LIMIT exit SUCCESS for {contract} on exchange {target_exch} at price {fallback_price} with product {target_product}")
        except Exception as m_err:
            logging.error(f"Fallback exit failed for {contract}: {m_err}")

def _load_program_config_file():
    possible_paths = [
        paths.PROGRAM_CONFIG_FILE,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "input", "program_config.json"),
        os.path.join(os.path.dirname(__file__), "input", "program_config.json")
    ]
    cfg_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if cfg_path:
        try:
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def is_candle_before_entry(c_date, entry_time_val):
    if not entry_time_val:
        return False
    try:
        c_dt = pd.to_datetime(c_date)
        e_dt = pd.to_datetime(entry_time_val)
        if hasattr(c_dt, 'tz') and c_dt.tz is not None:
            c_dt = c_dt.tz_convert('Asia/Kolkata').tz_localize(None)
        if hasattr(e_dt, 'tz') and e_dt.tz is not None:
            e_dt = e_dt.tz_convert('Asia/Kolkata').tz_localize(None)
        if e_dt.hour < 8 and c_dt.hour >= 9:
            e_dt = e_dt + timedelta(hours=5, minutes=30)
        return c_dt < e_dt
    except Exception:
        try:
            c_str = str(c_date).replace("T", " ").split("+")[0].strip()[:16]
            e_str = str(entry_time_val).replace("T", " ").split("+")[0].strip()[:16]
            return c_str < e_str
        except Exception:
            return False

def get_sl_floor_time(pos):
    """Timestamp from which the CURRENT current_sl is enforced.

    Critical guard for trailing stops (CANDLE_CLOSE_SL false-trigger family:
    TRAIL-1/TRAIL-2 raise current_sl; historical candles that closed before the
    SL was raised must NEVER be re-judged against the new, higher SL).
    When sl_set_time is absent (fresh position, initial SL), the floor falls
    back to the sanitized entry_time so the original SL applies to all
    post-entry candles (legacy behaviour preserved).
    """
    st = str(pos.get("sl_set_time") or "").strip()
    if st and st.lower() != "none":
        return st
    stage = int(pos.get("trailing_stage") or 0)
    if stage >= 1:
        # Legacy position that was ALREADY trailed before sl_set_time existed:
        # unknown exact trail moment, so enforce the trailed SL conservatively
        # only from today onwards - never against pre-trail historical bars.
        return dt.now().strftime("%Y-%m-%d 00:00:00")
    return sanitize_entry_time(pos)


def sanitize_entry_time(pos, now_ts=None):
    """
    Guarantee entry_time is a usable candle-filter timestamp for ACTIVE positions.
    Rules:
      - empty/None entry_time  -> fall back to created_at (or now)
      - entry_time older than created_at -> use created_at (real execution reference)
    Returns a sanitized ISO-ish string and stores it back into pos['entry_time'].
    """
    now_ts = now_ts or dt.now()
    et = str(pos.get("entry_time") or "").strip()
    ca = str(pos.get("created_at") or "").strip()
    def _parse(v):
        try:
            d = pd.to_datetime(v)
            if hasattr(d, 'tz') and d.tz is not None:
                d = d.tz_convert('Asia/Kolkata').tz_localize(None)
            return d
        except Exception:
            return None
    et_dt = _parse(et) if et and et.lower() != "none" else None
    ca_dt = _parse(ca) if ca and ca.lower() != "none" else None
    if et_dt is None:
        clean = ca if ca_dt is not None else now_ts.isoformat()
    elif ca_dt is not None and et_dt < ca_dt:
        clean = ca
    else:
        clean = et
    pos["entry_time"] = clean
    return clean

def monitor_active_positions(kite, registry, positions_dict, lock, product_type, engine_name,
                              timeframe_entry, trade_db, log_fn, save_state_fn=None,
                              live=True):
    from_date = (dt.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = dt.now().strftime("%Y-%m-%d")
    to_clear = []

    # Load sl_mode from program config if available ("hybrid", "candle_close", or "tick_ltp")
    cfg = _load_program_config_file()
    sl_mode = cfg.get("sl_mode", "hybrid")
    emergency_buffer_pct = float(cfg.get("emergency_buffer_pct", 0.15))
    failsafe_start_str = cfg.get("failsafe_start_time", "09:45")
    try:
        f_h, f_m = map(int, failsafe_start_str.split(":"))
        fs_start_t = datetime_time(f_h, f_m)
    except Exception:
        fs_start_t = datetime_time(9, 45)

    if dt.now().time() < fs_start_t:
        logging.debug(f"[FAILSAFE PAUSED BEFORE {failsafe_start_str} AM] Automated active position exit checks paused until {failsafe_start_str} AM.")
        return

    with lock:
        items = list(positions_dict.items())

    for sym, pos in items:
        try:
            contract = pos.get("contract") or pos.get("symbol") or sym
            c_str = str(contract).upper()
            is_stock_spot = pos.get("position_type") == "stock" or (pos.get("position_type") is None and not ("CE" in c_str or "PE" in c_str))

            token = pos.get("option_token")
            if not token and not is_stock_spot and kite:
                try:
                    exch = "BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO"
                    q = kite.quote([f"{exch}:{contract}"])
                    if f"{exch}:{contract}" in q:
                        token = int(q[f"{exch}:{contract}"].get("instrument_token", 0))
                        if token:
                            with lock:
                                positions_dict[sym]["option_token"] = token
                except Exception as tok_err:
                    logging.debug(f"Option token lookup error for {contract}: {tok_err}")

            if not token and is_stock_spot:
                token = registry.get(sym, {}).get("token")

            if not token:
                logging.warning(f"[MONITOR SKIP] Could not resolve valid token for {contract}. Skipping spot token fallback to prevent target corruption.")
                continue

            pos_tf = pos.get("timeframe") or timeframe_entry
            df = fetch_and_resample_candles(kite, token, from_date, to_date, pos_tf)
            if df.empty:
                continue

            last = df.iloc[-1]
            cp = float(last['close'])
            tid = pos.get("trade_id")
            is_stock = pos.get("position_type") == "stock"
            current_sl = float(pos.get("current_sl", 0))

            # Fetch live quote for LTP
            live_ltp = 0.0
            try:
                contract_name = pos.get("contract") or pos.get("symbol") or sym
                exch = "NSE" if is_stock else ("BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO")
                q_key = f"{exch}:{contract_name}"
                q_res = kite.quote([q_key])
                if q_key in q_res:
                    q_info = q_res[q_key]
                    live_ltp = float(q_info.get("last_price", 0))
            except Exception as q_err:
                logging.debug(f"Live quote fetch error for {sym}: {q_err}")

            # Compute High (hp) strictly for candles AFTER trade entry_time + live_ltp
            entry_time_str = sanitize_entry_time(pos)
            hp = live_ltp if live_ltp > 0 else cp
            for idx in range(len(df)):
                c_row = df.iloc[idx]
                c_date = str(c_row.get('date', ''))
                if is_candle_before_entry(c_date, entry_time_str):
                    continue
                hp = max(hp, float(c_row['high']))

            sl_hit = False
            sl_reason = ""
            event_time = last.get('date')

            # Track current TF candle timestamp on position for UI/monitoring
            with lock:
                if sym in positions_dict:
                    positions_dict[sym]["candle_tf_time"] = str(event_time) if event_time else ""
                    positions_dict[sym]["timeframe"] = pos_tf

            # 1) SL Evaluation (Separated SL Monitor: Skipped 09:15-09:45 AM, Active at 09:45 AM+)
            now_time_str = dt.now().strftime("%H:%M")
            is_before_0945 = now_time_str < "09:45"
            is_start_0945 = "09:45" <= now_time_str <= "09:47"

            if current_sl > 0:
                sl_floor = get_sl_floor_time(pos)
                if is_before_0945:
                    # Target monitoring runs from 09:15 AM, but SL is skipped until 09:45 AM
                    pass
                elif is_start_0945:
                    # 09:45 AM Failsafe Check: If trading below SL & prev candle closed below SL & current candle trading below SL
                    prev_date = str(df.iloc[-2]['date']) if len(df) >= 2 else ""
                    prev_closed_below = (len(df) >= 2 and float(df.iloc[-2]['close']) <= current_sl
                                         and not is_candle_before_entry(prev_date, sl_floor))
                    curr_below = (live_ltp > 0 and live_ltp <= current_sl) or (float(df.iloc[-1]['close']) <= current_sl)
                    if curr_below and prev_closed_below:
                        sl_hit = True
                        sl_reason = f"SL_FAILSAFE_0945_TRIGGER (LTP {live_ltp:.2f} <= {current_sl:.2f} & Prev Bar Closed Below)"
                        cp = live_ltp if live_ltp > 0 else float(df.iloc[-1]['close'])
                        event_time = last.get('date')
                else:
                    # Normal Active SL Monitoring after 09:45 AM.
                    # ONLY candles >= sl_floor are judged against current_sl. A candle that
                    # formed BEFORE the current SL was set (e.g. pre-trailing entry-day bar)
                    # must never trip the SL, otherwise trailing raises SL and old dips
                    # retroactively become "breaches" (ISSUE-040 family).
                    entry_time_str = sanitize_entry_time(pos)
                    for idx in range(len(df)):
                        c_row = df.iloc[idx]
                        c_date = str(c_row.get('date', ''))
                        if is_candle_before_entry(c_date, entry_time_str):
                            continue
                        if is_candle_before_entry(c_date, sl_floor):
                            continue
                        if float(c_row['close']) <= current_sl:
                            sl_hit = True
                            sl_reason = f"CANDLE_CLOSE_SL ({pos_tf} Bar @ {c_date})"
                            cp = float(c_row['close'])
                            event_time = c_row.get('date')
                            break

            # 2) Emergency Hard Stop / Direct LTP evaluation (Active after 09:45 AM)
            if not sl_hit and current_sl > 0 and live_ltp > 0 and not is_before_0945:
                if sl_mode == "tick_ltp" and live_ltp <= current_sl:
                    sl_hit = True
                    sl_reason = f"TICK_LTP_SL ({live_ltp})"
                    cp = live_ltp
                elif sl_mode == "hybrid":
                    emergency_threshold = current_sl * (1.0 - emergency_buffer_pct)
                    if live_ltp <= emergency_threshold:
                        sl_hit = True
                        sl_reason = f"EMERGENCY_HARD_SL (LTP {live_ltp:.2f} <= {emergency_threshold:.2f})"
                        cp = live_ltp

            if sl_hit:
                logging.warning(f"SL [{sl_reason}]: {sym} at {cp} (TF: {pos_tf})")
                if is_stock:
                    close_stock_position(kite, pos, live, product_type)
                else:
                    close_position(kite, pos, live, product_type)
                entry_s = pos.get("entry_spot", 0)
                # Exit PnL must reflect the actual live price at trigger time, NOT a
                # stale historical bar close (which caused -12.68% bookings on profitable
                # fills, e.g. LT26AUG4050PE filled ~80.25 but booked at 50.60).
                exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else current_sl)
                pnl = ((exit_price - entry_s) / entry_s * 100) if entry_s else 0
                log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_SL", "CLOSED",
                       f"SL hit [{sl_reason}]: {exit_price:.2f}", pnl,
                       entry=entry_s, sl=current_sl, target=pos.get("t1", ""),
                       event_time=event_time)
                if tid:
                    trade_db.update_trade(tid, {
                        "status": "SL_HIT",
                        "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "pnl_percent": round(pnl, 2),
                        "details": f"SL hit [{sl_reason}] | TF: {pos_tf}"
                    })
                to_clear.append(sym)
                continue
            t1_val = float(pos.get("t1")) if pos.get("t1") is not None and pos.get("t1") != "N/A" else None
            t2_val = float(pos.get("t2")) if pos.get("t2") is not None and pos.get("t2") != "N/A" else None
            t3_val = float(pos.get("t3")) if pos.get("t3") is not None and pos.get("t3") != "N/A" else None

            has_higher_targets = (t2_val is not None and t2_val > 0) or (t3_val is not None and t3_val > 0)

            # Early exit target buffers (1 to 2 points earlier to prevent missing out on wicks)
            def _get_target_buffer(t_val):
                if not t_val or t_val <= 0: return 0.0
                if t_val <= 50: return max(0.50, round(t_val * 0.015, 2))
                elif t_val <= 200: return max(1.00, round(t_val * 0.015, 2))
                else: return max(2.00, round(t_val * 0.010, 2))

            buf_t1 = _get_target_buffer(t1_val)
            buf_t2 = _get_target_buffer(t2_val)
            buf_t3 = _get_target_buffer(t3_val)

            # 3) Target Exits & Trailing Evaluation
            if t1_val and hp >= (t1_val - buf_t1):
                # RULE: If T2 or T3 is NOT available, exit 100% at T1 (early exit threshold)!
                if not has_higher_targets:
                    logging.info(f"T1 FULL EXIT (No T2/T3): {sym} reached {hp:.2f} (Target: {t1_val:.2f}, Buffer: {buf_t1:.2f})")
                    if is_stock:
                        close_stock_position(kite, pos, live, product_type)
                    else:
                        close_position(kite, pos, live, product_type)
                    entry_s = pos.get("entry_spot", 0)
                    exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else t1_val)
                    pnl = ((exit_price - entry_s) / entry_s * 100) if entry_s else 0
                    log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_T1", "CLOSED",
                           f"T1={t1_val:.2f} (Exit @ {exit_price:.2f})", pnl,
                           entry=entry_s, sl=pos.get("current_sl", ""), target=t1_val,
                           event_time=last.get('date'))
                    if tid:
                        trade_db.update_trade(tid, {
                            "status": "TARGET_HIT",
                            "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pnl_percent": round(pnl, 2),
                            "details": f"T1 exit ({hp:.2f} >= {t1_val - buf_t1:.2f})"
                        })
                    to_clear.append(sym)
                    continue
                elif pos.get("trailing_stage", 0) == 0:
                    new_sl = pos.get("entry_spot", 0)
                    sl_stamp = dt.now().isoformat()
                    with lock:
                        if sym in positions_dict:
                            positions_dict[sym]["current_sl"] = new_sl
                            positions_dict[sym]["trailing_stage"] = 1
                            positions_dict[sym]["sl_set_time"] = sl_stamp
                    logging.info(f"TRAIL-1 {sym}: SL=BE ({new_sl:.2f})")
                    log_fn(sym, pos.get("pattern", ""), timeframe_entry, "TRAIL_BE", "MUTATED",
                           f"SL={new_sl:.2f}",
                           entry=pos.get("entry_spot", 0), sl=new_sl, target=t1_val,
                           event_time=last.get('date'))
                    if tid:
                        trade_db.update_trade(tid, {"trailing_stage": 1, "current_sl": new_sl, "sl_set_time": sl_stamp})

            if pos.get("trailing_stage", 0) == 1 and t2_val and hp >= (t2_val - buf_t2):
                new_sl = t1_val or pos.get("entry_spot", 0)
                sl_stamp = dt.now().isoformat()
                with lock:
                    if sym in positions_dict:
                        positions_dict[sym]["current_sl"] = new_sl
                        positions_dict[sym]["trailing_stage"] = 2
                        positions_dict[sym]["sl_set_time"] = sl_stamp
                logging.info(f"TRAIL-2 {sym}: SL=T1 ({new_sl:.2f})")
                log_fn(sym, pos.get("pattern", ""), timeframe_entry, "TRAIL_T1", "MUTATED",
                       f"SL={new_sl:.2f}",
                       entry=pos.get("entry_spot", 0), sl=new_sl, target=t2_val,
                       event_time=last.get('date'))
                if tid:
                    trade_db.update_trade(tid, {"trailing_stage": 2, "current_sl": new_sl, "sl_set_time": sl_stamp})

            if t3_val and hp >= (t3_val - buf_t3):
                logging.info(f"T3 EXIT: {sym} reached {hp:.2f} (Target: {t3_val:.2f})")
                if pos.get("position_type") == "stock":
                    close_stock_position(kite, pos, live, product_type)
                else:
                    close_position(kite, pos, live, product_type)
                entry_s = pos.get("entry_spot", 0)
                exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else t3_val)
                pnl = ((exit_price - entry_s) / entry_s * 100) if entry_s else 0
                log_fn(sym, pos.get("pattern", ""), timeframe_entry, "EXIT_T3", "CLOSED",
                       f"T3={t3_val:.2f} (Exit @ {exit_price:.2f})", pnl,
                       entry=entry_s, sl=pos.get("current_sl", ""), target=t3_val,
                       event_time=last.get('date'))
                if tid:
                    trade_db.update_trade(tid, {"status": "TARGET_HIT", "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"), "pnl_percent": round(pnl, 2)})
                to_clear.append(sym)
        except Exception as e:
            logging.error(f"Risk error {sym}: {e}")

    if to_clear:
        with lock:
            for s in to_clear:
                positions_dict.pop(s, None)

    if to_clear and save_state_fn:
        save_state_fn()


