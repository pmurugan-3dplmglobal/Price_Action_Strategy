import json
import os
import sys
from datetime import datetime as dt, timedelta

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from kiteconnect import KiteConnect
from trading_core import (
    load_kite_session,
    fetch_and_resample_candles,
    find_profit_targets,
    derive_sl_targets_for_contract
)

api_k, acc_t = load_kite_session()
kite = KiteConnect(api_key=api_k, access_token=acc_t)

# Load Active Positions from DB
db_p = "Trade_Option/output/monitor/active_positions_db.json"
db_data = json.load(open(db_p)) if os.path.exists(db_p) else {}
positions = db_data.get("positions", [])

# Fetch Live Quotes from Kite API
quote_keys = []
for p in positions:
    c = p.get("contract") or p.get("symbol")
    is_stock = p.get("position_type") == "stock"
    exch = "NSE" if is_stock else "NFO"
    if c:
        quote_keys.append(f"{exch}:{c}")

quotes = {}
if kite and quote_keys:
    try:
        quotes = kite.quote(quote_keys)
    except Exception as e:
        print(f"Quote error: {e}")

print("=== ALL ACTIVE POSITIONS DEEP NEGATION ANALYSIS ===")
analysis_results = []

for p in positions:
    sym = p.get("symbol")
    contract = p.get("contract") or sym
    entry = float(p.get("entry_spot") or 0)
    sl = float(p.get("current_sl") or 0)
    t1 = p.get("t1")
    t2 = p.get("t2")
    t3 = p.get("t3")
    qty = p.get("lot_size", 1) * p.get("position_size", 1)
    tf = p.get("timeframe", "75min")
    is_stock = p.get("position_type") == "stock"
    exch = "NSE" if is_stock else "NFO"
    q_key = f"{exch}:{contract}"
    
    ltp = 0.0
    if q_key in quotes:
        ltp = float(quotes[q_key].get("last_price", 0))

    raw_pnl = (ltp - entry) * qty if (entry > 0 and ltp > 0) else 0.0
    pnl_pct = ((ltp - entry) / entry * 100) if (entry > 0 and ltp > 0) else 0.0

    # Derive Anchor TF Negation Targets
    anchor_tf = "75min" if tf in ["15minute", "75min"] else ("60minute" if tf == "60minute" else "75min")
    an_res = derive_sl_targets_for_contract(kite, contract, ltp if ltp > 0 else entry, "15minute", anchor_tf)
    
    analysis_results.append({
        "symbol": sym,
        "contract": contract,
        "entry": entry,
        "current_sl": sl,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "ltp": ltp,
        "qty": qty,
        "pnl_rs": round(raw_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "anchor_tf": anchor_tf,
        "an_sl": an_res.get("current_sl") if an_res else None,
        "an_t1": an_res.get("t1") if an_res else None,
        "an_t2": an_res.get("t2") if an_res else None,
        "an_t3": an_res.get("t3") if an_res else None,
    })

print(json.dumps(analysis_results, indent=2))
