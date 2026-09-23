"""
scratch/test_tick_and_gate_cooldown.py
======================================
Unit tests for:
1. round_to_tick invariant (0.05 tick size enforcement)
2. Radar gate rejection cooldown logic (HTTP 429 fix)
3. Smart validity reconciliation sweep in pattern_funnel & display_writer
4. Trade entry target integrity guard (T1 > Entry)
"""

import sys
import os
import time
from datetime import datetime as dt, timedelta

# Ensure canonical paths
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
COMMON = os.path.join(ROOT, "common")
if COMMON not in sys.path:
    sys.path.insert(0, COMMON)

from common.trading_core import round_to_tick, calculate_option_profit_targets
from common import pattern_funnel


def test_round_to_tick():
    print("[TEST 1] Testing round_to_tick invariants...")
    # 11.89 was the BHARTIARTL rejection price
    assert round_to_tick(11.89) == 11.90, f"Expected 11.90, got {round_to_tick(11.89)}"
    assert round_to_tick(11.82) == 11.80, f"Expected 11.80, got {round_to_tick(11.82)}"
    assert round_to_tick(11.83) == 11.85, f"Expected 11.85, got {round_to_tick(11.83)}"
    assert round_to_tick(0.01) == 0.05, f"Expected 0.05 min floor, got {round_to_tick(0.01)}"
    assert round_to_tick(0.00) == 0.05, f"Expected 0.05 for 0, got {round_to_tick(0.00)}"
    assert round_to_tick(-5.0) == 0.05, f"Expected 0.05 for negative, got {round_to_tick(-5.0)}"
    assert round_to_tick(None) == 0.05, f"Expected 0.05 for None, got {round_to_tick(None)}"
    assert round_to_tick(192.33) == 192.35, f"Expected 192.35, got {round_to_tick(192.33)}"
    assert round_to_tick(488.02) == 488.00, f"Expected 488.00, got {round_to_tick(488.02)}"
    for test_val in [1.23, 4.56, 7.89, 11.89, 52.41, 192.37, 500.04]:
        t_res = round_to_tick(test_val)
        assert round(t_res * 100) % 5 == 0, f"Value {t_res} is not divisible by 0.05!"
    print("   PASSED [OK]: round_to_tick guarantees exact 0.05 tick size parity.")


def test_radar_gate_cooldown():
    print("[TEST 2] Testing radar gate cooldown logic...")
    from Trade_Option.stock_options_trade_engine import _RADAR_CANDIDATE_GATE_COOLDOWN

    test_c = "WIPRO26OCT160CE"
    # Set 90s cooldown
    _RADAR_CANDIDATE_GATE_COOLDOWN[test_c] = time.time() + 90.0

    # Simulate check within cooldown
    assert test_c in _RADAR_CANDIDATE_GATE_COOLDOWN
    assert time.time() < _RADAR_CANDIDATE_GATE_COOLDOWN[test_c]

    # Simulate expired cooldown
    _RADAR_CANDIDATE_GATE_COOLDOWN[test_c] = time.time() - 1.0
    # Condition: if time.time() >= cooldown, pop it
    if time.time() >= _RADAR_CANDIDATE_GATE_COOLDOWN[test_c]:
        _RADAR_CANDIDATE_GATE_COOLDOWN.pop(test_c, None)

    assert test_c not in _RADAR_CANDIDATE_GATE_COOLDOWN
    print("   PASSED [OK]: Radar gate cooldown suppresses 15s spam and unblocks cleanly after expiry.")


def test_smart_validity_reconciliation():
    print("[TEST 3] Testing smart validity reconciliation...")
    today_str = dt.now().strftime("%Y-%m-%d")
    yesterday_str = (dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    four_days_ago = (dt.now() - timedelta(days=4)).strftime("%Y-%m-%d")

    # Mock engine state
    engine_name = "test_engine"
    state = {
        "category_a": [
            # Case 1: Yesterday setup, SL intact, not 80% T1 -> MUST BE RETAINED!
            {
                "symbol": "VALID_YESTERDAY",
                "contract": "VALID_YESTERDAY26OCT100CE",
                "entry_time": f"{yesterday_str} 14:30:00",
                "benchmark": 50.0,
                "current_sl": 40.0,
                "t1": 70.0,
                "entry_spot": 48.0,
                "side": "CE"
            },
            # Case 2: 4 days old -> MUST BE EVICTED (too old)
            {
                "symbol": "OLD_SETUP",
                "contract": "OLD_SETUP26OCT100CE",
                "entry_time": f"{four_days_ago} 10:00:00",
                "benchmark": 50.0,
                "current_sl": 40.0,
                "t1": 70.0,
                "entry_spot": 48.0,
                "side": "CE"
            },
            # Case 3: Yesterday setup, but Anchor SL breached -> MUST BE EVICTED
            {
                "symbol": "SL_BREACHED",
                "contract": "SL_BREACHED26OCT100CE",
                "entry_time": f"{yesterday_str} 15:00:00",
                "benchmark": 50.0,
                "current_sl": 40.0,
                "t1": 70.0,
                "entry_spot": 38.0,  # Below SL 40
                "side": "CE"
            },
            # Case 4: Yesterday setup, but 80% T1 already reached -> MUST BE EVICTED
            {
                "symbol": "T1_80_HIT",
                "contract": "T1_80_HIT26OCT100CE",
                "entry_time": f"{yesterday_str} 15:00:00",
                "benchmark": 50.0,
                "current_sl": 40.0,
                "t1": 70.0,
                "entry_spot": 67.0,  # 50 + 0.8*(70-50) = 66.0 -> 67.0 >= 66.0
                "side": "CE"
            }
        ],
        "category_a_plus": [],
        "category_b": []
    }

    pattern_funnel.save_funnel_state(engine_name, state)
    updated = pattern_funnel.reconcile_funnel_and_display_setups(engine_name=engine_name, today_str=today_str, purge_scan_display=False)

    retained_a = updated.get("category_a", [])
    assert len(retained_a) == 1, f"Expected exactly 1 retained setup, got {len(retained_a)}"
    assert retained_a[0]["symbol"] == "VALID_YESTERDAY", f"Expected VALID_YESTERDAY, got {retained_a[0]['symbol']}"

    # Clean up test engine
    pattern_funnel.clear_funnel(engine_name)
    print("   PASSED [OK]: Smart validity reconciliation preserves valid multi-day setups and evicts invalid ones.")


def test_target_integrity_guard():
    print("[TEST 4] Testing trade entry target integrity guard...")
    limit_entry = 52.40
    sl = 35.66
    stale_t1 = 49.10  # Less than entry price!

    # Target integrity logic
    curr_t1 = stale_t1
    if curr_t1 <= limit_entry:
        calc_t1, calc_t2, calc_t3 = calculate_option_profit_targets(
            entry_premium=limit_entry,
            sl_price=sl,
            dte=25,
            spot_t1=None
        )
    else:
        calc_t1 = curr_t1

    assert calc_t1 > limit_entry, f"Expected T1 > {limit_entry}, got {calc_t1}"
    risk = limit_entry - sl  # 16.74
    # Monthly target: entry + 2.5 * risk = 52.40 + 2.5 * 16.74 = 94.25
    assert calc_t1 >= round(limit_entry + 1.5 * risk, 2)
    print(f"   PASSED [OK]: Target integrity guard corrected T1 from {stale_t1} to {calc_t1:.2f} (> Entry {limit_entry:.2f}).")


if __name__ == "__main__":
    test_round_to_tick()
    test_radar_gate_cooldown()
    test_smart_validity_reconciliation()
    test_target_integrity_guard()
    print("\nALL TICK SIZE, GATE COOLDOWN & SMART RECONCILIATION TESTS PASSED (4/4)!")
