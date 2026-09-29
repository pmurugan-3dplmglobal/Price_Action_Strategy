"""
Comprehensive Backtest Engine: 45-Minute High Breakout Strategy
Evaluates 30 days of 5-minute historical data across F&O stocks.
Compares Raw vs Volume Filtered, SL formulations, and Target Exit variants.
"""
import sys
import os
import io
# Fix Windows console encoding
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

def simulate_day(group, t_date, symbol, lot_size, exit_mode="T1_1.5R", use_volume_filter=False, sl_mode="RED_LOW"):
    # 09:15 to 10:00 candles
    opening_mask = (group['date'].dt.time >= datetime.strptime("09:15", "%H:%M").time()) & \
                   (group['date'].dt.time < datetime.strptime("10:00", "%H:%M").time())
    opening = group[opening_mask]
    if len(opening) < 8:
        return None

    high_45m = opening['high'].max()
    low_45m = opening['low'].min()
    avg_vol_45m = opening['volume'].mean()

    trading_mask = (group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time())
    subsequent = group[trading_mask]

    for idx, row in subsequent.iterrows():
        c_time = row['date'].time()
        c_open = row['open']
        c_high = row['high']
        c_low = row['low']
        c_close = row['close']
        c_vol = row['volume']
        ema9 = row['ema9']

        # No new entries after 12:30 (avoid afternoon theta chop)
        if c_time > datetime.strptime("12:30", "%H:%M").time():
            break

        # Check breakout: green candle closing above 45m high
        if c_close > high_45m and c_close > c_open:
            # Volume filter check
            if use_volume_filter and avg_vol_45m > 0:
                if c_vol < 1.3 * avg_vol_45m:
                    continue

            # Determine SL
            buffer = get_tiered_buffer(c_close)
            if sl_mode == "RED_LOW":
                past_slice = group.loc[:idx-1]
                red_candles = past_slice[past_slice['close'] < past_slice['open']]
                ref_sl = red_candles.iloc[-1]['low'] if not red_candles.empty else c_low
            elif sl_mode == "CANDLE_LOW":
                ref_sl = c_low
            else: # EMA9
                ref_sl = ema9

            sl_price = round(ref_sl - buffer, 2)
            risk_pts = round(c_close - sl_price, 2)

            # Sanity guards
            if risk_pts <= 0 or risk_pts > (c_close * 0.025) or risk_pts < (c_close * 0.002):
                continue

            target_1 = round(c_close + 1.5 * risk_pts, 2)
            target_2 = round(c_close + 2.5 * risk_pts, 2)

            # Evaluate remaining candles for this day
            remaining = subsequent.loc[idx+1:]
            trade_exit_price = None
            trade_exit_reason = None
            trade_exit_time = None
            be_active = False

            for _, r_bar in remaining.iterrows():
                b_time = r_bar['date'].time()
                b_high = r_bar['high']
                b_low = r_bar['low']
                b_close = r_bar['close']

                curr_sl = c_close if be_active else sl_price

                # 1. Stop Loss check
                if b_low <= curr_sl:
                    trade_exit_price = curr_sl
                    trade_exit_reason = "BE_STOP" if be_active else "STOP_LOSS"
                    trade_exit_time = str(b_time)
                    break

                # 2. Target check
                if exit_mode == "T1_1.5R":
                    if b_high >= target_1:
                        trade_exit_price = target_1
                        trade_exit_reason = "TARGET_1 (1.5R)"
                        trade_exit_time = str(b_time)
                        break
                elif exit_mode == "T2_2.5R":
                    if b_high >= target_2:
                        trade_exit_price = target_2
                        trade_exit_reason = "TARGET_2 (2.5R)"
                        trade_exit_time = str(b_time)
                        break
                    elif b_high >= target_1:
                        be_active = True
                elif exit_mode == "SPLIT_RUNNER":
                    # 50% booked at T1, remainder trailed to BE
                    if b_high >= target_1 and not be_active:
                        be_active = True
                    if b_high >= target_2:
                        trade_exit_price = target_2
                        trade_exit_reason = "TARGET_2 (Split)"
                        trade_exit_time = str(b_time)
                        break

                # 3. EOD exit
                if b_time >= datetime.strptime("15:15", "%H:%M").time():
                    trade_exit_price = b_close
                    trade_exit_reason = "EOD_15:15"
                    trade_exit_time = str(b_time)
                    break

            if trade_exit_price is None:
                # Incomplete day (e.g. today's live session still ongoing)
                trade_exit_price = subsequent.iloc[-1]['close']
                trade_exit_reason = "LIVE_OPEN"
                trade_exit_time = str(subsequent.iloc[-1]['date'].time())

            pnl_pts = round(trade_exit_price - c_close, 2)
            r_mult = round(pnl_pts / risk_pts, 2)
            opt_pnl_pts = round(pnl_pts * 0.50, 2)
            opt_pnl_rs = round(opt_pnl_pts * lot_size, 2)

            return {
                "date": str(t_date),
                "symbol": symbol,
                "lot_size": lot_size,
                "entry_time": str(c_time),
                "entry_price": c_close,
                "sl_price": sl_price,
                "risk_pts": risk_pts,
                "exit_price": trade_exit_price,
                "exit_reason": trade_exit_reason,
                "exit_time": trade_exit_time,
                "pnl_pts": pnl_pts,
                "r_mult": r_mult,
                "opt_pnl_rs": opt_pnl_rs
            }
    return None

def run_backtest_suite(kite, symbols, days=35):
    to_d = date.today()
    from_d = to_d - timedelta(days=days)

    results_matrix = {
        "RAW_T1": [],
        "RAW_T2": [],
        "VOL_FILTER_T1": [],
        "VOL_FILTER_T2": []
    }

    print(f"Fetching 30-day 5m candles for {len(symbols)} symbols...")
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
                df['trade_date'] = df['date'].dt.date
                symbol_data[sym] = (df, lot)
        except Exception as e:
            continue

    print(f"Loaded valid data for {len(symbol_data)} symbols. Running multi-scenario simulation...\n")

    for scenario_name, (exit_m, vol_f) in [
        ("RAW_T1 (No Filter, Target 1.5R)", ("T1_1.5R", False)),
        ("RAW_T2 (No Filter, Target 2.5R + BE)", ("T2_2.5R", False)),
        ("VOL_FILTER_T1 (Vol >= 1.3x, Target 1.5R)", ("T1_1.5R", True)),
        ("VOL_FILTER_T2 (Vol >= 1.3x, Target 2.5R + BE)", ("T2_2.5R", True))
    ]:
        all_trades = []
        for sym, (df, lot) in symbol_data.items():
            for t_date, group in df.groupby('trade_date'):
                group = group.reset_index(drop=True)
                t = simulate_day(group, t_date, sym, lot, exit_mode=exit_m, use_volume_filter=vol_f)
                if t:
                    all_trades.append(t)

        tdf = pd.DataFrame(all_trades)
        if not tdf.empty:
            closed = tdf[tdf['exit_reason'] != 'LIVE_OPEN']
            wins = closed[closed['pnl_pts'] > 0]
            losses = closed[closed['pnl_pts'] < 0]
            be = closed[closed['pnl_pts'] == 0]
            total = len(closed)
            wr = round(len(wins) / total * 100, 1) if total > 0 else 0
            tot_pnl_rs = closed['opt_pnl_rs'].sum()
            avg_win = wins['opt_pnl_rs'].mean() if len(wins) > 0 else 0
            avg_loss = abs(losses['opt_pnl_rs'].mean()) if len(losses) > 0 else 0
            profit_factor = round((wins['opt_pnl_rs'].sum()) / abs(losses['opt_pnl_rs'].sum()), 2) if abs(losses['opt_pnl_rs'].sum()) > 0 else 999.0
            avg_r = round(closed['r_mult'].mean(), 2) if total > 0 else 0

            print(f"{'='*75}")
            print(f"SCENARIO: {scenario_name}")
            print(f"{'='*75}")
            print(f"Total Trades:      {total} ({len(wins)} Wins / {len(losses)} Losses / {len(be)} Breakeven)")
            print(f"Win Rate:          {wr}%")
            print(f"Avg Win / Loss:    ₹{avg_win:,.0f} / ₹{avg_loss:,.0f} (per 1 lot)")
            print(f"Profit Factor:     {profit_factor}")
            print(f"Average R-Multiple:{avg_r}R")
            print(f"Total Net P&L:     ₹{tot_pnl_rs:,.2f}")
            print(f"{'='*75}\n")

if __name__ == "__main__":
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    sync_stock_tokens(kite)

    # Top high-liquidity F&O universe (including Cummins, Adani Ent, Laurus Labs, Reliance, etc.)
    target_universe = [
        "CUMMINSIND", "ADANIENT", "LAURUSLABS", "RELIANCE", "TCS", "INFY", "HDFCBANK",
        "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "TATASTEEL", "TATAMOTORS", "JSWSTEEL",
        "AXISBANK", "KOTAKBANK", "MARUTI", "M&M", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR",
        "TITAN", "NTPC", "POWERGRID", "VEDL", "COALINDIA", "BEL", "BHEL", "HAL"
    ]
    run_backtest_suite(kite, target_universe, days=35)
