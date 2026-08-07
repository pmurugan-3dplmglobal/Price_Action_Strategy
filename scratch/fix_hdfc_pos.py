import json
import os

p_active = "Trade_Option/output/monitor/active_positions_db.json"
p_overrides = "Trade_Option/output/monitor/sl_target_overrides.json"
p_trades = "Trade_Option/output/monitor/trades_db.json"

# 1. Update active_positions_db.json
if os.path.exists(p_active):
    with open(p_active, "r") as f:
        data = json.load(f)
    positions = data.get("positions", [])
    updated = False
    for p in positions:
        if p.get("symbol") == "HDFCBANK" or p.get("contract") == "HDFCBANK26AUG750CE":
            print("Updating active position record from HDFCBANK26AUG750CE to HDFCBANK26AUG730CE...")
            p["contract"] = "HDFCBANK26AUG730CE"
            p["option_token"] = 25558786
            p["entry_spot"] = 19.90
            p["current_sl"] = 17.91
            p["t1"] = 24.80
            p["t2"] = 31.70
            p["t3"] = 34.00
            p["pattern"] = "TIMEFRAME_SWING_MANUAL"
            p["user_edited"] = True
            updated = True
    if updated:
        with open(p_active, "w") as f:
            json.dump(data, f, indent=2)
        print("Successfully updated active_positions_db.json")

# 2. Update sl_target_overrides.json
if os.path.exists(p_overrides):
    with open(p_overrides, "r") as f:
        ov = json.load(f)
    for section in ["nifty50", "index"]:
        if section in ov and "HDFCBANK26AUG750CE" in ov[section]:
            print(f"Removing HDFCBANK26AUG750CE from {section} overrides...")
            del ov[section]["HDFCBANK26AUG750CE"]
            ov[section]["HDFCBANK26AUG730CE"] = {
                "current_sl": 17.91,
                "t1": 24.80,
                "t2": 31.70,
                "t3": 34.00,
                "user_edited": True
            }
    with open(p_overrides, "w") as f:
        json.dump(ov, f, indent=2)
    print("Successfully updated sl_target_overrides.json")

print("HDFC Bank position fix complete.")
