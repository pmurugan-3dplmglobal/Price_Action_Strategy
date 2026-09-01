import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import csv
from common import paths

today_str = "2026-08-31"

print("=" * 80)
print(f"COMPLETE JOURNAL CHRONOLOGY FOR TODAY ({today_str})")
print("=" * 80)

if os.path.exists(paths.TRADE_JOURNAL_CSV):
    with open(paths.TRADE_JOURNAL_CSV, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader, None)
        print(f"Header: {header}\n")
        rows = [r for r in reader if r and r[0].startswith(today_str)]
        
        # Group by symbol/contract
        by_symbol = {}
        for r in rows:
            sym = r[1]
            if sym not in by_symbol:
                by_symbol[sym] = []
            by_symbol[sym].append(r)
            
        print(f"Unique symbols traded / tracked today: {len(by_symbol)}\n")
        for sym, s_rows in by_symbol.items():
            print(f"=== {sym} ({len(s_rows)} events) ===")
            for r in s_rows:
                ts, s, pattern, tf, evt, status, entry, sl, tgt, rr, remarks, pnl = (r + [""] * 12)[:12]
                print(f"  [{ts}] Event: {evt:12s} | Status: {status:8s} | Pattern: {pattern:15s} | Entry: {entry:8s} | SL: {sl:8s} | Tgt: {tgt:8s} | PnL: {pnl:8s}")
                if remarks:
                    print(f"       Remarks: {remarks}")
            print()
