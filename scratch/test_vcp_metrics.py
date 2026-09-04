import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import pandas as pd
import numpy as np
from common.swing_detection import calculate_vcp_metrics

def test_vcp():
    print("=== Testing calculate_vcp_metrics ===")

    # Test 1: Empty / Insufficient dataframe fallback
    df_empty = pd.DataFrame()
    r_empty = calculate_vcp_metrics(df_empty)
    assert r_empty["atr_ratio"] == 1.0, f"Expected 1.0, got {r_empty}"
    assert r_empty["is_squeeze"] is False
    assert r_empty["vcp_tier"] == "NORMAL"
    print("[PASS] Test 1: Safe fallback on empty dataframe")

    # Test 2: Normal volatility (random walk)
    np.random.seed(42)
    closes = 100.0 + np.cumsum(np.random.randn(50))
    highs = closes + np.random.uniform(0.5, 1.5, size=50)
    lows = closes - np.random.uniform(0.5, 1.5, size=50)
    df_normal = pd.DataFrame({"close": closes, "high": highs, "low": lows})
    r_norm = calculate_vcp_metrics(df_normal)
    print(f"[PASS] Test 2: Normal volatility -> ATR ratio: {r_norm['atr_ratio']}, Squeeze: {r_norm['is_squeeze']}, Tier: {r_norm['vcp_tier']}")

    # Test 3: Tight contraction / Squeeze (last 10 candles very tight)
    closes_tight = np.copy(closes)
    highs_tight = np.copy(highs)
    lows_tight = np.copy(lows)
    # Test 3: Recent immediate contraction (last 3 candles contracted relative to 14-period baseline)
    closes_recent = np.copy(closes)
    highs_recent = np.copy(highs)
    lows_recent = np.copy(lows)
    for i in range(-3, 0):
        closes_recent[i] = closes_recent[-4] + np.random.uniform(-0.02, 0.02)
        highs_recent[i] = closes_recent[i] + 0.05
        lows_recent[i] = closes_recent[i] - 0.05

    df_recent = pd.DataFrame({"close": closes_recent, "high": highs_recent, "low": lows_recent})
    r_recent = calculate_vcp_metrics(df_recent)
    badge_repr_rec = r_recent['vcp_badge'].encode('ascii', 'backslashreplace').decode('ascii')
    print(f"[PASS] Test 3: Immediate contraction -> ATR ratio: {r_recent['atr_ratio']}, Squeeze: {r_recent['is_squeeze']}, Tier: {r_recent['vcp_tier']}, Badge: {badge_repr_rec}")
    assert r_recent["atr_ratio"] < 0.60, f"Expected ATR ratio < 0.60, got {r_recent['atr_ratio']}"

    # Test 4: Prolonged Squeeze (last 25 candles inside Keltner Channel)
    closes_sqz = np.copy(closes)
    highs_sqz = np.copy(highs)
    lows_sqz = np.copy(lows)
    for i in range(-25, 0):
        closes_sqz[i] = closes_sqz[-26] + np.random.uniform(-0.02, 0.02)
        highs_sqz[i] = closes_sqz[i] + 0.05
        lows_sqz[i] = closes_sqz[i] - 0.05
    # make the very last 3 even tighter to trigger ULTRA_SQUEEZE
    for i in range(-3, 0):
        closes_sqz[i] = closes_sqz[-4]
        highs_sqz[i] = closes_sqz[i] + 0.01
        lows_sqz[i] = closes_sqz[i] - 0.01

    df_sqz = pd.DataFrame({"close": closes_sqz, "high": highs_sqz, "low": lows_sqz})
    r_sqz = calculate_vcp_metrics(df_sqz)
    badge_repr_sqz = r_sqz['vcp_badge'].encode('ascii', 'backslashreplace').decode('ascii')
    print(f"[PASS] Test 4: Squeeze -> ATR ratio: {r_sqz['atr_ratio']}, Squeeze: {r_sqz['is_squeeze']}, Tier: {r_sqz['vcp_tier']}, Badge: {badge_repr_sqz}")
    assert r_sqz["is_squeeze"] is True, f"Expected squeeze to be True, got {r_sqz['is_squeeze']}"
    assert r_sqz["vcp_tier"] in ("ULTRA_SQUEEZE", "SQUEEZE")

    print("\nALL VCP UNIT TESTS PASSED!")

if __name__ == "__main__":
    test_vcp()
