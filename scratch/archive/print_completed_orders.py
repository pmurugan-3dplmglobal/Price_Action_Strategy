import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
today_str = "2026-09-24"
orders_today = [o for o in orders if str(o.get('order_timestamp', '')).startswith(today_str)]
completed = [o for o in orders_today if o.get('status') == 'COMPLETE']
print(f"Total completed orders today: {len(completed)}")
for o in completed:
    t = str(o.get('order_timestamp'))[11:19]
    print(f"{t} | {o.get('tradingsymbol')} | {o.get('transaction_type')} | Qty={o.get('quantity')} | AvgP={o.get('average_price')} | Tag={o.get('tag')} | GUID={o.get('guid')}")
