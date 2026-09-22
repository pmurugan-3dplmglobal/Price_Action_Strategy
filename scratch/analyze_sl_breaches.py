import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

data = json.load(open('scratch/post_entry_audit.json', encoding="utf-8"))
sl_list = data['post_sl']

print(f"=== DETAILED FORENSIC ANALYSIS OF {len(sl_list)} POST-ENTRY SL BREACHES ===\n")

for i, x in enumerate(sl_list, 1):
    drop_pct = ((x['post_low'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    curr_pct = ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    risk_pct = ((x['sl'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    print(f"[{i}] {x['symbol']} - {x['contract']} ({x['side']}) | Pattern: {x['pattern']}")
    print(f"    Tier: {x.get('tier')} ({x.get('tier_label')}) | RR: {x.get('rr')}")
    print(f"    Entry Time: {x.get('entry_time')} | Staged Time: {x.get('staged_time')}")
    print(f"    Entry (BM): {x['entry']:.2f} | SL: {x['sl']:.2f} (Risk: {risk_pct:.1f}%) | Target: {x['t1']:.2f}")
    print(f"    Post-Entry Low: {x['post_low']:.2f} ({drop_pct:.1f}%) | Current LTP: {x['ltp']:.2f} ({curr_pct:+.1f}%)")
    print(f"    Spot Confluence: {x.get('spot_confluence')} | Type: {x.get('spot_confluence_type')}")
    print(f"    Option VWAP: {x.get('vwap')} | Stretch: {x.get('vwap_stretch')}% | Status: {x.get('vwap_status')}")
    print(f"    VCP: {x.get('vcp_tier')} ({x.get('vcp_badge')}) | ATR Ratio: {x.get('atr_ratio')}")
    print("-" * 80)
