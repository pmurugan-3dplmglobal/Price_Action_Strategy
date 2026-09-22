import sys
sys.path.insert(0, ".")
from common.trading_core import load_kite_session

from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
if kite:
    net_pos = kite.positions().get("net", [])
    print("Kite Net Positions:")
    for p in net_pos:
        qty = p.get("quantity", 0)
        ts = p.get("tradingsymbol", "")
        ltp = p.get("last_price", 0.0)
        buy_p = p.get("average_price", 0.0)
        pnl = p.get("pnl", 0.0)
        if qty != 0:
            print(f"  {ts}: Qty={qty}, Buy={buy_p}, LTP={ltp}, PnL={pnl}")
        elif "APLAPOLLO" in ts or "CANBK" in ts:
            print(f"  {ts} (CLOSED): Qty={qty}, Buy={buy_p}, LTP={ltp}, PnL={pnl}")
else:
    print("Failed to get Kite session")
