import json

def parse_yesterday_details():
    with open('scratch/live_positions.json') as f:
        pos = json.load(f)
    with open('scratch/360one_opt_candles.json') as f:
        c_360 = json.load(f)
    with open('scratch/ultracemco_opt_candles.json') as f:
        c_ultra = json.load(f)
    with open('scratch/lici_opt_candles.json') as f:
        c_lici = json.load(f)

    print("=== YESTERDAY'S CARRIED TRADES (OVERNIGHT INVENTORY) ===")
    for p in pos['data']['net']:
        if p.get('overnight_quantity', 0) > 0:
            sym = p['tradingsymbol']
            qty = p['overnight_quantity']
            buy_price = p['buy_price']
            buy_val = p['buy_value']
            close_price = p['close_price']
            yesterday_pnl = (close_price - buy_price) * qty
            print(f"Symbol: {sym}")
            print(f"  Qty: {qty}")
            print(f"  Entry Buy Avg: Rs {buy_price:.2f}")
            print(f"  Invested Capital: Rs {buy_val:,.2f}")
            print(f"  Yesterday Close: Rs {close_price:.2f}")
            print(f"  Yesterday Unrealized M2M: Rs {yesterday_pnl:,.2f} ({yesterday_pnl/buy_val*100:+.2f}%)")
            
            # Find when yesterday price hit buy_price
            candles = None
            if "360ONE" in sym:
                candles = c_360
            elif "ULTRACEMCO" in sym:
                candles = c_ultra
            elif "LICI" in sym:
                candles = c_lici
            
            if candles:
                print(f"  Yesterday Candle History for {sym}:")
                # print last 30 candles before today
                for c in candles:
                    # check if not today
                    if "2026-10-01" not in c[0]:
                        # print candles around yesterday
                        pass
                # Print yesterday's candles summary
                yest_candles = [c for c in candles if "2026-10-01" not in c[0]]
                if yest_candles:
                    print(f"    Total prior candles: {len(yest_candles)}")
                    print(f"    Prior Day Open: {yest_candles[-25][1]:.2f} | High: {max(c[2] for c in yest_candles[-25:]):.2f} | Low: {min(c[3] for c in yest_candles[-25:]):.2f} | Close: {yest_candles[-1][4]:.2f}")
                    # Find candidate entry candles matching buy_price
                    for c in yest_candles[-25:]:
                        if c[3] <= buy_price <= c[2]:
                            print(f"    --> Candidate Entry Window: {c[0]} (L:{c[3]} - H:{c[2]}) Vol:{c[5]}")

if __name__ == '__main__':
    parse_yesterday_details()
