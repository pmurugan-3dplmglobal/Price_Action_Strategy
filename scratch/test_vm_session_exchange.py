import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

req_tok = "Aed5554tCgluS6DzZNw7epf37ngUB42x"

cmd = f"""{REMOTE_DIR}/venv/bin/python -c "
import json
from kiteconnect import KiteConnect

p = '{REMOTE_DIR}/input/program_config.json'
with open(p) as f:
    d = json.load(f)

api_key = d.get('api_key')
api_secret = d.get('api_secret')
print(f'Attempting session exchange for API Key: {{api_key}}')

kite = KiteConnect(api_key=api_key)
try:
    data = kite.generate_session('{req_tok}', api_secret=api_secret)
    access_token = data.get('access_token')
    print('SUCCESS! Access token generated:', access_token[:10] + '...')
    
    # Save to VM token files
    token_dict = {{
        'api_key': api_key,
        'access_token': access_token,
        'generated_at': '2026-08-31 12:30:00'
    }}
    for fpath in ['{REMOTE_DIR}/input/kite_access_token.txt', '{REMOTE_DIR}/Trade_Option/input/kite_access_token.txt', '{REMOTE_DIR}/Trade_Stock/input/kite_access_token.txt']:
        with open(fpath, 'w') as fh:
            json.dump(token_dict, fh, indent=2)
    print('Saved token to all VM token files!')
except Exception as e:
    print('Exchange error:', e)
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print(res.stdout)
