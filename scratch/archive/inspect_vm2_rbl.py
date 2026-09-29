import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
ip = "129.225.69.131"

remote_script = """import sys, json, os
sys.path.insert(0, '/home/trade/Trade_Kite/Price_Action_Strategy')
sys.path.insert(0, '/home/trade/Trade_Kite/Price_Action_Strategy/common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = kite.orders()
rbl_orders = [o for o in orders if 'RBLBANK' in o.get('tradingsymbol', '')]
for o in rbl_orders:
    print('Order ID:', o.get('order_id'))
    print('  Variety:', o.get('variety'))
    print('  Status:', o.get('status'))
    print('  Tag / Variety / Product:', o.get('tag'), o.get('variety'), o.get('product'))
    print('  Timestamp:', o.get('order_timestamp'))
    print('  Price / AvgPrice:', o.get('price'), o.get('average_price'))
    print('  Quantity:', o.get('quantity'))
    print('  Message:', o.get('status_message'))

# Also check logs on VM2 around 12:32 and 14:14
log_file = '/home/trade/Trade_Kite/Price_Action_Strategy/output/logs/bull_nifty50_scanner.log'
if os.path.exists(log_file):
    print('\\n--- Scanner logs for RBLBANK ---')
    with open(log_file, 'r', errors='ignore') as f:
        for line in f:
            if 'RBLBANK' in line:
                print(' ', line.strip())
"""

proc = subprocess.Popen(
    ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}", "cat > /tmp/check_rbl.py && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python /tmp/check_rbl.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
stdout, stderr = proc.communicate(input=remote_script)
print(stdout or stderr)
