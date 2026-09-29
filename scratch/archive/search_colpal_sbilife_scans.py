import json
import os
import glob

# Search scan display files
files = [
    "output/monitor/scan_display.json",
    "output/monitor/scan_display_stock.json",
    "output/monitor/scan_display_stock_bear.json",
    "output/monitor/scan_display_stock_weekly.json",
    "output/monitor/scan_display_stock_weekly_bear.json",
    "output/monitor/pattern_funnel.json"
]

print("=== SCAN DISPLAY SEARCH FOR COLPAL & SBILIFE ===")
for fn in files:
    if os.path.exists(fn):
        try:
            with open(fn, "r") as f:
                d = json.load(f)
            items = d.get("scans", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for item in items:
                sym = item.get("symbol", "")
                cnt = item.get("contract", "")
                if "COLPAL" in sym or "COLPAL" in cnt or "SBILIFE" in sym or "SBILIFE" in cnt:
                    print(f"File: {fn} | Symbol: {sym} | Contract: {cnt}")
                    print(f"  Pattern: {item.get('pattern')}, Timeframe: {item.get('timeframe')}, Side: {item.get('side')}, Tier: {item.get('tier_badge') or item.get('tier_label')}")
                    print(f"  Benchmark: {item.get('benchmark')}, SL: {item.get('sl')}, T1: {item.get('t1')}, T2: {item.get('t2')}")
                    print(f"  RVOL: {item.get('rvol') or item.get('opt_rvol')}, Stage: {item.get('stage')}, Reason: {item.get('reason')}")
                    print("-" * 40)
        except Exception as e:
            print(f"Error reading {fn}: {e}")

# Search recent log entries
print("\n=== LOG ENTRIES FOR COLPAL & SBILIFE ===")
log_files = glob.glob("output/logs/*.log")
for lf in log_files:
    try:
        with open(lf, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for line in lines[-1000:]:
            if "COLPAL" in line or "SBILIFE" in line:
                print(f"[{os.path.basename(lf)}] {line.strip()}")
    except Exception as e:
        pass
