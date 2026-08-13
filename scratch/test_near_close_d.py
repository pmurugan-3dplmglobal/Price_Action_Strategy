import sys
import os
import pandas as pd
from datetime import datetime as dt, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

from timeframe_utils import get_tf_minutes, is_live_candle_near_close
from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish, scan_anchor_bcd_breakout_generic

print("--- Testing Near-Close Timing Helpers ---")
now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
print(f"Current Time: {now_str}")
print(f"30m TF minutes: {get_tf_minutes('30min')}")
print(f"15m TF minutes: {get_tf_minutes('15m')}")
print(f"75m TF minutes: {get_tf_minutes('75min')}")

# Simulated candle 28 minutes into a 30m bar
candle_28m_ago = (dt.now() - timedelta(minutes=28)).strftime("%Y-%m-%d %H:%M:%S")
print(f"28m old candle near close (30m TF): {is_live_candle_near_close(candle_28m_ago, '30min', 0.90)}") # Expected True

# Simulated candle 5 minutes into a 30m bar
candle_5m_ago = (dt.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
print(f"5m old candle near close (30m TF): {is_live_candle_near_close(candle_5m_ago, '30min', 0.90)}") # Expected False

print("All near-close unit tests executed successfully!")
