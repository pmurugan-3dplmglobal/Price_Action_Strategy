import sys, os, json
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
COMMON_DIR = os.path.join(PROJECT_ROOT, 'common')
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
import paths
with open(paths.TOKEN_FILE) as f:
    tdata = json.load(f)
from kiteconnect import KiteConnect
kite = KiteConnect(api_key=tdata['api_key'], access_token=tdata['access_token'])


print('Orders:')

for o in kite.orders():
    sym = o.get('tradingsymbol', '')
    if '23400' in sym or 'NIFTY' in sym:
        print(o.get('order_timestamp'), sym, o.get('transaction_type'), 'Qty:', o.get('quantity'), 'Price:', o.get('price'), 'Avg:', o.get('average_price'), 'Status:', o.get('status'), 'Tag:', o.get('tag'))


for p in kite.positions().get('net', []):
    sym = p.get('tradingsymbol', '')
    if '23400' in sym or 'NIFTY' in sym:
        print('POS:', sym, 'Qty:', p.get('quantity'), 'BuyQty:', p.get('buy_quantity'), 'Avg:', p.get('buy_price'), 'Pnl:', p.get('pnl'))
