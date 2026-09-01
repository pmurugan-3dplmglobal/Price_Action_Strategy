import sys, json, os

_ROOT = "/home/opc/Price_Action_Strategy"
sys.path.insert(0, f"{_ROOT}/common")
sys.path.insert(0, f"{_ROOT}/Trade_Option")

print("==================================================")
print(" 140.245.197.71 LIVE POSITIONS AUDIT")
print("==================================================")

# 1. Kite Profile and Live Positions
from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call

try:
    api_k, acc_t = load_kite_session(f"{_ROOT}/input/kite_access_token.txt")
    kite = KiteConnect(api_key=api_k)
    kite.set_access_token(acc_t)
    profile = kite.profile()
    print("Kite Account:", profile.get("user_id"), "|", profile.get("user_name"))
    
    pos_data = safe_kite_call(kite.positions) or {}
    net = pos_data.get("net", [])
    open_pos = [p for p in net if int(p.get("quantity", 0)) != 0]
    print(f"\nLive Kite Open Positions: {len(open_pos)}")
    for p in open_pos:
        print(f"  {p.get('tradingsymbol')} | Qty: {p.get('quantity')} | BuyAvg: {p.get('average_price')} | LTP: {p.get('last_price')} | PnL: {p.get('pnl')}")
except Exception as e:
    print("Kite Error:", e)

# 2. SQLite Active Trades
import trade_db
active_db = trade_db.get_active_trades()
print(f"\nSQLite Active Trades (Total: {len(active_db)}):")
for t in active_db:
    print(f"  ID {t.get('id')} | {t.get('contract', t.get('symbol'))} | SL: {t.get('current_sl')} | T1: {t.get('t1')} | Status: {t.get('status')}")

# 3. active_positions_db.json
act_file = f"{_ROOT}/output/monitor/active_positions_db.json"
if os.path.exists(act_file):
    with open(act_file) as f:
        act_data = json.load(f)
    print(f"\nactive_positions_db.json count: {len(act_data.get('positions', []))}")
    for p in act_data.get("positions", []):
        print(f"  {p.get('contract', p.get('symbol'))} | {p.get('status')}")
