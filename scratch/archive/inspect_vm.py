import subprocess

remote_script = """
import json, glob, os, subprocess

print('=== SCAN DISPLAY FILES ===')
for f in sorted(glob.glob('/home/opc/Price_Action_Strategy/output/monitor/scan_display*.json')):
    try:
        data = json.load(open(f))
        print(f, 'mtime:', int(os.path.getmtime(f)), 'staged:', len(data.get('staged_trades', [])), 'active:', len(data.get('active_live', [])))
    except Exception as e:
        print(f, e)

print('\\n=== PATTERN FUNNEL ===')
try:
    pf = json.load(open('/home/opc/Price_Action_Strategy/output/monitor/pattern_funnel.json'))
    print('Top keys:', list(pf.keys()))
    for k, v in pf.items():
        if isinstance(v, dict):
            print(k, '-> A+:', len(v.get('category_a_plus', [])), 'A:', len(v.get('category_a', [])), 'B:', len(v.get('category_b', [])))
except Exception as e:
    print('pattern_funnel error:', e)

print('\\n=== RUNNING PYTHON PROCESSES ===')
ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
for line in ps.splitlines():
    if 'python' in line:
        print(line)

print('\\n=== TAIL OF RECENT LOGS ===')
for log in ['bull_nifty50_scanner.log', 'bull_index_trade_engine.log', 'bull_daily_scanner.log']:
    p = f'/home/opc/Price_Action_Strategy/output/logs/{log}'
    if os.path.exists(p):
        print(f'\\n--- {log} (last 10 lines) ---')
        lines = open(p).readlines()[-10:]
        print(''.join(lines))
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
