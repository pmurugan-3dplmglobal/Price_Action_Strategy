import json
import os
import glob
import sqlite3

print("==================================================")
print(" DIAGNOSTIC: INDEX OPTIONS TRADE ENGINE")
print("==================================================")

# 1. Check live log
log_f = os.path.join("output", "logs", "bull_index_trade_engine.log")
if os.path.exists(log_f):
    with open(log_f, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    print(f"\n[1] Log File: {log_f} ({len(lines)} lines)")
    print("--- Last 30 lines ---")
    for l in lines[-30:]:
        print("  " + l.strip())
else:
    print(f"\n[1] {log_f} not found!")

# 2. Check scan display file
disp_f = os.path.join("output", "monitor", "scan_display_index.json")
if os.path.exists(disp_f):
    with open(disp_f, "r", encoding="utf-8") as f:
        disp = json.load(f)
    print(f"\n[2] scan_display_index.json:")
    print(f"  Date: {disp.get('date')}, Timestamp: {disp.get('timestamp')}")
    staged = disp.get("staged_trades", [])
    print(f"  Staged Trades: {len(staged)}")
    for st in staged:
        print(f"    - {st.get('symbol')} | {st.get('contract')} | {st.get('pattern')} | Entry: {st.get('entry_spot')} | SL: {st.get('current_sl')} | T1: {st.get('t1')} | Tier: {st.get('tier_badge')}")
    active = disp.get("active_positions", [])
    print(f"  Active Positions: {len(active)}")
    for ap in active:
        print(f"    - {ap.get('symbol')} | {ap.get('contract')} | Status: {ap.get('status')}")
else:
    print(f"\n[2] {disp_f} not found!")

# 3. Check Live Flags
print(f"\n[3] Flags:")
for flag_name, flag_p in [
    ("Index Live Flag", os.path.join("input", "index_live_execution.txt")),
    ("Nifty50 Live Flag", os.path.join("input", "nifty50_live_execution.txt"))
]:
    if os.path.exists(flag_p):
        with open(flag_p) as f:
            val = f.read().strip()
        print(f"  {flag_name}: {val} ({'ON' if val == '1' else 'OFF'})")
    else:
        print(f"  {flag_name}: Missing (OFF)")

# 4. Check active trades in SQLite
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at FROM trades WHERE engine = 'index' ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    print(f"\n[4] SQLite index trades ({len(rows)} recent):")
    for r in rows:
        print(f"  ID {r[0]} | {r[1]} | {r[2]} | {r[3]} | Status: {r[4]} | Created: {r[5]}")
    conn.close()
