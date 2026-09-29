import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

orders = kite.orders()
for o in orders:
    if o.get("order_id") == "260929190717553" or o.get("tradingsymbol") == "SWIGGY26OCT255CE":
        print(f"Order {o.get('order_id')}: status={o.get('status')}, status_message={o.get('status_message')}")
