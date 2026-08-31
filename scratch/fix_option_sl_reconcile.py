import os
import sys
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call
from targets import calculate_sl_buffer
import trade_db

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" RECONCILING OPTION BUYING STOP-LOSSES")
print("==================================================")

pos_data = safe_kite_call(kite.positions) or {}
pos = pos_data.get("net", [])
active_kite = [p for p in pos if int(p.get("quantity", 0)) > 0]

reconciled = []

for p in active_kite:
    tsym = str(p.get("tradingsymbol", "")).strip().upper()
    qty = int(p.get("quantity", 0))
    buy_avg = float(p.get("average_price") or p.get("buy_price") or 0.0)
    ltp = float(p.get("last_price") or 0.0)
    is_index = any(idx in tsym for idx in ["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY", "FINNIFTY"]) and not any(st in tsym for st in ["NIFTYIT", "NIFTYPHARMA"])
    engine = "index" if is_index else "nifty50"
    
    from registries import extract_underlying_symbol
    base_sym = extract_underlying_symbol(tsym) or tsym

    # Lookup existing active trade
    db_trade = None
    for at in trade_db.get_active_trades(engine):
        if at.get("contract") == tsym or at.get("symbol") == base_sym:
            db_trade = at
            break
            
    ep = buy_avg if buy_avg > 0 else ltp
    
    # Specific curated technical SLs for today's active portfolio:
    custom_sl_map = {
        "TATAPOWER26SEP350CE": (7.20, 20.10, 29.20, 30.50),
        "POWERGRID26SEP270CE": (2.75, 4.85, 5.15, 7.25),
        "SOLARINDS26SEP19750PE": (328.00, 420.00, 480.00, 520.00),
        "KOTAKBANK26SEP420PE": (5.00, 9.30, 9.95, 0.0),
        "LICI26SEP420CE": (5.80, 16.50, 18.10, 19.10),
        "NIFTY2690123950CE": (110.00, 336.40, 400.00, 0.0),
        "POLYCAB26SEP9200CE": (150.00, 246.20, 295.50, 316.65),
        "SENSEX2690377200CE": (200.00, 632.00, 670.00, 698.00)
    }
    
    if tsym in custom_sl_map:
        sl_val, t1_val, t2_val, t3_val = custom_sl_map[tsym]
    else:
        sl_val = round(ep * 0.85, 2)
        risk = ep - sl_val
        t1_val = round(ep + 1.88 * risk, 2)
        t2_val = round(ep + 2.50 * risk, 2)
        t3_val = round(ep + 3.50 * risk, 2)

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
        "trailing_stage": 0,
        "lot_size": qty,
        "position_size": 1,
        "pattern": db_trade.get("pattern", "KITE_RECONCILED") if db_trade else "KITE_RECONCILED",
        "timeframe": "15minute" if is_index else "30minute",
        "entry_time": db_trade.get("entry_time", dt.now().isoformat()) if db_trade else dt.now().isoformat(),
        "position_type": "option",
        "side": "PE" if "PE" in tsym else "CE"
    }

    if db_trade and db_trade.get("id"):
        trade_db.update_trade(db_trade["id"], pos_dict)
    else:
        trade_db.create_trade(engine, base_sym, pos_dict)

    reconciled.append({
        "Contract": tsym,
        "Engine": engine,
        "Qty": qty,
        "BuyPrice": ep,
        "LTP": ltp,
        "SL": sl_val,
        "T1": t1_val,
        "PnL": p.get("pnl")
    })

print("\n=== RECONCILED ACTIVE POSITIONS ===")
df_res = pd.DataFrame(reconciled)
print(df_res.to_string(index=False))
