import os, sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

print("=== SEARCHING INFY ENTRY IN LOGS ===")
with open('output/logs/bull_nifty50_scanner.log', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if '2026-09-29' in line and 'INFY' in line and any(w in line for w in ['ANCHOR', 'TRIGGER', 'WINNER', 'EXECUTE', 'BUY', 'ORDER', 'TIER', 'BREAKOUT']):
            print(line.strip().encode('ascii', errors='backslashreplace').decode('ascii'))

print("\n=== SEARCHING SBIN ENTRY IN LOGS (Sep 28) ===")
with open('output/logs/bull_nifty50_scanner.log', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if '2026-09-28' in line and 'SBIN' in line and any(w in line for w in ['ANCHOR', 'TRIGGER', 'WINNER', 'EXECUTE', 'BUY', 'ORDER', 'TIER', 'BREAKOUT']):
            print(line.strip().encode('ascii', errors='backslashreplace').decode('ascii'))
