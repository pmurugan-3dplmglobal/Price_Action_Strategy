import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import sqlite3
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TRADES_DB, TOKEN_FILE, monitor_file

STATE_FILE = monitor_file("stock_positions_state.json")

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)
pos = kite.positions().get('net', [])
print("=== BROKER NET POSITIONS (Qty != 0) ===")
held_symbols = set()
for p in pos:
    q = p.get('quantity', 0)
    if q != 0:
        sym = p.get('tradingsymbol')
        held_symbols.add(sym)
        print(f"  {sym}: qty={q}, m2m={p.get('m2m')}, pnl={p.get('pnl')}")

print(f"\nTotal non-zero broker positions: {len(held_symbols)}")

print("\n=== STOCK POSITIONS STATE FILE ===")
try:
    with open(STATE_FILE, "r") as f:
        st = json.load(f)
except Exception as e:
    print(f"Error loading state file: {e}")
    st = {}

print(f"Total entries in state file: {len(st)}")
for k, v in st.items():
    cnt = v.get("contract", "")
    stat = v.get("status", "")
    qty = v.get("quantity", 0)
    is_on_broker = cnt in held_symbols
    print(f"  {k} -> {cnt}: status={stat}, qty={qty}, on_broker={is_on_broker}")
