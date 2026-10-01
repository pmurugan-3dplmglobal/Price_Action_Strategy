import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze():
    with open('scratch/replay_22_sessions_results.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = len(data)
    ce_setups = [s for s in data if s['side'] == 'CE']
    pe_setups = [s for s in data if s['side'] == 'PE']

    print(f"=== 22-SESSION REPLAY STATISTICAL MASTER ANALYSIS (1 MONTH) ===")
    print(f"Total Setups Evaluated: {total}")
    print(f"CE (Bullish Breakouts): {len(ce_setups)} ({len(ce_setups)/total*100:.1f}%)")
    print(f"PE (Bearish Breakdowns): {len(pe_setups)} ({len(pe_setups)/total*100:.1f}%)")

    # Global Win Rate (Target T1 Hit)
    t1_hits = [s for s in data if s['t1_hit']]
    overall_win_rate = len(t1_hits) / total * 100
    print(f"\nOverall Target T1 Hit Rate (Win Rate): {len(t1_hits)} / {total} ({overall_win_rate:.2f}%)")

    # By Side
    ce_t1 = [s for s in ce_setups if s['t1_hit']]
    pe_t1 = [s for s in pe_setups if s['t1_hit']]
    print(f"  CE Win Rate (T1 Hit): {len(ce_t1)} / {len(ce_setups)} ({len(ce_t1)/len(ce_setups)*100:.2f}%)")
    print(f"  PE Win Rate (T1 Hit): {len(pe_t1)} / {len(pe_setups)} ({len(pe_t1)/len(pe_setups)*100:.2f}%)")

    # Multibaggers (+50%+ option peak gain)
    multibaggers = [s for s in data if s['opt_peak_gain_pct'] >= 50.0]
    doublers = [s for s in data if s['opt_peak_gain_pct'] >= 100.0]
    print(f"\nMultibagger Setups (Option Gain >= +50%): {len(multibaggers)} ({len(multibaggers)/total*100:.1f}%)")
    print(f"100%+ Doublers (Option Gain >= +100%): {len(doublers)} ({len(doublers)/total*100:.1f}%)")

    # SPOT_SL_GUARD Analysis
    # How many times did spot wick touch SL, but 15m candle close held, allowing the trade to reach T1?
    saved_by_guard = [s for s in data if s.get('saved_by_spot_guard')]
    print(f"\nPremature Shakeouts SAVED by SPOT_SL_GUARD: {len(saved_by_guard)} setups!")
    print(f"  (These setups would have been stopped out by option-tick noise, but went on to hit Target T1!)")

    # Session by Session Breakdown
    sessions = sorted(list(set(s['date'] for s in data)))
    print(f"\n=== SESSION-BY-SESSION WIN RATES ACROSS ALL {len(sessions)} SESSIONS ===")
    print(f"{'Date':<12} | {'Total':<6} | {'CE Hits':<10} | {'PE Hits':<10} | {'Win Rate %':<12} | {'Multibaggers':<12}")
    print("-" * 75)
    for sess in sessions:
        s_data = [s for s in data if s['date'] == sess]
        s_t1 = [s for s in s_data if s['t1_hit']]
        s_ce = [s for s in s_data if s['side'] == 'CE']
        s_pe = [s for s in s_data if s['side'] == 'PE']
        s_ce_hit = [s for s in s_ce if s['t1_hit']]
        s_pe_hit = [s for s in s_pe if s['t1_hit']]
        s_multi = [s for s in s_data if s['opt_peak_gain_pct'] >= 50.0]
        wr = len(s_t1) / len(s_data) * 100 if s_data else 0
        print(f"{sess:<12} | {len(s_data):<6} | {len(s_ce_hit)}/{len(s_ce):<7} | {len(s_pe_hit)}/{len(s_pe):<7} | {wr:>6.1f}%      | {len(s_multi):<12}")

    # Top 20 Best Performing Setups of the Month
    print("\n=== TOP 20 RUNAWAY EXPLOSIVE SETUPS OF THE MONTH ===")
    sorted_gains = sorted(data, key=lambda x: x['opt_peak_gain_pct'], reverse=True)
    for s in sorted_gains[:20]:
        print(f"{s['date']} | {s['symbol']:<12} | {s['side']:<3} | Pat: {s['pattern']:<18} | Entry: {s['entry']:<7} | MFE: +{s['spot_mfe_pct']:>5.2f}% | Opt Gain: +{s['opt_peak_gain_pct']:>5.1f}% | T1 Hit: {s['t1_hit']}")

if __name__ == '__main__':
    analyze()
