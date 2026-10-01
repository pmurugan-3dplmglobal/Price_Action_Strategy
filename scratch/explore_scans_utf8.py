import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

def explore():
    with open('scratch/archive/poovendan_scan_display.json', 'r', encoding='utf-8') as f:
        p_scan = json.load(f)
    print("=== POOVENDAN SCAN DISPLAY ===")
    print("Date:", p_scan.get('date'), "Timestamp:", p_scan.get('timestamp'))
    staged = p_scan.get('staged_trades', [])
    print(f"Total Staged: {len(staged)}")
    
    # Show tier distribution
    tiers = {}
    patterns = {}
    for s in staged:
        tb = s.get('tier_badge', 'UNKNOWN')
        tiers[tb] = tiers.get(tb, 0) + 1
        pat = s.get('pattern', 'UNKNOWN')
        patterns[pat] = patterns.get(pat, 0) + 1
        
    print("Tiers:", tiers)
    print("Top Patterns:", sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5])

    print("\nTop 10 Staged Candidates by R:R:")
    sorted_staged = sorted(staged, key=lambda x: x.get('rr', 0) or 0, reverse=True)
    for s in sorted_staged[:10]:
        print(f"  {s.get('symbol'):<12} | {s.get('contract'):<22} | Tier: {s.get('tier_badge')} | RR: {s.get('rr'):<5} | Pat: {s.get('pattern')} | TF: {s.get('timeframe')}")

    # Check today_broker_full_dump.json
    if os.path.exists('scratch/archive/today_broker_full_dump.json'):
        with open('scratch/archive/today_broker_full_dump.json', 'r', encoding='utf-8') as f:
            b_dump = json.load(f)
            print("\n=== TODAY BROKER FULL DUMP ===")
            print("Orders:", len(b_dump.get('orders', [])))
            print("Net Positions:", len(b_dump.get('net_positions', [])))
            for p in b_dump.get('net_positions', [])[:5]:
                print("  Pos:", p.get('tradingsymbol'), "Qty:", p.get('quantity'), "BuyAvg:", p.get('buy_price'), "SellAvg:", p.get('sell_price'), "PnL:", p.get('pnl'))

if __name__ == '__main__':
    explore()
