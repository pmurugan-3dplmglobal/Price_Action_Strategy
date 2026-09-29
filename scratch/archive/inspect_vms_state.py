import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_script = r"""
import sqlite3
import json
import os

print('=== PATTERN FUNNEL ===')
funnel_path = 'output/monitor/pattern_funnel.json'
if os.path.exists(funnel_path):
    try:
        f = json.load(open(funnel_path))
        for eng, data in f.items():
            if isinstance(data, dict):
                c_ap = len(data.get('category_a_plus', []))
                c_a = len(data.get('category_a', []))
                c_b = len(data.get('category_b', []))
                print(f"  {eng}: A+={c_ap}, A={c_a}, B={c_b}, updated={data.get('updated_at')}")
                for cat, items in [('A+', data.get('category_a_plus', [])), ('A', data.get('category_a', [])), ('B', data.get('category_b', []))]:
                    for it in items[:3]:
                        print(f"    [{cat}] {it.get('symbol')} {it.get('contract')} side={it.get('side')} A_time={it.get('candle_a_time')}")
    except Exception as e:
        print('Error reading funnel:', e)

print('\n=== SCAN DISPLAY ===')
disp_path = 'output/monitor/scan_display.json'
if os.path.exists(disp_path):
    try:
        d = json.load(open(disp_path))
        print(f"  scan_display date={d.get('date')}, ts={d.get('timestamp')}")
        print(f"  staged_trades={len(d.get('staged_trades', []))}")
        print(f"  all_staged_today={len(d.get('all_staged_today', []))}")
        print(f"  carry_forward={len(d.get('carry_forward', []))}")
        for item in d.get('staged_trades', [])[:5]:
            print(f"    staged: {item.get('symbol')} {item.get('contract')} status={item.get('status')}")
    except Exception as e:
        print('Error reading scan_display:', e)

print('\n=== TRADES DB (TODAY 2026-09-23) ===')
db_path = 'output/monitor/trades.sqlite3'
if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT id, engine, symbol, contract, status, created_at FROM trades WHERE created_at LIKE '2026-09-23%'")
        rows = c.fetchall()
        print(f"  Total trades in DB today: {len(rows)}")
        for r in rows:
            print(f"    {r}")
    except Exception as e:
        print('Error reading sqlite3:', e)
"""

print("=== VM 2 (Bhavani: 129.225.69.131) ===")
cmd2 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
    "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"
]
res2 = subprocess.run(cmd2, input=py_script, capture_output=True, text=True)
print(res2.stdout or res2.stderr)

print("\n=== VM 1 (Poovendan: 140.245.197.71) ===")
cmd1 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "cd /home/opc/Price_Action_Strategy && /home/opc/Price_Action_Strategy/venv/bin/python -"
]
res1 = subprocess.run(cmd1, input=py_script, capture_output=True, text=True)
print(res1.stdout or res1.stderr)
