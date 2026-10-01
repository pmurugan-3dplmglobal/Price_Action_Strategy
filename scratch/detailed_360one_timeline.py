import json
from datetime import datetime

def run():
    with open('scratch/360one_spot_candles.json') as f:
        spot = json.load(f)
    with open('scratch/360one_opt_candles.json') as f:
        opt = json.load(f)
        
    print("=== 360ONE SPOT TIMELINE (Today Oct 1) ===")
    for c in spot:
        dt = c[0]
        if "2026-10-01" in dt or "2024-10-01" in dt or "2025-10-01" in dt or dt.startswith("2026"):
            print(f"{dt[11:16]} | Spot Open: {c[1]:<7.2f} High: {c[2]:<7.2f} Low: {c[3]:<7.2f} Close: {c[4]:<7.2f} Vol: {c[5]}")

    print("\n=== 360ONE 1040 CE TIMELINE (Today) ===")
    for c in opt:
        dt = c[0]
        print(f"{dt[11:16]} | Opt Open: {c[1]:<6.2f} High: {c[2]:<6.2f} Low: {c[3]:<6.2f} Close: {c[4]:<6.2f} Vol: {c[5]}")

if __name__ == '__main__':
    run()
