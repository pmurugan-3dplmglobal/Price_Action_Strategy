"""
Active position monitoring, SL/target evaluation, trailing stops,
and position close execution (both options and stock spot).
Extracted from trading_core.py (2026-08-11).
"""
import os
import sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import json
import logging
import time
import threading
from datetime import datetime as dt, timedelta, time as datetime_time
import pandas as pd
import paths
from targets import get_sl_buffer_distance
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

def is_contract_held_on_broker(kite, contract):
    """Safely check if contract is currently held on broker with non-zero quantity.
    
    Returns (is_held: bool, quantity: int).
    """
    if not kite or not contract:
        return False, 0
    try:
        norm = str(contract).replace(" ", "").upper()
        kp = kite.positions()
        for p in (kp.get("net", []) or []):
            tsym = str(p.get("tradingsymbol", "")).replace(" ", "").upper()
            if tsym == norm:
                qty = int(p.get("quantity", 0))
                if abs(qty) > 0:
                    return True, qty
    except Exception as e:
        logging.warning(f"[BROKER_CHECK] Failed to query broker positions for {contract}: {e}")
    return False, 0

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

    # ALWAYS-LIVE RISK GUARDIAN INVARIANT:
    # If a live Kite session is connected and real broker shares are held,
    # the exit MUST ALWAYS route live to the exchange!
    # Paper mode is strictly for scanner auto-entries, NEVER for abandoning risk management on real capital.
    if kite:
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
                        live_market = True  # Real short position held on broker: FORCE LIVE EXIT
                    elif live_held > 0:
                        is_short = False
                        live_market = True  # Real long position held on broker: FORCE LIVE EXIT
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
            if not qty_override:
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
                    if not qty_override:
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
                if not qty_override:
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

def is_new_entry_allowed(live_execution_active=True, is_option=False, is_index=False):
    """Check if new trade entries are allowed.
    If live_execution_active is False (offline/scan-only/after-market mode), returns True to allow scanning & research anytime.
    If live_execution_active is True, restricts new entries strictly to Mon-Fri:
    - Options opening 60 seconds (09:15:00 - 09:15:59 IST) restricted: 09:16:00 IST start.
    - Cash equities / normal: 09:15:00 IST start.
    - Index Options (is_index=True): Hard 13:30:00 IST cutoff! Eliminates late-day expiry chop & EOD square-off traps.
    - Other instruments: 15:20:00 IST cutoff.
    """
    if not live_execution_active:
        return True
    now = get_ist_now()
    if now.weekday() >= 5:
        return False
    t_now = now.time()
    start_time = datetime_time(9, 16) if is_option else datetime_time(9, 15)
    end_time = datetime_time(13, 30) if is_index else datetime_time(15, 20)
    return start_time <= t_now <= end_time

def get_exchange_freeze_limit(symbol_or_contract: str) -> int:
    """Returns the NSE/BSE exchange freeze limit for options and index contracts."""
    s = str(symbol_or_contract).upper()
    if "BANKNIFTY" in s:
        return 900
    elif "FINNIFTY" in s:
        return 1800
    elif "MIDCPNIFTY" in s:
        return 2800
    elif "NIFTY" in s:
        return 1755
    elif "SENSEX" in s or "BANKEX" in s:
        return 1000
    return 1755

def slice_quantity_for_freeze(symbol_or_contract: str, total_qty: int) -> list:
    """Slices order quantity into chunks <= exchange freeze limit to prevent RMS rejections."""
    limit = get_exchange_freeze_limit(symbol_or_contract)
    if total_qty <= limit or limit <= 0:
        return [total_qty]
    slices = []
    rem = total_qty
    while rem > 0:
        chunk = min(rem, limit)
        slices.append(chunk)
        rem -= chunk
    return slices

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
    # ALWAYS-LIVE RISK GUARDIAN INVARIANT:
    # If a live Kite session is connected and real broker contracts are held (live_held > 0),
    # the exit MUST ALWAYS route live to the exchange!
    # Paper mode is strictly for scanner auto-entries, NEVER for abandoning risk management on real capital.
    if kite:
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
                    live_market = True  # Real broker contracts detected: auto-promote to LIVE exit
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

    qty_slices = slice_quantity_for_freeze(contract, qty)
    try:
        placed_oids = []
        for s_qty in qty_slices:
            s_oid = kite.place_order(
                variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                quantity=s_qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=price, product=target_product
            )
            placed_oids.append(str(s_oid))
        oid = placed_oids[0]
        if not qty_override:
            save_executed_exit(contract, oid, {"type": "LIMIT", "price": price, "qty": qty, "order_ids": placed_oids})
        logging.info(f"Closed {contract} with Marketable LIMIT order price {price} on exchange {target_exch} (Orders: {placed_oids}, Total Qty: {qty})")

        # Helper to ensure short leg is covered on any successful primary exit
        def _cover_spread_leg2():
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
                        leg2_slices = slice_quantity_for_freeze(leg2_c, leg2_qty)
                        leg2_oids = []
                        for l2_s_qty in leg2_slices:
                            oid_leg2 = kite.place_order(
                                variety=kite.VARIETY_REGULAR, tradingsymbol=leg2_c,
                                exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_BUY,
                                quantity=l2_s_qty, order_type=kite.ORDER_TYPE_MARKET,
                                product=target_product
                            )
                            leg2_oids.append(str(oid_leg2))
                        save_executed_exit(leg2_c, leg2_oids[0], {"type": "SPREAD_LEG2_EXIT", "qty": leg2_qty, "order_ids": leg2_oids})
                        logging.info(f"[SPREAD EXIT] Covered short leg {leg2_c} (Orders: {leg2_oids}, Qty: {leg2_qty})")
                    except Exception as leg2_err:
                        logging.error(f"[SPREAD EXIT ERROR] Failed to exit short leg {leg2_c}: {leg2_err}")

        _cover_spread_leg2()
        return {"success": True, "order_id": str(oid), "type": "LIMIT", "price": price, "qty": qty, "order_ids": placed_oids}
    except Exception as primary_err:
        logging.warning(f"Primary LIMIT exit with {target_product} on {target_exch} failed for {contract}: {primary_err}. Retrying with aggressive limit fallback...")
        try:
            fallback_price = max(0.05, round(round((ref_price * 0.98) / 0.05) * 0.05, 2))
            placed_fallback_oids = []
            for s_qty in qty_slices:
                s_oid = kite.place_order(
                    variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                    exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=s_qty, order_type=kite.ORDER_TYPE_LIMIT,
                    price=fallback_price, product=target_product
                )
                placed_fallback_oids.append(str(s_oid))
            oid = placed_fallback_oids[0]
            if not qty_override:
                save_executed_exit(contract, oid, {"type": "LIMIT_FALLBACK", "price": fallback_price, "qty": qty, "order_ids": placed_fallback_oids})
            logging.info(f"Fallback Marketable LIMIT exit SUCCESS for {contract} on exchange {target_exch} at price {fallback_price} (Orders: {placed_fallback_oids})")
            if 'pos' in locals() and pos.get("position_type") == "option_spread":
                try:
                    _cover_spread_leg2()
                except Exception as cov_err:
                    logging.error(f"Fallback spread leg2 cover error: {cov_err}")
            return {"success": True, "order_id": str(oid), "type": "LIMIT_FALLBACK", "price": fallback_price, "qty": qty, "order_ids": placed_fallback_oids}
        except Exception as m_err:
            try:
                placed_m_oids = []
                for s_qty in qty_slices:
                    s_oid = kite.place_order(
                        variety=kite.VARIETY_REGULAR, tradingsymbol=contract,
                        exchange=target_exch, transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=s_qty, order_type=kite.ORDER_TYPE_MARKET,
                        product=target_product
                    )
                    placed_m_oids.append(str(s_oid))
                oid = placed_m_oids[0]
                if not qty_override:
                    save_executed_exit(contract, oid, {"type": "MARKET_EMERGENCY", "qty": qty, "order_ids": placed_m_oids})
                logging.info(f"Emergency MARKET exit SUCCESS for {contract} on exchange {target_exch} (Orders: {placed_m_oids})")
                if 'pos' in locals() and pos.get("position_type") == "option_spread":
                    try:
                        _cover_spread_leg2()
                    except Exception as cov_err:
                        logging.error(f"Emergency spread leg2 cover error: {cov_err}")
                return {"success": True, "order_id": str(oid), "type": "MARKET_EMERGENCY", "qty": qty, "order_ids": placed_m_oids}
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

def get_seconds_since_entry(pos):
    """Return seconds elapsed since trade entry, or a large number if unavailable."""
    try:
        et = sanitize_entry_time(pos)
        if not et:
            return 999999.0
        et_dt = pd.to_datetime(et)
        if hasattr(et_dt, 'tz') and et_dt.tz is not None:
            et_dt = et_dt.tz_convert('Asia/Kolkata').tz_localize(None)
        now_dt = get_ist_now(naive=True)
        return max(0.0, float((now_dt - et_dt).total_seconds()))
    except Exception:
        return 999999.0


def reconcile_and_cancel_stale_orders(kite, positions_dict=None, position_lock=None, engine_name="all", live=True):
    """
    Evaluates all OPEN and TRIGGER PENDING entry orders on Kite.
    Cancels orders if:
    1. TARGET REACHED: Live LTP >= T1 * (1 - buffer) or High >= T1 before fill (prevents buying falling knife).
    2. TIME-TO-LIVE (TTL) EXPIRED: Order unfilled for > unfilled_order_ttl_minutes (default: 30m).
    3. STOP LOSS BREACHED: Contract LTP <= SL (or High >= SL for short stock) before fill.
    4. EOD CUTOFF: Current time >= eod_cutoff_time (default: 15:15 IST).

    Also synchronizes filled orders:
    - If order became COMPLETE on Kite: marks order_status = 'FILLED' and updates entry_spot.
    - If cancelled: removes from positions_dict, marks trade_db status = 'CANCELLED', releases pattern locks.
    """
    if kite is None:
        return {"cancelled": 0, "evaluated": 0}

    cfg = _load_program_config_file()
    cfg_om = cfg.get("order_management", {}) if isinstance(cfg, dict) else {}
    if not cfg_om.get("enable_stale_order_cancellation", True):
        return {"cancelled": 0, "evaluated": 0}

    ttl_minutes = float(cfg_om.get("unfilled_order_ttl_minutes", 30))
    buffer_pct = float(cfg_om.get("target_reached_buffer_pct", 0.02))
    cancel_target = bool(cfg_om.get("cancel_on_target_reached", True))
    cancel_sl = bool(cfg_om.get("cancel_on_sl_breach", True))
    cancel_ttl = bool(cfg_om.get("cancel_on_ttl_expired", True))
    eod_time_str = str(cfg_om.get("eod_cutoff_time", "15:15"))

    try:
        orders = kite.orders()
        if not orders:
            return {"cancelled": 0, "evaluated": 0}
    except Exception as e:
        logging.debug(f"[ORDER_MANAGER] Failed to fetch Kite orders: {e}")
        return {"cancelled": 0, "evaluated": 0}

    try:
        kp = kite.positions()
        net_pos_dict = {p.get("tradingsymbol"): p for p in kp.get("net", []) if p.get("tradingsymbol")}
    except Exception as e:
        logging.debug(f"[ORDER_MANAGER] Failed to fetch Kite positions: {e}")
        net_pos_dict = {}

    # Synchronize orders that filled on Kite: update order_status from 'OPEN' to 'FILLED'
    completed_orders_by_id = {str(o.get("order_id")): o for o in orders if o.get("status") == "COMPLETE"}
    completed_orders_by_sym = {o.get("tradingsymbol"): o for o in orders if o.get("status") == "COMPLETE"}

    if positions_dict:
        items_to_check = []
        if position_lock:
            with position_lock:
                items_to_check = list(positions_dict.items())
        else:
            items_to_check = list(positions_dict.items())

        for sym, pos in items_to_check:
            if pos.get("order_status") == "OPEN":
                oid = str(pos.get("order_id", ""))
                c = pos.get("contract") or sym
                matched_o = completed_orders_by_id.get(oid) or completed_orders_by_sym.get(c)
                if matched_o:
                    avg_p = float(matched_o.get("average_price") or 0.0)
                    logging.info(f"[ORDER_MANAGER] Order #{oid} for {sym} ({c}) filled on Kite @ {avg_p:.2f}. Mutating status to FILLED.")
                    if position_lock:
                        with position_lock:
                            if sym in positions_dict:
                                positions_dict[sym]["order_status"] = "FILLED"
                                if avg_p > 0:
                                    positions_dict[sym]["entry_spot"] = avg_p
                    else:
                        pos["order_status"] = "FILLED"
                        if avg_p > 0:
                            pos["entry_spot"] = avg_p

    open_orders = [o for o in orders if o.get("status") in ["OPEN", "TRIGGER PENDING"]]
    if not open_orders:
        return {"cancelled": 0, "evaluated": 0}

    # Batch quote for all open order symbols
    quote_keys = []
    for o in open_orders:
        tsym = o.get("tradingsymbol")
        if not tsym:
            continue
        exch = o.get("exchange")
        if not exch:
            is_opt = is_option_contract(tsym)
            exch = "BFO" if ("SENSEX" in tsym.upper() or "BANKEX" in tsym.upper()) else ("NFO" if is_opt else "NSE")
        quote_keys.append(f"{exch}:{tsym}")

    quotes = {}
    if quote_keys:
        try:
            quotes = kite.quote(quote_keys)
        except Exception as e:
            logging.debug(f"[ORDER_MANAGER] Batch quote failed: {e}")

    import trade_db
    from session import log_to_journal
    try:
        active_trades = trade_db.get_active_trades()
    except Exception:
        active_trades = []

    trades_by_oid = {str(t.get("order_id")): t for t in active_trades if t.get("order_id")}
    trades_by_contract = {t.get("contract"): t for t in active_trades if t.get("contract")}
    trades_by_sym = {t.get("symbol"): t for t in active_trades if t.get("symbol")}

    now_ist = get_ist_now(naive=True)
    cancelled_count = 0

    for o in open_orders:
        tsym = o.get("tradingsymbol")
        if not tsym:
            continue
        oid = str(o.get("order_id"))
        var = o.get("variety") or getattr(kite, "VARIETY_REGULAR", "regular")
        exch = o.get("exchange", "NFO")
        ttype = str(o.get("transaction_type", "")).upper()
        order_price = float(o.get("price") or 0.0)
        filled_qty = int(o.get("filled_quantity", 0))
        is_opt = is_option_contract(tsym)
        held_qty = int(net_pos_dict.get(tsym, {}).get("quantity", 0))

        # Disregard position exit orders (only evaluate entry orders)
        if is_opt:
            if ttype != "BUY":
                continue
        else:
            if held_qty > 0 and ttype == "SELL":
                continue
            if held_qty < 0 and ttype == "BUY":
                continue

        # Calculate Order Age in minutes
        order_ts = o.get("order_timestamp")
        age_min = 0.0
        if order_ts:
            if isinstance(order_ts, str):
                ts_clean = order_ts.replace("T", " ").split(".")[0].split("+")[0]
                try:
                    o_dt = dt.strptime(ts_clean, "%Y-%m-%d %H:%M:%S")
                    age_min = max(0.0, (now_ist - o_dt).total_seconds() / 60.0)
                except Exception:
                    pass
            elif isinstance(order_ts, dt):
                age_min = max(0.0, (now_ist - order_ts.replace(tzinfo=None)).total_seconds() / 60.0)

        # Retrieve setup parameters (T1, SL, direction)
        t_match = trades_by_oid.get(oid) or trades_by_contract.get(tsym) or trades_by_sym.get(tsym)
        p_match = None
        matched_pos_key = None
        if positions_dict:
            if tsym in positions_dict:
                p_match = positions_dict[tsym]
                matched_pos_key = tsym
            else:
                for pk, pv in positions_dict.items():
                    if isinstance(pv, dict) and (pv.get("contract") == tsym or str(pv.get("order_id", "")) == oid):
                        p_match = pv
                        matched_pos_key = pk
                        break
            if not p_match and t_match and t_match.get("symbol") in positions_dict:
                p_match = positions_dict[t_match.get("symbol")]
                matched_pos_key = t_match.get("symbol")

        info = p_match or t_match or {}
        t1 = float(info.get("t1") or 0.0) if info.get("t1") not in [None, "N/A", ""] else 0.0
        sl = float(info.get("current_sl") or info.get("sl") or 0.0) if info.get("current_sl") not in [None, "N/A", ""] else 0.0
        sym = info.get("symbol") or matched_pos_key or tsym
        pat = info.get("pattern") or "ABCD"
        side = info.get("side") or ("PE" if "PE" in tsym.upper() else ("CE" if "CE" in tsym.upper() else "BULL"))
        direction = str(info.get("direction") or "BULL").upper()
        trade_id = info.get("id") or info.get("trade_id")
        engine_key = info.get("engine") or ("index" if ("NIFTY" in tsym.upper() or "SENSEX" in tsym.upper()) else "nifty50")

        # Fallback to lookup_scan_sl_target if T1 or SL not in memory/DB
        if (t1 <= 0 or sl <= 0) and kite:
            try:
                from resolve import lookup_scan_sl_target
                is_stk = not is_opt
                sl_lookup = lookup_scan_sl_target(contract=tsym, symbol=sym, engine=engine_key, kite=kite,
                                                  entry_price=order_price, is_stock=is_stk, side=direction)
                if sl_lookup:
                    if t1 <= 0:
                        t1 = float(sl_lookup.get("t1") or 0.0)
                    if sl <= 0:
                        sl = float(sl_lookup.get("current_sl") or sl_lookup.get("sl") or 0.0)
                    if not sym:
                        sym = sl_lookup.get("symbol") or tsym
            except Exception:
                pass

        # Quote metrics
        q_key = f"{exch}:{tsym}"
        q_data = quotes.get(q_key, {})
        ltp = float(q_data.get("last_price") or 0.0)
        ohlc = q_data.get("ohlc", {})
        day_high = float(ohlc.get("high") or ltp)
        day_low = float(ohlc.get("low") or ltp)

        cancel_reason = None
        reason_code = None
        is_short_stock = (not is_opt) and (direction == "BEAR" or ttype == "SELL")

        # Invalidation Condition 1: Target T1 Touched Before Fill
        # Invariant: Must evaluate live LTP only. Session day_high/day_low from hours before order creation
        # must NEVER falsely cancel a freshly placed limit order.
        if cancel_target and t1 > 0:
            if is_short_stock:
                target_thresh = round(t1 * (1.0 + buffer_pct), 2)
                if ltp > 0 and ltp <= target_thresh:
                    cancel_reason = f"Target T1 ({t1:.2f}) touched before fill (LTP {ltp:.2f} <= {target_thresh:.2f})"
                    reason_code = "CANCELLED_TARGET_REACHED"
            else:
                target_thresh = round(t1 * (1.0 - buffer_pct), 2)
                if ltp > 0 and ltp >= target_thresh:
                    cancel_reason = f"Target T1 ({t1:.2f}) touched before fill (LTP {ltp:.2f} >= {target_thresh:.2f})"
                    reason_code = "CANCELLED_TARGET_REACHED"

        # Invalidation Condition 2: Stop Loss Breached Before Fill
        # Invariant: Must evaluate live LTP only. Pre-entry session day_low/day_high must not falsely cancel order.
        if not cancel_reason and cancel_sl and sl > 0:
            if is_short_stock:
                if ltp > 0 and ltp >= sl:
                    cancel_reason = f"SL breached before fill (LTP {ltp:.2f} >= SL {sl:.2f})"
                    reason_code = "CANCELLED_SL_BREACHED"
            else:
                if ltp > 0 and ltp <= sl:
                    cancel_reason = f"SL breached before fill (LTP {ltp:.2f} <= SL {sl:.2f})"
                    reason_code = "CANCELLED_SL_BREACHED"

        # Invalidation Condition 3: Time-To-Live (TTL) Expired
        if not cancel_reason and cancel_ttl and age_min >= ttl_minutes:
            cancel_reason = f"TTL Expired: Unfilled for {age_min:.1f}m (Limit: {ttl_minutes:.0f}m)"
            reason_code = "CANCELLED_TTL_EXPIRED"

        # Invalidation Condition 4: EOD Cutoff
        if not cancel_reason:
            now_hm = now_ist.strftime("%H:%M")
            if now_hm >= eod_time_str:
                cancel_reason = f"EOD Cutoff reached ({now_hm} >= {eod_time_str})"
                reason_code = "CANCELLED_EOD_CUTOFF"

        if cancel_reason:
            logging.warning(f"[UNFILLED_ORDER_MANAGER] Cancelling {tsym} Order #{oid}: {cancel_reason}")
            if live:
                try:
                    kite.cancel_order(variety=var, order_id=oid)
                except Exception as cancel_err:
                    logging.error(f"[UNFILLED_ORDER_MANAGER] kite.cancel_order failed for #{oid}: {cancel_err}")

            if positions_dict is not None:
                def _cleanup_pos():
                    keys_to_clean = [k for k in [tsym, sym, matched_pos_key] if k and k in positions_dict]
                    for k in keys_to_clean:
                        if filled_qty == 0:
                            positions_dict.pop(k, None)
                        else:
                            positions_dict[k]["order_status"] = "COMPLETE"
                if position_lock:
                    with position_lock:
                        _cleanup_pos()
                else:
                    _cleanup_pos()

            if filled_qty == 0:
                if trade_id:
                    trade_db.update_trade_status(
                        trade_id, "CANCELLED",
                        exit_price=ltp if ltp > 0 else order_price,
                        exit_reason=reason_code,
                        details=f"Unfilled order #{oid} cancelled: {cancel_reason}"
                    )
                trade_db.mark_order_cancelled_by_contract_or_oid(tsym, oid, reason_code, cancel_reason)
                pat_key = f"{sym}|{pat}|{side}|{info.get('strike','')}"
                trade_db.clear_executed_pattern(engine_key, pat_key)
            else:
                if trade_id:
                    trade_db.update_trade(trade_id, {
                        "position_size": filled_qty,
                        "order_status": "COMPLETE"
                    })

            try:
                log_to_journal(
                    sym, pat, info.get("timeframe", "15minute"),
                    "CANCEL_UNFILLED", "CANCELLED",
                    f"Order #{oid} cancelled: {cancel_reason}",
                    entry=order_price, sl=sl, target=t1,
                    event_time=now_ist.strftime("%Y-%m-%d %H:%M:%S")
                )
            except Exception:
                pass

            cancelled_count += 1

    return {"cancelled": cancelled_count, "evaluated": len(open_orders)}


def monitor_active_positions(kite, registry, positions_dict, lock, product_type, engine_name,
                              timeframe_entry, trade_db, log_fn, save_state_fn=None,
                              live=True):
    from_date = (get_ist_now(naive=True) - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = get_ist_now(naive=True).strftime("%Y-%m-%d")
    to_clear = []

    # 0. Reconcile and cancel any stale / unfilled entry orders on Kite
    if kite and live:
        try:
            reconcile_and_cancel_stale_orders(kite, positions_dict=positions_dict, position_lock=lock,
                                              engine_name=engine_name, live=live)
        except Exception as o_mgr_err:
            logging.debug(f"[ORDER_MANAGER] Stale order evaluation error: {o_mgr_err}")

    # Load sl_mode from program config if available ("hybrid", "candle_close", or "tick_ltp")
    cfg = _load_program_config_file()
    sl_mode = cfg.get("sl_mode", "hybrid")
    emergency_buffer_pct = float(cfg.get("emergency_buffer_pct", 0.15))
    failsafe_start_str = cfg.get("failsafe_start_time", "09:50")
    pause_morning_circuit = cfg.get("pause_morning_circuit_breaker", True)
    pause_sl_monitor = bool(cfg.get("pause_sl_monitor", False))
    try:
        f_h, f_m = map(int, failsafe_start_str.split(":"))
        fs_start_t = datetime_time(f_h, f_m)
        fs_end_m = (f_m + 2) % 60
        fs_end_h = f_h + ((f_m + 2) // 60)
        fs_end_str = f"{fs_end_h:02d}:{fs_end_m:02d}"
    except Exception:
        fs_start_t = datetime_time(9, 50)
        fs_end_str = "09:52"

    # Target monitoring runs from 09:15 AM market open; SL checks are gated inside by is_before_failsafe / failsafe_start_time.

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
            # If position is still an unfilled entry limit order waiting on Kite,
            # do NOT execute trailing SL or profit exits on 0 held quantity.
            if pos.get("order_status") == "OPEN":
                continue
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

            now_time_str = get_ist_now().strftime("%H:%M")
            is_before_failsafe = now_time_str < failsafe_start_str
            secs_since_entry = get_seconds_since_entry(pos)
            is_fresh_fill = secs_since_entry < 120.0

            if df.empty:
                # If trade is fresh (< 120s) or morning circuit is paused before failsafe time,
                # do NOT execute emergency tick exit on empty candle data (allows candles and opening spreads to settle).
                if is_fresh_fill or (is_before_failsafe and pause_morning_circuit):
                    logging.info(f"[CANDLE_OUTAGE_SHIELD_SUPPRESSED] Suppressed empty-candle SL for {sym}: Fresh fill ({secs_since_entry:.0f}s old) or morning circuit paused.")
                    continue

                # CVE-4 FIX: Decouple emergency tick protection from candle REST API outages
                entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
                current_sl = float(pos.get("current_sl", 0))
                if live_ltp > 0 and entry_s > 0:
                    max_loss_pct = float(cfg.get("max_option_loss_pct", 35.0)) / 100.0 if not is_stock else 0.08
                    if is_short_stock:
                        hard_max_sl = round(entry_s * (1.0 + max_loss_pct), 2)
                        is_breached = (live_ltp >= hard_max_sl) or (current_sl > 0 and live_ltp >= current_sl * 1.05)
                    else:
                        hard_max_sl = round(entry_s * (1.0 - max_loss_pct), 2)
                        is_breached = (live_ltp <= hard_max_sl) or (current_sl > 0 and live_ltp <= current_sl * 0.95)
                    if is_breached:
                        if pause_sl_monitor:
                            logging.info(f"[SL_PAUSE_ACTIVE] Outage emergency breach for {sym} (LTP {live_ltp:.2f}) but SL Exit Monitor is PAUSED. Skipping emergency exit.")
                            continue
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

            # 1) SL Evaluation (Separated SL Monitor: Skipped until failsafe_start_str, Active at failsafe_start_str+)
            now_time_str = get_ist_now().strftime("%H:%M")
            is_before_failsafe = now_time_str < failsafe_start_str
            is_start_failsafe = failsafe_start_str <= now_time_str <= fs_end_str

            # ── INTRADAY THETA STAGNATION GUARD (12:30 IST RULE) ──
            # For intraday options (3m, 5m, 15m), holding stagnant trades through mid-day (12:30 - 14:30)
            # bleeds premium to severe theta decay even if spot is flat.
            # If position held > 60m, time is >= 12:30 IST, and PnL is stagnant (-7.0% <= curr_pnl_pct <= 8.0%),
            # tighten SL to Entry - 10% floor to prevent afternoon decay plunge.
            theta_stagnation_enabled = cfg.get("enable_theta_stagnation_guard", True) if isinstance(cfg, dict) else True
            if theta_stagnation_enabled and not is_stock and is_short_tf and now_time_str >= "12:30" and now_time_str < "14:30":
                if pos.get("trailing_stage", 0) == 0 and not pos.get("theta_stagnation_tightened"):
                    entry_time_str = str(pos.get("entry_time") or "")
                    held_mins = 0
                    if entry_time_str:
                        try:
                            et_c = entry_time_str.split("+")[0].replace("T", " ")
                            held_mins = (get_ist_now() - dt.fromisoformat(et_c)).total_seconds() / 60.0
                        except Exception:
                            pass
                    if held_mins >= 60.0:
                        entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
                        curr_p = live_ltp if live_ltp > 0 else (cp if cp > 0 else entry_s)
                        curr_pnl = ((curr_p - entry_s) / entry_s * 100) if entry_s > 0 else 0.0
                        if -7.0 <= curr_pnl <= 8.0:
                            tight_sl = round(round((entry_s * 0.90) / 0.05) * 0.05, 2)
                            curr_sl = float(pos.get("current_sl") or 0.0)
                            if tight_sl > curr_sl:
                                with lock:
                                    if sym in positions_dict:
                                        positions_dict[sym]["current_sl"] = tight_sl
                                        positions_dict[sym]["theta_stagnation_tightened"] = True
                                logging.info(f"[THETA_STAGNATION_GUARD] {sym} held for {held_mins:.0f}m at {now_time_str} IST with flat PnL ({curr_pnl:.1f}%). Tightened SL from {curr_sl:.2f} -> {tight_sl:.2f} (-10% cap) to protect against afternoon decay.")
                                if tid:
                                    trade_db.update_trade(tid, {"current_sl": tight_sl, "theta_stagnation_tightened": True})

            # ── STALE / OUTLIER ENTRY PRICE GUARD ──
            # Prevent false emergency SL triggers when entry_spot or current_sl has an extreme data mismatch vs live LTP
            # (e.g. BSE entry 12.0 with SL 1.0 when live option market is trading at 0.60, or stale DB entry 110 vs live 28).
            is_outlier_entry = False
            entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
            if entry_s > 0 and live_ltp > 0:
                if (entry_s / live_ltp > 2.5 or live_ltp / entry_s > 2.5):
                    is_outlier_entry = True
                    logging.warning(f"[STALE OUTLIER GUARD] {sym} entry {entry_s:.2f} diverges >250% from live LTP {live_ltp:.2f}. Skipping false emergency SL trigger.")
            if current_sl > 0 and live_ltp > 0:
                if current_sl / live_ltp > 2.5 or live_ltp / current_sl > 2.5:
                    is_outlier_entry = True
                    logging.warning(f"[STALE OUTLIER GUARD] {sym} SL {current_sl:.2f} diverges >250% from live LTP {live_ltp:.2f}. Skipping false emergency SL trigger.")

            if current_sl > 0:
                sl_floor = get_sl_floor_time(pos)
                if is_before_failsafe:
                    # Timeframe Closing Basis Invariant:
                    # Target monitoring runs from 09:15 AM; all automated SL checks and emergency circuit breakers
                    # are paused until failsafe_start_str AM (default 09:50 AM) to allow the opening 30-min candle
                    # to close and settle on closing-basis without opening spread/tick noise whipsaws.
                    if not pause_morning_circuit:
                        # True Catastrophic Disaster Shield (only if explicitly unpaused, threshold >= 40%):
                        if is_fresh_fill:
                            logging.info(f"[FRESH_FILL_SPREAD_GUARD] Suppressed morning circuit breaker for {sym}: Trade entered {secs_since_entry:.0f}s ago (<120s cooldown).")
                        elif entry_s > 0 and live_ltp > 0 and not is_outlier_entry:
                            opt_loss_cap = float(cfg.get("max_option_loss_pct", 40.0)) / 100.0 if not is_stock else 0.15
                            if is_short_stock and live_ltp >= (entry_s * 1.15):
                                sl_hit = True
                                rise_pct = (live_ltp - entry_s) / entry_s * 100.0
                                sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_15PCT (Short Stock LTP {live_ltp:.2f} up {rise_pct:.1f}% from entry {entry_s:.2f})"
                                cp = live_ltp
                                event_time = last.get('date')
                            elif not is_short_stock and not is_stock and live_ltp <= (entry_s * (1.0 - opt_loss_cap)):
                                sl_hit = True
                                drop_pct = (entry_s - live_ltp) / entry_s * 100.0
                                sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_{int(opt_loss_cap*100)}PCT (Option LTP {live_ltp:.2f} down {drop_pct:.1f}% from entry {entry_s:.2f})"
                                cp = live_ltp
                                event_time = last.get('date')
                            elif not is_short_stock and is_stock and live_ltp <= (entry_s * 0.85):
                                sl_hit = True
                                drop_pct = (entry_s - live_ltp) / entry_s * 100.0
                                sl_reason = f"MORNING_CATASTROPHIC_CIRCUIT_15PCT (Stock LTP {live_ltp:.2f} down {drop_pct:.1f}% from entry {entry_s:.2f})"
                                cp = live_ltp
                                event_time = last.get('date')
                elif is_start_failsafe and not is_outlier_entry:
                    # Failsafe Check at failsafe_start_time (09:50 AM):
                    # Trigger ONLY IF previous candle closed in breach AND current live price is in breach.
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
                        sl_reason = f"SL_FAILSAFE_MORNING_TRIGGER (LTP {live_ltp:.2f} {' >=' if is_short_stock else ' <='} {current_sl:.2f} & Prev Bar Closed Breach)"
                        cp = live_ltp if live_ltp > 0 else float(df.iloc[-1]['close'])
                        event_time = last.get('date')
                elif not is_outlier_entry:
                    # Normal Active SL Monitoring after failsafe_start_time
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

            # 2) Emergency Hard Stop / Direct LTP evaluation (Active after failsafe_start_time)
            if not sl_hit and current_sl > 0 and live_ltp > 0 and not is_before_failsafe and not is_outlier_entry:
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
            # SUBORDINATE INVARIANT: The structural Anchor SL, UI Override SL, or Trailed SL (current_sl) ALWAYS takes higher precedence.
            # A fixed 15% mathematical loss threshold must NEVER preempt a valid wider Anchor SL or a custom UI/Trailed SL.
            # It acts solely as a last-resort safety net when no valid current_sl exists (current_sl <= 0) or when current_sl is also in breach.
            max_loss_pct = float(cfg.get("max_option_loss_pct", 15)) / 100.0 if not is_stock else 0.08
            if is_short_stock:
                hard_max_sl_threshold = round(entry_s * (1.0 + max_loss_pct), 2) if entry_s > 0 else 0.0
                has_active_sl = current_sl > 0 and current_sl > entry_s
                # If an active Anchor/UI/Trailed SL exists, do NOT trigger HARD_MAX unless price is also >= current_sl
                is_sl_eligible = (not has_active_sl) or (live_ltp >= current_sl)
                if not sl_hit and hard_max_sl_threshold > 0 and live_ltp > 0 and live_ltp >= hard_max_sl_threshold and is_sl_eligible and not is_before_failsafe and not is_outlier_entry:
                    sl_hit = True
                    sl_reason = f"HARD_MAX_{int(max_loss_pct*100)}PCT_SL (LTP {live_ltp:.2f} >= {hard_max_sl_threshold:.2f})"
                    cp = live_ltp
            else:
                hard_max_sl_threshold = round(entry_s * (1.0 - max_loss_pct), 2) if entry_s > 0 else 0.0
                has_active_sl = current_sl > 0 and current_sl < entry_s
                # If an active Anchor/UI/Trailed SL exists, do NOT trigger HARD_MAX unless price is also <= current_sl
                is_sl_eligible = (not has_active_sl) or (live_ltp <= current_sl)
                if not sl_hit and hard_max_sl_threshold > 0 and live_ltp > 0 and live_ltp <= hard_max_sl_threshold and is_sl_eligible and not is_before_failsafe and not is_outlier_entry:
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

            if sl_hit and not is_stock and enable_spot_guard and not is_trailed_stop and kite:
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
                        if live_spot > 0:
                            pos["last_known_spot"] = live_spot
                        else:
                            live_spot = float(pos.get("last_known_spot") or pos.get("spot_entry") or 0.0)

                        side_str = str(pos.get("side", "CE")).upper()
                        is_bull = side_str in ["CE", "BUY", "BULL"]
                        # Catastrophic option emergency cap: If option drops beyond opt_emergency_cap (35%), exit regardless of spot
                        # BUT do NOT trigger catastrophic override if trade is a fresh fill (<120s) to allow opening spread to settle
                        opt_emergency_cap = float(cfg.get("max_option_loss_pct", 35.0)) / 100.0
                        is_catastrophic_opt = (entry_s > 0 and live_ltp > 0 and live_ltp <= (entry_s * (1.0 - opt_emergency_cap)) and not is_fresh_fill and not is_outlier_entry)

                        if is_bull and live_spot > spot_sl and not is_catastrophic_opt:
                            logging.info(f"[SPOT_SL_GUARD] Suppressed premature option SL exit for {sym} ({pos.get('contract')}): Option LTP {live_ltp:.2f} tripped SL, but Underlying Spot ({live_spot:.2f}) is strictly holding above support ({spot_sl:.2f}).")
                            sl_hit = False
                        elif (not is_bull) and live_spot < spot_sl and not is_catastrophic_opt:
                            logging.info(f"[SPOT_SL_GUARD] Suppressed premature PE option SL exit for {sym} ({pos.get('contract')}): Underlying Spot ({live_spot:.2f}) is strictly below ceiling ({spot_sl:.2f}).")
                            sl_hit = False
                    except Exception as s_err:
                        logging.warning(f"Spot SL guard check error for {sym}: {s_err}")
                        # API Resiliency (Rate-Limit / 429 Shield): Fall back to last_known_spot or spot_entry
                        cached_spot = float(pos.get("last_known_spot") or pos.get("spot_entry") or 0.0)
                        side_str = str(pos.get("side", "CE")).upper()
                        is_bull = side_str in ["CE", "BUY", "BULL"]
                        opt_emergency_cap = float(cfg.get("max_option_loss_pct", 35.0)) / 100.0
                        is_catastrophic_opt = (entry_s > 0 and live_ltp > 0 and live_ltp <= (entry_s * (1.0 - opt_emergency_cap)) and not is_fresh_fill and not is_outlier_entry)
                        if cached_spot > 0 and not is_catastrophic_opt:
                            if is_bull and cached_spot > spot_sl:
                                logging.info(f"[SPOT_SL_GUARD FAILSAFE] API query error ({s_err}) for {sym}; last known spot ({cached_spot:.2f}) is holding above support ({spot_sl:.2f}). Suppressing premature option SL exit.")
                                sl_hit = False
                            elif (not is_bull) and cached_spot < spot_sl:
                                logging.info(f"[SPOT_SL_GUARD FAILSAFE] API query error ({s_err}) for {sym}; last known spot ({cached_spot:.2f}) is holding below ceiling ({spot_sl:.2f}). Suppressing premature PE option SL exit.")
                                sl_hit = False

            if sl_hit:
                if pause_sl_monitor:
                    logging.info(f"[SL_PAUSE_ACTIVE] SL triggered [{sl_reason}] for {sym} at {cp} (TF: {pos_tf}) but SL Exit Monitor is PAUSED. Skipping SL exit. Targets remain active.")
                    sl_hit = False
                else:
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

            # Compute position ATR for adaptive buffer / breakeven calculations
            atr = float(pos.get("atr", 0.0) or 0.0)
            if atr <= 0:
                if df is not None and not df.empty and len(df) >= 3:
                    high_low_diff = (df['high'] - df['low']).abs()
                    atr = float(high_low_diff.tail(14).mean()) if len(df) >= 14 else float(high_low_diff.mean())
                else:
                    atr = entry_s * 0.02
            if pd.isna(atr) or atr <= 0:
                atr = entry_s * 0.02

            # Feature 5: Trailing Stage 1 (Gain Lock)
            # - Options: Trigger when peak gain >= +18% (Minervini rule) -> Trail SL to +10% above Entry (prevents normal option noise from slipping good trades)
            # - Stocks: Trigger when peak gain >= +10% -> Trail SL to +BE (Entry + buffer for Bull, Entry - buffer for Bear)
            trail_rules = cfg.get("trailing_rules", {}) if isinstance(cfg.get("trailing_rules"), dict) else {}
            opt_gain_trigger = float(trail_rules.get("option_trail_1_gain_pct", cfg.get("option_trail_1_gain_pct", 18.0)))
            opt_sl_lock_pct = float(trail_rules.get("option_trail_1_sl_pct", cfg.get("option_trail_1_sl_pct", 10.0)))
            stock_gain_trigger = float(trail_rules.get("stock_trail_1_gain_pct", cfg.get("stock_trail_1_gain_pct", 10.0)))

            req_gain = stock_gain_trigger if is_stock else opt_gain_trigger

            if pos.get("trailing_stage", 0) == 0 and gain_pct >= req_gain and has_higher_targets:
                curr_sl = float(pos.get("current_sl") or 0.0)
                if not is_stock:
                    # Option contract (CE or PE long buyer): lock in +10% gain above entry
                    sl_offset = entry_s * (opt_sl_lock_pct / 100.0)
                    opt_target = round(round((entry_s + sl_offset) / 0.05) * 0.05, 2)
                    new_sl = max(curr_sl, opt_target)
                    trail_label = f"TRAIL-1 (+{opt_gain_trigger:.0f}% Gain Lock -> +{opt_sl_lock_pct:.0f}% SL)"
                    log_sl_label = f"SL=+{opt_sl_lock_pct:.0f}% {new_sl:.2f} (+{gain_pct:.1f}% gain locked)"
                elif is_short_stock:
                    buf_dist = get_sl_buffer_distance(entry_s, side="BEAR")
                    be_offset = max(buf_dist, 0.5 * atr)
                    be_target = round(round((entry_s - be_offset) / 0.05) * 0.05, 2)
                    new_sl = min(curr_sl, be_target) if curr_sl > 0 else be_target
                    trail_label = "TRAIL-1 (+10% Gain Lock -> +2% BE)"
                    log_sl_label = f"SL=+BE {new_sl:.2f} (+{gain_pct:.1f}% gain locked)"
                else:
                    buf_dist = get_sl_buffer_distance(entry_s, side="BULL")
                    be_offset = max(buf_dist, 0.5 * atr)
                    be_target = round(round((entry_s + be_offset) / 0.05) * 0.05, 2)
                    new_sl = max(curr_sl, be_target)
                    trail_label = "TRAIL-1 (+10% Gain Lock -> +2% BE)"
                    log_sl_label = f"SL=+BE {new_sl:.2f} (+{gain_pct:.1f}% gain locked)"

                sl_stamp = dt.now().isoformat()
                with lock:
                    if sym in positions_dict:
                        positions_dict[sym]["current_sl"] = new_sl
                        positions_dict[sym]["trailing_stage"] = 1
                        positions_dict[sym]["sl_set_time"] = sl_stamp
                ext_metric = f"Low={lp:.2f}" if is_short_stock else f"High={hp:.2f}"
                logging.info(f"{trail_label} {sym}: {ext_metric} (+{gain_pct:.1f}%) -> SL={new_sl:.2f}")
                log_fn(sym, pos.get("pattern", ""), timeframe_entry, "TRAIL_BE", "MUTATED",
                       log_sl_label,
                       entry=entry_s, sl=new_sl, target=t1_val,
                       event_time=last.get('date'))
                if tid:
                    trade_db.update_trade(tid, {"trailing_stage": 1, "current_sl": new_sl, "sl_set_time": sl_stamp})

            t1_hit = ((lp <= (t1_val + buf_t1)) if is_short_stock else (hp >= (t1_val - buf_t1))) if (t1_val is not None and t1_val > 0) else False
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
                    lot_sz = get_option_lot_size(pos.get("contract","")) or pos.get("lot_size", 1) or 1
                    raw_pos_size = int(pos.get("position_size", 1))
                    raw_qty = int(pos.get("quantity") or 0)
                    total_qty = raw_qty if raw_qty > 0 else (raw_pos_size * lot_sz if not is_stock else raw_pos_size)
                    num_lots = max(1, total_qty // lot_sz) if not is_stock else total_qty
                    tranche_mode = cfg.get("tranche_mode", True) if isinstance(cfg, dict) else True
                    # 2-Tranche Model: If holding >= 2 lots/units, book 50% profit at T1 and ride runner
                    if tranche_mode and num_lots >= 2:
                        half_lots = num_lots // 2
                        partial_qty = half_lots * lot_sz if not is_stock else half_lots
                        remaining_qty = total_qty - partial_qty
                        remaining_lots = num_lots - half_lots
                        logging.info(f"[TRANCHE_1_EXIT] Booking 50% partial profit ({half_lots} lots / {partial_qty} qty) at T1 ({t1_val:.2f}) for {sym}. Remaining {remaining_lots} lots ({remaining_qty} qty) will ride to T2/T3 with BE SL.")
                        if is_stock:
                            exit_res = close_stock_position(kite, pos, live, product_type, qty_override=partial_qty)
                        else:
                            exit_res = close_position(kite, pos, live, product_type, qty_override=partial_qty)
                        
                        exit_ok = bool(exit_res and exit_res.get("success"))
                        if exit_ok:
                            if is_short_stock:
                                buf_dist = get_sl_buffer_distance(entry_s, side="BEAR")
                                be_offset = max(buf_dist, 0.5 * atr)
                                be_sl = round(round((entry_s - be_offset) / 0.05) * 0.05, 2)
                                partial_pnl = ((entry_s - t1_val) / entry_s * 100) if entry_s else 0
                            else:
                                buf_dist = get_sl_buffer_distance(entry_s, side="BULL")
                                be_offset = max(buf_dist, 0.5 * atr)
                                be_sl = round(round((entry_s + be_offset) / 0.05) * 0.05, 2)
                                partial_pnl = ((t1_val - entry_s) / entry_s * 100) if entry_s else 0
                            with lock:
                                if sym in positions_dict:
                                    positions_dict[sym]["position_size"] = remaining_lots
                                    positions_dict[sym]["quantity"] = remaining_qty
                                    positions_dict[sym]["current_sl"] = be_sl
                                    positions_dict[sym]["trailing_stage"] = 1
                                    positions_dict[sym]["t1_booked"] = True
                                    positions_dict[sym]["sl_set_time"] = dt.now().isoformat()
                            log_fn(sym, pos.get("pattern", ""), pos_tf, "EXIT_T1_PARTIAL", "PARTIAL",
                                   f"T1 Banked 50% ({partial_qty} qty) @ {t1_val:.2f} | Runner SL=+BE ({be_sl:.2f})",
                                   partial_pnl,
                                   entry=entry_s, sl=be_sl, target=t2_val or t3_val,
                                   event_time=last.get('date'))
                            if tid:
                                trade_db.update_trade(tid, {
                                    "position_size": remaining_lots,
                                    "quantity": remaining_qty,
                                    "trailing_stage": 1,
                                    "t1_booked": True,
                                    "current_sl": be_sl,
                                    "sl_set_time": dt.now().isoformat(),
                                    "details": f"T1 50% Banked ({partial_qty} qty) @ {t1_val:.2f} | Runner active ({remaining_qty} qty)"
                                })
                        else:
                            logging.critical(f"[TRANCHE_1_EXIT FAILED] Partial exit order for {sym} failed ({exit_res}). Preserving full position.")
                    else:
                        # Single-lot trailing to Positive Breakeven
                        curr_sl = float(pos.get("current_sl") or 0.0)
                        if is_short_stock:
                            buf_dist = get_sl_buffer_distance(entry_s, side="BEAR")
                            be_offset = max(buf_dist, 0.5 * atr)
                            be_sl = round(round((entry_s - be_offset) / 0.05) * 0.05, 2)
                            new_sl = min(curr_sl, be_sl) if curr_sl > 0 else be_sl
                        else:
                            buf_dist = get_sl_buffer_distance(entry_s, side="BULL")
                            be_offset = max(buf_dist, 0.5 * atr)
                            be_sl = round(round((entry_s + be_offset) / 0.05) * 0.05, 2)
                            new_sl = max(curr_sl, be_sl)
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

            t2_hit = ((lp <= (t2_val + buf_t2)) if is_short_stock else (hp >= (t2_val - buf_t2))) if (t2_val is not None and t2_val > 0) else False
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
                        new_sl = max(curr_sl, target_base)
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

            t3_hit = ((lp <= (t3_val + buf_t3)) if is_short_stock else (hp >= (t3_val - buf_t3))) if (t3_val is not None and t3_val > 0) else False
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

    # 0. Reconcile and cancel stale / unfilled entry orders on Kite
    try:
        reconcile_and_cancel_stale_orders(kite, live=live)
    except Exception as e:
        logging.debug(f"[STANDALONE_MONITOR] Stale order reconcile error: {e}")

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
                from resolve import lookup_scan_sl_target, derive_sl_targets_for_contract
                broker_avg_p = float(p.get("average_price", 0))
                sl_info = lookup_scan_sl_target(tsym, tsym, eng_type, kite=kite, entry_price=broker_avg_p, side="BEAR" if is_short_eq else "BULL")

                # Sanitize recovered SL: Prevent immediate stop trigger if lookup returned a stale SL from an old trade
                cand_sl = float(sl_info.get("current_sl") or 0.0) if sl_info else 0.0
                cand_t1 = float(sl_info.get("t1") or 0.0) if sl_info else 0.0
                cand_t2 = float(sl_info.get("t2") or 0.0) if sl_info else 0.0
                cand_t3 = float(sl_info.get("t3") or 0.0) if sl_info else 0.0
                cand_pat = sl_info.get("pattern", "BROKER_RECOVERED") if sl_info else "BROKER_RECOVERED"
                cand_spot_sl = sl_info.get("spot_sl") if sl_info else None
                cand_spot_entry = sl_info.get("spot_entry") if sl_info else None
                cand_spot_token = sl_info.get("spot_token") if sl_info else None

                sl_invalid = False
                if broker_avg_p > 0 and cand_sl > 0:
                    if is_short_eq:
                        # Short stock: SL must be strictly above entry price
                        if cand_sl <= broker_avg_p or cand_sl / broker_avg_p > 2.0:
                            sl_invalid = True
                    else:
                        # Long stock or option: SL must be strictly below entry price
                        if cand_sl >= broker_avg_p or broker_avg_p / cand_sl > 2.5:
                            sl_invalid = True

                if sl_invalid and kite and broker_avg_p > 0:
                    logging.warning(f"[BROKER_RECOVERY] Stale SL ({cand_sl:.2f}) detected for {tsym} vs broker entry ({broker_avg_p:.2f}). Deriving fresh SL/targets.")
                    derived = derive_sl_targets_for_contract(kite, tsym, broker_avg_p, "15minute", "15minute", side="BEAR" if is_short_eq else "BULL")
                    if derived:
                        cand_sl = float(derived.get("current_sl") or 0.0)
                        cand_t1 = float(derived.get("t1") or 0.0)
                        cand_t2 = float(derived.get("t2") or 0.0)
                        cand_t3 = float(derived.get("t3") or 0.0)
                        cand_pat = derived.get("pattern", "DERIVED_RECOVERY")
                        cand_spot_sl = derived.get("spot_sl")
                        cand_spot_entry = derived.get("spot_entry")
                        cand_spot_token = derived.get("spot_token")

                lot_sz = get_option_lot_size(tsym) or 1
                num_lots = max(1, abs(p_qty) // lot_sz) if (is_opt and lot_sz > 0) else abs(p_qty)
                broker_pos_dict = {
                    "contract": tsym,
                    "symbol": tsym,
                    "quantity": abs(p_qty),
                    "position_size": num_lots,
                    "lot_size": lot_sz,
                    "entry_spot": broker_avg_p,
                    "entry_price": broker_avg_p,
                    "current_sl": cand_sl,
                    "t1": cand_t1,
                    "t2": cand_t2,
                    "t3": cand_t3,
                    "spot_sl": cand_spot_sl,
                    "spot_entry": cand_spot_entry,
                    "spot_token": cand_spot_token,
                    "trailing_stage": int(sl_info.get("trailing_stage") or 0) if sl_info else 0,
                    "pattern": cand_pat,
                    "position_type": "option" if is_opt else "stock",
                    "side": "SELL" if is_short_eq else ("PE" if (is_opt and c_str.endswith("PE")) else ("CE" if is_opt else "BUY")),
                    "direction": "BEAR" if (is_short_eq or (is_opt and c_str.endswith("PE"))) else "BULL",
                    "product": p.get("product", "MIS" if is_short_eq else "CNC"),
                    "source": "kite"
                }

                # Persist unlinked broker position directly into SQLite to preserve state across ticks/restarts
                try:
                    from resolve import resolve_underlying
                    underlying_sym = resolve_underlying(tsym, eng_type)
                    tid, _created = trade_db.create_trade(eng_type, underlying_sym, broker_pos_dict)
                    if tid:
                        broker_pos_dict["id"] = tid
                        logging.info(f"[BROKER_RECOVERY_PERSIST] Persisted unlinked broker position {tsym} (Trade #{tid}) into trades.sqlite3")
                except Exception as p_err:
                    logging.warning(f"Could not persist broker position {tsym} into DB: {p_err}")

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
            timeframe_entry="15minute",
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



