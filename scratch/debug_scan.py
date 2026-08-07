import sys
import os
import logging
from datetime import datetime as dt, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

sys.path.append('common')
sys.path.append('Trade_Option')

from trading_core import load_kite_session, STOCK_REGISTRY, fetch_and_resample_candles
from kiteconnect import KiteConnect
import stock_options_trade_engine

print("=" * 80)
print("             STARTING DEEP DIAGNOSTIC SCAN RUNNER")
print("=" * 80)

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

print(f"Loaded Kite Session for API Key: {ak[:4]}... Token: {at[:6]}...")
print(f"Scanning {len(STOCK_REGISTRY)} Nifty 50 stocks...")

results = stock_options_trade_engine.run_scan_cycle(kite)
print("\n" + "=" * 80)
print(f"Final run_scan_cycle returned {len(results or [])} staged trade(s):")
for r in (results or []):
    print(f"  MATCH: {r.get('contract')} | Pattern: {r.get('pattern')} | Side: {r.get('side')} | RR: {r.get('rr')} | Entry: {r.get('entry_spot')} | SL: {r.get('current_sl')} | T1: {r.get('t1')}")
print("=" * 80)

# Read display file content
disp_path = os.path.join("Trade_Option", "output", "monitor", "scan_display_data.json")
if os.path.exists(disp_path):
    with open(disp_path, "r", encoding="utf-8") as fh:
        import json
        d = json.load(fh)
    staged = d.get("staged_trades", [])
    active = d.get("active_live", [])
    carry = d.get("carry_forward", [])
    print(f"\nContents of {disp_path}:")
    print(f"  Date: {d.get('date')} | Timestamp: {d.get('timestamp')}")
    print(f"  Staged Trades Count: {len(staged)}")
    print(f"  Active Live Count:   {len(active)} -> {[a.get('contract') for a in active]}")
    print(f"  Carry Forward Count: {len(carry)} -> {[c.get('contract') for c in carry]}")
    if staged:
        print("  Staged Trade Contracts:")
        for s in staged:
            print(f"    - {s.get('contract')} ({s.get('pattern')}) Entry: {s.get('entry_spot')} SL: {s.get('current_sl')} T1: {s.get('t1')} RR: {s.get('rr')}")
