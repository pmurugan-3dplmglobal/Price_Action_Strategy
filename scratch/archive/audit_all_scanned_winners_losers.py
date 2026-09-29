import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime as dt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

# 1. Load scan_display.json
scan_file = "output/monitor/scan_display.json"
with open(scan_file, "r") as f:
    scan_data = json.load(f)

# Extract all staged/scanned setups today
setups_raw = scan_data.get("all_staged_today", [])
if not setups_raw:
    setups_raw = scan_data.get("staged_trades", [])

# Deduplicate by contract
unique_setups = {}
for s in setups_raw:
    cnt = s.get("contract")
    if cnt and cnt not in unique_setups:
        unique_setups[cnt] = s

print(f"Total Unique Scanned Candidates to Evaluate: {len(unique_setups)}")

# 2. Batch fetch Kite quotes for all contracts
contracts = list(unique_setups.keys())
batch_size = 50
quotes = {}
for i in range(0, len(contracts), batch_size):
    batch = [f"NFO:{c}" for c in contracts[i:i+batch_size]]
    try:
        q_res = kite.quote(batch)
        for k, v in q_res.items():
            quotes[k.replace("NFO:", "")] = v
    except Exception as e:
        print(f"Error fetching batch {i}: {e}")

# 3. Evaluate Performance for Each Candidate
evaluated = []
for cnt, s in unique_setups.items():
    q = quotes.get(cnt, {})
    ohlc = q.get("ohlc", {})
    day_high = float(ohlc.get("high") or 0.0)
    day_low = float(ohlc.get("low") or 0.0)
    ltp = float(q.get("last_price") or 0.0)

    bm = float(s.get("benchmark") or s.get("entry_spot") or 0.0)
    sl = float(s.get("current_sl") or s.get("sl") or 0.0)
    t1 = float(s.get("t1") or 0.0)
    t2 = float(s.get("t2") or 0.0)
    side = s.get("side", "CE")
    pat = s.get("pattern", "UNKNOWN")
    tf = s.get("timeframe", "30minute")
    tier = s.get("tier_label") or ("T1_GOLD" if s.get("tier") == 1 else "T2_CORE")
    sym = s.get("symbol", cnt)

    if bm <= 0 or day_high <= 0:
        continue

    # MFE (Max Favorable Excursion % from Benchmark)
    mfe_pct = round(((day_high - bm) / bm) * 100.0, 2)
    # MAE (Max Adverse Excursion % from Benchmark)
    mae_pct = round(((day_low - bm) / bm) * 100.0, 2)
    # Close Return % (from Benchmark to LTP)
    close_ret_pct = round(((ltp - bm) / bm) * 100.0, 2)

    # Check Target & SL hits
    t1_hit = (day_high >= t1) if t1 > 0 else False
    sl_hit = (day_low <= sl) if sl > 0 else False

    # Classification
    if mfe_pct >= 25.0 or t1_hit:
        outcome = "BIG_WINNER (25%+ / T1)"
        outcome_grp = "WINNER"
    elif mfe_pct >= 10.0:
        outcome = "MODERATE_WINNER (10-25%)"
        outcome_grp = "WINNER"
    elif close_ret_pct >= 0:
        outcome = "MILD_GAIN_OR_FLAT (0-10%)"
        outcome_grp = "NEUTRAL"
    elif sl_hit or mae_pct <= -20.0:
        outcome = "STOPPED_OUT / HARD_LOSS"
        outcome_grp = "LOSER"
    else:
        outcome = "MINOR_DRAWDOWN (< -10%)"
        outcome_grp = "LOSER"

    evaluated.append({
        "symbol": sym,
        "contract": cnt,
        "side": side,
        "pattern": pat,
        "timeframe": tf,
        "tier": tier,
        "benchmark": bm,
        "sl": sl,
        "t1": t1,
        "day_low": day_low,
        "day_high": day_high,
        "ltp": ltp,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "close_ret_pct": close_ret_pct,
        "t1_hit": t1_hit,
        "sl_hit": sl_hit,
        "outcome": outcome,
        "outcome_grp": outcome_grp
    })

df = pd.DataFrame(evaluated)
print(f"\nSuccessfully Analyzed: {len(df)} Setups")

# Save detailed results to JSON
out_path = "output/monitor/scanned_setups_full_eod_analysis.json"
df.to_json(out_path, orient="records", indent=2)
print(f"Saved full EOD analysis to {out_path}")

# Print Summary Tables
print("\n" + "=" * 90)
print("              🏆 OVERALL WINNER VS LOSER SUMMARY ACROSS ALL SCANNED SETUPS")
print("=" * 90)
outcome_counts = df["outcome"].value_counts()
for k, v in outcome_counts.items():
    pct = (v / len(df)) * 100
    print(f"  {k:30s} : {v:3d} setups ({pct:.1f}%)")

print("\n" + "-" * 90)
print("              📐 PERFORMANCE BREAKDOWN BY PATTERN CATEGORY")
print("-" * 90)
pat_summary = df.groupby("pattern").agg(
    total=("contract", "count"),
    winners=("outcome_grp", lambda x: (x == "WINNER").sum()),
    losers=("outcome_grp", lambda x: (x == "LOSER").sum()),
    avg_mfe=("mfe_pct", "mean"),
    max_mfe=("mfe_pct", "max"),
    t1_hits=("t1_hit", "sum")
).reset_index()
pat_summary["win_rate_pct"] = (pat_summary["winners"] / pat_summary["total"]) * 100.0
pat_summary = pat_summary.sort_values(by="win_rate_pct", ascending=False)
print(pat_summary.to_string(index=False))

print("\n" + "-" * 90)
print("              📊 PERFORMANCE BREAKDOWN BY SIDE (CE vs PE)")
print("-" * 90)
side_summary = df.groupby("side").agg(
    total=("contract", "count"),
    winners=("outcome_grp", lambda x: (x == "WINNER").sum()),
    losers=("outcome_grp", lambda x: (x == "LOSER").sum()),
    avg_mfe=("mfe_pct", "mean"),
    max_mfe=("mfe_pct", "max")
).reset_index()
side_summary["win_rate_pct"] = (side_summary["winners"] / side_summary["total"]) * 100.0
print(side_summary.to_string(index=False))

print("\n" + "-" * 90)
print("              🥇 TOP 15 SCANNED WINNERS OF THE DAY")
print("-" * 90)
top_winners = df.sort_values(by="mfe_pct", ascending=False).head(15)
print(top_winners[["symbol", "contract", "side", "pattern", "benchmark", "day_high", "ltp", "mfe_pct", "outcome"]].to_string(index=False))

print("\n" + "-" * 90)
print("              ❌ TOP SCANNED LOSERS / DRAWDOWN SETUPS OF THE DAY")
print("-" * 90)
top_losers = df.sort_values(by="close_ret_pct", ascending=True).head(10)
print(top_losers[["symbol", "contract", "side", "pattern", "benchmark", "day_low", "ltp", "close_ret_pct", "outcome"]].to_string(index=False))
