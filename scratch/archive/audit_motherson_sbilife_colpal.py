import subprocess
import json
import sqlite3
import os
import sys

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

# 1. Query VM2 for MOTHERSON
print("=" * 60)
print("1. QUERYING MOTHERSON ON BHAVANI VM2 (129.225.69.131)")
print("=" * 60)
remote_py_vm2 = """
import sqlite3, json
conn = sqlite3.connect('/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%MOTHERSON%' OR symbol LIKE '%MOTHERSON%' ORDER BY id DESC LIMIT 5")
rows = c.fetchall()
print(f"Found {len(rows)} rows for MOTHERSON in VM2 DB:")
for r in rows:
    print(f"ID={r[0]} sym={r[1]} contract={r[2]} status={r[3]} created={r[5]} updated={r[6]}")
    try:
        dj = json.loads(r[4])
        print("  Full trade details:")
        print(f"    pattern={dj.get('pattern')}, tf={dj.get('timeframe')}, side={dj.get('side')}, tier={dj.get('tier_label')}")
        print(f"    entry_price={dj.get('entry_price')}, entry_spot={dj.get('entry_spot')}")
        print(f"    current_sl={dj.get('current_sl')}, spot_sl={dj.get('spot_sl')}")
        print(f"    exit_price={dj.get('exit_price')}, exit_reason={dj.get('exit_reason')}, pnl={dj.get('pnl')}")
        print(f"    mfe_pct={dj.get('mfe_pct')}, mae_pct={dj.get('mae_pct')}")
        print(f"    order_id={dj.get('order_id')}, exit_order_id={dj.get('exit_order_id')}")
    except Exception as e:
        print(f"  Error parsing json: {e}")
conn.close()
"""
cmd_vm2 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
    f"/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -c \"{remote_py_vm2}\""
]
res_vm2 = subprocess.run(cmd_vm2, capture_output=True, text=True, timeout=20)
print(res_vm2.stdout or res_vm2.stderr)

# 2. Query VM1 for SBILIFE and COLPAL
print("\n" + "=" * 60)
print("2. QUERYING SBILIFE & COLPAL ON POOVENDAN VM1 (140.245.197.71)")
print("=" * 60)
remote_py_vm1 = """
import sqlite3, json
conn = sqlite3.connect('/home/opc/Price_Action_Strategy/output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%SBILIFE%' OR contract LIKE '%COLPAL%' OR symbol LIKE '%SBILIFE%' OR symbol LIKE '%COLPAL%' ORDER BY id DESC LIMIT 10")
rows = c.fetchall()
print(f"Found {len(rows)} rows for SBILIFE/COLPAL in VM1 DB:")
for r in rows:
    print(f"ID={r[0]} sym={r[1]} contract={r[2]} status={r[3]} created={r[5]} updated={r[6]}")
    try:
        dj = json.loads(r[4])
        print("  Trade details:")
        print(f"    pattern={dj.get('pattern')}, tf={dj.get('timeframe')}, side={dj.get('side')}, tier={dj.get('tier_label')}")
        print(f"    entry_price={dj.get('entry_price')}, entry_spot={dj.get('entry_spot')}")
        print(f"    current_sl={dj.get('current_sl')}, spot_sl={dj.get('spot_sl')}")
        print(f"    exit_price={dj.get('exit_price')}, exit_reason={dj.get('exit_reason')}, pnl={dj.get('pnl')}")
        print(f"    mfe_pct={dj.get('mfe_pct')}, mae_pct={dj.get('mae_pct')}")
        print(f"    order_id={dj.get('order_id')}, exit_order_id={dj.get('exit_order_id')}")
    except Exception as e:
        print(f"  Error parsing json: {e}")
conn.close()
"""
cmd_vm1 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    f"/home/opc/Price_Action_Strategy/venv/bin/python -c \"{remote_py_vm1}\""
]
res_vm1 = subprocess.run(cmd_vm1, capture_output=True, text=True, timeout=20)
print(res_vm1.stdout or res_vm1.stderr)

# 3. Query local Kite session for today's orders on both symbols
print("\n" + "=" * 60)
print("3. QUERYING LOCAL KITE ORDERS FOR SBILIFE, COLPAL, MOTHERSON")
print("=" * 60)
try:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from kiteconnect import KiteConnect
    from common.session import load_kite_session, ensure_kite_session
    from common.paths import TOKEN_FILE
    api_key, access_token = load_kite_session(TOKEN_FILE)
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    ensure_kite_session(kite)
    orders = kite.orders()
    target_syms = ["SBILIFE", "COLPAL", "MOTHERSON"]
    for o in orders:
        ts = o.get("tradingsymbol", "")
        if any(s in ts for s in target_syms):
            print(f"Order: {o.get('order_id')} | {ts} | {o.get('transaction_type')} {o.get('quantity')} @ {o.get('price') or o.get('average_price')} | status={o.get('status')} | time={o.get('order_timestamp')} | tag={o.get('tag')} | reason={o.get('status_message')}")
except Exception as e:
    print(f"Error checking local Kite: {e}")
