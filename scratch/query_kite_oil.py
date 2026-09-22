import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.session import load_kite_session
from kiteconnect import KiteConnect

try:
    api_key, access_token = load_kite_session()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    print("=== KITE ORDERS TODAY ===")
    orders = kite.orders()
    oil_orders = [o for o in orders if "OIL" in str(o.get("tradingsymbol", ""))]
    for o in oil_orders:
        print(json.dumps({
            "order_id": o.get("order_id"),
            "order_timestamp": str(o.get("order_timestamp")),
            "exchange_timestamp": str(o.get("exchange_timestamp")),
            "tradingsymbol": o.get("tradingsymbol"),
            "transaction_type": o.get("transaction_type"),
            "order_type": o.get("order_type"),
            "quantity": o.get("quantity"),
            "price": o.get("price"),
            "trigger_price": o.get("trigger_price"),
            "average_price": o.get("average_price"),
            "status": o.get("status"),
            "status_message": o.get("status_message"),
            "tag": o.get("tag"),
            "variety": o.get("variety"),
            "exchange": o.get("exchange"),
            "product": o.get("product")
        }, indent=2))
        
    print("\n=== KITE POSITIONS ===")
    pos = kite.positions()
    for p in pos.get("net", []):
        if "OIL" in str(p.get("tradingsymbol", "")):
            print(json.dumps(p, indent=2))
            
    for p in pos.get("day", []):
        if "OIL" in str(p.get("tradingsymbol", "")):
            print(json.dumps(p, indent=2))
            
    print("\n=== KITE TRADES TODAY ===")
    trades = kite.trades()
    oil_trades = [t for t in trades if "OIL" in str(t.get("tradingsymbol", ""))]
    for t in oil_trades:
        print(json.dumps(t, indent=2))
        
    print("\n=== KITE GTT TRIGGERS ===")
    try:
        gtts = kite.get_gtts()
        oil_gtts = [g for g in gtts if "OIL" in str(g)]
        print(f"OIL GTTs: {oil_gtts}")
    except Exception as ge:
        print("GTT fetch error:", ge)

except Exception as e:
    print("Error connecting to Kite:", e)
