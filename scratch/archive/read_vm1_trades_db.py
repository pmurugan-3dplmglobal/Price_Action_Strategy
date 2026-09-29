import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
py_code = """
import json, os
for p in ['output/monitor/trades_db.json', 'output/monitor/journal_trades_db.json', 'output/monitor/active_positions_db.json']:
    print(f"=== {p} ===")
    if os.path.exists(p):
        d = json.load(open(p))
        if isinstance(d, dict):
            items = d.get('trades', list(d.values()))
        else:
            items = d
        for t in items[-10:]:
            if isinstance(t, dict):
                print(f"{t.get('symbol')} | {t.get('contract')} | Status: {t.get('status')} | Exit: {t.get('exit_reason')} | Entry: {t.get('entry_spot') or t.get('entry_price')} | SL: {t.get('current_sl')} | T1: {t.get('t1')} | PnL: {t.get('pnl')}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=py_code, capture_output=True, text=True)
print(res.stdout or res.stderr)
