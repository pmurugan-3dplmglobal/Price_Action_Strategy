import json

# 1. Clean executed_exit_orders.json
exit_file = "output/monitor/executed_exit_orders.json"
try:
    with open(exit_file, "r") as f:
        data = json.load(f)
    # Remove mock test keys and phantom leg
    keys_to_remove = [k for k in data if k.startswith("NIFTY26915") or k.startswith("BANKNIFTY26SEP") or k.startswith("APLAPOLLO")]
    for k in keys_to_remove:
        del data[k]
        print(f"Removed {k} from executed_exit_orders.json")
    with open(exit_file, "w") as f:
        json.dump(data, f, indent=4)
except Exception as e:
    print(f"Error updating executed_exit_orders: {e}")

# 2. Sanitize APLAPOLLO in stock_positions_state.json
state_file = "output/monitor/stock_positions_state.json"
try:
    with open(state_file, "r") as f:
        state = json.load(f)
    if "APLAPOLLO" in state:
        apl = state["APLAPOLLO"]
        apl["position_type"] = "option"
        for leg_key in ["spread_type", "leg2_contract", "leg2_token", "leg2_strike", "leg2_qty"]:
            if leg_key in apl:
                del apl[leg_key]
                print(f"Removed {leg_key} from APLAPOLLO state")
        with open(state_file, "w") as f:
            json.dump(state, f, indent=4)
        print("Successfully sanitized APLAPOLLO in stock_positions_state.json")
except Exception as e:
    print(f"Error sanitizing stock_positions_state.json: {e}")
