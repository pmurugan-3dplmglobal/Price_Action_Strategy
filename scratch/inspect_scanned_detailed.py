import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect_audit():
    with open('scratch/archive/scanned_setups_detailed_audit.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("=== SCANNED SETUPS DETAILED AUDIT (Total: {}) ===".format(len(data)))
    for item in data[:15]:
        sym = item.get('symbol')
        cnt = item.get('contract')
        tier = item.get('tier_badge') or item.get('tier')
        rr = item.get('rr')
        gain_high = item.get('gain_high_pct') or item.get('max_gain_pct') or item.get('gain_high')
        outcome = item.get('outcome') or item.get('status')
        print(f"Symbol: {sym:<12} | Contract: {cnt:<22} | Tier: {tier} | RR: {rr} | Gain High: {gain_high} | Outcome: {outcome}")

if __name__ == '__main__':
    inspect_audit()
