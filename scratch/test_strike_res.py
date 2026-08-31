import os
import sys

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
import pandas as pd

from resolve import resolve_option_strikes
from position_monitor import _get_nfo_cache

df_nfo = _get_nfo_cache()
print(f"NFO Cache size: {len(df_nfo)}")
if not df_nfo.empty:
    print(f"Columns: {list(df_nfo.columns)}")
    print(f"Unique names sample: {df_nfo['name'].dropna().unique()[:20]}")

for sym, spot, step in [("NIFTY", 24500, 50), ("BANKNIFTY", 51000, 100), ("SENSEX", 80000, 100)]:
    ce = resolve_option_strikes(df_nfo, sym, spot, step, "CE", 1)
    pe = resolve_option_strikes(df_nfo, sym, spot, step, "PE", 1)
    print(f"\n{sym} (Spot: {spot}, Step: {step}):")
    print(f"  CE strikes ({len(ce)}): {[c['tradingsymbol'] for c in ce]}")
    print(f"  PE strikes ({len(pe)}): {[p['tradingsymbol'] for p in pe]}")
