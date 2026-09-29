import json
import os
import sys
import pandas as pd
from datetime import datetime as dt
import time

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")
from common.trading_core import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

with open("output/monitor/scan_display.json", "r") as f:
    d = json.load(f)

staged = d.get("all_staged_today", [])
print(f"Total Staged Setups in Scan Display: {len(staged)}")

# Collect all contracts to quote
contracts_to_quote = []
for s in staged:
    c = s.get("contract")
    if c:
        exch = "BFO" if ("SENSEX" in c or "BANKEX" in c) else "NFO"
        contracts_to_quote.append(f"{exch}:{c}")
    elif s.get("symbol"):
        contracts_to_quote.append(f"NSE:{s.get('symbol')}")

# Bulk quote in chunks of 50
quotes = {}
chunk_size = 50
for i in range(0, len(contracts_to_quote), chunk_size):
    chunk = contracts_to_quote[i:i+chunk_size]
    try:
        q = kite.quote(chunk)
        quotes.update(q)
    except Exception as e:
        print(f"Quote error chunk {i}: {e}")
    time.sleep(0.3)

print(f"Fetched quotes for {len(quotes)} instruments.")

analysis = []
for s in staged:
    sym = s.get("symbol")
    pattern = s.get("pattern")
    side = s.get("side")
    c = s.get("contract")
    bm = float(s.get("benchmark", 0.0) or 0.0)
    sl = float(s.get("sl", 0.0) or s.get("current_sl", 0.0) or 0.0)
    t1 = float(s.get("t1", 0.0) or 0.0)
    t2 = float(s.get("t2", 0.0) or 0.0)
    tier = s.get("tier_badge") or s.get("tier_label") or "T2"
    
    q_key = f"NFO:{c}" if c else f"NSE:{sym}"
    if q_key not in quotes:
        q_key = f"BFO:{c}"
    q = quotes.get(q_key, {})
    
    ltp = float(q.get("last_price", 0.0))
    ohlc = q.get("ohlc", {})
    high = float(ohlc.get("high", 0.0))
    low = float(ohlc.get("low", 0.0))
    open_p = float(ohlc.get("open", 0.0))
    close_p = float(ohlc.get("close", 0.0))
    
    # In Price Action: Breakout trigger happens when price crosses Benchmark (bm)
    # For Options: bm is option entry trigger price (breakout above Point D).
    # Trigger condition: high >= bm
    triggered = (high >= bm) if (bm > 0 and high > 0) else False
    
    outcome = "NOT_TRIGGERED"
    pct_gain = 0.0
    
    if triggered:
        # Check if Target 1 was reached
        if t1 > 0 and high >= t1:
            outcome = "TARGET_HIT (SUCCESS)"
            pct_gain = ((high - bm) / bm) * 100 if bm > 0 else 0.0
        elif sl > 0 and ltp <= sl:
            outcome = "SL_HIT (FAILURE)"
            pct_gain = ((ltp - bm) / bm) * 100 if bm > 0 else 0.0
        elif high > bm:
            outcome = "TRIGGERED_IN_PROFIT" if ltp >= bm else "PULLBACK"
            pct_gain = ((ltp - bm) / bm) * 100 if bm > 0 else 0.0
        else:
            outcome = "TRIGGERED_FLAT"
    else:
        # Did not trigger breakout
        outcome = "NOT_TRIGGERED (INCUBATING)"
        pct_gain = ((ltp - bm) / bm) * 100 if bm > 0 else 0.0

    analysis.append({
        "symbol": sym,
        "contract": c or sym,
        "pattern": pattern,
        "side": side,
        "tier": tier,
        "benchmark": bm,
        "sl": sl,
        "t1": t1,
        "day_high": high,
        "day_low": low,
        "ltp": ltp,
        "triggered": triggered,
        "outcome": outcome,
        "max_gain_pct": round(((high - bm) / bm * 100), 1) if (bm > 0 and high > 0) else 0.0,
        "current_gain_pct": round(pct_gain, 1)
    })

df_all = pd.DataFrame(analysis)
df_success = df_all[df_all["outcome"].str.contains("TARGET_HIT")]
df_profit = df_all[df_all["outcome"] == "TRIGGERED_IN_PROFIT"]
df_failed = df_all[df_all["outcome"].str.contains("SL_HIT")]
df_incubating = df_all[df_all["outcome"].str.contains("NOT_TRIGGERED")]

print("\n================================================================================")
print(f"                       SCANNED SETUPS SCORECARD (TOTAL: {len(df_all)})")
print("================================================================================")
print(f"1. TARGET HIT (SUCCESS)    : {len(df_success)}")
print(f"2. TRIGGERED IN PROFIT     : {len(df_profit)}")
print(f"3. SL HIT (FAILURE)        : {len(df_failed)}")
print(f"4. NOT TRIGGERED / INCUBATING: {len(df_incubating)}")

print("\n--- 1. SUCCESSFUL SCANNED SETUPS (HIT TARGET 1) ---")
if not df_success.empty:
    print(df_success[["symbol", "contract", "pattern", "tier", "benchmark", "t1", "day_high", "max_gain_pct"]].to_string(index=False))

print("\n--- 2. TRIGGERED IN PROFIT (RUNNERS) ---")
if not df_profit.empty:
    print(df_profit[["symbol", "contract", "pattern", "tier", "benchmark", "ltp", "day_high", "max_gain_pct"]].to_string(index=False))

print("\n--- 3. FAILED SCANNED SETUPS (SL HIT / REVERSED) ---")
if not df_failed.empty:
    print(df_failed[["symbol", "contract", "pattern", "tier", "benchmark", "sl", "ltp", "current_gain_pct"]].to_string(index=False))

print("\n--- 4. NOT TRIGGERED / INCUBATING SETUPS ---")
if not df_incubating.empty:
    print(df_incubating[["symbol", "contract", "pattern", "tier", "benchmark", "day_high", "ltp"]].head(15).to_string(index=False))

with open("scratch/scanned_setups_detailed_audit.json", "w") as out_f:
    json.dump(analysis, out_f, indent=2)

