import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze():
    with open('scratch/sim_case1_results.json') as f:
        c1 = json.load(f)
    with open('scratch/sim_case2_results.json') as f:
        c2 = json.load(f)

    print("=== QUANTITATIVE COMPARISON: CASE 1 vs. CASE 2 ===")
    print(f"Case 1 (Anchor 30m / Entry 15m): {len(c1)} Trades Evaluated")
    print(f"Case 2 (Anchor 30m / Entry 30m): {len(c2)} Trades Evaluated\n")

    # Win Rates (Intraday T1 Hit)
    c1_t1 = [t for t in c1 if t['intra_t1']]
    c2_t1 = [t for t in c2 if t['intra_t1']]
    c1_sl = [t for t in c1 if t['intra_sl']]
    c2_sl = [t for t in c2 if t['intra_sl']]

    c1_wr = len(c1_t1) / len(c1) * 100
    c2_wr = len(c2_t1) / len(c2) * 100
    c1_slr = len(c1_sl) / len(c1) * 100
    c2_slr = len(c2_sl) / len(c2) * 100

    print("1. WIN RATE & SL HIT RATE (Intraday):")
    print(f"   CASE 1 (Anchor 30m / Entry 15m): Target T1 Win Rate = {c1_wr:.2f}% | SL Hit Rate = {c1_slr:.2f}%")
    print(f"   CASE 2 (Anchor 30m / Entry 30m): Target T1 Win Rate = {c2_wr:.2f}% | SL Hit Rate = {c2_slr:.2f}%")

    # Average Risk % and MFE %
    c1_avg_risk = sum(t['risk_pct'] for t in c1) / len(c1)
    c2_avg_risk = sum(t['risk_pct'] for t in c2) / len(c2)
    c1_avg_mfe = sum(t['intra_mfe'] for t in c1) / len(c1)
    c2_avg_mfe = sum(t['intra_mfe'] for t in c2) / len(c2)
    c1_avg_opt_mfe = sum(t['opt_intra_mfe'] for t in c1) / len(c1)
    c2_avg_opt_mfe = sum(t['opt_intra_mfe'] for t in c2) / len(c2)

    print("\n2. RISK & RUNNER EXPANSION (MFE):")
    print(f"   CASE 1: Avg Risk = {c1_avg_risk:.2f}% | Avg Spot MFE = +{c1_avg_mfe:.2f}% | Avg Opt Peak = +{c1_avg_opt_mfe:.1f}%")
    print(f"   CASE 2: Avg Risk = {c2_avg_risk:.2f}% | Avg Spot MFE = +{c2_avg_mfe:.2f}% | Avg Opt Peak = +{c2_avg_opt_mfe:.1f}%")

    # Intraday EOD P&L (Each Day Closing)
    c1_avg_pnl = sum(t['intra_pnl'] for t in c1) / len(c1)
    c2_avg_pnl = sum(t['intra_pnl'] for t in c2) / len(c2)
    print("\n3. EACH DAY CLOSING (Square-Off at 15:15 PM EOD):")
    print(f"   CASE 1 Intraday EOD Spot Return: {c1_avg_pnl:+.2f}%")
    print(f"   CASE 2 Intraday EOD Spot Return: {c2_avg_pnl:+.2f}%")

    # Multi-Bagger Frequency
    c1_multi = [t for t in c1 if t['opt_intra_mfe'] >= 50.0]
    c2_multi = [t for t in c2 if t['opt_intra_mfe'] >= 50.0]
    print("\n4. MULTI-BAGGER RUNNERS (>= +50% Option Expansion):")
    print(f"   CASE 1: {len(c1_multi)} Multi-Baggers ({len(c1_multi)/len(c1)*100:.2f}%)")
    print(f"   CASE 2: {len(c2_multi)} Multi-Baggers ({len(c2_multi)/len(c2)*100:.2f}%)")

if __name__ == '__main__':
    analyze()
