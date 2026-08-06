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
    derive_sl_targets_for_contract
)

api_k, acc_t = load_kite_session()
kite = KiteConnect(api_key=api_k, access_token=acc_t)

exact_8_trades = [
    {"contract": "COALINDIA26AUG410CE", "sym": "COALINDIA", "buy_price": 7.25, "qty": 1350, "tf": "60minute"},
    {"contract": "SBIN26AUG1020CE", "sym": "SBIN", "buy_price": 28.20, "qty": 750, "tf": "75min"},
    {"contract": "BAJAJFINSV26AUG1920PE", "sym": "BAJAJFINSV", "buy_price": 50.00, "qty": 300, "tf": "75min"},
    {"contract": "TATACONSUM26AUG1100PE", "sym": "TATACONSUM", "buy_price": 21.75, "qty": 550, "tf": "75min"},
    {"contract": "SHRIRAMFIN26AUG1040CE", "sym": "SHRIRAMFIN", "buy_price": 25.50, "qty": 825, "tf": "75min"},
    {"contract": "HCLTECH26AUG1340PE", "sym": "HCLTECH", "buy_price": 32.525, "qty": 400, "tf": "75min"},
    {"contract": "INDIGO26AUG5300PE", "sym": "INDIGO", "buy_price": 171.55, "qty": 150, "tf": "75min"},
    {"contract": "BEL26AUG390CE", "sym": "BEL", "buy_price": 8.7667, "qty": 1425, "tf": "75min"}
]

quote_keys = [f"NFO:{t['contract']}" for t in exact_8_trades]
quotes = kite.quote(quote_keys) if kite else {}

results = []
for t in exact_8_trades:
    c = t["contract"]
    bp = t["buy_price"]
    qty = t["qty"]
    tf = t["tf"]
    q_key = f"NFO:{c}"
    ltp = float(quotes.get(q_key, {}).get("last_price", 0)) if q_key in quotes else bp
    
    pnl_rs = (ltp - bp) * qty
    pnl_pct = ((ltp - bp) / bp * 100) if bp > 0 else 0.0

    res = derive_sl_targets_for_contract(kite, c, bp, "15minute", tf)
    
    results.append({
        "symbol": t["sym"],
        "contract": c,
        "buy_price": bp,
        "ltp": ltp,
        "qty": qty,
        "pnl_rs": round(pnl_rs, 2),
        "pnl_pct": round(pnl_pct, 2),
        "sl": res.get("current_sl") if res else round(bp * 0.90, 2),
        "t1": res.get("t1") if res else None,
        "t2": res.get("t2") if res else None,
        "t3": res.get("t3") if res else None,
        "pattern": res.get("pattern") if res else "NEGATION_DERIVED"
    })

print(json.dumps(results, indent=2))
