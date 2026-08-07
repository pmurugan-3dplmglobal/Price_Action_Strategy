import json
import os

p_active = "Trade_Option/output/monitor/active_positions_db.json"
p_overrides = "Trade_Option/output/monitor/sl_target_overrides.json"

# 1. Update active_positions_db.json
if os.path.exists(p_active):
    with open(p_active, "r") as f:
        data = json.load(f)
    for p in data.get("positions", []):
        if "JIOFIN" in str(p.get("contract", "")) or "JIOFIN" in str(p.get("symbol", "")):
            print("Updating JIOFIN active position to Stage 1 Trailing (SL = Breakeven 7.80)...")
            p["current_sl"] = 7.80
            p["trailing_stage"] = 1
            p["user_edited"] = True
    with open(p_active, "w") as f:
        json.dump(data, f, indent=2)
    print("Updated active_positions_db.json")

# 2. Update sl_target_overrides.json
if os.path.exists(p_overrides):
    with open(p_overrides, "r") as f:
        ov = json.load(f)
    for sec in ["nifty50", "index"]:
        if sec in ov and "JIOFIN26AUG265PE" in ov[sec]:
            ov[sec]["JIOFIN26AUG265PE"]["current_sl"] = 7.80
            ov[sec]["JIOFIN26AUG265PE"]["trailing_stage"] = 1
            ov[sec]["JIOFIN26AUG265PE"]["user_edited"] = True
    with open(p_overrides, "w") as f:
        json.dump(ov, f, indent=2)
    print("Updated sl_target_overrides.json")

print("JIOFIN Breakeven trailing update complete.")
