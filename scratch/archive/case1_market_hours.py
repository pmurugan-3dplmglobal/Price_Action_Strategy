import sys
import os
import re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

symbols = ["VMM", "VBL", "BSE"]
print("=== LOGS DURING MARKET HOURS (09:15 to 15:30) FOR VMM, VBL, BSE ===")

market_re = re.compile(r"2026-09-29 (09:[1-5][0-9]|1[0-4]:[0-9]{2}|15:[0-2][0-9]|15:30)")

with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if any(s in line for s in symbols) and market_re.search(line):
            if "PRIORITY SCAN ORDER" not in line:
                print(line.strip())
