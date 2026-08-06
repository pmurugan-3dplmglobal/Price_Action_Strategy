import os
import sys
import json
import time
import pandas as pd
from datetime import datetime as dt, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append('common')
sys.path.append('Trade_Stock')

from trading_core import (
    load_kite_session,
    fetch_and_resample_candles,
    scan_anchor_bcd_breakout,
    scan_anchor_bcd_breakout_bearish,
    STOCK_REGISTRY
)
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

ref_now = dt.now()
from_date = (ref_now - timedelta(days=100)).strftime("%Y-%m-%d")
to_date = ref_now.strftime("%Y-%m-%d")

def process_stock(symbol, config):
    token = config["token"]
    stock_trades = []
    
    for tf in ["day", "30minute"]:
        try:
            df_spot = fetch_and_resample_candles(kite, token, (ref_now - timedelta(days=200)).strftime("%Y-%m-%d"), to_date, tf)
            if df_spot is None or df_spot.empty or len(df_spot) < 15:
                continue

            window_df = df_spot[df_spot['date'] >= from_date]
            if window_df.empty:
                continue

            # Sample Candidate Endpoints to avoid scanning 1500 times per stock
            step = 1 if tf == "day" else max(1, len(window_df) // 40)
            candidate_indices = range(max(4, window_df.index[0]), window_df.index[-1] + 1, step)

            for cand_idx in candidate_indices:
                sub_df = df_spot.iloc[: cand_idx + 1]
                
                # Check Bullish Setup
                bull_res = scan_anchor_bcd_breakout(sub_df, sub_df)
                if bull_res:
                    d_time_str = str(bull_res.get("CandleTime") or sub_df.iloc[-1]['date'])
                    d_date = d_time_str[:10]
                    if from_date <= d_date <= to_date:
                        if not any(t["Symbol"] == symbol and t["Side"] == "BULL" and t["D_Time"] == d_time_str for t in stock_trades):
                            stock_trades.append({
                                "Symbol": symbol,
                                "Side": "BULL",
                                "TF": tf,
                                "Pattern": bull_res["Pattern"],
                                "D_Time": d_time_str,
                                "Entry": bull_res["Close"],
                                "SL": bull_res["SL"],
                                "T1": bull_res["T1"],
                                "T2": bull_res.get("T2"),
                                "T3": bull_res.get("T3"),
                                "cand_idx": cand_idx,
                                "df_ref": df_spot
                            })

                # Check Bearish Setup
                bear_res = scan_anchor_bcd_breakout_bearish(sub_df, sub_df)
                if bear_res:
                    d_time_str = str(bear_res.get("CandleTime") or sub_df.iloc[-1]['date'])
                    d_date = d_time_str[:10]
                    if from_date <= d_date <= to_date:
                        if not any(t["Symbol"] == symbol and t["Side"] == "BEAR" and t["D_Time"] == d_time_str for t in stock_trades):
                            stock_trades.append({
                                "Symbol": symbol,
                                "Side": "BEAR",
                                "TF": tf,
                                "Pattern": bear_res["Pattern"],
                                "D_Time": d_time_str,
                                "Entry": bear_res["Close"],
                                "SL": bear_res["SL"],
                                "T1": bear_res["T1"],
                                "T2": bear_res.get("T2"),
                                "T3": bear_res.get("T3"),
                                "cand_idx": cand_idx,
                                "df_ref": df_spot
                            })
        except Exception:
            continue
            
    return stock_trades

def main():
    t0 = time.time()
    print("=" * 125)
    print(f"      PRICE ACTION STRATEGY — FAST 100-DAY STOCK SPOT BACKTEST ({from_date} to {to_date})")
    print("=" * 125 + "\n")

    all_spot_trades = []
    
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(process_stock, sym, cfg): sym for sym, cfg in STOCK_REGISTRY.items()}
        for f in as_completed(futures):
            sym = futures[f]
            try:
                res = f.result()
                if res:
                    all_spot_trades.extend(res)
            except Exception as e:
                pass

    print(f"Total Spot Setups Detected over 100 Days: {len(all_spot_trades)}\n")

    pattern_metrics = {}

    for t in all_spot_trades:
        pat = t["Pattern"]
        side = t["Side"]
        entry_p = float(t["Entry"])
        sl_p = float(t["SL"])
        t1_p = float(t["T1"])
        t2_p = float(t["T2"]) if t.get("T2") else None
        t3_p = float(t["T3"]) if t.get("T3") else None
        df_spot = t["df_ref"]
        cand_idx = t["cand_idx"]

        if pat not in pattern_metrics:
            pattern_metrics[pat] = {"total": 0, "wins": 0, "losses": 0, "active": 0, "pnl_list": []}
        pattern_metrics[pat]["total"] += 1

        post_df = df_spot.iloc[cand_idx + 1:]
        outcome = "ACTIVE"
        pnl = 0.0

        if not post_df.empty:
            for idx, row in post_df.iterrows():
                low = float(row['low'])
                high = float(row['high'])
                close = float(row['close'])

                if side == "BULL":
                    if close <= sl_p or low <= sl_p:
                        outcome = "SL_HIT"
                        pnl = round((sl_p - entry_p) / entry_p * 100, 2)
                        break
                    if t3_p and high >= t3_p:
                        outcome = "T3_HIT"
                        pnl = round((t3_p - entry_p) / entry_p * 100, 2)
                        break
                    if t2_p and high >= t2_p:
                        outcome = "T2_HIT"
                        pnl = round((t2_p - entry_p) / entry_p * 100, 2)
                        break
                    if high >= t1_p:
                        outcome = "T1_HIT"
                        pnl = round((t1_p - entry_p) / entry_p * 100, 2)
                        break
                else: # BEAR
                    if close >= sl_p or high >= sl_p:
                        outcome = "SL_HIT"
                        pnl = round((entry_p - sl_p) / entry_p * 100, 2)
                        break
                    if t3_p and low <= t3_p:
                        outcome = "T3_HIT"
                        pnl = round((entry_p - t3_p) / entry_p * 100, 2)
                        break
                    if t2_p and low <= t2_p:
                        outcome = "T2_HIT"
                        pnl = round((entry_p - t2_p) / entry_p * 100, 2)
                        break
                    if low <= t1_p:
                        outcome = "T1_HIT"
                        pnl = round((entry_p - t1_p) / entry_p * 100, 2)
                        break

        t["Outcome"] = outcome
        t["PnL_Pct"] = pnl

        if "HIT" in outcome:
            pattern_metrics[pat]["wins"] += 1
            pattern_metrics[pat]["pnl_list"].append(pnl)
        elif outcome == "SL_HIT":
            pattern_metrics[pat]["losses"] += 1
            pattern_metrics[pat]["pnl_list"].append(pnl)
        else:
            pattern_metrics[pat]["active"] += 1

    print("=" * 125)
    print("              100-DAY STOCK SPOT ENGINE — PATTERN WIN RATE & RELIABILITY TABLE")
    print("=" * 125)
    print(f"{'Pattern Name':<25} | {'Total':<6} | {'Wins (T1+)':<10} | {'Losses (SL)':<11} | {'Active':<8} | {'Win Rate %':<10} | {'Avg Win P&L %'}")
    print("-" * 125)

    total_wins = 0
    total_losses = 0
    total_active = 0

    for pat, stats in sorted(pattern_metrics.items(), key=lambda x: x[1]["total"], reverse=True):
        completed = stats["wins"] + stats["losses"]
        wr = (stats["wins"] / completed * 100) if completed > 0 else 0.0
        avg_pnl = round(sum(stats["pnl_list"]) / len(stats["pnl_list"]), 2) if stats["pnl_list"] else 0.0
        
        total_wins += stats["wins"]
        total_losses += stats["losses"]
        total_active += stats["active"]
        
        print(f"{pat:<25} | {stats['total']:<6} | {stats['wins']:<10} | {stats['losses']:<11} | {stats['active']:<8} | {wr:<10.2f}% | {avg_pnl:+.2f}%")

    print("-" * 125)
    overall_completed = total_wins + total_losses
    overall_wr = (total_wins / overall_completed * 100) if overall_completed > 0 else 0.0
    print(f"  • OVERALL SPOT METRICS: Total Trades: {len(all_spot_trades)} | Completed: {overall_completed} | Wins: {total_wins} | Losses: {total_losses} | Active: {total_active} | OVERALL WIN RATE: {overall_wr:.2f}%")
    print("=" * 125 + "\n")

    print(f"Finished in {time.time() - t0:.2f} seconds!")

if __name__ == "__main__":
    main()
