import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_script = """
import sqlite3
import json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, engine, symbol, contract, status, data_json, created_at FROM trades WHERE created_at LIKE '2026-09-22%'")
rows = c.fetchall()
print(f'Total trades today: {len(rows)}')
for r in rows:
    tid, eng, sym, contract, status, dj_str, cat = r
    d = json.loads(dj_str) if dj_str else {}
    tier = d.get('tier_badge') or d.get('tier') or 'N/A'
    entry = d.get('entry_price') or d.get('entry_spot') or d.get('Close') or 0
    exit_p = d.get('exit_price') or 0
    pnl = d.get('pnl') or d.get('realized_pnl') or 0
    reason = d.get('exit_reason') or d.get('reason') or ''
    pattern = d.get('pattern') or d.get('Pattern') or ''
    side = d.get('side') or d.get('Side') or ''
    print(f'{sym:12} | {contract:22} | {side:4} | Tier: {str(tier):6} | Entry: {entry:<7} | Exit: {exit_p:<7} | PnL: {pnl:<9} | Status: {status:12} | {reason} | {pattern}')
"""

print("=== VM 2 (Bhavani) TRADES ===")
cmd2 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
    "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"
]
res2 = subprocess.run(cmd2, input=py_script, capture_output=True, text=True)
print(res2.stdout or res2.stderr)

print("\n=== VM 1 (Poovendan) TRADES ===")
cmd1 = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71",
    "cd /home/opc/Price_Action_Strategy && python3 -"
]
res1 = subprocess.run(cmd1, input=py_script, capture_output=True, text=True)
print(res1.stdout or res1.stderr)
