import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("output/monitor/scan_display.json", "r", encoding="utf-8") as f:
    sd = json.load(f)

for st in sd.get("staged_trades", []):
    if "ADANIENT" in str(st):
        print("STAGED TRADE ADANIENT:")
        print(json.dumps(st, indent=2))

for al in sd.get("active_live", []):
    if "ADANIENT" in str(al):
        print("ACTIVE LIVE ADANIENT:")
        print(json.dumps(al, indent=2))
