import subprocess
import json

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VM_IP = '140.245.197.71'
VM_USER = 'opc'
VM_DIR = '/home/opc/Price_Action_Strategy'

REMOTE_SCRIPT = """
import json
from common.session import load_kite_session
from kiteconnect import KiteConnect

k, t = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(t)

symbols = ['NSE:NIFTY MID SELECT', 'NFO:MIDCPNIFTY26SEP14575CE', 'NFO:MIDCPNIFTY26SEP14550CE', 'NFO:MIDCPNIFTY26SEP14600CE']
q = kite.quote(symbols)
print('---QUOTE_JSON_START---')
print(json.dumps(q, default=str, indent=2))
print('---QUOTE_JSON_END---')

# Check pattern funnel
f_path = 'output/monitor/pattern_funnel.json'
import os
if os.path.exists(f_path):
    with open(f_path) as f:
        funnel = json.load(f)
    print('---FUNNEL_START---')
    midcp_items = [item for cat, items in funnel.get('index', {}).items() for item in items if isinstance(item, dict) and 'MIDCP' in str(item.get('symbol',''))]
    print(json.dumps(midcp_items))
    print('---FUNNEL_END---')

# Check scan display index
sd_path = 'output/monitor/scan_display_index.json'
if os.path.exists(sd_path):
    with open(sd_path) as f:
        sd = json.load(f)
    print('---SCAN_DISPLAY_START---')
    staged = [item for item in sd.get('staged_trades', []) if 'MIDCP' in str(item.get('symbol','')) or '14575' in str(item.get('contract',''))]
    print(json.dumps(staged))
    print('---SCAN_DISPLAY_END---')

# Check active positions
ap_path = 'output/monitor/active_positions_db.json'
if os.path.exists(ap_path):
    with open(ap_path) as f:
        ap = json.load(f)
    print('---ACTIVE_POSITIONS_START---')
    print(json.dumps(ap))
    print('---ACTIVE_POSITIONS_END---')
"""

cmd = [
    'ssh',
    '-i', SSH_KEY,
    '-o', 'StrictHostKeyChecking=no',
    f'{VM_USER}@{VM_IP}',
    f'cd {VM_DIR} && ./venv/bin/python -c "{REMOTE_SCRIPT}"'
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
