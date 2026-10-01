import json
import datetime

def analyze_candles():
    with open('scratch/360one_spot_candles.json') as f:
        spot_360 = json.load(f)
    with open('scratch/360one_opt_candles.json') as f:
        opt_360 = json.load(f)
    with open('scratch/ultracemco_opt_candles.json') as f:
        opt_ultra = json.load(f)
    with open('scratch/live_orders.json') as f:
        orders = json.load(f)

    print("=== 360ONE SPOT CANDLES ===")
    for c in spot_360[-20:]:
        print(f"{c[0]} | O:{c[1]:<7.2f} H:{c[2]:<7.2f} L:{c[3]:<7.2f} C:{c[4]:<7.2f} V:{c[5]}")

    print("\n=== 360ONE 1040 CE CANDLES ===")
    for c in opt_360[-20:]:
        print(f"{c[0]} | O:{c[1]:<7.2f} H:{c[2]:<7.2f} L:{c[3]:<7.2f} C:{c[4]:<7.2f} V:{c[5]}")

    print("\n=== LIVE ORDERS FOR 360ONE ===")
    for o in orders:
        if "360ONE" in o.get("tradingsymbol", ""):
            print(f"Order: {o.get('order_id')} | {o.get('transaction_type')} {o.get('tradingsymbol')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Time: {o.get('order_timestamp')} | Tag: {o.get('tag')} | StatusMsg: {o.get('status_message')}")

    print("\n=== LIVE ORDERS FOR ALL TRADES ===")
    for o in orders:
        print(f"Order: {o.get('order_id')} | {o.get('transaction_type')} {o.get('tradingsymbol')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Time: {o.get('order_timestamp')} | Tag: {o.get('tag')}")

if __name__ == '__main__':
    analyze_candles()
