import json
import os
import sys
import pandas as pd
from datetime import datetime as dt

sys.path.insert(0, ".")
from common.trading_core import (
    load_kite_session,
    fetch_and_resample_candles,
    STOCK_REGISTRY,
    INDEX_REGISTRY
)
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

scan_file = "output/monitor/scan_display.json"
with open(scan_file, "r") as f:
    scan_data = json.load(f)

staged = scan_data.get("all_staged_today", [])
print(f"Total staged setups to evaluate: {len(staged)}")

results = []

for item in staged:
    sym = item.get("symbol")
    pattern = item.get("pattern")
    tf = item.get("timeframe", "30minute")
    side = item.get("side", "CE")
    direction = item.get("direction", "BULL")
    bm = float(item.get("benchmark", 0.0) or 0.0)
    sl = float(item.get("sl", 0.0) or item.get("current_sl", 0.0) or 0.0)
    t1 = float(item.get("t1", 0.0) or 0.0)
    tier = item.get("tier_badge", "T2")
    token = item.get("spot_token")
    
    if not token and sym in STOCK_REGISTRY:
        token = STOCK_REGISTRY[sym].get("token")
    if not token and sym in INDEX_REGISTRY:
        token = INDEX_REGISTRY[sym].get("token")
        
    if not token or bm <= 0:
        continue

    # Fetch today's 5m/15m candles
    try:
        from_dt = dt.now().strftime("%Y-%m-%d 09:15:00")
        to_dt = dt.now().strftime("%Y-%m-%d 15:30:00")
        candles = kite.historical_data(token, from_dt, to_dt, "5minute")
        if not candles:
            continue
        df = pd.DataFrame(candles)
        day_high = df["high"].max()
        day_low = df["low"].min()
        day_close = df["close"].iloc[-1]
        
        # Check trigger & outcome based on side / direction
        # Note: In Price Action Strategy, benchmark is on Option contract or Spot?
        # Let's check if benchmark is option premium or spot price!
        # If bm < 500 and stock is > 1000, bm is OPTION premium!
        # If bm > 500 and stock is > 1000, bm is SPOT price!
        is_opt_bm = (bm < 500 and df["close"].iloc[-1] > 1000) or ("strike" in item and bm < float(item.get("strike", 9999)))
        
        results.append({
            "symbol": sym,
            "pattern": pattern,
            "timeframe": tf,
            "side": side,
            "direction": direction,
            "tier": tier,
            "benchmark": bm,
            "sl": sl,
            "t1": t1,
            "is_opt_bm": is_opt_bm,
            "spot_high": day_high,
            "spot_low": day_low,
            "spot_close": day_close,
            "rr": item.get("rr", 0.0),
            "created_at": item.get("created_at") or item.get("entry_time") or ""
        })
    except Exception as e:
        print(f"Error evaluating {sym}: {e}")

df_res = pd.DataFrame(results)
print(f"Successfully processed {len(df_res)} candidates.")
with open("scratch/scanned_candidates_processed.json", "w") as out_f:
    json.dump(results, out_f, indent=2)

print("\nSample processed setups:")
print(df_res[["symbol", "pattern", "side", "tier", "benchmark", "sl", "t1", "spot_close"]].head(20).to_string())
