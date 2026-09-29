import subprocess

remote_script = """
import json, os

tk_path = '/home/opc/Price_Action_Strategy/input/kite_access_token.txt'
if os.path.exists(tk_path):
    print(open(tk_path).read())
else:
    print('TOKEN FILE MISSING ON VM!')
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
