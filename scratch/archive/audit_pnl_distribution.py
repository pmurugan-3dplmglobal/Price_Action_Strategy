import sys
import os
import sqlite3
import json
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("=== P&L AUDIT IN TRADES.SQLITE3 ===")
conn = sqlite3.connect("output/monitor/trades.sqlite3")
c = conn.cursor()
c.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades")
rows = c.fetchall()
conn.close()

trades = []
for r in rows:
    tid, eng, sym, cnt, stat, cat, uat, dj_str = r
    dj = json.loads(dj_str) if dj_str else {}
    pnl = dj.get("pnl")
    pnl_pct = dj.get("pnl_percent") or dj.get("pnl_pct")
    exit_reason = dj.get("exit_reason")
    entry_p = dj.get("entry_price") or dj.get("entry_spot")
    exit_p = dj.get("exit_price")
    trades.append({
        "id": tid, "engine": eng, "symbol": sym, "contract": cnt,
        "status": stat, "created_at": cat, "updated_at": uat,
        "pnl": pnl, "pnl_pct": pnl_pct, "exit_reason": exit_reason,
        "entry_price": entry_p, "exit_price": exit_p
    })

df = pd.DataFrame(trades)
print(f"Total trades recorded: {len(df)}")
closed = df[df["status"].isin(["COMPLETED", "CLOSED", "CLOSED_EXTERNALLY", "SL_HIT", "TARGET_HIT"])]
print(f"Closed trades: {len(closed)}")

# Filter trades with numeric pnl
pnl_trades = []
for t in trades:
    p = t.get("pnl")
    if p is not None:
        try:
            pnl_trades.append({**t, "pnl_num": float(p)})
        except:
            pass

df_pnl = pd.DataFrame(pnl_trades)
print(f"Trades with recorded PnL: {len(df_pnl)}")
if not df_pnl.empty:
    winners = df_pnl[df_pnl["pnl_num"] > 0]
    losers = df_pnl[df_pnl["pnl_num"] < 0]
    print(f"Winners: {len(winners)} (Total +Rs {winners['pnl_num'].sum():.2f}, Avg +Rs {winners['pnl_num'].mean():.2f})")
    print(f"Losers: {len(losers)} (Total -Rs {abs(losers['pnl_num'].sum()):.2f}, Avg -Rs {losers['pnl_num'].mean():.2f})")
    print(f"Net PnL: Rs {df_pnl['pnl_num'].sum():.2f}")

print("\n=== TODAY'S BROKER POSITIONS AUDIT ===")
# Look at the positions that user showed earlier:
# BHARTIARTL26OCT1780CE | PnL: +593.75
# COALINDIA26OCT420PE | PnL: -742.50
# ULTRACEMCO26OCT10900PE | PnL: +1320.00
# SENSEX26O0172600CE | PnL: -135.00
# ADANIPORTS26OCT1780CE | PnL: +1496.25
# INFY26OCT1000CE | PnL: -3000.00
# NIFTY26SEP22500CE | PnL: +7159.75 (MANUAL BOT SAVER)
# NIFTY26SEP22600CE | PnL: -975.00
# NTPC26OCT320CE | PnL: +1725.00
# SBILIFE26OCT1720PE | PnL: -1537.50
# SBIN26OCT960CE | PnL: -3112.50
# SHRIRAMFIN26OCT980CE | PnL: +2021.25
# VEDL26OCT260CE | PnL: -1840.00
