import subprocess

remote_script = """
import json, sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
import paths, session
from kiteconnect import KiteConnect

try:
    k, t = session.load_kite_session(paths.TOKEN_FILE)
    kite = KiteConnect(api_key=k)
    kite.set_access_token(t)
    profile = kite.profile()
    print('KITE USER:', profile.get('user_name'), profile.get('user_id'))
except Exception as e:
    print('KITE AUTH ERROR:', type(e), e)
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    '/home/opc/Price_Action_Strategy/venv/bin/python'
], input=remote_script, capture_output=True, text=True)

print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
