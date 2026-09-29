import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
code = """
import sqlite3, json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%NAUKRI%' OR contract LIKE '%NAUKRI%' ORDER BY id DESC")
for r in c.fetchall()[:5]:
    tid, sym, cnt, st, cat, uat, dj = r
    d = json.loads(dj) if dj else {}
    print(f"ID: {tid} | {sym} ({cnt}) | Status: {st} | Created: {cat} | Updated: {uat}")
    print(f"  Entry: {d.get('entry_price')} | Exit: {d.get('exit_price')} | Reason: {d.get('exit_reason')}")
    print(f"  SL: {d.get('current_sl')} | T1: {d.get('t1')} | Pattern: {d.get('pattern')} | TF: {d.get('timeframe')}")
    print(f"  Spot Entry: {d.get('spot_entry')} | Spot SL: {d.get('spot_sl')} | Anchor High: {d.get('anchor_high')}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=code, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(res.stdout or res.stderr)
