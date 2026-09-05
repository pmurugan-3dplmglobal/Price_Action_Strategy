"""
Active position monitoring, SL/target evaluation, trailing stops,
and position close execution (both options and stock spot).
Extracted from trading_core.py (2026-08-11).
"""
import os
import sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import json
import logging
import time
import threading
from datetime import datetime as dt, timedelta, time as datetime_time
import pandas as pd
import paths
from timeframe_utils import fetch_and_resample_candles, get_ist_now, get_ist_date, get_ist_time

NFO_CACHE_FILE = paths.NFO_CACHE_FILE
EXECUTED_EXITS_FILE = paths.EXECUTED_EXITS_FILE
ACTIVE_POSITIONS = {}
position_lock = threading.Lock()

def live_execution_enabled(flag_path):
    return os.path.exists(flag_path)

def is_option_contract(contract_str):
    """
    Determine if a symbol/contract represents an Option contract (e.g. NIFTY24SEP25000CE, INFY24SEP1500PE).
    Cash equities (e.g. PETRONET, PEL, PERSISTENT, HDFCBANK, CENTRALBK) return False.
    """
    if not contract_str:
        return False
    c = str(contract_str).strip().upper()
    if ":" in c:
        c = c.split(":")[-1]
    return (c.endswith("CE") or c.endswith("PE")) and any(ch.isdigit() for ch in c)

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
                return exp_date < get_ist_date()
    except Exception as e:
        logging.warning(f"Expiry cache lookup failed for {c}: {e}")
    # Check standard monthly contract pattern (e.g. RELIANCE26AUG1340PE)
    _MONTH_MAP = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
    m_mon = re.search(r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d+)(CE|PE)$", c)
    if m_mon:
        yy = int("20" + m_mon.group(1))
        mon_str = m_mon.group(2)
        month_num = _MONTH_MAP[mon_str]
        today = get_ist_date()
        if yy < today.year:
            return True
        if yy == today.year and month_num < today.month:
            return True
        if yy == today.year and month_num == today.month:
            # If current month and day is >= 27th (past typical monthly expiry Thursday)
            if today.day >= 27:
                return True

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
                        return exp_date < get_ist_date()
                    except Exception:
                        continue
    return False

def close_stock_position(kite, pos, live_market=True, product=None, qty_override=None, live=None, product_type=None):
    if live is not None:
        live_market = live
    if product_type is not None and product is None:
        product = product_type
    if not kite:
        logging.info(f"[BACKTEST EXIT] Closed stock {pos.get('contract','')}")
        return
    contract = pos.get("contract") or pos.get("symbol")
    if not contract:
        logging.error("close_stock_position failed: missing contract/symbol name")
        return {"success": False, "reason": "NO_CONTRACT"}

    raw_qty = qty_override if qty_override is not None else (pos.get("position_size") or pos.get("quantity") or 0)
    try:
        qty = abs(int(raw_qty))
    except Exception:
        qty = 0

    # Live position quantity verification & already-closed guard
    side_str = str(pos.get("side") or "").upper()
    dir_str = str(pos.get("direction") or "").upper()
    is_short = side_str in ["SELL", "PE", "BEAR"] or dir_str == "BEAR" or (str(pos.get("product") or "").upper() == "MIS" and side_str in ["SELL", "BEAR"])
    live_held = None

    if kite and live_market:
        try:
            net_positions = kite.positions().get("net", [])
            for p in net_positions:
                if p.get("tradingsymbol") == contract:
                    live_held = int(p.get("quantity", 0))
                    prod = p.get("product")
                    if prod:
                        product = prod
                    if live_held < 0:
                        is_short = True
                    elif live_held > 0:
                        is_short = False
                    break
        except Exception as p_err:
            logging.warning(f"Could not verify live net quantity for stock {contract}: {p_err}")

    if live_held is not None:
        if live_held == 0:
            logging.info(f"[ALREADY CLOSED] Stock {contract} has 0 quantity in Kite net positions. Skipping duplicate exit.")
            save_executed_exit(contract, "ALREADY_CLOSED", {"status": "ZERO_QTY"})
            return {"success": True, "order_id": "ALREADY_CLOSED", "status": "ZERO_QTY"}
        held_qty = abs(int(live_held))
        qty = min(qty, held_qty) if qty > 0 else held_qty

    if qty <= 0:
        qty = 1

    # Automatic Open-Order Purge Guard: Cancel any existing OPEN / TRIGGER PENDING orders for this stock
    if kite and live_market:
        try:
            open_orders = [o for o in kite.orders() if o.get("tradingsymbol") == contract and o.get("status") in ["OPEN", "TRIGGER PENDING"]]
            for oo in open_orders:
                prev_oid = str(oo.get("order_id"))
                var = oo.get("variety", kite.VARIETY_REGULAR)
                logging.info(f"[PURGE OPEN ORDER] Cancelling existing {oo.get('status')} order #{prev_oid} on stock {contract} to release broker quantity lock.")
                try:
                    kite.cancel_order(variety=var, order_id=prev_oid)
                except Exception as cancel_err:
                    logging.warning(f"Could not cancel open order #{prev_oid} for stock {contract}: {cancel_err}")
        except Exception as o_err:
            logging.warning(f"Order book query for open order purge failed for stock {contract}: {o_err}")

    if is_contract_exit_executed(contract):
        prev = EXECUTED_EXITS.get(contract, {})
        oid = str(prev.get("order_id", ""))
        prev_ts = prev.get("timestamp", "")
        
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

        if is_reentry:
            logging.info(f"[EXIT GUARD RESET] Stock {contract} is a fresh re-entry (entry_time={pos_entry_time} > exit_ts={prev_ts}). Resetting stale exit guard order {oid}.")
            clear_executed_exit(contract)
        elif oid == "REJECTED_ERROR":
            # CVE-1 FIX: Handle REJECTED_ERROR with backoff retry rather than permanent lockout
            elapsed_secs = 999
            if prev_ts:
                try:
                    elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                except Exception:
                    pass
            retry_count = int(prev.get("details", {}).get("retry_count", 0))
            if elapsed_secs < 15:
                logging.info(f"[EXIT GUARD BACKOFF] Stock {contract} previous exit failed. Backing off ({elapsed_secs:.0f}s < 15s).")
                return {"success": False, "order_id": "REJECTED_ERROR", "status": "BACKOFF"}
            elif retry_count < 5:
                logging.warning(f"[EXIT RETRY] Retrying failed exit for stock {contract} (attempt {retry_count + 1}/5, elapsed={elapsed_secs:.0f}s)...")
                clear_executed_exit(contract)
            else:
                logging.critical(f"[EXIT RETRY EXHAUSTED] All 5 exit attempts failed for stock {contract}! Manual intervention required.")
                if elapsed_secs >= 60:
                    clear_executed_exit(contract)
                return {"success": False, "order_id": "REJECTED_ERROR", "status": "MAX_RETRIES_EXCEEDED"}
        elif oid and kite and live_market and oid != "ALREADY_CLOSED":
            o_status = None
            try:
                orders = kite.orders()
                for o in orders:
                    if str(o.get("order_id")) == str(oid):
                        o_status = o.get("status")
                        break
                if o_status in ["OPEN", "TRIGGER PENDING"]:
                    elapsed_secs = 999
                    if prev_ts:
                        try:
                            elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                        except Exception:
                            pass
                    if elapsed_secs < 15:
                        logging.info(f"[EXIT GUARD BLOCK] Stock {contract} exit order {oid} is {o_status} (placed {elapsed_secs:.0f}s ago). Waiting for fill.")
                        return {"success": False, "order_id": oid, "status": "WAITING_FILL"}
                    logging.warning(f"[PENDING LIMIT EXIT DETECTED] Stock order {oid} for {contract} is OPEN/UNFILLED after {elapsed_secs:.0f}s. Cancelling and executing fallback...")
                    try:
                        kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=oid)
                    except Exception as c_err:
                        logging.warning(f"Could not cancel pending order {oid}: {c_err}")
                    clear_executed_exit(contract)
                elif o_status in ["CANCELLED", "REJECTED", "EXPIRED", "CANCELLED ALL"]:
                    elapsed_secs = 0
                    if prev_ts:
                        try:
                            elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                        except Exception:
                            pass
                    if elapsed_secs < 30:
                        logging.info(f"[EXIT GUARD COOLDOWN] Stock order {oid} for {contract} was {o_status} ({elapsed_secs:.0f}s ago). Backing off before retry.")
                        return {"success": False, "order_id": oid, "status": "COOLDOWN"}
                    logging.warning(f"[EXIT GUARD RESET] Stock order {oid} for {contract} was {o_status} > 30s ago. Retrying exit.")
                    clear_executed_exit(contract)
                else:
                    logging.info(f"[EXIT GUARD BLOCK] Stock {contract} exit order {oid} is {o_status or 'UNKNOWN'}. Skipping duplicate exit call.")
                    return {"success": False, "order_id": oid, "status": o_status or "UNKNOWN"}
            except Exception as check_err:
                logging.debug(f"Could not verify exit order status for {contract}: {check_err}")
                logging.info(f"[EXIT GUARD BLOCK] Stock {contract} exit order {oid} status could not be verified. Skipping duplicate exit call.")
                return {"success": False, "order_id": oid, "status": "VERIFY_FAILED"}
        else:
            logging.info(f"[EXIT GUARD BLOCK] Stock {contract} exit order already submitted (Order ID: {prev.get('order_id')}). Skipping duplicate exit call.")
            return {"success": False, "order_id": str(prev.get('order_id')), "status": "ALREADY_SUBMITTED"}

    target_product = product or pos.get("product")
    if is_short:
        target_product = kite.PRODUCT_MIS
    elif not target_product:
        target_product = kite.PRODUCT_CNC

    exit_txn = kite.TRANSACTION_TYPE_BUY if is_short else kite.TRANSACTION_TYPE_SELL
    action_label = "cover (BUY)" if is_short else "sell (SELL)"

    try:
        q_key = f"{kite.EXCHANGE_NSE}:{contract}"
        q = kite.quote([q_key])
        q_data = q.get(q_key, {}) if isinstance(q, dict) else {}
        ltp = float(q_data.get("last_price", 0))
        if is_short:
            depth_sell = q_data.get("depth", {}).get("sell", [])
            ask = float(depth_sell[0].get("price", 0)) if depth_sell else 0
            price = round((ask if ask > 0 else ltp) * 1.005, 1)
        else:
            depth_buy = q_data.get("depth", {}).get("buy", [])
            bid = float(depth_buy[0].get("price", 0)) if depth_buy else 0
            price = round((bid if bid > 0 else ltp) * 0.995, 1)

        try:
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                exchange=kite.EXCHANGE_NSE, transaction_type=exit_txn,
                quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=price, product=target_product
            )
            save_executed_exit(contract, oid, {"type": "LIMIT", "price": price, "qty": qty, "txn": exit_txn})
            logging.info(f"Closed stock {contract} via {action_label} with product {target_product} (Order ID: {oid})")
            return {"success": True, "order_id": str(oid), "type": "LIMIT", "price": price, "qty": qty}
        except Exception as primary_err:
            logging.warning(f"Primary stock exit with {target_product} failed for {contract}: {primary_err}. Retrying with fallback...")
            if not is_short:
                alt_product = kite.PRODUCT_MIS if target_product == kite.PRODUCT_CNC else kite.PRODUCT_CNC
                try:
                    oid = kite.place_order(
                        variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                        exchange=kite.EXCHANGE_NSE, transaction_type=exit_txn,
                        quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                        price=price, product=alt_product
                    )
                    save_executed_exit(contract, oid, {"type": "LIMIT_ALT", "price": price, "qty": qty, "txn": exit_txn})
                    logging.info(f"Fallback stock exit SUCCESS for {contract} with product {alt_product} (Order ID: {oid})")
                    return {"success": True, "order_id": str(oid), "type": "LIMIT_ALT", "price": price, "qty": qty}
                except Exception as alt_err:
                    pass
            try:
                oid = kite.place_order(
                    variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                    exchange=kite.EXCHANGE_NSE, transaction_type=exit_txn,
                    quantity=qty, order_type=kite.ORDER_TYPE_MARKET,
                    product=target_product
                )
                save_executed_exit(contract, oid, {"type": "MARKET_EMERGENCY", "qty": qty, "txn": exit_txn})
                logging.info(f"Emergency MARKET stock exit SUCCESS for {contract} via {action_label} with product {target_product} (Order ID: {oid})")
                return {"success": True, "order_id": str(oid), "type": "MARKET_EMERGENCY", "qty": qty}
            except Exception as m_final_err:
                save_executed_exit(contract, "REJECTED_ERROR", {"error": str(m_final_err)})
                logging.error(f"All stock exit attempts failed for {contract}: primary={primary_err}, market={m_final_err}")
                return {"success": False, "order_id": "REJECTED_ERROR", "error": str(m_final_err)}
    except Exception as e:
        save_executed_exit(contract, "REJECTED_ERROR", {"error": str(e)})
        logging.error(f"Stock exit failed for {contract}: {e}")
        return {"success": False, "order_id": "REJECTED_ERROR", "error": str(e)}

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
    details = dict(details) if details else {}
    if str(order_id) == "REJECTED_ERROR":
        prev_retries = int(EXECUTED_EXITS.get(contract, {}).get("details", {}).get("retry_count", 0))
        details["retry_count"] = prev_retries + 1
    EXECUTED_EXITS[contract] = {
        "order_id": str(order_id),
        "timestamp": dt.now().isoformat(),
        "details": details
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
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    t_now = now.time()
    return datetime_time(9, 15) <= t_now <= datetime_time(15, 30)

def is_new_entry_allowed(live_execution_active=True):
    """Check if new trade entries are allowed.
    If live_execution_active is False (offline/scan-only/after-market mode), returns True to allow scanning & research anytime.
    If live_execution_active is True, restricts new entries strictly to Mon-Fri 09:15 to 15:20 IST.
    """
    if not live_execution_active:
        return True
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    t_now = now.time()
    return datetime_time(9, 15) <= t_now <= datetime_time(15, 20)

def close_position(kite, pos, live_market=True, product=None, qty_override=None, live=None, product_type=None):
    if live is not None:
        live_market = live
    if product_type is not None and product is None:
        product = product_type
    contract = pos.get("contract") or pos.get("tradingsymbol")
    if not contract:
        return
    
    target_product = pos.get("product")
    try:
        if kite:
            kp = kite.positions()
            for p in (kp.get("day", []) + kp.get("net", [])):
                if p.get("tradingsymbol") == contract and int(p.get("quantity", 0)) > 0:
                    target_product = p.get("product")
                    break
    except Exception as e:
        logging.warning(f"Could not fetch Kite position product for {contract}: {e}")
    if not target_product:
        target_product = product or (kite.PRODUCT_NRML if kite else "NRML")

    c_str = str(contract).upper()
    is_option = is_option_contract(c_str)
    if "SENSEX" in c_str or "BSE" in c_str or "BANKEX" in c_str:
        target_exch = "BFO" if is_option else "BSE"
    elif is_option:
        target_exch = "NFO"
    else:
        target_exch = "NSE"

    qty = qty_override if qty_override is not None else (pos.get("quantity") or (get_option_lot_size(contract) or pos.get("lot_size", 1)) * pos.get("position_size", 1))

    # Live position quantity verification & already-closed guard
    if kite and live_market:
        try:
            net_positions = kite.positions().get("net", [])
            for p in net_positions:
                if p.get("tradingsymbol") == contract:
                    live_held = int(p.get("quantity", 0))
                    if live_held <= 0:
                        logging.info(f"[ALREADY CLOSED] {contract} has {live_held} quantity in Kite net positions. Skipping exit order.")
                        save_executed_exit(contract, "ALREADY_CLOSED", {"status": "ZERO_QTY"})
                        return {"success": True, "order_id": "ALREADY_CLOSED", "status": "ZERO_QTY"}
                    qty = min(qty, live_held)
                    break
        except Exception as p_err:
            logging.warning(f"Could not verify live net quantity for {contract}: {p_err}")

    # Automatic Open-Order Purge Guard: Cancel any existing OPEN / TRIGGER PENDING orders for this contract
    if kite and live_market:
        try:
            open_orders = [o for o in kite.orders() if o.get("tradingsymbol") == contract and o.get("status") in ["OPEN", "TRIGGER PENDING"]]
            for oo in open_orders:
                prev_oid = str(oo.get("order_id"))
                var = oo.get("variety", kite.VARIETY_REGULAR)
                logging.info(f"[PURGE OPEN ORDER] Cancelling existing {oo.get('status')} order #{prev_oid} on option {contract} to release broker quantity lock.")
                try:
                    kite.cancel_order(variety=var, order_id=prev_oid)
                except Exception as cancel_err:
                    logging.warning(f"Could not cancel open order #{prev_oid} for option {contract}: {cancel_err}")
        except Exception as o_err:
            logging.warning(f"Order book query for open order purge failed for option {contract}: {o_err}")

    if kite and live_market and not is_market_open():
        logging.info(f"[MARKET CLOSED] Skipping live Zerodha exit order for {contract} outside market hours (09:15-15:30 IST). Position status logged.")
        return {"success": False, "reason": "MARKET_CLOSED"}

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
        oid = str(prev.get("order_id", ""))
        prev_ts = prev.get("timestamp", "")
        
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

        if is_reentry:
            logging.info(f"[EXIT GUARD RESET] Contract {contract} is a fresh re-entry (entry_time={pos_entry_time} > exit_ts={prev_ts}). Resetting stale exit guard {oid}.")
            clear_executed_exit(contract)
        elif oid == "REJECTED_ERROR":
            # CVE-1 FIX: Handle REJECTED_ERROR with backoff retry rather than permanent lockout
            elapsed_secs = 999
            if prev_ts:
                try:
                    elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                except Exception:
                    pass
            retry_count = int(prev.get("details", {}).get("retry_count", 0))
            if elapsed_secs < 15:
                logging.info(f"[EXIT GUARD BACKOFF] Contract {contract} previous exit failed. Backing off ({elapsed_secs:.0f}s < 15s).")
                return {"success": False, "order_id": "REJECTED_ERROR", "status": "BACKOFF"}
            elif retry_count < 5:
                logging.warning(f"[EXIT RETRY] Retrying failed exit for contract {contract} (attempt {retry_count + 1}/5, elapsed={elapsed_secs:.0f}s)...")
                clear_executed_exit(contract)
            else:
                logging.critical(f"[EXIT RETRY EXHAUSTED] All 5 exit attempts failed for contract {contract}! Manual intervention required.")
                if elapsed_secs >= 60:
                    clear_executed_exit(contract)
                return {"success": False, "order_id": "REJECTED_ERROR", "status": "MAX_RETRIES_EXCEEDED"}
        elif oid and kite and live_market and oid != "ALREADY_CLOSED":
            o_status = None
            try:
                orders = kite.orders()
                for o in orders:
                    if str(o.get("order_id")) == str(oid):
                        o_status = o.get("status")
                        break
                if o_status in ["OPEN", "TRIGGER PENDING"]:
                    elapsed_secs = 999
                    if prev_ts:
                        try:
                            elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                        except Exception:
                            pass
                    if elapsed_secs < 15:
                        logging.info(f"[EXIT GUARD BLOCK] {contract} exit order {oid} is {o_status} (placed {elapsed_secs:.0f}s ago). Waiting for fill.")
                        return {"success": False, "order_id": oid, "status": "WAITING_FILL"}
                    logging.warning(f"[PENDING LIMIT EXIT DETECTED] Order {oid} for {contract} has been OPEN for {elapsed_secs:.0f}s. Cancelling order and executing aggressive Marketable LIMIT exit fallback...")
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
                    return {"success": True, "order_id": str(m_oid), "type": "MARKETABLE_LIMIT_FALLBACK", "price": fallback_price, "qty": qty}
                elif o_status in ["CANCELLED", "REJECTED", "EXPIRED", "CANCELLED ALL"]:
                    elapsed_secs = 0
                    if prev_ts:
                        try:
                            elapsed_secs = (dt.now() - dt.fromisoformat(prev_ts.split("+")[0])).total_seconds()
                        except Exception:
                            pass
                    if elapsed_secs < 30:
                        logging.info(f"[EXIT GUARD COOLDOWN] Order {oid} for {contract} was {o_status} ({elapsed_secs:.0f}s ago). Backing off before retry.")
                        return {"success": False, "order_id": oid, "status": "COOLDOWN"}
                    logging.warning(f"[EXIT GUARD RESET] Order {oid} for {contract} was {o_status} > 30s ago ({elapsed_secs:.0f}s). Retrying exit.")
                    clear_executed_exit(contract)
                else:
                    logging.info(f"[EXIT GUARD BLOCK] {contract} exit order {oid} is {o_status or 'UNKNOWN'}. Skipping duplicate exit call.")
                    return {"success": False, "order_id": oid, "status": o_status or "UNKNOWN"}
            except Exception as check_err:
                logging.debug(f"Could not verify exit order status for {contract}: {check_err}")
                logging.info(f"[EXIT GUARD BLOCK] {contract} exit order {oid} status could not be verified. Skipping duplicate exit call.")
                return {"success": False, "order_id": oid, "status": "VERIFY_FAILED"}
        else:
            logging.info(f"[EXIT GUARD BLOCK] {contract} exit order already submitted (Order ID: {prev.get('order_id')}). Skipping duplicate exit call.")
            return {"success": False, "order_id": str(prev.get('order_id')), "status": "ALREADY_SUBMITTED"}

    if not live_market:
        logging.info(f"[BACKTEST EXIT] {contract}")
        return {"success": True, "reason": "BACKTEST"}

    try:
        oid = kite.place_order(
            variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
            exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
            price=price, product=target_product
        )
        if not qty_override:
            save_executed_exit(contract, oid, {"type": "LIMIT", "price": price, "qty": qty})
        logging.info(f"Closed {contract} with Marketable LIMIT order price {price} on exchange {target_exch} (Order ID: {oid}, Qty: {qty})")

        # Spread Exit: If 2-leg Debit Spread, cover the short leg concurrently
        if pos.get("position_type") == "option_spread" and pos.get("leg2_contract"):
            leg2_c = pos.get("leg2_contract")
            leg2_qty = pos.get("leg2_qty") or qty
            leg2_already_closed = False
            if kite and live_market:
                try:
                    for p in kite.positions().get("net", []):
                        if p.get("tradingsymbol") == leg2_c:
                            live_short_qty = int(p.get("quantity", 0))
                            if live_short_qty >= 0:
                                leg2_already_closed = True
                                logging.info(f"[SPREAD EXIT] Short leg {leg2_c} already covered on Kite (Qty: {live_short_qty}). Skipping duplicate order.")
                            else:
                                leg2_qty = min(leg2_qty, abs(live_short_qty))
                            break
                except Exception as leg2_check_err:
                    logging.warning(f"Could not verify live net quantity for leg2 {leg2_c}: {leg2_check_err}")

            if not leg2_already_closed:
                try:
                    oid_leg2 = kite.place_order(
                        variety=kite.VARIETY_REGULAR, tradingsymbol=leg2_c,
                        exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_BUY,
                        quantity=leg2_qty, order_type=kite.ORDER_TYPE_MARKET,
                        product=target_product
                    )
                    save_executed_exit(leg2_c, oid_leg2, {"type": "SPREAD_LEG2_EXIT", "qty": leg2_qty})
                    logging.info(f"[SPREAD EXIT] Covered short leg {leg2_c} (Order ID: {oid_leg2}, Qty: {leg2_qty})")
                except Exception as leg2_err:
                    logging.error(f"[SPREAD EXIT ERROR] Failed to exit short leg {leg2_c}: {leg2_err}")
        return {"success": True, "order_id": str(oid), "type": "LIMIT", "price": price, "qty": qty}
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
            if not qty_override:
                save_executed_exit(contract, oid, {"type": "LIMIT_FALLBACK", "price": fallback_price, "qty": qty})
            logging.info(f"Fallback Marketable LIMIT exit SUCCESS for {contract} on exchange {target_exch} at price {fallback_price} with product {target_product}")
            return {"success": True, "order_id": str(oid), "type": "LIMIT_FALLBACK", "price": fallback_price, "qty": qty}
        except Exception as m_err:
            try:
                oid = kite.place_order(
                    variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                    exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=qty, order_type=kite.ORDER_TYPE_MARKET,
                    product=target_product
                )
                if not qty_override:
                    save_executed_exit(contract, oid, {"type": "MARKET_EMERGENCY", "qty": qty})
                logging.info(f"Emergency MARKET exit SUCCESS for {contract} on exchange {target_exch} with product {target_product}")
                return {"success": True, "order_id": str(oid), "type": "MARKET_EMERGENCY", "qty": qty}
            except Exception as m_final_err:
                save_executed_exit(contract, "REJECTED_ERROR", {"error": str(m_final_err)})
                logging.error(f"All exit attempts failed for {contract}: primary={primary_err}, alt={m_err}, market={m_final_err}")
                return {"success": False, "order_id": "REJECTED_ERROR", "error": str(m_final_err)}

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
    from_date = (get_ist_now(naive=True) - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = get_ist_now(naive=True).strftime("%Y-%m-%d")
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

    # Target monitoring runs from 09:15 AM market open; SL checks are gated inside by is_before_0945 / failsafe_start_time.

    # Update WebSocket subscriptions for active positions
    ws_mon = None
    try:
        from websocket_monitor import get_global_ws_monitor
        ws_mon = get_global_ws_monitor(
            getattr(kite, "api_key", None),
            getattr(kite, "access_token", None),
            failsafe_start_time=failsafe_start_str
        )
        if ws_mon:
            ws_mon.update_subscriptions(positions_dict)
    except Exception as ws_init_err:
        logging.debug(f"[WEBSOCKET] ws_mon init error: {ws_init_err}")
        ws_mon = None

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

            # Fetch live quote: Try WebSocket tick first (sub-millisecond), fallback to REST quote
            live_ltp = 0.0
            if ws_mon and token:
                ws_ltp, is_fresh = ws_mon.get_ltp(token, max_age_seconds=15.0)
                if ws_ltp > 0 and is_fresh:
                    live_ltp = ws_ltp

            if live_ltp <= 0 and kite:
                try:
                    contract_name = pos.get("contract") or pos.get("symbol") or sym
                    exch = "NSE" if is_stock_spot else ("BFO" if ("SENSEX" in c_str or "BSE" in c_str) else "NFO")
                    q_key = f"{exch}:{contract_name}"
                    q_res = kite.quote([q_key])
                    if q_key in q_res:
                        q_info = q_res[q_key]
                        live_ltp = float(q_info.get("last_price", 0))
                except Exception as q_err:
                    logging.debug(f"Live quote fetch error for {sym}: {q_err}")

            pos_tf = pos.get("timeframe") or timeframe_entry
            df = fetch_and_resample_candles(kite, token, from_date, to_date, pos_tf)
            is_stock = pos.get("position_type") == "stock"
            side_val = str(pos.get("side", "")).upper()
            dir_val = str(pos.get("direction", "")).upper()
            is_short_stock = is_stock and (side_val in ["SELL", "PE", "BEAR"] or dir_val == "BEAR")

            if df.empty:
                # CVE-4 FIX: Decouple emergency tick protection from candle REST API outages
                entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
                current_sl = float(pos.get("current_sl", 0))
                if live_ltp > 0 and entry_s > 0:
                    max_loss_pct = 0.15 if not is_stock else 0.08
                    if is_short_stock:
                        hard_max_sl = round(entry_s * (1.0 + max_loss_pct), 2)
                        is_breached = (live_ltp >= hard_max_sl) or (current_sl > 0 and live_ltp >= current_sl * 1.05)
                    else:
                        hard_max_sl = round(entry_s * (1.0 - max_loss_pct), 2)
                        is_breached = (live_ltp <= hard_max_sl) or (current_sl > 0 and live_ltp <= current_sl * 0.95)
                    if is_breached:
                        logging.critical(f"[CANDLE_API_OUTAGE_SHIELD] Candle fetch empty for {sym}, but live LTP {live_ltp:.2f} breached emergency threshold (Entry {entry_s:.2f}, SL {current_sl:.2f}). Executing emergency exit.")
                        if is_stock:
                            exit_res = close_stock_position(kite, pos, live, product_type)
                        else:
                            exit_res = close_position(kite, pos, live, product_type)
                        if exit_res and exit_res.get("success"):
                            to_clear.append(sym)
                continue

            last = df.iloc[-1]
            cp = float(last['close'])
            tid = pos.get("trade_id")
            current_sl = float(pos.get("current_sl", 0))

            # Compute High (hp) and Low (lp) strictly for candles AFTER trade entry_time + live_ltp
            entry_time_str = sanitize_entry_time(pos)
            hp = live_ltp if live_ltp > 0 else cp
            lp = live_ltp if live_ltp > 0 else cp
            for idx in range(len(df)):
                c_row = df.iloc[idx]
                c_date = str(c_row.get('date', ''))
                if is_candle_before_entry(c_date, entry_time_str):
                    continue
                hp = max(hp, float(c_row['high']))
                lp = min(lp, float(c_row['low']))

            sl_hit = False
            sl_reason = ""
            event_time = last.get('date')

            # Track current TF candle timestamp on position for UI/monitoring
            with lock:
                if sym in positions_dict:
                    positions_dict[sym]["candle_tf_time"] = str(event_time) if event_time else ""
                    positions_dict[sym]["timeframe"] = pos_tf

            # ── FRIDAY EOD 15:15 SMART OPTION AUTO-SQUAREOFF GUARD ──
            # On Fridays (weekday == 4 >= 15:15 IST), manage weekend carryover risk:
            # 1. Short-TF (<= 5min) and Index Options ALWAYS square off (high weekend gamma & decay).
            # 2. Stock Options evaluate an Intelligent Carry Gate:
            #    - HOLD over weekend if:
            #      a) Runner on house money: trailing_stage >= 1 (T1 hit, partial booked or SL at BE)
            #      b) Strong profit cushion: P&L >= +2.0% into close
            #      c) Fresh afternoon breakout: Entered on Friday after 13:30 IST & P&L >= 0.0%
            #      d) Tier 1 Gold setup: tier == 1 / TIER_1_GOLD & P&L >= 0.0%
            #    - SQUARE OFF if Stagnant / Underwater:
            #      Entered earlier in session, P&L < +2.0%, T1 untouched. Eliminates 66-hr weekend theta tax.
            now_dt = get_ist_now().replace(tzinfo=None)
            is_thursday = now_dt.weekday() == 3
            is_friday = now_dt.weekday() == 4
            is_eod_time = now_dt.strftime("%H:%M") >= "15:15"
            pos_tf_str = str(pos.get("timeframe") or timeframe_entry or "").lower()
            is_short_tf = any(tf in pos_tf_str for tf in ["3m", "3min", "3minute", "5m", "5min", "5minute"])
            is_index_contract = (engine_name == "index") or (pos.get("engine") == "index") or any(idx_sym in c_str for idx_sym in ["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY", "FINNIFTY", "BANKEX"])

            # ── 15:15 EOD INTRADAY MIS AUTO-SQUAREOFF GUARD ──
            is_mis_pos = (str(pos.get("product", "")).upper() == "MIS") or is_short_stock
            if is_mis_pos and is_eod_time:
                logging.info(f"[15:15 EOD MIS SQUAREOFF] Closing {sym} ({contract}) | Intraday MIS Auto-Squareoff")
                if is_stock:
                    exit_res = close_stock_position(kite, pos, live, "MIS")
                else:
                    exit_res = close_position(kite, pos, live, "MIS")
                exit_ok = True
                if live and kite:
                    exit_ok = bool(exit_res and exit_res.get("success"))
                if exit_ok:
                    exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else entry_s)
                    pnl = ((entry_s - exit_price) / entry_s * 100) if is_short_stock else (((exit_price - entry_s) / entry_s * 100) if entry_s else 0)
                    log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_EOD_MIS", "CLOSED",
                           f"15:15 EOD MIS Auto-Squareoff (Exit @ {exit_price:.2f})", pnl,
                           entry=entry_s, sl=pos.get("current_sl", ""), target=pos.get("t1", ""),
                           event_time=last.get('date'))
                    if tid:
                        trade_db.update_trade(tid, {
                            "status": "COMPLETED",
                            "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pnl_percent": round(pnl, 2),
                            "details": f"15:15 EOD MIS Auto-Squareoff | Exit @ {exit_price:.2f}"
                        })
                    to_clear.append(sym)
                else:
                    logging.critical(f"[EOD_MIS_SQUAREOFF FAILED] MIS exit order for {sym} failed ({exit_res}). Retaining for retry.")
                continue

            if (is_friday or is_thursday) and is_eod_time and not is_stock:
                entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
                curr_p = live_ltp if live_ltp > 0 else (cp if cp > 0 else entry_s)
                curr_pnl_pct = ((curr_p - entry_s) / entry_s * 100) if entry_s > 0 else 0.0

                should_squareoff = False
                squareoff_reason = ""
                day_name = "Thursday" if is_thursday else "Friday"

                if is_short_tf or is_index_contract:
                    should_squareoff = True
                    squareoff_reason = f"{day_name} 15:15 EOD Index/Intraday Auto-Squareoff [{'WEEKLY_THETA_GUARD' if is_thursday else 'WEEKEND_DECAY_GUARD'}]"
                else:
                    # Stock Option: Apply Intelligent Carry Gate
                    is_runner_be = int(pos.get("trailing_stage") or 0) >= 1
                    is_solid_profit = curr_pnl_pct >= float(cfg.get("friday_min_profit_pct", 2.0))
                    
                    # Check if fresh afternoon entry (e.g. entered after 13:30 on Friday)
                    is_fresh_pm = False
                    pos_et = str(pos.get("entry_time") or "")
                    if pos_et:
                        try:
                            et_clean = pos_et.split("+")[0].replace("T", " ")
                            et_obj = dt.fromisoformat(et_clean)
                            if et_obj.date() == now_dt.date() and et_obj.strftime("%H:%M") >= "13:30":
                                is_fresh_pm = True
                        except Exception:
                            pass
                    
                    is_tier1_gold = (int(pos.get("tier") or 0) == 1) or ("GOLD" in str(pos.get("tier_label", "")).upper())

                    # Qualified to hold?
                    qualified_to_hold = is_runner_be or is_solid_profit or (is_fresh_pm and curr_pnl_pct >= 0.0) or (is_tier1_gold and curr_pnl_pct >= 0.0)

                    if not qualified_to_hold:
                        should_squareoff = True
                        squareoff_reason = f"{day_name} 15:15 EOD Stagnant Square-off [THETA_PROTECTION] (PnL {curr_pnl_pct:.2f}% < +2.0%, T1 untouched)"
                    else:
                        hold_tag = "RUNNER_BE" if is_runner_be else ("PROFIT_CUSHION" if is_solid_profit else ("FRESH_PM_ENTRY" if is_fresh_pm else "TIER_1_GOLD_ACCUMULATION"))
                        logging.info(f"[{day_name.upper()} 15:15 CARRY APPROVED] Holding {sym} ({contract}) into next session: Tag={hold_tag} | PnL {curr_pnl_pct:.2f}% | Entry {entry_s:.2f} -> LTP {curr_p:.2f}")

                if should_squareoff:
                    logging.info(f"[{day_name.upper()} 15:15 EOD SQUAREOFF] Closing {sym} ({contract}) | {squareoff_reason}")
                    exit_res = close_position(kite, pos, live, product_type)
                    exit_ok = True
                    if live and kite:
                        exit_ok = bool(exit_res and exit_res.get("success"))
                    if exit_ok:
                        exit_price = curr_p
                        pnl = curr_pnl_pct
                        log_fn(sym, pos.get("pattern", ""), pos_tf, f"EXIT_EOD_{day_name.upper()}", "CLOSED",
                               f"{squareoff_reason} (Exit @ {exit_price:.2f})", pnl,
                               entry=entry_s, sl=pos.get("current_sl", ""), target=pos.get("t1", ""),
                               event_time=last.get('date'))
                        if tid:
                            trade_db.update_trade(tid, {
                                "status": "COMPLETED",
                                "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "pnl_percent": round(pnl, 2),
                                "details": f"{squareoff_reason} | Exit @ {exit_price:.2f}"
                            })
                        to_clear.append(sym)
                    else:
                        logging.critical(f"[EOD_SQUAREOFF FAILED] EOD exit order for {sym} failed or pending ({exit_res}). Retaining for retry.")
                    continue

            # 1) SL Evaluation (Separated SL Monitor: Skipped 09:15-09:45 AM, Active at 09:45 AM+)
            now_time_str = get_ist_now().strftime("%H:%M")
            is_before_0945 = now_time_str < "09:45"
            is_start_0945 = "09:45" <= now_time_str <= "09:47"

            # ── STALE / OUTLIER ENTRY PRICE GUARD ──
            # Prevent false emergency SL triggers when entry_spot or current_sl has an extreme data mismatch vs live LTP
            # (e.g. BSE entry 12.0 with SL 1.0 when live option market is trading at 0.60).
            is_outlier_entry = False
            entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
            if entry_s > 0 and live_ltp > 0:
                if (entry_s / live_ltp > 3.0 or live_ltp / entry_s > 3.0) and pos.get("user_edited"):
                    is_outlier_entry = True
                    logging.warning(f"[STALE OUTLIER GUARD] {sym} entry {entry_s:.2f} diverges >300% from live LTP {live_ltp:.2f}. Skipping false emergency SL trigger.")

            if current_sl > 0:
                sl_floor = get_sl_floor_time(pos)
                if is_before_0945:
                    # Target monitoring runs from 09:15 AM, structural candle SL is skipped until 09:45 AM.
                    # CVE-3 FIX: Morning Catastrophic Circuit Breaker active 09:15-09:45 AM.
                    # Protects against catastrophic opening gap-downs (>= 25% for options, >= 12% for stocks).
                    if entry_s > 0 and live_ltp > 0 and not is_outlier_entry:
                        opt_loss_cap = float(cfg.get("max_option_loss_pct", 15)) / 100.0 if not is_stock else 0.08
                        if is_short_stock and live_ltp >= (entry_s * 1.12):
                            sl_hit = True
                            rise_pct = (live_ltp - entry_s) / entry_s * 100.0
                            sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_12PCT (Short Stock LTP {live_ltp:.2f} up {rise_pct:.1f}% from entry {entry_s:.2f})"
                            cp = live_ltp
                            event_time = last.get('date')
                        elif not is_short_stock and not is_stock and live_ltp <= (entry_s * (1.0 - opt_loss_cap)):
                            sl_hit = True
                            drop_pct = (entry_s - live_ltp) / entry_s * 100.0
                            sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_{int(opt_loss_cap*100)}PCT (Option LTP {live_ltp:.2f} down {drop_pct:.1f}% from entry {entry_s:.2f})"
                            cp = live_ltp
                            event_time = last.get('date')
                        elif not is_short_stock and is_stock and live_ltp <= (entry_s * 0.88):
                            sl_hit = True
                            drop_pct = (entry_s - live_ltp) / entry_s * 100.0
                            sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_12PCT (Stock LTP {live_ltp:.2f} down {drop_pct:.1f}% from entry {entry_s:.2f})"
                            cp = live_ltp
                            event_time = last.get('date')
                elif is_start_0945:
                    # 09:45 AM Failsafe Check: If trading breached SL & prev candle closed breach & current candle trading breach
                    prev_date = str(df.iloc[-2]['date']) if len(df) >= 2 else ""
                    if is_short_stock:
                        prev_closed_breach = (len(df) >= 2 and float(df.iloc[-2]['close']) >= current_sl
                                             and not is_candle_before_entry(prev_date, sl_floor))
                        curr_breach = (live_ltp > 0 and live_ltp >= current_sl) or (float(df.iloc[-1]['close']) >= current_sl)
                    else:
                        prev_closed_breach = (len(df) >= 2 and float(df.iloc[-2]['close']) <= current_sl
                                             and not is_candle_before_entry(prev_date, sl_floor))
                        curr_breach = (live_ltp > 0 and live_ltp <= current_sl) or (float(df.iloc[-1]['close']) <= current_sl)
                    if curr_breach and prev_closed_breach:
                        sl_hit = True
                        sl_reason = f"SL_FAILSAFE_0945_TRIGGER (LTP {live_ltp:.2f} {' >=' if is_short_stock else ' <='} {current_sl:.2f} & Prev Bar Closed Breach)"
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
                        c_close_val = float(c_row['close'])
                        if is_short_stock and c_close_val >= current_sl:
                            sl_hit = True
                            sl_reason = f"CANDLE_CLOSE_SL ({pos_tf} Bar @ {c_date})"
                            cp = c_close_val
                            event_time = c_row.get('date')
                            break
                        elif not is_short_stock and c_close_val <= current_sl:
                            sl_hit = True
                            sl_reason = f"CANDLE_CLOSE_SL ({pos_tf} Bar @ {c_date})"
                            cp = c_close_val
                            event_time = c_row.get('date')
                            break

                    # ── LIVE RECLAIM GUARD ──
                    # If a historical candle closed below SL, but the current live market price has reclaimed
                    # above Entry Price (live_ltp >= entry_s) and the latest completed bar closed above current_sl,
                    # do NOT execute a retroactive SL exit on a profitable running trade (ISSUE-041).
                    if sl_hit and "CANDLE_CLOSE_SL" in sl_reason:
                        entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
                        latest_completed_close = float(df.iloc[-2]['close']) if len(df) >= 2 else 0.0
                        if is_short_stock:
                            if entry_s > 0 and live_ltp <= entry_s and latest_completed_close < current_sl:
                                logging.info(f"[RECLAIM_GUARD] Suppressed retroactive {sl_reason} for short {sym} ({pos.get('contract')}): Trade reclaimed below Entry ({live_ltp:.2f} <= {entry_s:.2f}) and latest completed bar closed at {latest_completed_close:.2f} < SL ({current_sl:.2f}). Trade remains active.")
                                sl_hit = False
                                sl_reason = ""
                        else:
                            if entry_s > 0 and live_ltp >= entry_s and latest_completed_close > current_sl:
                                logging.info(f"[RECLAIM_GUARD] Suppressed retroactive {sl_reason} for {sym} ({pos.get('contract')}): Trade has reclaimed above Entry ({live_ltp:.2f} >= {entry_s:.2f}) and latest completed bar closed at {latest_completed_close:.2f} > SL ({current_sl:.2f}). Trade remains active.")
                                sl_hit = False
                                sl_reason = ""

            # 2) Emergency Hard Stop / Direct LTP evaluation (Active after 09:45 AM)
            if not sl_hit and current_sl > 0 and live_ltp > 0 and not is_before_0945 and not is_outlier_entry:
                if is_short_stock:
                    if sl_mode == "tick_ltp" and live_ltp >= current_sl:
                        sl_hit = True
                        sl_reason = f"TICK_LTP_SL ({live_ltp})"
                        cp = live_ltp
                    elif sl_mode == "hybrid":
                        emergency_cushion = max(0.30, current_sl * 0.05) if current_sl < 10 else max(1.00, current_sl * emergency_buffer_pct)
                        emergency_threshold = round(current_sl + emergency_cushion, 2)
                        if live_ltp >= emergency_threshold:
                            sl_hit = True
                            sl_reason = f"EMERGENCY_HARD_SL (LTP {live_ltp:.2f} >= {emergency_threshold:.2f})"
                            cp = live_ltp
                else:
                    if sl_mode == "tick_ltp" and live_ltp <= current_sl:
                        sl_hit = True
                        sl_reason = f"TICK_LTP_SL ({live_ltp})"
                        cp = live_ltp
                    elif sl_mode == "hybrid":
                        emergency_cushion = max(0.30, current_sl * 0.05) if current_sl < 10 else max(1.00, current_sl * emergency_buffer_pct)
                        emergency_threshold = round(current_sl - emergency_cushion, 2)
                        if live_ltp <= emergency_threshold:
                            sl_hit = True
                            sl_reason = f"EMERGENCY_HARD_SL (LTP {live_ltp:.2f} <= {emergency_threshold:.2f})"
                            cp = live_ltp

            # 2b) Hard Max-Loss Circuit Shield (Default 15% Cap on Entry Price for Options, 8% for Stocks)
            max_loss_pct = float(cfg.get("max_option_loss_pct", 15)) / 100.0 if not is_stock else 0.08
            if is_short_stock:
                hard_max_sl_threshold = round(entry_s * (1.0 + max_loss_pct), 2) if entry_s > 0 else 0.0
                if not sl_hit and hard_max_sl_threshold > 0 and live_ltp > 0 and live_ltp >= hard_max_sl_threshold and not is_before_0945 and not is_outlier_entry:
                    sl_hit = True
                    sl_reason = f"HARD_MAX_{int(max_loss_pct*100)}PCT_SL (LTP {live_ltp:.2f} >= {hard_max_sl_threshold:.2f})"
                    cp = live_ltp
            else:
                hard_max_sl_threshold = round(entry_s * (1.0 - max_loss_pct), 2) if entry_s > 0 else 0.0
                if not sl_hit and hard_max_sl_threshold > 0 and live_ltp > 0 and live_ltp <= hard_max_sl_threshold and not is_before_0945 and not is_outlier_entry:
                    sl_hit = True
                    sl_reason = f"HARD_MAX_{int(max_loss_pct*100)}PCT_SL (LTP {live_ltp:.2f} <= {hard_max_sl_threshold:.2f})"
                    cp = live_ltp

            # 2c) Spot-Anchored Structural SL Guard for Options
            # ONLY applies to INITIAL Stop Loss (trailing_stage == 0 and current_sl < entry_s).
            # Once a position has been TRAILED to Breakeven or Profit (trailing_stage >= 1 or current_sl >= entry_s),
            # the Trailed SL must NEVER be suppressed by initial morning spot support (ISSUE-042).
            enable_spot_guard = cfg.get("enable_spot_sl_guard", True) if isinstance(cfg, dict) else True
            trailing_stg = int(pos.get("trailing_stage") or 0)
            is_trailed_stop = (trailing_stg >= 1) or (entry_s > 0 and current_sl >= (entry_s * 0.99))
            is_hard_max_sl = "HARD_MAX_" in sl_reason or "CATASTROPHIC" in sl_reason

            if sl_hit and not is_hard_max_sl and not is_stock and enable_spot_guard and not is_trailed_stop and kite:
                spot_tok = pos.get("spot_token") or pos.get("index_token") or pos.get("underlying_token")
                if not spot_tok:
                    from registries import STOCK_REGISTRY, INDEX_REGISTRY
                    reg_entry = STOCK_REGISTRY.get(sym) or INDEX_REGISTRY.get(sym)
                    if isinstance(reg_entry, dict):
                        spot_tok = reg_entry.get("token")
                    elif isinstance(reg_entry, int):
                        spot_tok = reg_entry

                spot_sl = float(pos.get("spot_sl") or 0.0)
                if spot_tok and spot_sl <= 0:
                    try:
                        df_spot_chk = fetch_and_resample_candles(kite, spot_tok, from_date, to_date, pos_tf or timeframe_entry)
                        if df_spot_chk is not None and len(df_spot_chk) >= 5:
                            side_s = str(pos.get("side", "CE")).upper()
                            if side_s in ["CE", "BUY", "BULL"]:
                                low_val = float(df_spot_chk['low'].iloc[-10:].min())
                                spot_sl = round(low_val - max(0.50, low_val * 0.005), 2)
                            else:
                                high_val = float(df_spot_chk['high'].iloc[-10:].max())
                                spot_sl = round(high_val + max(0.50, high_val * 0.005), 2)
                            pos["spot_sl"] = spot_sl
                    except Exception as derive_spot_err:
                        logging.debug(f"Dynamic spot_sl derivation failed for {sym}: {derive_spot_err}")

                if spot_tok and spot_sl > 0:
                    try:
                        sq = kite.ltp([spot_tok])
                        live_spot = float(list(sq.values())[0]["last_price"]) if sq else 0.0
                        side_str = str(pos.get("side", "CE")).upper()
                        is_bull = side_str in ["CE", "BUY", "BULL"]
                        # Catastrophic option emergency cap: If option drops beyond max_loss_pct (15%), exit regardless of spot
                        is_catastrophic_opt = (entry_s > 0 and live_ltp > 0 and live_ltp <= (entry_s * (1.0 - max_loss_pct)))

                        if is_bull and live_spot > spot_sl and not is_catastrophic_opt:
                            logging.info(f"[SPOT_SL_GUARD] Suppressed premature option SL exit for {sym} ({pos.get('contract')}): Option LTP {live_ltp:.2f} tripped SL, but Underlying Spot ({live_spot:.2f}) is strictly holding above support ({spot_sl:.2f}).")
                            sl_hit = False
                        elif (not is_bull) and live_spot < spot_sl and not is_catastrophic_opt:
                            logging.info(f"[SPOT_SL_GUARD] Suppressed premature PE option SL exit for {sym} ({pos.get('contract')}): Underlying Spot ({live_spot:.2f}) is strictly below ceiling ({spot_sl:.2f}).")
                            sl_hit = False
                    except Exception as s_err:
                        logging.warning(f"Spot SL guard check error for {sym}: {s_err}")

            if sl_hit:
                logging.warning(f"SL [{sl_reason}]: {sym} at {cp} (TF: {pos_tf})")
                if is_stock:
                    exit_res = close_stock_position(kite, pos, live, product_type)
                else:
                    exit_res = close_position(kite, pos, live, product_type)
                
                exit_ok = True
                if live and kite:
                    exit_ok = bool(exit_res and exit_res.get("success"))

                if exit_ok:
                    entry_s = pos.get("entry_spot", 0)
                    exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else current_sl)
                    pnl = ((entry_s - exit_price) / entry_s * 100) if is_short_stock else (((exit_price - entry_s) / entry_s * 100) if entry_s else 0)
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
                else:
                    logging.critical(f"[EXIT_SL FAILED] Exit order for {sym} failed or pending ({exit_res}). Retaining in memory for retry.")
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
            entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
            if is_short_stock:
                gain_pct = ((entry_s - lp) / entry_s * 100) if entry_s > 0 else 0.0
            else:
                gain_pct = ((hp - entry_s) / entry_s * 100) if entry_s > 0 else 0.0

            # Feature 5: Positive Breakeven (+BE: Entry + 2% for Long, Entry - 2% for Short) Triggered when peak gain >= +10%
            if pos.get("trailing_stage", 0) == 0 and gain_pct >= 10.0 and has_higher_targets:
                curr_sl = float(pos.get("current_sl") or 0.0)
                if is_short_stock:
                    be_target = round(round((entry_s * 0.98) / 0.05) * 0.05, 2)
                    new_sl = min(curr_sl, be_target) if curr_sl > 0 else be_target
                else:
                    is_bull = str(pos.get("side","CE")).upper() in ["CE", "BUY", "BULL"]
                    if is_bull:
                        be_target = round(round((entry_s * 1.02) / 0.05) * 0.05, 2)
                        new_sl = max(curr_sl, be_target)
                    else:
                        be_target = round(round((entry_s * 0.98) / 0.05) * 0.05, 2)
                        new_sl = min(curr_sl, be_target) if curr_sl > 0 else be_target
                sl_stamp = dt.now().isoformat()
                with lock:
                    if sym in positions_dict:
                        positions_dict[sym]["current_sl"] = new_sl
                        positions_dict[sym]["trailing_stage"] = 1
                        positions_dict[sym]["sl_set_time"] = sl_stamp
                ext_metric = f"Low={lp:.2f}" if is_short_stock else f"High={hp:.2f}"
                logging.info(f"TRAIL-1 (+10% Gain Lock -> +2% BE) {sym}: {ext_metric} (+{gain_pct:.1f}%) -> SL=+BE ({new_sl:.2f})")
                log_fn(sym, pos.get("pattern", ""), timeframe_entry, "TRAIL_BE", "MUTATED",
                       f"SL=+BE {new_sl:.2f} (+{gain_pct:.1f}% gain locked)",
                       entry=entry_s, sl=new_sl, target=t1_val,
                       event_time=last.get('date'))
                if tid:
                    trade_db.update_trade(tid, {"trailing_stage": 1, "current_sl": new_sl, "sl_set_time": sl_stamp})

            t1_hit = (lp <= (t1_val + buf_t1)) if is_short_stock else (hp >= (t1_val - buf_t1))
            if t1_val and t1_hit:
                # RULE: If T2 or T3 is NOT available, exit 100% at T1 (early exit threshold)!
                if not has_higher_targets:
                    reached_val = lp if is_short_stock else hp
                    logging.info(f"T1 FULL EXIT (No T2/T3): {sym} reached {reached_val:.2f} (Target: {t1_val:.2f}, Buffer: {buf_t1:.2f})")
                    if is_stock:
                        exit_res = close_stock_position(kite, pos, live, product_type)
                    else:
                        exit_res = close_position(kite, pos, live, product_type)
                    
                    exit_ok = True
                    if live and kite:
                        exit_ok = bool(exit_res and exit_res.get("success"))

                    if exit_ok:
                        exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else t1_val)
                        pnl = ((entry_s - exit_price) / entry_s * 100) if is_short_stock else (((exit_price - entry_s) / entry_s * 100) if entry_s else 0)
                        log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_T1", "CLOSED",
                               f"T1={t1_val:.2f} (Exit @ {exit_price:.2f})", pnl,
                               entry=entry_s, sl=pos.get("current_sl", ""), target=t1_val,
                               event_time=last.get('date'))
                        det_str = f"T1 exit ({lp:.2f} <= {t1_val + buf_t1:.2f})" if is_short_stock else f"T1 exit ({hp:.2f} >= {t1_val - buf_t1:.2f})"
                        if tid:
                            trade_db.update_trade(tid, {
                                "status": "TARGET_HIT",
                                "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "pnl_percent": round(pnl, 2),
                                "details": det_str
                            })
                        to_clear.append(sym)
                    else:
                        logging.critical(f"[EXIT_T1 FAILED] T1 exit order for {sym} failed or pending ({exit_res}). Retaining in memory for retry.")
                    continue
                elif pos.get("trailing_stage", 0) == 0:
                    pos_size = int(pos.get("position_size", 1))
                    tranche_mode = cfg.get("tranche_mode", True) if isinstance(cfg, dict) else True
                    # 2-Tranche Model: If holding >= 2 lots/units, book 50% profit at T1 and ride runner
                    if tranche_mode and pos_size >= 2:
                        half_size = pos_size // 2
                        lot_sz = get_option_lot_size(pos.get("contract","")) or pos.get("lot_size", 1)
                        partial_qty = half_size * lot_sz if not is_stock else half_size
                        logging.info(f"[TRANCHE_1_EXIT] Booking 50% partial profit ({half_size} lots / {partial_qty} qty) at T1 ({t1_val:.2f}) for {sym}. Remaining {pos_size - half_size} lots will ride to T2/T3 with BE SL.")
                        if is_stock:
                            exit_res = close_stock_position(kite, pos, live, product_type, qty_override=partial_qty)
                        else:
                            exit_res = close_position(kite, pos, live, product_type, qty_override=partial_qty)
                        
                        exit_ok = True
                        if live and kite:
                            exit_ok = bool(exit_res and exit_res.get("success"))

                        if exit_ok:
                            if is_short_stock:
                                be_sl = round(round((entry_s * 0.98)/0.05)*0.05, 2)
                                partial_pnl = ((entry_s - t1_val) / entry_s * 100) if entry_s else 0
                            else:
                                is_bull = str(pos.get("side","CE")).upper() in ["CE", "BUY", "BULL"]
                                be_sl = round(round((entry_s * 1.02)/0.05)*0.05, 2) if is_bull else round(round((entry_s * 0.98)/0.05)*0.05, 2)
                                partial_pnl = ((t1_val - entry_s) / entry_s * 100) if entry_s else 0
                            with lock:
                                if sym in positions_dict:
                                    positions_dict[sym]["position_size"] = pos_size - half_size
                                    positions_dict[sym]["current_sl"] = be_sl
                                    positions_dict[sym]["trailing_stage"] = 1
                                    positions_dict[sym]["sl_set_time"] = dt.now().isoformat()
                            log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_T1_PARTIAL", "PARTIAL",
                                   f"T1 Banked 50% @ {t1_val:.2f} | Runner SL=+BE ({be_sl:.2f})",
                                   partial_pnl,
                                   entry=entry_s, sl=be_sl, target=t2_val or t3_val,
                                   event_time=last.get('date'))
                            if tid:
                                trade_db.update_trade(tid, {
                                    "position_size": pos_size - half_size,
                                    "trailing_stage": 1,
                                    "current_sl": be_sl,
                                    "sl_set_time": dt.now().isoformat(),
                                    "details": f"T1 50% Banked @ {t1_val:.2f} | Runner active"
                                })
                        else:
                            logging.critical(f"[TRANCHE_1_EXIT FAILED] Partial exit order for {sym} failed ({exit_res}). Preserving full position.")
                    else:
                        # Single-lot trailing to Positive Breakeven (+2%)
                        curr_sl = float(pos.get("current_sl") or 0.0)
                        if is_short_stock:
                            be_sl = round(round((entry_s * 0.98)/0.05)*0.05, 2)
                            new_sl = min(curr_sl, be_sl) if curr_sl > 0 else be_sl
                        else:
                            is_bull = str(pos.get("side","CE")).upper() in ["CE", "BUY", "BULL"]
                            be_sl = round(round((entry_s * 1.02)/0.05)*0.05, 2) if is_bull else round(round((entry_s * 0.98)/0.05)*0.05, 2)
                            new_sl = max(curr_sl, be_sl) if is_bull else (min(curr_sl, be_sl) if curr_sl > 0 else be_sl)
                        sl_stamp = dt.now().isoformat()
                        with lock:
                            if sym in positions_dict:
                                positions_dict[sym]["current_sl"] = new_sl
                                positions_dict[sym]["trailing_stage"] = 1
                                positions_dict[sym]["sl_set_time"] = sl_stamp
                        logging.info(f"TRAIL-1 {sym}: SL=+BE ({new_sl:.2f})")
                        log_fn(sym, pos.get("pattern", ""), timeframe_entry, "TRAIL_BE", "MUTATED",
                               f"SL=+BE {new_sl:.2f}",
                               entry=entry_s, sl=new_sl, target=t1_val,
                               event_time=last.get('date'))
                        if tid:
                            trade_db.update_trade(tid, {"trailing_stage": 1, "current_sl": new_sl, "sl_set_time": sl_stamp})

            t2_hit = (lp <= (t2_val + buf_t2)) if is_short_stock else (hp >= (t2_val - buf_t2))
            if pos.get("trailing_stage", 0) == 1 and t2_val and t2_hit:
                has_t3 = t3_val is not None and t3_val > 0
                if not has_t3:
                    # RULE: If T3 is NOT available, T2 is final target -> FULL EXIT at T2!
                    reached_val = lp if is_short_stock else hp
                    logging.info(f"T2 FULL EXIT (No T3): {sym} reached {reached_val:.2f} (Target: {t2_val:.2f}, Buffer: {buf_t2:.2f})")
                    if is_stock:
                        exit_res = close_stock_position(kite, pos, live, product_type)
                    else:
                        exit_res = close_position(kite, pos, live, product_type)
                    
                    exit_ok = True
                    if live and kite:
                        exit_ok = bool(exit_res and exit_res.get("success"))

                    if exit_ok:
                        entry_s = pos.get("entry_spot", 0)
                        exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else t2_val)
                        pnl = ((entry_s - exit_price) / entry_s * 100) if is_short_stock else (((exit_price - entry_s) / entry_s * 100) if entry_s else 0)
                        log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_T2", "CLOSED",
                               f"T2={t2_val:.2f} (Exit @ {exit_price:.2f})", pnl,
                               entry=entry_s, sl=pos.get("current_sl", ""), target=t2_val,
                               event_time=last.get('date'))
                        det_str = f"T2 exit ({lp:.2f} <= {t2_val + buf_t2:.2f})" if is_short_stock else f"T2 exit ({hp:.2f} >= {t2_val - buf_t2:.2f})"
                        if tid:
                            trade_db.update_trade(tid, {
                                "status": "TARGET_HIT",
                                "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "pnl_percent": round(pnl, 2),
                                "details": det_str
                            })
                        to_clear.append(sym)
                    else:
                        logging.critical(f"[EXIT_T2 FAILED] T2 exit order for {sym} failed or pending ({exit_res}). Retaining in memory for retry.")
                    continue
                else:
                    curr_sl = float(pos.get("current_sl") or 0.0)
                    target_base = float(t1_val or pos.get("entry_spot") or 0.0)
                    if is_short_stock:
                        new_sl = min(curr_sl, target_base) if curr_sl > 0 else target_base
                    else:
                        new_sl = max(curr_sl, target_base) if str(pos.get("side","CE")).upper() in ["CE", "BUY", "BULL"] else (min(curr_sl, target_base) if curr_sl > 0 else target_base)
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

            t3_hit = (lp <= (t3_val + buf_t3)) if is_short_stock else (hp >= (t3_val - buf_t3))
            if t3_val and t3_hit:
                reached_val = lp if is_short_stock else hp
                logging.info(f"T3 EXIT: {sym} reached {reached_val:.2f} (Target: {t3_val:.2f})")
                if is_stock:
                    exit_res = close_stock_position(kite, pos, live, product_type)
                else:
                    exit_res = close_position(kite, pos, live, product_type)
                
                exit_ok = True
                if live and kite:
                    exit_ok = bool(exit_res and exit_res.get("success"))

                if exit_ok:
                    entry_s = pos.get("entry_spot", 0)
                    exit_price = live_ltp if live_ltp > 0 else (cp if cp > 0 else t3_val)
                    pnl = ((entry_s - exit_price) / entry_s * 100) if is_short_stock else (((exit_price - entry_s) / entry_s * 100) if entry_s else 0)
                    log_fn(sym, pos.get("pattern", ""), timeframe_entry, "EXIT_T3", "CLOSED",
                           f"T3={t3_val:.2f} (Exit @ {exit_price:.2f})", pnl,
                           entry=entry_s, sl=pos.get("current_sl", ""), target=t3_val,
                           event_time=last.get('date'))
                    if tid:
                        trade_db.update_trade(tid, {"status": "TARGET_HIT", "exit_time": dt.now().strftime("%Y-%m-%d %H:%M:%S"), "pnl_percent": round(pnl, 2)})
                    to_clear.append(sym)
                else:
                    logging.critical(f"[EXIT_T3 FAILED] T3 exit order for {sym} failed or pending ({exit_res}). Retaining in memory for retry.")
        except Exception as e:
            logging.error(f"Risk error {sym}: {e}")

    if to_clear:
        with lock:
            for s in to_clear:
                positions_dict.pop(s, None)

    if to_clear and save_state_fn:
        save_state_fn()


def monitor_all_active_positions(kite, live=True):
    """
    Standalone position monitor: actively protects ALL open trades across all engines
    (index, nifty50, daily, bear_trade, ema_engine) independently of scanner loops.
    """
    if kite is None:
        return 0

    import trade_db
    from session import log_to_journal
    from registries import STOCK_REGISTRY, INDEX_REGISTRY

    # 1. Auto-reconcile zero-qty broker positions
    try:
        trade_db.reconcile_broker_live_positions(kite)
    except Exception as e:
        logging.debug(f"[STANDALONE_MONITOR] Reconcile error: {e}")

    # 2. Get active trades from DB
    try:
        active_trades = trade_db.get_active_trades()
    except Exception as e:
        logging.error(f"[STANDALONE_MONITOR] Error reading active trades: {e}")
        active_trades = []

    # 3. Group by engine/type
    index_positions = {}
    stock_options_positions = {}
    stock_cash_positions = {}

    for t in active_trades:
        sym = t.get("symbol") or t.get("contract")
        if not sym:
            continue
        eng = str(t.get("engine", "nifty50")).lower()
        pos_data = dict(t)
        if eng == "index" or ("NIFTY" in str(sym).upper() and ("CE" in str(sym).upper() or "PE" in str(sym).upper())) or ("SENSEX" in str(sym).upper() and ("CE" in str(sym).upper() or "PE" in str(sym).upper())):
            index_positions[sym] = pos_data
        elif pos_data.get("position_type") == "stock" or eng in ["daily", "bear_trade", "weekly", "weekly_bear"]:
            stock_cash_positions[sym] = pos_data
        else:
            stock_options_positions[sym] = pos_data

    # 4. Check for unlinked live broker positions on Kite
    try:
        pos_data = kite.positions()
        net_pos = [p for p in pos_data.get("net", []) if p.get("tradingsymbol") and int(p.get("quantity", 0)) != 0]
        for p in net_pos:
            tsym = p.get("tradingsymbol")
            if not tsym:
                continue
            # If not in any active group, auto-stage into monitor dict
            if tsym not in index_positions and tsym not in stock_options_positions and tsym not in stock_cash_positions:
                c_str = tsym.upper()
                is_opt = is_option_contract(c_str)
                is_index = is_opt and ("NIFTY" in c_str or "BANKNIFTY" in c_str or "SENSEX" in c_str or "FINNIFTY" in c_str or "MIDCPNIFTY" in c_str)
                p_qty = int(p.get("quantity", 0))
                is_short_eq = (not is_opt) and (p_qty < 0)
                eng_type = "index" if is_index else ("nifty50" if is_opt else ("daily_bear" if is_short_eq else "daily"))
                
                # Auto-lookup scan SL/targets from trade history or chart
                from resolve import lookup_scan_sl_target
                sl_info = lookup_scan_sl_target(tsym, tsym, eng_type, kite=kite, entry_price=float(p.get("average_price", 0)), side="BEAR" if is_short_eq else "BULL")
                
                broker_pos_dict = {
                    "contract": tsym,
                    "symbol": tsym,
                    "quantity": abs(p_qty),
                    "position_size": abs(p_qty),
                    "entry_spot": float(p.get("average_price", 0)),
                    "entry_price": float(p.get("average_price", 0)),
                    "current_sl": float(sl_info.get("current_sl") or 0.0) if sl_info else 0.0,
                    "t1": float(sl_info.get("t1") or 0.0) if sl_info else 0.0,
                    "t2": float(sl_info.get("t2") or 0.0) if sl_info else 0.0,
                    "t3": float(sl_info.get("t3") or 0.0) if sl_info else 0.0,
                    "trailing_stage": int(sl_info.get("trailing_stage") or 0) if sl_info else 0,
                    "pattern": sl_info.get("pattern", "BROKER_RECOVERED") if sl_info else "BROKER_RECOVERED",
                    "position_type": "option" if is_opt else "stock",
                    "side": "SELL" if is_short_eq else ("PE" if (is_opt and c_str.endswith("PE")) else ("CE" if is_opt else "BUY")),
                    "direction": "BEAR" if (is_short_eq or (is_opt and c_str.endswith("PE"))) else "BULL",
                    "product": p.get("product", "MIS" if is_short_eq else "CNC"),
                    "source": "kite"
                }
                if is_index and is_opt:
                    index_positions[tsym] = broker_pos_dict
                elif is_opt:
                    stock_options_positions[tsym] = broker_pos_dict
                else:
                    stock_cash_positions[tsym] = broker_pos_dict
    except Exception as e:
        logging.debug(f"[STANDALONE_MONITOR] Broker position fetch error: {e}")

    # 5. Monitor each group
    monitored_count = 0
    if index_positions:
        lock_idx = threading.Lock()
        monitor_active_positions(
            kite=kite,
            registry=INDEX_REGISTRY,
            positions_dict=index_positions,
            lock=lock_idx,
            product_type="NRML",
            engine_name="index",
            timeframe_entry="3minute",
            trade_db=trade_db,
            log_fn=log_to_journal,
            live=live
        )
        monitored_count += len(index_positions)

    if stock_options_positions:
        lock_opt = threading.Lock()
        monitor_active_positions(
            kite=kite,
            registry=STOCK_REGISTRY,
            positions_dict=stock_options_positions,
            lock=lock_opt,
            product_type="NRML",
            engine_name="nifty50",
            timeframe_entry="30minute",
            trade_db=trade_db,
            log_fn=log_to_journal,
            live=live
        )
        monitored_count += len(stock_options_positions)

    if stock_cash_positions:
        lock_cash = threading.Lock()
        monitor_active_positions(
            kite=kite,
            registry=STOCK_REGISTRY,
            positions_dict=stock_cash_positions,
            lock=lock_cash,
            product_type="CNC",
            engine_name="daily",
            timeframe_entry="day",
            trade_db=trade_db,
            log_fn=log_to_journal,
            live=live
        )
        monitored_count += len(stock_cash_positions)

    return monitored_count



