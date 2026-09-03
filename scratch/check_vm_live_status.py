import json
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "common"))

from kiteconnect import KiteConnect
import paths
import session

def check():
    api_key, access_token = session.load_kite_session()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    pos_db_file = paths.ACTIVE_POSITIONS_DB
    if not os.path.exists(pos_db_file):
        print(f"File not found: {pos_db_file}")
        return

    pos_data = json.load(open(pos_db_file, "r", encoding="utf-8"))
    positions = pos_data.get("positions", [])
    print(f"=== Total Active Positions in DB: {len(positions)} ===")

    tokens = []
    for p in positions:
        tok = p.get("option_token") or p.get("token")
        if tok:
            tokens.append(int(tok))

    quotes = {}
    if tokens:
        try:
            quotes = kite.ltp(tokens)
        except Exception as e:
            print(f"LTP fetch error: {e}")

    # Also fetch Kite net positions
    try:
        net_pos = kite.positions().get("net", [])
        print(f"\n=== Kite Net Positions from Broker: {len(net_pos)} ===")
        for np in net_pos:
            ts = np.get("tradingsymbol")
            qty = np.get("quantity")
            pnl = np.get("pnl")
            ltp = np.get("last_price")
            b_price = np.get("buy_price") or np.get("average_price")
            print(f"  [Kite Position] {ts} | Qty: {qty} | AvgBuy: {b_price} | LTP: {ltp} | PnL: {pnl}")
    except Exception as e:
        print(f"Kite positions() fetch error: {e}")

    print("\n=== System Active Positions Analysis ===")
    for p in positions:
        sym = p.get("symbol")
        contract = p.get("contract") or sym
        tok = p.get("option_token") or p.get("token")
        entry = float(p.get("entry_spot") or p.get("entry_price") or 0.0)
        sl = float(p.get("current_sl") or 0.0)
        t1 = float(p.get("t1") or 0.0)
        t2 = float(p.get("t2") or 0.0)
        t3 = float(p.get("t3") or 0.0)
        stage = p.get("trailing_stage")
        engine = p.get("engine")
        created_at = p.get("created_at")

        ltp = 0.0
        if tok and int(tok) in quotes:
            ltp = float(quotes[int(tok)].get("last_price", 0.0))
        elif tok and str(tok) in quotes:
            ltp = float(quotes[str(tok)].get("last_price", 0.0))

        sl_breached = (ltp <= sl) if (ltp > 0 and sl > 0) else False
        pnl_pct = ((ltp - entry) / entry * 100) if (entry > 0 and ltp > 0) else 0.0

        print(f"\nSymbol: {sym} | Contract: {contract} | Engine: {engine}")
        print(f"  Token: {tok} | CreatedAt: {created_at} | TrailingStage: {stage}")
        print(f"  Entry: {entry:.2f} | Current SL: {sl:.2f} | Live LTP: {ltp:.2f} | PnL%: {pnl_pct:.2f}%")
        print(f"  Targets: T1={t1:.2f}, T2={t2:.2f}, T3={t3:.2f}")
        print(f"  SL Breached based on Live LTP? {'>>> YES, BREACHED <<<' if sl_breached else 'NO (LTP above SL)'}")

if __name__ == "__main__":
    check()
