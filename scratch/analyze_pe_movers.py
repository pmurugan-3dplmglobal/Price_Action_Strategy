import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze_pe_movers():
    # 1. Scanned detailed audit
    with open('scratch/archive/scanned_setups_detailed_audit.json', 'r', encoding='utf-8') as f:
        scanned_detailed = json.load(f)

    # 2. Comparative study
    with open('scratch/archive/comparative_study_winners_vs_losers.json', 'r', encoding='utf-8') as f:
        comp_study = json.load(f)

    # 3. Poovendan scan display
    with open('scratch/archive/poovendan_scan_display.json', 'r', encoding='utf-8') as f:
        scan_display = json.load(f)

    print("=== PE WINNERS & LEADERS IN SCANNED SETUPS AUDIT ===")
    pe_detailed = [x for x in scanned_detailed if x.get('side') == 'PE' or 'PE' in x.get('contract', '')]
    pe_winners = sorted(pe_detailed, key=lambda x: float(x.get('max_gain_pct', 0) or 0), reverse=True)

    for item in pe_winners:
        sym = item.get('symbol')
        cnt = item.get('contract')
        pat = item.get('pattern')
        tier = item.get('tier')
        bm = item.get('benchmark')
        sl = item.get('sl')
        t1 = item.get('t1')
        dh = item.get('day_high')
        dl = item.get('day_low')
        max_gain = item.get('max_gain_pct')
        eod_gain = item.get('current_gain_pct')
        out = item.get('outcome')
        print(f"{sym:<12} | {cnt:<24} | Pat: {pat:<12} | Tier: {tier} | BM: {bm:<6} | SL: {sl:<6} | Peak: +{max_gain:>5.1f}% | EOD: {eod_gain:>5.1f}% | DayHi: {dh} | DayLo: {dl} | {out}")

    print("\n=== PE WINNERS IN COMPARATIVE STUDY ===")
    comp_pe = [x for x in comp_study if x.get('side') == 'PE' or 'PE' in x.get('contract', '')]
    for item in comp_pe:
        print(f"{item.get('symbol'):<12} | {item.get('contract'):<24} | Pat: {item.get('pattern'):<12} | EntryTime: {item.get('entry_time')} | AnchorTime: {item.get('anchor_time')} | BM: {item.get('benchmark')} | SL: {item.get('sl')} | RR: {item.get('rr')} | GainHigh: +{item.get('gain_high'):.1f}% | CurrGain: {item.get('curr_gain'):.1f}% | Group: {item.get('group')}")

    print("\n=== PE CANDIDATES IN POOVENDAN SCAN DISPLAY (Total: {}) ===".format(len(scan_display.get('staged_trades', []))))
    staged_pe = [x for x in scan_display.get('staged_trades', []) if x.get('side') == 'PE' or 'PE' in x.get('contract', '')]
    print(f"Total Staged PE Setups: {len(staged_pe)}")
    for item in sorted(staged_pe, key=lambda x: float(x.get('rr', 0) or 0), reverse=True)[:15]:
        print(f"{item.get('symbol'):<12} | {item.get('contract'):<24} | Tier: {item.get('tier_badge')} | RR: {item.get('rr')} | Pat: {item.get('pattern')} | TF: {item.get('timeframe')} | BM: {item.get('benchmark')} | SL: {item.get('anchor_floor')}")

if __name__ == '__main__':
    analyze_pe_movers()
