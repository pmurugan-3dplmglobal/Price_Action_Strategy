import sys
import os
import pandas as pd
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.patterns_bull import scan_trend_continuation_reentry
from common.patterns_bear import scan_trend_continuation_reentry_bearish

def test_shreecem_crash_rejected():
    """
    Test that a crashing asset like SHREECEM26OCT21750PE (which fell -36% from 740 to 474 below EMA 13)
    is strictly rejected by scan_trend_continuation_reentry.
    """
    # Create synthetic candles simulating the SHREECEM crash:
    # 1. 15 bars of rising prices up to 740
    # 2. 10 bars of precipitous collapse down to 470
    dates = pd.date_range("2026-10-01 09:15", periods=25, freq="30min")
    
    # Rise to 740, then crash to 474
    closes = [
        500, 520, 540, 560, 580, 600, 630, 660, 700, 740, # Part 1 & peak
        730, 700, 650, 600, 550, 510, 490, 480, 470, 465, 460, 455, 450, 470, 474 # Collapse
    ]
    opens = [c - 5 for c in closes]
    opens[-2] = 460 # trigger candle is green (open 460 -> close 470)
    highs = [c + 5 for c in closes]
    lows = [o - 5 for o in opens]
    vols = [1000] * 25

    df_entry = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols
    })
    
    df_anchor = df_entry.copy()

    result = scan_trend_continuation_reentry(df_entry, df_anchor)
    assert result is None, f"Expected None for crashing asset, but got {result}"
    print("[PASS] test_shreecem_crash_rejected: Freefalling asset correctly rejected!")

def test_genuine_bullish_trend_continuation_accepted():
    """
    Test that a healthy uptrend with price holding above EMA 13, small pullback (e.g. 4%),
    and healthy volume triggers a valid D2 signal with full structural attributes.
    """
    dates = pd.date_range("2026-10-01 09:15", periods=25, freq="30min")
    
    # Steady uptrend with higher highs and higher lows
    # Part 1: 100 to 110 (low 99.5, high 111)
    # Part 2: 120 to 126 (min low 119.5, high 127)
    # Pullback touches 120.0 (near 119.5 support), then green trigger candle
    closes = [
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110,
        120, 121, 122, 123, 125, 126, 125, 123, 121, 120, 119.8, 120.2, 121.5, 122.0
    ]
    opens = [c - 0.5 for c in closes]
    opens[-2] = 120.2 # trigger candle is green (120.2 -> 121.5)
    highs = [c + 0.8 for c in closes]
    highs[16] = 127.0 # peak
    lows = [o - 0.5 for o in opens]
    lows[-2] = 119.8 # touches support
    lows[11] = 119.5 # part 2 base support
    vols = [5000] * 25

    df_entry = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols
    })
    
    # Create anchor dataframe with higher targets
    anchor_dates = pd.date_range("2026-10-01 09:15", periods=30, freq="1h")
    df_anchor = pd.DataFrame({
        "date": anchor_dates,
        "open": [100 + i for i in range(30)],
        "high": [105 + i*1.2 for i in range(30)],
        "low": [98 + i for i in range(30)],
        "close": [102 + i for i in range(30)],
        "volume": [10000] * 30
    })

    result = scan_trend_continuation_reentry(df_entry, df_anchor)
    assert result is not None, "Expected valid D2 signal for healthy uptrend, got None"
    assert result["Benchmark"] is not None and result["Benchmark"] > 0, "Benchmark must be populated"
    assert result["AnchorFloor"] is not None and result["AnchorFloor"] > 0, "AnchorFloor must be populated"
    assert result["tier"] == 2, f"Tier should be 2 (Core), got {result['tier']}"
    assert result["tier_label"] == "TIER_2_CORE"
    print(f"[PASS] test_genuine_bullish_trend_continuation_accepted: Result={result['Pattern']}, Benchmark={result['Benchmark']}, SL={result['SL']}, Tier={result['tier_label']}")

def test_genuine_bearish_trend_continuation_accepted():
    """
    Test that a healthy downtrend with price staying below EMA 13 triggers a valid D2 Bearish signal.
    """
    dates = pd.date_range("2026-10-01 09:15", periods=25, freq="30min")
    
    # Downtrend with lower highs and lower lows
    # Part 1: 200 down to 185
    # Part 2: 170 down to 160, bounce back up to 170 resistance, red trigger candle forms
    closes = [
        200, 198, 196, 194, 192, 190, 188, 186, 185, 184, 183,
        170, 168, 166, 164, 162, 160, 162, 165, 167, 169, 169.5, 167.0, 166.5, 166.0
    ]
    opens = [c + 0.5 for c in closes]
    opens[-2] = 169.5 # trigger candle is red (open 169.5 -> close 166.5)
    highs = [o + 0.5 for o in opens]
    highs[-2] = 170.2 # retests 170.0 resistance
    lows = [c - 0.5 for c in closes]
    vols = [5000] * 25

    df_entry = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols
    })

    # Create anchor dataframe with lower support targets (150, 140, etc.)
    anchor_dates = pd.date_range("2026-10-01 09:15", periods=30, freq="1h")
    df_anchor = pd.DataFrame({
        "date": anchor_dates,
        "open": [190 - (i * 2.5) for i in range(30)],
        "high": [192 - (i * 2.5) for i in range(30)],
        "low": [185 - (i * 2.5) for i in range(30)],
        "close": [188 - (i * 2.5) for i in range(30)],
        "volume": [10000] * 30
    })

    result = scan_trend_continuation_reentry_bearish(df_entry, df_anchor)
    assert result is not None, "Expected valid D2 Bearish signal for healthy downtrend, got None"
    assert result["Benchmark"] is not None and result["Benchmark"] > 0, "Benchmark must be populated"
    assert result["AnchorFloor"] is not None and result["AnchorFloor"] > 0, "AnchorFloor must be populated"
    assert result["tier"] == 2, f"Tier should be 2 (Core), got {result['tier']}"
    assert result["tier_label"] == "TIER_2_CORE"
    print(f"[PASS] test_genuine_bearish_trend_continuation_accepted: Result={result['Pattern']}, Benchmark={result['Benchmark']}, SL={result['SL']}, Tier={result['tier_label']}")

if __name__ == "__main__":
    test_shreecem_crash_rejected()
    test_genuine_bullish_trend_continuation_accepted()
    test_genuine_bearish_trend_continuation_accepted()
    print("\nALL 3 D2 CONTINUATION TESTS PASSED PERFECTLY!")
