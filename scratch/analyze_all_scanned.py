import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze_all_scanned():
    with open('scratch/archive/scanned_setups_detailed_audit.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    outcomes = {}
    total_gains = []
    winners = []
    losers = []
    pullbacks = []

    for item in data:
        out = item.get('outcome')
        gain = item.get('max_gain_pct')
        if gain is None:
            gain = 0.0
        else:
            gain = float(gain)
        total_gains.append(gain)
        
        outcomes[out] = outcomes.get(out, 0) + 1
        
        entry = (item.get('symbol'), item.get('contract'), item.get('tier'), item.get('pattern'), gain, item.get('current_gain_pct', 0))
        if "PROFIT" in str(out):
            winners.append(entry)
        elif "SL_HIT" in str(out):
            losers.append(entry)
        else:
            pullbacks.append(entry)

    print(f"Total Scanned Setups Audited: {len(data)}")
    print("Outcome Counts:", outcomes)
    print(f"Average Max Gain %: {sum(total_gains)/len(total_gains):.2f}%")
    print(f"Max Gain % Range: {min(total_gains):.2f}% to {max(total_gains):.2f}%")

    print("\n=== TOP 15 WINNERS DETECTED & STAGED BY SCANNER ===")
    for w in sorted(winners, key=lambda x: x[4], reverse=True)[:15]:
        print(f"  {w[0]:<12} | {w[1]:<24} | Tier: {w[2]} | Pat: {w[3]:<12} | Peak Gain: +{w[4]:.1f}% | EOD Gain: {w[5]:+.1f}%")

    print("\n=== LOSERS / SL HITS ===")
    for l in losers:
        print(f"  {l[0]:<12} | {l[1]:<24} | Tier: {l[2]} | Pat: {l[3]:<12} | Peak Gain: +{l[4]:.1f}% | EOD Gain: {l[5]:+.1f}%")

    print("\n=== PULLBACKS / INCUBATING ===")
    for p in pullbacks[:8]:
        print(f"  {p[0]:<12} | {p[1]:<24} | Tier: {p[2]} | Pat: {p[3]:<12} | Peak Gain: +{p[4]:.1f}% | EOD Gain: {p[5]:+.1f}%")

if __name__ == '__main__':
    analyze_all_scanned()
