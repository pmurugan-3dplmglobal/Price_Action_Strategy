import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import sqlite3
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE, monitor_file

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

# 1. Fetch live net positions from broker
broker_net = kite.positions().get("net", [])
held_positions = {}
for p in broker_net:
    q = p.get("quantity", 0)
    if q != 0:
        held_positions[p.get("tradingsymbol")] = q

print(f"Live broker held positions (qty != 0): {held_positions}")

# 2. Clean stock_positions_state.json
state_path = monitor_file("stock_positions_state.json")
try:
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
except Exception as e:
    print(f"Error loading state: {e}")
    state = {}

cleaned_state = {}
purged_symbols = []

for sym, data in state.items():
    cnt = data.get("contract", "")
    if cnt in held_positions:
        data["quantity"] = held_positions[cnt]
        cleaned_state[sym] = data
        print(f"KEEPING ACTIVE: {sym} -> {cnt} (qty={held_positions[cnt]})")
    else:
        purged_symbols.append((sym, cnt))
        print(f"PURGING GHOST: {sym} -> {cnt} (not held on broker)")

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(cleaned_state, f, indent=2)

print(f"\nUpdated {state_path}: {len(cleaned_state)} active positions remaining ({len(purged_symbols)} purged).")

# 3. Clean trades.sqlite3
db_path = monitor_file("trades.sqlite3")
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT id, symbol, contract, status, data_json FROM trades WHERE status IN ('ACTIVE', 'OPEN')")
active_trades = c.fetchall()
print(f"\nChecking {len(active_trades)} active/open trades in SQLite:")

updated_trades = 0
for row in active_trades:
    tid, sym, cnt, stat, dj_str = row
    if cnt not in held_positions:
        print(f"  Fixing SQLite trade ID={tid} ({sym} / {cnt}): status '{stat}' -> 'FAILED'")
        try:
            dj = json.loads(dj_str) if dj_str else {}
        except Exception:
            dj = {}
        dj["status"] = "FAILED"
        dj["exit_reason"] = "BROKER_REJECTED_OR_PURGED_GHOST"
        dj["pnl"] = 0.0
        new_dj_str = json.dumps(dj)
        c.execute("UPDATE trades SET status='FAILED', data_json=? WHERE id=?", (new_dj_str, tid))
        updated_trades += 1
    else:
        print(f"  Trade ID={tid} ({sym} / {cnt}) is verified held on broker.")

conn.commit()
conn.close()
print(f"SQLite update complete: {updated_trades} ghost trades marked as FAILED.")
