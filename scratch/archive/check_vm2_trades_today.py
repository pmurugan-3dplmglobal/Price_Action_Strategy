import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import sqlite3, json
conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, data_json FROM trades WHERE id = 799")
row = c.fetchone()
print(f"Trade {row[0]}: {row[1]} {row[2]} Status: {row[3]} Time: {row[4]}")
d = json.loads(row[5])
print("Entry spot / price:", d.get('entry_spot'), d.get('entry_price'), "SL:", d.get('current_sl'), "T1:", d.get('t1'))
print("Leg 1 Filled OID:", d.get('order_id'))
print("Leg 2 Rejected OID:", d.get('leg2_order_id'))
print("Spread info in data_json:", d.get('position_type'), d.get('leg2_contract'))
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
       "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"]
res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
print(res.stdout or res.stderr)
