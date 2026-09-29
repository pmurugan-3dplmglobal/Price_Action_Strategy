import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import json, os

for p in ['output/monitor/active_positions_db.json', 'output/monitor/trades.sqlite3']:
    print(f"=== {p} ===")
    if p.endswith('.json') and os.path.exists(p):
        d = json.load(open(p))
        for k, v in d.items():
            if 'BHARTI' in k or 'BHARTI' in str(v):
                print(f"Key: {k}")
                print(f"  contract: {v.get('contract')}")
                print(f"  position_type: {v.get('position_type')}")
                print(f"  leg2_contract: {v.get('leg2_contract')}")
                print(f"  leg2_order_id: {v.get('leg2_order_id')}")
                print(f"  status: {v.get('status')}")
                print(f"  current_sl: {v.get('current_sl')}")
                print(f"  t1: {v.get('t1')}")
    elif p.endswith('.sqlite3') and os.path.exists(p):
        import sqlite3
        conn = sqlite3.connect(p)
        c = conn.cursor()
        c.execute("SELECT id, symbol, contract, status, created_at, data_json FROM trades WHERE symbol LIKE '%BHARTI%' ORDER BY id DESC LIMIT 2")
        rows = c.fetchall()
        for r in rows:
            tid, sym, cnt, st, cat, dj_str = r
            print(f"DB Trade ID: {tid} | Sym: {sym} | Contract: {cnt} | Status: {st} | Time: {cat}")
            d = json.loads(dj_str) if dj_str else {}
            print(f"  Spread Info: pos_type={d.get('position_type')} leg2={d.get('leg2_contract')} leg2_oid={d.get('leg2_order_id')}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
       "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"]
res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
print(res.stdout or res.stderr)
