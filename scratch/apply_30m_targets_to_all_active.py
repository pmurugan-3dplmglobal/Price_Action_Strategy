import json
import os
import sys

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from kiteconnect import KiteConnect
from trading_core import (
    load_kite_session,
    derive_sl_targets_for_contract,
    clear_executed_exit
)

api_k, acc_t = load_kite_session()
kite = KiteConnect(api_key=api_k, access_token=acc_t)

db_p = "Trade_Option/output/monitor/active_positions_db.json"
ov_p = "Trade_Option/output/monitor/sl_target_overrides.json"

db_data = json.load(open(db_p)) if os.path.exists(db_p) else {"positions": []}
positions = db_data.get("positions", [])

overrides = json.load(open(ov_p)) if os.path.exists(ov_p) else {}

print("=== RE-DERIVING 30MIN ANCHOR NEGATION TARGETS FOR ALL ACTIVE POSITIONS ===")

updated_summary = []

for p in positions:
    sym = p.get("symbol")
    c = p.get("contract") or sym
    entry = float(p.get("entry_spot") or 0)
    is_stock = p.get("position_type") == "stock"
    exch = "NSE" if is_stock else "NFO"
    q_key = f"{exch}:{c}"

    # Fetch live quote for LTP / Entry
    ltp = 0.0
    if kite:
        try:
            q = kite.quote([q_key])
            ltp = float(q.get(q_key, {}).get("last_price", 0))
        except Exception as e:
            print(f"Quote err for {c}: {e}")

    ref_price = entry if entry > 0 else ltp

    # Run 30min Anchor TF Negation Target Derivation
    res = derive_sl_targets_for_contract(kite, c, ref_price, "15minute", "30minute")
    
    if res:
        sl_val = res.get("current_sl")
        t1_val = res.get("t1")
        t2_val = res.get("t2")
        t3_val = res.get("t3")
        pattern = res.get("pattern", "NEGATION_30M")

        # Update position entry in DB structure
        p["current_sl"] = sl_val
        p["t1"] = t1_val
        p["t2"] = t2_val
        p["t3"] = t3_val
        p["timeframe"] = "30minute"
        p["user_edited"] = True

        # Update Overrides file
        vals = {
            "current_sl": sl_val,
            "t1": t1_val,
            "t2": t2_val,
            "t3": t3_val,
            "user_edited": True
        }
        for eng in ["nifty50", "index"]:
            overrides.setdefault(eng, {})[c] = vals
            if sym:
                overrides.setdefault(eng, {})[sym] = vals

        clear_executed_exit(c)
        if sym:
            clear_executed_exit(sym)

        updated_summary.append({
            "contract": c,
            "ref_price": ref_price,
            "new_30m_sl": sl_val,
            "new_30m_t1": t1_val if t1_val else "N/A",
            "new_30m_t2": t2_val if t2_val else "N/A",
            "new_30m_t3": t3_val if t3_val else "N/A",
            "pattern": pattern
        })

# Save updated files
os.makedirs(os.path.dirname(db_p), exist_ok=True)
json.dump(db_data, open(db_p, "w"), indent=2)

os.makedirs(os.path.dirname(ov_p), exist_ok=True)
json.dump(overrides, open(ov_p, "w"), indent=2)

print("UPDATED ACTIVE POSITIONS SUMMARY (30MIN ANCHOR TF):")
print(json.dumps(updated_summary, indent=2))
