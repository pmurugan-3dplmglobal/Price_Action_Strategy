"""
Deep Investigation: High 20-Candle Average Volume & Liquidity Tiers
Evaluates whether 'High Volume Avg of Last 20 Candles' works when defined as:
1. High Absolute Turnover (Turnover = SMA20_Vol * Price >= Rs 50 Lakhs per 5m candle)
2. Relative Volume Spike (Current Vol >= 1.5x SMA20_Vol)
3. High Liquidity Universe vs Low Liquidity Universe
"""
import sys
import os
import io

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

def run_turnover_test():
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    sync_stock_tokens(kite)

    universe = [
        "CUMMINSIND", "ADANIENT", "LAURUSLABS", "RELIANCE", "TCS", "INFY", "HDFCBANK",
        "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "TATASTEEL", "TATAMOTORS", "JSWSTEEL",
        "AXISBANK", "KOTAKBANK", "MARUTI", "M&M", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR",
        "TITAN", "NTPC", "POWERGRID", "VEDL", "COALINDIA", "BEL", "BHEL", "HAL",
        "AUROPHARMA", "BPCL", "CIPLA", "DLF", "EICHERMOT", "GRASIM", "HCLTECH",
        "HEROMOTOCO", "HINDALCO", "INDUSINDBK", "IOC", "JIOFIN", "ONGC", "PFC",
        "RECLTD", "SBICARD", "SHRIRAMFIN", "SIEMENS", "TRENT", "ULTRACEMCO", "WIPRO"
    ]

    to_d = date.today()
    from_d = to_d - timedelta(days=35)

    data_store = {}
    for sym in universe:
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
                df['trade_date'] = df['date'].dt.date
                df['vol_sma20'] = df['volume'].rolling(window=20).mean()
                df['turnover_sma20'] = df['vol_sma20'] * df['close'] # Rs per 5m candle
                from common.trap_adx_engine import calculate_dmi
                pdi, mdi, adx = calculate_dmi(df, period=14)
                df['plus_di'] = pdi
                df['minus_di'] = mdi
                df['adx'] = adx
                data_store[sym] = (df, lot)
        except Exception:
            continue

    scenarios = [
        {"name": "Tier 1: High Turnover (Avg Vol * Price >= Rs 50 Lakhs / candle)", "min_turnover": 5000000, "vol_surge": 1.5},
        {"name": "Tier 2: Ultra-High Turnover (Avg Vol * Price >= Rs 1 Crore / candle)", "min_turnover": 10000000, "vol_surge": 1.5},
        {"name": "Tier 4: Ultra-High Turnover + Morning Only (10:00 - 11:15 AM)", "min_turnover": 10000000, "vol_surge": 1.5, "max_time": "11:15"},
        {"name": "Tier 5: Ultra-High Turnover + Morning + Vol Surge 1.5x + ADX >= 20 (+DI >= 26)", "min_turnover": 10000000, "vol_surge": 1.5, "max_time": "11:15", "use_adx": True}
    ]

    print("==========================================================================================")
    print("TURNOVER & 20-CANDLE VOLUME AVERAGE BACKTEST (30 DAYS, 50 STOCKS)")
    print("==========================================================================================")

    for sc in scenarios:
        trades = []
        max_time_str = sc.get("max_time", "12:30")
        min_to = sc.get("min_turnover", 0)
        max_to = sc.get("max_turnover", float("inf"))
        surge = sc.get("vol_surge", 1.5)

        for sym, (df, lot) in data_store.items():
            for t_date, group in df.groupby('trade_date'):
                group = group.reset_index(drop=True)
                opening = group[(group['date'].dt.time >= datetime.strptime("09:15", "%H:%M").time()) &
                                (group['date'].dt.time < datetime.strptime("10:00", "%H:%M").time())]
                if len(opening) < 8:
                    continue
                high_45m = opening['high'].max()

                subsequent = group[group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time()]
                for idx, row in subsequent.iterrows():
                    c_time = row['date'].time()
                    if c_time > datetime.strptime(max_time_str, "%H:%M").time():
                        break

                    c_open = row['open']
                    c_high = row['high']
                    c_low = row['low']
                    c_close = row['close']
                    c_vol = row['volume']
                    vol_sma20 = row['vol_sma20']
                    to_sma20 = row['turnover_sma20']

                    # 1. Breakout check
                    if c_close <= high_45m or c_close <= c_open:
                        continue

                    # 2. Turnover / Baseline 20-candle Volume check
                    if pd.isna(to_sma20) or to_sma20 < min_to or to_sma20 > max_to:
                        continue

                    # 3. Surge check
                    if pd.isna(vol_sma20) or vol_sma20 <= 0 or c_vol < (surge * vol_sma20):
                        continue

                    # 4. ADX check
                    if sc.get("use_adx"):
                        pdi = row['plus_di']
                        mdi = row['minus_di']
                        adx_v = row['adx']
                        if pdi < 26.0 or pdi <= mdi or adx_v < 20.0:
                            continue

                    # SL calculation
                    buffer = get_tiered_buffer(c_close)
                    past_slice = group.loc[:idx-1]
                    red_candles = past_slice[past_slice['close'] < past_slice['open']]
                    ref_sl = red_candles.iloc[-1]['low'] if not red_candles.empty else c_low
                    sl_price = round(ref_sl - buffer, 2)
                    risk_pts = round(c_close - sl_price, 2)

                    if risk_pts <= 0 or risk_pts > (c_close * 0.025) or risk_pts < (c_close * 0.002):
                        continue

                    target_1 = round(c_close + 1.5 * risk_pts, 2)

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
                    opt_pnl_pts = round(pnl_pts * 0.50, 2)
                    opt_pnl_rs = round(opt_pnl_pts * lot, 2)
                    r_mult = round(pnl_pts / risk_pts, 2)

                    trades.append({
                        "sym": sym, "pnl_pts": pnl_pts, "opt_pnl_rs": opt_pnl_rs, "r": r_mult, "exit": exit_r
                    })
                    break

        tdf = pd.DataFrame(trades)
        if not tdf.empty:
            wins = tdf[tdf['pnl_pts'] > 0]
            losses = tdf[tdf['pnl_pts'] < 0]
            wr = round(len(wins) / len(tdf) * 100, 1)
            p_factor = round(wins['opt_pnl_rs'].sum() / abs(losses['opt_pnl_rs'].sum()), 2) if abs(losses['opt_pnl_rs'].sum()) > 0 else 999.0
            tot_pnl = tdf['opt_pnl_rs'].sum()
            avg_w = wins['opt_pnl_rs'].mean() if len(wins) > 0 else 0
            avg_l = abs(losses['opt_pnl_rs'].mean()) if len(losses) > 0 else 0
            
            print(f"[{sc['name']}]")
            print(f"Trades: {len(tdf):3d} | Win Rate: {wr:4.1f}% ({len(wins)}W / {len(losses)}L)")
            print(f"Profit Factor: {p_factor:4.2f} | Avg Win: Rs {avg_w:,.0f} | Avg Loss: Rs {avg_l:,.0f} | Net P&L: Rs {tot_pnl:+10,.2f}\n")
        else:
            print(f"[{sc['name']}]: No trades triggered.\n")

if __name__ == "__main__":
    run_turnover_test()
