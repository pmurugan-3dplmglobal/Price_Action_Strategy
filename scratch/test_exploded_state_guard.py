"""
scratch/test_exploded_state_guard.py
====================================
Unit test suite verifying the Anti-Exploded State & Point-of-Execution Chase Protection Guard.
"""

import os
import sys

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from exploded_state_guard import check_exploded_state_guard


def run_tests():
    print("=== RUNNING TEST_EXPLODED_STATE_GUARD ===")
    passed = 0
    total = 0

    # Test 1: Pristine Early Breakout Entry (Approved)
    # BM = 100, SL = 80, T1 = 140. Live Ask = 104 (+4% from BM, 10% consumed, Live RR = 36/24 = 1.5)
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=104.0, benchmark_price=100.0, t1_target=140.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE"
    )
    assert ok is True, f"Test 1 Failed: {reason}"
    assert metrics["consumed_pct"] == 10.0
    print(f"PASS Test 1: Pristine early entry approved ({metrics})")
    passed += 1

    # Test 2: Target 1 Already Hit (Blocked)
    # BM = 100, T1 = 140, Live Ask = 142
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=142.0, benchmark_price=100.0, t1_target=140.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE"
    )
    assert ok is False, "Test 2 Failed: Should reject when T1 already hit"
    assert "TARGET 1 ALREADY HIT" in reason
    print(f"PASS Test 2: Target already hit blocked -> {reason}")
    passed += 1

    # Test 3: Near-Target Climax (Blocked)
    # BM = 100, T1 = 140. Span = 40. 85% of span = 34 -> Ceiling = 134. Live Ask = 136
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=136.0, benchmark_price=100.0, t1_target=140.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE"
    )
    assert ok is False, "Test 3 Failed: Should reject near-target exhaustion"
    assert "NEAR-TARGET CLIMAX" in reason
    print(f"PASS Test 3: Near-target exhaustion blocked -> {reason}")
    passed += 1

    # Test 4: > 20% Distance Consumed (Blocked)
    # BM = 100, T1 = 140. Span = 40. 25% of span = 10 -> Max allowed = 108. Live Ask = 112 (consumed 30%)
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=112.0, benchmark_price=100.0, t1_target=140.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE"
    )
    assert ok is False, "Test 4 Failed: Should reject when > 20% consumed"
    assert "MOVE ALREADY EXPLODED" in reason
    print(f"PASS Test 4: Move already exploded (>20% consumed) blocked -> {reason}")
    passed += 1

    # Test 5: Max Benchmark Chase Ceiling Exceeded (Blocked)
    # BM = 100, T1 = 200 (Span = 100). Live Ask = 110 (+10% above BM, max allowed 8%).
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=110.0, benchmark_price=100.0, t1_target=200.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE"
    )
    assert ok is False, "Test 5 Failed: Should reject when > 8% chase"
    assert "MAX CHASE EXCEEDED" in reason
    print(f"PASS Test 5: Max chase ceiling exceeded blocked -> {reason}")
    passed += 1

    # Test 6: Inverted Live R:R (Blocked)
    # BM = 100, T1 = 120, SL = 95. Live Ask = 108.
    # Current risk = 108 - 95 = 13. Remaining reward = 120 - 108 = 12. Live RR = 12/13 = 0.92 (< 1.0)
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=108.0, benchmark_price=100.0, t1_target=120.0, stop_loss=95.0,
        contract="NIFTY26OCT25000CE", max_target_consumed_pct=0.45, max_chase_pct=0.10
    )
    assert ok is False, "Test 6 Failed: Should reject when live R:R < 1.0"
    assert "INVERTED LIVE R:R" in reason
    print(f"PASS Test 6: Inverted live R:R (< 1.0) blocked -> {reason}")
    passed += 1

    # Test 7: Underlying Spot Climax (Blocked)
    # Option BM = 100, Live = 103 (Option looks okay). But Spot Trigger = 25000, Spot T1 = 25100, Live Spot = 25105 (Already hit T1!)
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=103.0, benchmark_price=100.0, t1_target=140.0, stop_loss=80.0,
        contract="NIFTY26OCT25000CE", spot_ltp=25105.0, spot_trigger=25000.0, spot_t1=25100.0
    )
    assert ok is False, "Test 7 Failed: Should reject when underlying spot hit T1"
    assert "UNDERLYING SPOT CLIMAX" in reason
    print(f"PASS Test 7: Underlying spot climax blocked -> {reason}")
    passed += 1

    # Test 8: Cash Equity Strict 1.5% Chase Ceiling (Blocked)
    # Spot Stock BM = 1000, T1 = 1080. Live LTP = 1018 (+1.8% above BM, max 1.5% for equity)
    total += 1
    ok, reason, metrics = check_exploded_state_guard(
        live_price=1018.0, benchmark_price=1000.0, t1_target=1080.0, stop_loss=980.0,
        symbol="RELIANCE", is_option=False
    )
    assert ok is False, "Test 8 Failed: Equity should reject > 1.5% chase"
    assert "MOVE ALREADY EXPLODED" in reason or "MAX CHASE EXCEEDED" in reason, f"Unexpected reason: {reason}"
    print(f"PASS Test 8: Equity > 1.5% chase blocked -> {reason}")
    passed += 1

    print(f"\nSUCCESS: All {passed}/{total} Anti-Exploded State Guard tests passed with 100% precision!")


if __name__ == "__main__":
    run_tests()
