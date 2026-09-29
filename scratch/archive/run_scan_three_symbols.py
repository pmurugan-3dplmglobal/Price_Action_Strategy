import os
import sys
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.resolve import scan_symbol
from common.registries import sync_stock_tokens, STOCK_REGISTRY

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

sync_stock_tokens(kite)

to_entry = datetime.now()
from_entry = to_entry - timedelta(days=10)
to_anchor = to_entry
from_anchor = to_entry - timedelta(days=20)

for sym in ["COLPAL", "SBILIFE", "MOTHERSON"]:
    cfg = STOCK_REGISTRY.get(sym, {})
    if not cfg:
        print(f"Config not found for {sym}")
        continue
    print("=" * 70)
    print(f"RUNNING SCAN_SYMBOL ON {sym} (Token: {cfg.get('token')})")
    print("=" * 70)
    try:
        candidates = scan_symbol(
            kite=kite,
            symbol=sym,
            config=cfg,
            from_entry=from_entry,
            to_entry=to_entry,
            from_anchor=from_anchor,
            to_anchor=to_anchor,
            timeframe_entry="15minute",
            timeframe_anchor="30minute"
        )
        print(f"Candidates returned: {len(candidates) if candidates else 0}")
        if candidates:
            for c in candidates:
                print(f"  {c.get('contract')} | Pattern: {c.get('pattern')} | Side: {c.get('side')} | Tier: {c.get('tier_badge')} {c.get('tier_label')}")
                print(f"    Entry/Close: {c.get('entry_spot')} | SL: {c.get('current_sl')} | T1: {c.get('t1')} | RR: {c.get('rr')}")
                print(f"    RVOL: {c.get('rvol')} | Spot Entry: {c.get('spot_entry')} | Benchmark: {c.get('benchmark')}")
    except Exception as e:
        print(f"Error scanning {sym}: {e}")
