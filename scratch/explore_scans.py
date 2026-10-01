import json
import os

def explore_scans():
    print("=== EXPLORING SCAN FILES ===")
    
    # 1. scanned_setups_analysis.json
    if os.path.exists('scratch/archive/scanned_setups_analysis.json'):
        with open('scratch/archive/scanned_setups_analysis.json', 'r', encoding='utf-8') as f:
            d = json.load(f)
            print("scanned_setups_analysis keys:", list(d.keys()))
            print("total:", d.get('total'))
            print("counts:", d.get('counts'))
            print("t1_hit count:", len(d.get('t1_hit', [])))
            print("runaway_08_t1 count:", len(d.get('runaway_08_t1', [])))
            for item in d.get('t1_hit', [])[:5]:
                print("  Sample T1 Hit:", item.get('symbol'), item.get('contract'), item.get('gain_high_pct'))

    # 2. post_entry_audit.json
    if os.path.exists('scratch/archive/post_entry_audit.json'):
        with open('scratch/archive/post_entry_audit.json', 'r', encoding='utf-8') as f:
            d = json.load(f)
            print("\npost_entry_audit keys:", list(d.keys()))
            for k in d.keys():
                print(f"  {k}: {len(d[k])} items")
            for item in d.get('post_t1', [])[:3]:
                print("  Sample post_t1:", item.get('symbol'), item.get('contract'), item.get('entry_p'), item.get('t1_p'), item.get('max_gain_pct'))

    # 3. poovendan_scan_display.json
    if os.path.exists('scratch/archive/poovendan_scan_display.json'):
        with open('scratch/archive/poovendan_scan_display.json', 'r', encoding='utf-8') as f:
            d = json.load(f)
            print("\npoovendan_scan_display keys:", list(d.keys()))
            print("staged_trades count:", len(d.get('staged_trades', [])))
            print("all_staged_today count:", len(d.get('all_staged_today', [])))
            for item in d.get('staged_trades', [])[:5]:
                print("  Staged:", item.get('symbol'), item.get('contract'), item.get('tier_badge'), item.get('pattern'), item.get('rr'))

if __name__ == '__main__':
    explore_scans()
