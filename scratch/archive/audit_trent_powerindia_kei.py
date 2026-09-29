import os
import json
import glob
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

files = [
    "output/logs/bull_nifty50_scanner.log",
    "output/monitor/scan_display.json",
    "scratch/scanned_setups_detailed_audit.json"
]

targets = ["TRENT", "POWERINDIA", "KEI"]

print("=== 1. SCAN DISPLAY METRICS FOR TARGETS ===")
with open("output/monitor/scan_display.json", "r") as f:
    d = json.load(f)

for item in d.get("all_staged_today", []):
    sym = item.get("symbol")
    if sym in targets:
        print(f"\n--- {sym} ---")
        for k in ["symbol", "contract", "pattern", "timeframe", "side", "tier_badge", "tier_label", "confidence_score", "benchmark", "sl", "t1", "t2", "t3", "rr", "spot_token", "option_token", "created_at", "entry_time"]:
            print(f"  {k}: {item.get(k)}")

print("\n=== 2. SCANNER LOG AUDIT FOR TARGETS ===")
log_file = "output/logs/bull_nifty50_scanner.log"
if os.path.exists(log_file):
    with open(log_file, "r", errors="ignore") as f:
        for line in f:
            for t in targets:
                if t in line:
                    # Filter out spammy lines if any, or print key decision lines
                    if any(kw in line for kw in ["REJECT", "GATE", "PORTFOLIO", "VIX", "DISPATCH", "SURGE", "MAX_", "TIER", "ANCHOR FORMED", "DEBIT SPREAD"]):
                        print(f"[{t}] {line.strip()}")
