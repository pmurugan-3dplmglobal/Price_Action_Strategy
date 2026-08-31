import os
import sys
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt, timedelta

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call
from targets import calculate_sl_buffer
from dashboard_sl_overrides import sanitize_sl_and_entry, read_sl_overrides
import trade_db

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" RUNNING FULL AUTOMATED BROKER RECONCILIATION")
print("==================================================")

# 1. Fetch live broker net positions
pos_data = safe_kite_call(kite.positions) or {}
pos = pos_data.get("net", [])
active_kite = [p for p in pos if int(p.get("quantity", 0)) > 0]
closed_kite = {p.get("tradingsymbol") for p in pos if int(p.get("quantity", 0)) == 0}

print(f"Active positions in Zerodha Kite: {len(active_kite)}")
print(f"Closed contracts today: {len(closed_kite)}")

# 2. Reconcile broker positions in trade_db
trade_db.reconcile_broker_live_positions(kite)

# 3. Clean up any SQLite active trades that are already closed on Zerodha (qty == 0)
for eng in ["nifty50", "index"]:
    for at in trade_db.get_active_trades(eng):
        cnt = at.get("contract") or at.get("symbol")
        if cnt in closed_kite:
            trade_db.update_trade_status(at["id"], "COMPLETED", exit_price=at.get("entry_spot", 0), exit_reason="BROKER_NET_QTY_ZERO")
            print(f"  [COMPLETED] Reconciled closed trade: {cnt} (ID {at['id']})")

# 4. Audit & Reconcile each live open contract
reconciled_summary = []

for p in active_kite:
    tsym = str(p.get("tradingsymbol", "")).strip().upper()
    qty = int(p.get("quantity", 0))
    buy_avg = float(p.get("average_price") or p.get("buy_price") or 0.0)
    ltp = float(p.get("last_price") or 0.0)
    side = "PE" if "PE" in tsym else "CE"
    exch = p.get("exchange", "NFO")
    is_index = any(idx in tsym for idx in ["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY", "FINNIFTY"]) and not any(st in tsym for st in ["NIFTYIT", "NIFTYPHARMA"])
    engine = "index" if is_index else "nifty50"
    
    # Extract base symbol
    from registries import extract_underlying_symbol
    base_sym = extract_underlying_symbol(tsym) or tsym

    # Check existing DB record
    db_trade = None
    active_trades = trade_db.get_active_trades(engine)
    for at in active_trades:
        if at.get("contract") == tsym or at.get("symbol") == base_sym:
            db_trade = at
            break

    # Determine entry price and SL
    ep = buy_avg if buy_avg > 0 else ltp
    
    # Check overrides first
    all_overrides = read_sl_overrides()
    overrides = all_overrides.get(engine, {})
    ov = overrides.get(tsym) or overrides.get(base_sym, {})
    
    sl_val = ov.get("current_sl") or (db_trade.get("current_sl") if db_trade else None)
    t1_val = ov.get("t1") or (db_trade.get("t1") if db_trade else None)
    t2_val = ov.get("t2") or (db_trade.get("t2") if db_trade else None)
    t3_val = ov.get("t3") or (db_trade.get("t3") if db_trade else None)
    
    # Sanitize or derive SL if missing / inverted
    if sl_val is None or sl_val <= 0 or (sl_val >= ep and db_trade and db_trade.get("trailing_stage", 0) == 0):
        # Derive structural SL from chart or Price Action buffer
        sl_val = calculate_sl_buffer(ep, side="BULL" if side == "CE" else "BEAR")
        print(f"  [DERIVED SL] {tsym}: Assigned fresh technical SL = {sl_val} (Entry: {ep})")
    
    if t1_val is None or t1_val <= ep:
        risk = max(1.0, ep - sl_val) if side == "CE" else max(1.0, sl_val - ep)
        t1_val = round(ep + 1.88 * risk, 2) if side == "CE" else round(ep - 1.88 * risk, 2)
        t2_val = round(ep + 2.50 * risk, 2) if side == "CE" else round(ep - 2.50 * risk, 2)
        t3_val = round(ep + 3.50 * risk, 2) if side == "CE" else round(ep - 3.50 * risk, 2)
    
    # Update SQLite trade
    pos_dict = {
        "engine": engine,
        "symbol": base_sym,
        "contract": tsym,
        "option_token": int(p.get("instrument_token", 0)),
        "entry_spot": ep,
        "current_sl": sl_val,
        "t1": t1_val,
        "t2": t2_val,
        "t3": t3_val,
        "trailing_stage": db_trade.get("trailing_stage", 0) if db_trade else 0,
        "lot_size": qty,
        "position_size": 1,
        "pattern": db_trade.get("pattern", "KITE_RECONCILED") if db_trade else "KITE_RECONCILED",
        "timeframe": db_trade.get("timeframe", "15minute" if is_index else "30minute") if db_trade else "30minute",
        "entry_time": db_trade.get("entry_time", dt.now().isoformat()) if db_trade else dt.now().isoformat(),
        "position_type": "option",
        "side": side
    }
    
    if db_trade and db_trade.get("id"):
        trade_db.update_trade(db_trade["id"], pos_dict)
    else:
        tid, _ = trade_db.create_trade(engine, base_sym, pos_dict)
        pos_dict["trade_id"] = tid
    
    reconciled_summary.append({
        "Contract": tsym,
        "Engine": engine,
        "Qty": qty,
        "BuyPrice": ep,
        "LTP": ltp,
        "SL": sl_val,
        "T1": t1_val,
        "T2": t2_val,
        "T3": t3_val,
        "PnL": p.get("pnl")
    })

print("\n==================================================")
print(" FINAL RECONCILED ACTIVE POSITIONS TABLE")
print("==================================================")
df_rec = pd.DataFrame(reconciled_summary)
print(df_rec.to_string(index=False))
