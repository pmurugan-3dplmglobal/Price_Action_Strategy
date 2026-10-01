import json
import os
import glob
import re

def find_actual_trades():
    print("=== SEARCHING ENTIRE WORKSPACE FOR ACTUAL TRADE DATA ===")
    
    # 1. Check watchlist.json in detail
    with open('input/watchlist.json') as f:
        wl = json.load(f)
    print(f"input/watchlist.json: {len(wl)} items")
    
    # 2. Check all json files in scratch/archive
    for fpath in glob.glob('scratch/archive/*.json') + glob.glob('archive/*.*'):
        try:
            with open(fpath, encoding='utf-8') as f:
                content = f.read()
                if any(k in content for k in ['order_id', 'entry_price', 'trade_id', 'realised', 'pnl']):
                    print(f"Found trade keywords in {fpath} ({len(content)} bytes)")
        except Exception:
            pass

    # 3. Check notes/ and docs/
    for fpath in glob.glob('notes/*.*') + glob.glob('docs/*.*'):
        try:
            with open(fpath, encoding='utf-8') as f:
                content = f.read()
                matches = re.findall(r'(₹\s*[-+]?[0-9,]+|\bPnL\b|\bNet P&L\b)', content)
                if matches:
                    print(f"Found PnL references in {fpath}: {len(matches)} matches")
        except Exception:
            pass

if __name__ == '__main__':
    find_actual_trades()
