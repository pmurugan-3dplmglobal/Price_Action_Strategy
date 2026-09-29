import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

data = json.load(open("scratch/comparative_study_winners_vs_losers.json", encoding="utf-8"))

print("=" * 115)
print(f"{'GROUP':<15} {'SYM':<11} {'CONTRACT':<20} {'PAT':<12} {'RR':<5} {'VCP':<6} {'STRCH%':<7} {'VOL':<8} {'HIGH%':<8} {'NOW%':<8}")
print("=" * 115)

for r in data:
    grp = r['group']
    sym = r['symbol']
    cntr = r['contract']
    pat = r['pattern'] or '-'
    rr = f"{r['rr']:.1f}" if r['rr'] else '-'
    vcp = f"{r['atr_ratio']:.2f}" if r['atr_ratio'] is not None else '-'
    stretch = f"{r['stretch']:.1f}%" if r['stretch'] is not None else '-'
    vol = f"{r['volume']:,}" if r['volume'] else '-'
    high_gain = f"+{r['gain_high']:.1f}%"
    curr_gain = f"{r['curr_gain']:+.1f}%"
    
    print(f"{grp:<15} {sym:<11} {cntr:<20} {pat:<12} {rr:<5} {vcp:<6} {stretch:<7} {vol:<8} {high_gain:<8} {curr_gain:<8}")

print("-" * 115)

# Detailed analysis
print("\n" + "=" * 80)
print("DEEP COMPARISON: WINNERS VS TAKEN LOSERS / STAGNANT")
print("=" * 80)
for r in data:
    print(f"\n[{r['group']}] {r['symbol']} ({r['contract']}):")
    print(f"  • Pattern: {r['pattern']} | Tier: {r['tier']} | Waves: {r['waves']} | Entry Time: {r['entry_time']}")
    print(f"  • Entry (BM): {r['benchmark']} | SL: {r['sl']} (Risk: -{r['risk_pct']:.1f}%) | T1: {r['t1']} (+{r['t1_pct']:.1f}%) | RR: {r['rr']}")
    print(f"  • VCP ATR Ratio: {r['atr_ratio']} ({r['vcp_tier']}) | Is Squeeze: {r['is_squeeze']}")
    print(f"  • Option VWAP: {r['opt_vwap']} | Stretch: {r['stretch']}% | Spot Confluence: {r['spot_confluence']} ({r['spot_confluence_type']})")
    print(f"  • Volume: {r['volume']:,} | Day High: {r['day_high']} ({r['gain_high']:+.1f}%) | LTP: {r['ltp']} ({r['curr_gain']:+.1f}%)")
