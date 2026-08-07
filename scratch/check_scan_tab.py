import json
import os

print("=== OPTION SCAN DISPLAY DATA ===")
p1 = 'Trade_Option/output/monitor/scan_display_data.json'
if os.path.exists(p1):
    d = json.load(open(p1))
    print("Keys:", list(d.keys()))
    print("Scanned Signals Count:", len(d.get('scanned_signals', [])))
    print("Active Positions Count:", len(d.get('active_positions', [])))
    print("Scanned Signals:", json.dumps(d.get('scanned_signals', []), indent=2))
else:
    print(p1, "does not exist")

print("\n=== INDEX SCAN DISPLAY DATA ===")
p2 = 'Trade_Option/output/monitor/scan_display_index_data.json'
if os.path.exists(p2):
    d = json.load(open(p2))
    print("Keys:", list(d.keys()))
    print("Scanned Signals Count:", len(d.get('scanned_signals', [])))
    print("Active Positions Count:", len(d.get('active_positions', [])))
    print("Scanned Signals:", json.dumps(d.get('scanned_signals', []), indent=2))
else:
    print(p2, "does not exist")

print("\n=== STOCK SCAN DISPLAY DATA ===")
p3 = 'Trade_Stock/output/monitor/scan_display_data.json'
if os.path.exists(p3):
    d = json.load(open(p3))
    print("Keys:", list(d.keys()))
    print("Scanned Signals Count:", len(d.get('scanned_signals', [])))
    print("Active Positions Count:", len(d.get('active_positions', [])))
    print("Scanned Signals:", json.dumps(d.get('scanned_signals', []), indent=2))
else:
    print(p3, "does not exist")
