import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

# 1. Test Kite Auth on VM1
remote_test = """
import sys
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect
ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
print('VM1 User:', kite.profile().get('user_name'))
"""

res = subprocess.run([
    'ssh', '-i', KEY, '-o', 'StrictHostKeyChecking=no', 'opc@140.245.197.71',
    'cd /home/opc/Price_Action_Strategy && python3'
], input=remote_test, capture_output=True, text=True, timeout=20)
print("VM1 Auth Test:")
print(res.stdout.strip() or res.stderr.strip())

# 2. Restart services
res_restart = subprocess.run([
    'ssh', '-i', KEY, '-o', 'StrictHostKeyChecking=no', 'opc@140.245.197.71',
    'sudo systemctl restart trading-options trading-stock trading-export'
], capture_output=True, text=True, timeout=30)
print('Restart exit code:', res_restart.returncode)

time.sleep(3)

# 3. Check service status
res_status = subprocess.run([
    'ssh', '-i', KEY, '-o', 'StrictHostKeyChecking=no', 'opc@140.245.197.71',
    'systemctl is-active trading-options trading-stock trading-export'
], capture_output=True, text=True, timeout=15)
print('VM1 Services Status:\n', res_status.stdout.strip())
