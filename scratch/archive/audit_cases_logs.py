import re
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

symbols = ["MANKIND", "VMM", "VBL", "BSE", "ADANIENT", "GLENMARK", "POLICYBZR", "KFINTECH", "HAL"]
log_file = "output/logs/bull_nifty50_scanner.log"

print("Searching log for specific patterns and events on 2026-09-29...")

results = {s: [] for s in symbols}

with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        # Only lines from today or yesterday
        if "2026-09-29" in line or "2026-09-28" in line:
            for s in symbols:
                if re.search(r'\b' + s + r'\b', line):
                    results[s].append(line.strip())

with open("scratch/log_cases_summary.txt", "w", encoding="utf-8") as out:
    for s in symbols:
        lines = results[s]
        out.write(f"\n==========================================\n")
        out.write(f"SYMBOL: {s} (Total matches on 28/29: {len(lines)})\n")
        out.write(f"==========================================\n")
        interesting = []
        for l in lines:
            if any(w in l for w in ["[ANCHOR", "PROMOT", "Category", "DISPATCH", "ORDER", "STALE", "REJECT", "SWAP", "STAGE", "80% T1", "Harami", "Engulfing", "Hammer", "Sweep", "anti-chase", "vwap", "VWAP", "HOLD", "funnel", "SURGE", "PRIORITY"]):
                interesting.append(l)
        out.write(f"Interesting log lines: {len(interesting)}\n")
        for l in interesting:
            out.write(f"  {l}\n")

print("Done! Written to scratch/log_cases_summary.txt")
