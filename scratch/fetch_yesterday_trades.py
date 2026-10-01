import json
from kiteconnect import KiteConnect

def fetch_kite_data():
    with open('input/kite_access_token.txt', 'r') as f:
        token = f.read().strip()
    with open('input/program_config.json', 'r') as f:
        cfg = json.load(f)
    api_key = cfg.get('api_key', 'o8nnw6kxykvrsrhg')

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)

    print("Fetching positions...")
    positions = kite.positions()
    print("Net positions count:", len(positions.get('net', [])))
    print("Day positions count:", len(positions.get('day', [])))
    
    print("\n=== OVERNIGHT POSITIONS (Entered Yesterday or prior) ===")
    for p in positions.get('net', []):
        overnight_qty = p.get('overnight_quantity', 0)
        print(f"Symbol: {p.get('tradingsymbol')} | Overnight Qty: {overnight_qty} | Buy Qty: {p.get('buy_quantity')} | Buy Avg: {p.get('buy_price')} | Sell Qty: {p.get('sell_quantity')} | Sell Avg: {p.get('sell_price')} | Close (Yesterday Close): {p.get('close_price')}")

    print("\nFetching trades...")
    trades = kite.trades()
    print(f"Trades count: {len(trades)}")
    for t in trades:
        print(f"Trade ID: {t.get('trade_id')} | Order ID: {t.get('order_id')} | Time: {t.get('trade_timestamp')} | Symbol: {t.get('tradingsymbol')} | Type: {t.get('transaction_type')} | Qty: {t.get('quantity')} | Price: {t.get('average_price') or t.get('price')}")

    print("\nFetching orders...")
    orders = kite.orders()
    print(f"Orders count: {len(orders)}")
    for o in orders:
        print(f"Order ID: {o.get('order_id')} | Time: {o.get('order_timestamp')} | Symbol: {o.get('tradingsymbol')} | Type: {o.get('transaction_type')} | Status: {o.get('status')} | Price: {o.get('price')} | Avg: {o.get('average_price')}")

if __name__ == '__main__':
    fetch_kite_data()
