"""
Enhanced Optimization Backtest: 45-Minute High Breakout
Investigates edge filters to transform the 45m breakout into positive expectancy.
Filters tested:
1. Trend Filter: EMA20 > EMA50 on 5m
2. Candle Quality: Bullish candle body >= 50% of candle range (avoiding topping wicks)
3. Volume Confirmation: Volume >= 1.5x of 45m average
4. Strict Morning Window: Breakouts only between 10:00 AM and 11:15 AM
"""
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np
from kiteconnect import KiteConnect
from common.trading_core import load_kite_session
from common.registries import sync_stock_tokens, STOCK_REGISTRY

def get_tiered_buffer(price):
    if price < 500:
        return 0.60
    elif price < 1000:
        return 1.00
    elif price < 2000:
        return 2.00
    else:
        return 4.00

def run_filter_optimization(kite, symbols, days=35):
    to_d = date.today()
    from_d = to_d - timedelta(days=days)

    symbol_data = {}
    for sym in symbols:
        reg = STOCK_REGISTRY.get(sym, {})
        tok = reg.get("token", 0)
        lot = reg.get("lot_size", 1)
        if tok == 0:
            continue
        try:
            c = kite.historical_data(tok, from_d, to_d, "5minute")
            if c and len(c) > 200:
                df = pd.DataFrame(c)
                df['date'] = pd.to_datetime(df['date'])
                df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                df['trade_date'] = df['date'].dt.date
                symbol_data[sym] = (df, lot)
        except Exception:
            continue

    configs = [
        ("A. Baseline Raw (No Filters, T1 1.5R)", False, False, False, "12:30"),
        ("B. Morning Window Only (10:00 - 11:15 AM)", False, False, False, "11:15"),
        ("C. Morning + Volume >= 1.5x", True, False, False, "11:15"),
        ("D. Morning + Volume 1.5x + EMA Trend (EMA20 > EMA50)", True, True, False, "11:15"),
        ("E. Full Synergy: Morning + Vol 1.5x + EMA Trend + Solid Candle Body (>=50%)", True, True, True, "11:15")
    ]

    for name, req_vol, req_ema, req_body, max_entry_time in configs:
        trades = []
        for sym, (df, lot) in symbol_data.items():
            for t_date, group in df.groupby('trade_date'):
                group = group.reset_index(drop=True)
                # 45m opening range
                opening = group[(group['date'].dt.time >= datetime.strptime("09:15", "%H:%M").time()) &
                                (group['date'].dt.time < datetime.strptime("10:00", "%H:%M").time())]
                if len(opening) < 8:
                    continue
                high_45m = opening['high'].max()
                avg_vol = opening['volume'].mean()

                subsequent = group[group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time()]
                for idx, row in subsequent.iterrows():
                    c_time = row['date'].time()
                    if c_time > datetime.strptime(max_entry_time, "%H:%M").time():
                        break

                    c_open = row['open']
                    c_high = row['high']
                    c_low = row['low']
                    c_close = row['close']
                    c_vol = row['volume']
                    ema20 = row['ema20']
                    ema50 = row['ema50']

                    # Breakout condition
                    if c_close <= high_45m or c_close <= c_open:
                        continue

                    # Filter: Volume
                    if req_vol and avg_vol > 0 and c_vol < 1.5 * avg_vol:
                        continue

                    # Filter: EMA Trend
                    if req_ema and ema20 <= ema50:
                        continue

                    # Filter: Candle Body
                    c_range = c_high - c_low
                    if req_body and c_range > 0:
                        c_body = c_close - c_open
                        if (c_body / c_range) < 0.50:
                            continue

                    # SL
                    buffer = get_tiered_buffer(c_close)
                    past_slice = group.loc[:idx-1]
                    red_candles = past_slice[past_slice['close'] < past_slice['open']]
                    ref_sl = red_candles.iloc[-1]['low'] if not red_candles.empty else c_low
                    sl_price = round(ref_sl - buffer, 2)
                    risk_pts = round(c_close - sl_price, 2)

                    if risk_pts <= 0 or risk_pts > (c_close * 0.025) or risk_pts < (c_close * 0.002):
                        continue

                    target_1 = round(c_close + 1.5 * risk_pts, 2)

                    # Simulate exit
                    remaining = subsequent.loc[idx+1:]
                    exit_p = None
                    exit_r = None
                    for _, r_bar in remaining.iterrows():
                        b_low = r_bar['low']
                        b_high = r_bar['high']
                        b_time = r_bar['date'].time()
                        b_close = r_bar['close']

                        if b_low <= sl_price:
                            exit_p = sl_price
                            exit_r = "SL"
                            break
                        if b_high >= target_1:
                            exit_p = target_1
                            exit_r = "T1"
                            break
                        if b_time >= datetime.strptime("15:15", "%H:%M").time():
                            exit_p = b_close
                            exit_r = "EOD"
                            break

                    if exit_p is None:
                        exit_p = subsequent.iloc[-1]['close']
                        exit_r = "LIVE"

                    pnl_pts = round(exit_p - c_close, 2)
                    opt_pnl = round(pnl_pts * 0.50 * lot, 2)
                    trades.append({
                        "sym": sym, "pnl_pts": pnl_pts, "opt_pnl": opt_pnl, "r": round(pnl_pts / risk_pts, 2), "exit": exit_r
                    })
                    break # 1 trade per day per symbol

        tdf = pd.DataFrame(trades)
        if not tdf.empty:
            wins = tdf[tdf['pnl_pts'] > 0]
            losses = tdf[tdf['pnl_pts'] < 0]
            wr = round(len(wins) / len(tdf) * 100, 1)
            p_factor = round(wins['opt_pnl'].sum() / abs(losses['opt_pnl'].sum()), 2) if abs(losses['opt_pnl'].sum()) > 0 else 999.0
            tot_pnl = tdf['opt_pnl'].sum()
            print(f"{'-'*75}")
            print(f"CONFIGURATION: {name}")
            print(f"Trades: {len(tdf):3d} | Win Rate: {wr:4.1f}% ({len(wins)}W/{len(losses)}L) | Profit Factor: {p_factor:4.2f} | Net PnL: ₹{tot_pnl:+10,.2f}")

if __name__ == "__main__":
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    sync_stock_tokens(kite)

    target_universe = [
        "CUMMINSIND", "ADANIENT", "LAURUSLABS", "RELIANCE", "TCS", "INFY", "HDFCBANK",
        "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "TATASTEEL", "TATAMOTORS", "JSWSTEEL",
        "AXISBANK", "KOTAKBANK", "MARUTI", "M&M", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR",
        "TITAN", "NTPC", "POWERGRID", "VEDL", "COALINDIA", "BEL", "BHEL", "HAL"
    ]
    run_filter_optimization(kite, target_universe, days=35)
