import json

with open('scratch/live_trades.json', encoding='utf-8') as f:
    trades = json.load(f).get('data', [])

with open('scratch/live_orders.json', encoding='utf-8') as f:
    orders = json.load(f).get('data', [])

with open('scratch/live_positions.json', encoding='utf-8') as f:
    positions = json.load(f).get('data', {})

print("=" * 80)
print("                       EXECUTED TRADES (FILLS)")
print("=" * 80)
for t in trades:
    print(f"Trade ID : {t.get('trade_id')}")
    print(f"Time     : {t.get('fill_timestamp')}")
    print(f"Symbol   : {t.get('tradingsymbol')} ({t.get('exchange')})")
    print(f"Action   : {t.get('transaction_type')} {t.get('quantity')} qty @ Rs {t.get('average_price'):.2f}")
    print(f"Order ID : {t.get('order_id')}")
    print("-" * 50)

print("\n" + "=" * 80)
print("                       ORDER BOOK (LIFECYCLE)")
print("=" * 80)
for o in orders:
    print(f"Order ID : {o.get('order_id')}")
    print(f"Time     : {o.get('order_timestamp')}")
    print(f"Symbol   : {o.get('tradingsymbol')} ({o.get('exchange')})")
    print(f"Type     : {o.get('transaction_type')} {o.get('order_type')} | Product: {o.get('product')}")
    print(f"Status   : {o.get('status')}")
    print(f"Tag      : {o.get('tag')}")
    print(f"Price    : Limit Rs {o.get('price')} | Avg Filled Rs {o.get('average_price')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')}")
    if o.get('status_message'):
        print(f"Status Msg: {o.get('status_message')}")
    print("-" * 50)

print("\n" + "=" * 80)
print("                       NET POSITIONS & P&L")
print("=" * 80)
total_realized_pnl = 0.0
total_unrealized_pnl = 0.0
for p in positions.get('net', []):
    qty = int(p.get('quantity', 0))
    pnl = float(p.get('pnl', 0.0))
    m2m = float(p.get('m2m', 0.0))
    buy_p = float(p.get('buy_price', 0.0))
    sell_p = float(p.get('sell_price', 0.0))
    ltp = float(p.get('last_price', 0.0))
    
    if qty == 0:
        total_realized_pnl += pnl
        pos_st = "CLOSED"
    else:
        total_unrealized_pnl += m2m
        pos_st = f"OPEN ({qty} qty)"
        
    print(f"Symbol   : {p.get('tradingsymbol')}")
    print(f"Status   : {pos_st}")
    print(f"Buy Avg  : Rs {buy_p:.2f} | Sell Avg: Rs {sell_p:.2f} | LTP: Rs {ltp:.2f}")
    print(f"Realized : Rs {pnl:,.2f} | M2M / Live: Rs {m2m:,.2f}")
    print("-" * 50)

print(f"\n>>> Total Realized P&L   : Rs {total_realized_pnl:,.2f}")
print(f">>> Total Unrealized M2M : Rs {total_unrealized_pnl:,.2f}")
print(f">>> Net Session P&L      : Rs {(total_realized_pnl + total_unrealized_pnl):,.2f}")
print("=" * 80)
