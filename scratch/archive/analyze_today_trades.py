import json
import os
import sys

def main():
    dump_file = "scratch/today_broker_full_dump.json"
    if not os.path.exists(dump_file):
        print("Missing", dump_file)
        return

    with open(dump_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    orders = data.get("orders", [])
    positions = data.get("net_positions", [])

    print("================================================================================")
    print("                     TODAY'S KITE BROKER ORDERS (2026-09-28)")
    print("================================================================================")
    for o in orders:
        ts = str(o.get("order_timestamp", ""))
        tt = o.get("transaction_type")
        sym = o.get("tradingsymbol")
        qty = o.get("quantity")
        ap = o.get("average_price") or o.get("price")
        stat = o.get("status")
        tag = o.get("tag")
        oid = o.get("order_id")
        msg = o.get("status_message") or ""
        guid = o.get("guid") or ""
        prod = o.get("product") or ""
        ot = o.get("order_type") or ""
        var = o.get("variety") or ""
        print(f"[{ts}] {tt:<4} {sym:<24} {qty:>5} @ {ap:>8} ({ot}/{prod}/{var}) | {stat:<10} | tag={tag} | guid={guid} | oid={oid} | {msg}")

    print("\n================================================================================")
    print("                    TODAY'S KITE NET POSITIONS (2026-09-28)")
    print("================================================================================")
    total_realized_pnl = 0.0
    total_unrealized_pnl = 0.0

    for p in positions:
        qty = int(p.get("quantity", 0))
        bq = int(p.get("buy_quantity", 0))
        sq = int(p.get("sell_quantity", 0))
        if qty == 0 and bq == 0 and sq == 0:
            continue

        sym = p.get("tradingsymbol")
        bv = float(p.get("buy_value", 0.0))
        sv = float(p.get("sell_value", 0.0))
        bp = (bv / bq) if bq > 0 else 0.0
        sp = (sv / sq) if sq > 0 else 0.0
        ltp = float(p.get("last_price", 0.0))
        pnl = float(p.get("pnl", 0.0))
        m2m = float(p.get("m2m", 0.0))
        
        status = "OPEN" if qty != 0 else "CLOSED"
        if status == "CLOSED":
            total_realized_pnl += pnl
        else:
            total_unrealized_pnl += pnl

        print(f"{sym:<24} | {status:<6} | Qty: {qty:>5} (Buy: {bq} @ {bp:.2f}, Sell: {sq} @ {sp:.2f}) | LTP: {ltp:>7.2f} | PnL: Rs {pnl:>10.2f} | M2M: Rs {m2m:>10.2f}")

    print("--------------------------------------------------------------------------------")
    print(f"Total Realized P&L:   Rs {total_realized_pnl:>10.2f}")
    print(f"Total Unrealized P&L: Rs {total_unrealized_pnl:>10.2f}")
    print(f"Net Total P&L:        Rs {total_realized_pnl + total_unrealized_pnl:>10.2f}")
    print("================================================================================")

    db_dump_file = "scratch/today_vm1_trades_db.json"
    if os.path.exists(db_dump_file):
        with open(db_dump_file, "r", encoding="utf-8") as f:
            trades = json.load(f)
        print("\n================================================================================")
        print(f"               VM1 TRADES.SQLITE3 DATABASE RECORDS (Total: {len(trades)})")
        print("================================================================================")
        for t in trades:
            d = json.loads(t.get("data_json") or "{}")
            tid = t.get("id")
            eng = t.get("engine")
            sym = t.get("symbol")
            cnt = t.get("contract")
            stat = t.get("status")
            pat = d.get("pattern") or d.get("pattern_name") or "-"
            ep = d.get("entry_spot") or d.get("entry_price") or 0.0
            sl = d.get("current_sl") or 0.0
            t1 = d.get("t1") or 0.0
            xp = d.get("exit_price")
            xr = d.get("exit_reason") or "-"
            pnl_p = d.get("pnl_percent")
            pnl_inr = d.get("pnl_inr")
            tf = d.get("timeframe") or "-"
            cat = d.get("category") or d.get("tier_label") or "-"
            created = t.get("created_at") or "-"
            print(f"Trade #{tid:<3} [{stat:<10}] {eng:<8} | {sym:<12} {cnt:<22} | Pat: {pat} ({tf})")
            print(f"   Entry: {ep} | SL: {sl} | T1: {t1} | Exit: {xp} ({xr}) | PnL: {pnl_p}% (Rs {pnl_inr}) | Created: {created}")
        print("================================================================================")

if __name__ == "__main__":
    main()
