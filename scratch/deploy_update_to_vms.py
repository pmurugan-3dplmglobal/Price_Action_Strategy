import subprocess
import sys

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VMS = [
    {
        'name': 'VM1 (Poovendan)',
        'ip': '140.245.197.71',
        'user': 'opc',
        'dir': '/home/opc/Price_Action_Strategy'
    },
    {
        'name': 'VM2 (Bhavani)',
        'ip': '129.225.69.131',
        'user': 'opc',
        'dir': '/home/trade/Trade_Kite/Price_Action_Strategy'
    }
]

BASH_SCRIPT = '''#!/usr/bin/env bash
set -e
cd "__DIR__"

echo "=== Pulling origin master ==="
git checkout -- input/watchlist.json 2>/dev/null || true
git pull origin master

echo "=== Verifying / updating program_config.json ==="
python3 -c "
import json, os
p = 'input/program_config.json'
if os.path.exists(p):
    with open(p, 'r', encoding='utf-8') as f:
        d = json.load(f)
    d.setdefault('index', {})['execution_mode'] = 'DEBIT_SPREAD'
    d.setdefault('index', {})['max_concurrent_positions'] = 1
    d.setdefault('index', {})['timeframe_entry'] = '15minute'
    d.setdefault('index', {})['timeframe_anchor'] = '60minute'
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2)
    print('Updated program_config.json execution_mode to DEBIT_SPREAD, max_pos 1, TF 15m/60m')
else:
    print('No local program_config.json found')
"

echo "=== Restarting services ==="
sudo systemctl restart trading-options trading-stock trading-export || sudo systemctl restart trading-options

sleep 3
echo -n "trading-options: "
systemctl is-active trading-options || true
echo -n "trading-stock: "
systemctl is-active trading-stock || true
echo -n "trading-export: "
systemctl is-active trading-export || true
uptime
'''

all_success = True
for vm in VMS:
    print(f"\n{'='*60}\nDeploying to {vm['name']} ({vm['ip']})...\n{'='*60}")
    script = BASH_SCRIPT.replace('__DIR__', vm['dir']).replace('\r\n', '\n').encode('utf-8')
    cmd = [
        'ssh',
        '-i', SSH_KEY,
        '-o', 'StrictHostKeyChecking=no',
        f"{vm['user']}@{vm['ip']}",
        'bash -s'
    ]
    res = subprocess.run(cmd, input=script, capture_output=True)
    print('STDOUT:')
    print(res.stdout.decode('utf-8', errors='replace'))
    if res.stderr:
        print('STDERR:')
        print(res.stderr.decode('utf-8', errors='replace'))
    print(f"Exit code: {res.returncode}")
    if res.returncode != 0:
        all_success = False

if all_success:
    print("\n>>> ALL CLOUD VMS DEPLOYED AND SERVICES RESTARTED SUCCESSFULLY! <<<")
else:
    print("\n>>> ONE OR MORE VMS ENCOUNTERED ERRORS DURING DEPLOYMENT <<<")
    sys.exit(1)
