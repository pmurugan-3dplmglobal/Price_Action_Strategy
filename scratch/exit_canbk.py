import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiteconnect import KiteConnect
from common.session import load_kite_session, optimize_kite_session
import time
import sqlite3
import json

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
optimize_kite_session(kite)

contract = "CANBK26SEP125CE"
qty = 6750

# Check position in Kite
pos = [p for p in kite.positions().get("net", []) if p.get("tradingsymbol") == contract and p.get("quantity") != 0]
if not pos:
    print(f"No open position found for {contract} in Kite!")
    sys.exit(0)

held_qty = pos[0]["quantity"]
buy_price = pos[0]["buy_price"]
print(f"Found open position: {contract} | Qty: {held_qty} | BuyPrice: {buy_price}")

# Check quote
q = kite.quote([f"NFO:{contract}"])[f"NFO:{contract}"]
depth = q.get("depth", {})
buy_orders = depth.get("buy", [])
best_bid = buy_orders[0]["price"] if buy_orders else q.get("last_price")
sell_price = round(best_bid, 2)
print(f"Placing SELL LIMIT order for {held_qty} qty @ {sell_price} (Best Bid)...")

order_id = kite.place_order(
    variety=kite.VARIETY_REGULAR,
    tradingsymbol=contract,
    exchange=kite.EXCHANGE_NFO,
    transaction_type=kite.TRANSACTION_TYPE_SELL,
    quantity=held_qty,
    order_type=kite.ORDER_TYPE_LIMIT,
    price=sell_price,
    product=kite.PRODUCT_NRML
)
print(f"Order placed successfully! Order ID: {order_id}")

# Wait up to 5 seconds to verify fill
time.sleep(2)
orders = kite.orders()
my_order = next((o for o in orders if str(o.get("order_id")) == str(order_id)), None)
if my_order:
    print(f"Order Status: {my_order.get('status')} | AvgPrice: {my_order.get('average_price')} | FilledQty: {my_order.get('filled_quantity')}")
    if my_order.get("status") == "COMPLETE":
        avg_exit = my_order.get("average_price")
        pnl = (avg_exit - buy_price) * held_qty
        print(f"Position successfully CLOSED! Realized PnL: Rs {pnl:.2f}")
        
        conn = sqlite3.connect("output/monitor/trades.sqlite3")
        row = conn.execute("SELECT data_json FROM trades WHERE id = 794").fetchone()
        if row:
            d = json.loads(row[0])
            d["status"] = "CLOSED"
            d["exit_price"] = avg_exit
            d["exit_reason"] = "MANUAL_DEBIT_SPREAD_ORPHAN_SQUAREOFF"
            conn.execute("UPDATE trades SET status = 'CLOSED', data_json = ?, updated_at = datetime('now', 'localtime') WHERE id = 794", (json.dumps(d),))
            conn.commit()
            print("Updated trade 794 in trades.sqlite3 to CLOSED.")
else:
    print("Could not retrieve order details immediately.")
