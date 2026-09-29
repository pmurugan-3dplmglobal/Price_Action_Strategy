import subprocess

remote_script = """
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy')
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
import json, pattern_funnel

# Test purge with live LTP from BOSCH
ltp_map = {"BOSCHLTD26SEP47500CE": 1850.0, "BOSCHLTD26SEP47000PE": 350.0}
pattern_funnel.purge_invalidated_or_triggered('nifty50', ltp_dict=ltp_map)
pf = json.load(open('/home/opc/Price_Action_Strategy/output/monitor/pattern_funnel.json'))
b_items = [x for k, v in pf.items() if isinstance(v, dict) for x in v.get('category_b', []) + v.get('category_a', []) + v.get('category_a_plus', []) if 'BOSCH' in str(x)]
print("Remaining BOSCH items after purge with LTP:", len(b_items))
print(json.dumps(b_items, indent=2, ensure_ascii=True))
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    '/home/opc/Price_Action_Strategy/venv/bin/python'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)

