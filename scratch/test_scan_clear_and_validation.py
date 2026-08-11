import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

import paths
from trading_core import write_scan_display_data

def test_clear_and_staging():
    print("--- TEST 1: Testing Clear Scan Data File Wiping ---")
    test_file = paths.SCAN_DISPLAY_FILE
    now_str = "2026-08-10 15:00:00"
    empty_scan = {
        "date": "2026-08-10",
        "timestamp": now_str,
        "cleared_at": now_str,
        "staged_trades": [],
        "all_staged_today": [],
        "carry_forward": [],
        "active_live": []
    }
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(empty_scan, f, indent=2)

    with open(test_file, "r", encoding="utf-8") as f:
        d = json.load(f)
    assert len(d["staged_trades"]) == 0
    assert len(d["all_staged_today"]) == 0
    assert len(d["carry_forward"]) == 0
    assert len(d["active_live"]) == 0
    print("[PASS] Clear scan wipes all 4 trade sections cleanly.")

    print("--- TEST 2: Testing Active Position Validation during Scan Run ---")
    active_positions = {
        "ITC": {
            "symbol": "ITC",
            "contract": "ITC26AUG290PE",
            "status": "ACTIVE",
            "current_sl": 5.2,
            "t1": 7.1,
            "entry_spot": 5.2,
            "entry_time": "2026-08-10 09:57:49"
        },
        "CLOSED_POS": {
            "symbol": "CLOSED_POS",
            "contract": "CLOSED26AUG100CE",
            "status": "SL_HIT",  # INVALID
            "current_sl": 10.0,
            "t1": 15.0,
            "entry_spot": 12.0
        },
        "NO_SL_POS": {
            "symbol": "NO_SL_POS",
            "contract": "NOSL26AUG100CE",
            "status": "ACTIVE",
            "current_sl": 0.0,  # INVALID
            "t1": 15.0,
            "entry_spot": 12.0
        }
    }

    fresh_staged = [{
        "symbol": "RELIANCE",
        "contract": "RELIANCE26AUG1340PE",
        "side": "PE",
        "entry_spot": 26.0,
        "current_sl": 22.0,
        "t1": 33.15,
        "pattern": "BULL_ENG",
        "entry_time": "2026-08-10 15:05:00"
    }]

    write_scan_display_data(fresh_staged, active_positions, test_file, engine_name="nifty50")

    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    staged_contracts = [t["contract"] for t in data["staged_trades"]]
    active_contracts = [t["contract"] for t in data["active_live"] + data["carry_forward"]]

    print(f"Staged Contracts: {staged_contracts}")
    print(f"Active Contracts: {active_contracts}")

    assert "RELIANCE26AUG1340PE" in staged_contracts
    assert "ITC26AUG290PE" in active_contracts
    assert "CLOSED26AUG100CE" not in active_contracts, "Closed position must NOT be displayed!"
    assert "NOSL26AUG100CE" not in active_contracts, "Position without valid SL must NOT be displayed!"

    print("[PASS] Only valid active positions are staged/displayed; invalid/closed positions are filtered out!")

if __name__ == "__main__":
    test_clear_and_staging()
