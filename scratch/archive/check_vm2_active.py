import sqlite3
import json
import os
import sys

p = "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3"
if not os.path.exists(p):
    p = os.path.join(os.path.dirname(__file__), "..", "output", "monitor", "trades.sqlite3")

con = sqlite3.connect(p)
cur = con.cursor()
cur.execute("SELECT id, symbol, contract, engine, status, created_at, data_json FROM trades WHERE status = 'ACTIVE'")
rows = cur.fetchall()
print(f"Total ACTIVE trades in SQLite (trades.sqlite3): {len(rows)}")
for r in rows:
    tid, sym, cnt, eng, st, cr, dj = r
    try:
        d = json.loads(dj)
        qty = d.get("quantity") or d.get("position_size")
    except Exception:
        qty = "unknown"
    print(f" ID: {tid} | Symbol: {sym} | Contract: {cnt} | Engine: {eng} | Qty: {qty} | Created: {cr}")

# Check broker positions & holdings
try:
    from kiteconnect import KiteConnect
    tok_p = "/home/trade/Trade_Kite/Price_Action_Strategy/input/kite_access_token.txt"
    if os.path.exists(tok_p):
        with open(tok_p) as f:
            tok_data = json.load(f)
        kite = KiteConnect(api_key=tok_data["api_key"])
        kite.set_access_token(tok_data["access_token"])
        net = kite.positions().get("net", [])
        active_broker = [bp for bp in net if bp.get("quantity", 0) != 0]
        print(f"\nLive Broker Net Positions on Kite: {len(active_broker)}")
        for bp in active_broker:
            print(f" - {bp.get('tradingsymbol')} | Qty: {bp.get('quantity')} | Product: {bp.get('product')}")
            
        holdings = kite.holdings()
        print(f"\nLive Demat CNC Holdings on Kite: {len(holdings)}")
        for h in holdings:
            print(f" - {h.get('tradingsymbol')} | Qty: {h.get('quantity')}")
            
        sys.path.insert(0, "/home/trade/Trade_Kite/Price_Action_Strategy/common")
        from portfolio_risk import evaluate_portfolio_risk
        allowed, reason, diag = evaluate_portfolio_risk(
            candidate_sym="INFY",
            engine="nifty50",
            kite=kite,
            live_positions={},
            include_db_trades=True
        )
        print(f"\nTest INFY evaluation: Allowed={allowed}, Reason={reason}")
        print(f"Active scripts in risk check: {diag.get('active_scripts')}")
except Exception as e:
    import traceback
    traceback.print_exc()
