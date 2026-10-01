import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

def deep_audit():
    # Load detailed audit data
    with open('scratch/archive/scanned_setups_detailed_audit.json', 'r', encoding='utf-8') as f:
        scanned = json.load(f)

    with open('scratch/archive/poovendan_scan_display.json', 'r', encoding='utf-8') as f:
        scan_disp = json.load(f)

    # Let's inspect all CE and PE trades in scanned
    ce_setups = [x for x in scanned if x.get('side') == 'CE' or 'CE' in x.get('contract', '')]
    pe_setups = [x for x in scanned if x.get('side') == 'PE' or 'PE' in x.get('contract', '')]

    print(f"Total Scanned Setups in Detailed Audit: {len(scanned)}")
    print(f"CE Setups: {len(ce_setups)} | PE Setups: {len(pe_setups)}")

    print("\n=== TOP CE SETUPS (Potential vs Outcome) ===")
    for s in sorted(ce_setups, key=lambda x: float(x.get('max_gain_pct', 0) or 0), reverse=True):
        print(f"CE: {s.get('symbol'):<12} | {s.get('contract'):<22} | Pat: {s.get('pattern'):<12} | Tier: {s.get('tier')} | BM: {s.get('benchmark')} | Peak: +{s.get('max_gain_pct'):.1f}% | EOD: {s.get('current_gain_pct'):+.1f}% | Out: {s.get('outcome')}")

    print("\n=== TOP PE SETUPS (Potential vs Outcome) ===")
    for s in sorted(pe_setups, key=lambda x: float(x.get('max_gain_pct', 0) or 0), reverse=True)[:15]:
        print(f"PE: {s.get('symbol'):<12} | {s.get('contract'):<22} | Pat: {s.get('pattern'):<12} | Tier: {s.get('tier')} | BM: {s.get('benchmark')} | Peak: +{s.get('max_gain_pct'):.1f}% | EOD: {s.get('current_gain_pct'):+.1f}% | Out: {s.get('outcome')}")

    # Now let's calculate the stats on staged setups in scan display
    staged = scan_disp.get('staged_trades', [])
    print(f"\nTotal Staged Setups in Scan Display: {len(staged)}")
    staged_ce = [x for x in staged if x.get('side') == 'CE' or 'CE' in x.get('contract', '')]
    staged_pe = [x for x in staged if x.get('side') == 'PE' or 'PE' in x.get('contract', '')]
    print(f"Staged CE: {len(staged_ce)} | Staged PE: {len(staged_pe)}")

if __name__ == '__main__':
    deep_audit()
