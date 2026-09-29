import json
import os
import sys

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from kiteconnect import KiteConnect
from trading_core import load_kite_session

print("=== OPTION ENGINE ACTIVE POSITIONS DB ===")
p1 = 'Trade_Option/output/monitor/active_positions_db.json'
if os.path.exists(p1):
    with open(p1) as f:
        print(json.dumps(json.load(f), indent=2))
else:
    print("None")

print("\n=== STOCK ENGINE ACTIVE POSITIONS DB ===")
p2 = 'Trade_Stock/output/monitor/active_positions_db.json'
if os.path.exists(p2):
    with open(p2) as f:
        print(json.dumps(json.load(f), indent=2))
else:
    print("None")

print("\n=== SL / TARGET OVERRIDES FILE ===")
p3 = 'Trade_Option/output/monitor/sl_target_overrides.json'
if os.path.exists(p3):
    with open(p3) as f:
        print(json.dumps(json.load(f), indent=2))
else:
    print("None")

print("\n=== KITE API LIVE OPEN POSITIONS ===")
try:
    api_k, acc_t = load_kite_session()
    kite = KiteConnect(api_key=api_k, access_token=acc_t)
    pos = kite.positions()
    open_pos = [p for p in pos.get('net', []) + pos.get('day', []) if abs(int(p.get('quantity', 0))) > 0]
    print(f"Found {len(open_pos)} open positions in Zerodha Kite:")
    for p in open_pos:
        print(f" - {p.get('tradingsymbol')} | Qty: {p.get('quantity')} | BuyPrice: {p.get('buy_price')} | LTP: {p.get('last_price')} | P&L: {p.get('pnl')}")
except Exception as e:
    print(f"Kite API fetch error: {e}")
