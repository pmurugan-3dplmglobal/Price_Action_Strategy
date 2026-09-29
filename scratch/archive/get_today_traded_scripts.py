import sys
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
traded_orders = [o for o in orders if o.get('status') == 'COMPLETE']
print(f"Total COMPLETE orders today: {len(traded_orders)}")

traded_by_symbol = {}
for o in traded_orders:
    sym = o.get('tradingsymbol')
    if sym not in traded_by_symbol:
        traded_by_symbol[sym] = []
    traded_by_symbol[sym].append(o)

print("\nAll Traded Scripts Today:")
for sym, ords in sorted(traded_by_symbol.items()):
    details = []
    total_buy_qty = sum(int(o.get('filled_quantity', 0)) for o in ords if o.get('transaction_type') == 'BUY')
    total_sell_qty = sum(int(o.get('filled_quantity', 0)) for o in ords if o.get('transaction_type') == 'SELL')
    buy_prices = [float(o.get('average_price', 0)) for o in ords if o.get('transaction_type') == 'BUY']
    sell_prices = [float(o.get('average_price', 0)) for o in ords if o.get('transaction_type') == 'SELL']
    avg_buy = sum(buy_prices) / len(buy_prices) if buy_prices else 0.0
    avg_sell = sum(sell_prices) / len(sell_prices) if sell_prices else 0.0
    print(f"  {sym:<25} | BuyQty: {total_buy_qty:<5} @ {avg_buy:<6.2f} | SellQty: {total_sell_qty:<5} @ {avg_sell:<6.2f} | Orders: {len(ords)}")
