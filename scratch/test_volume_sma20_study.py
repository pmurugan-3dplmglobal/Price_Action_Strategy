"""
Quantitative Backtest Study: 'High Volume Relative to Last 20 Candles' Filter
Tests whether selecting ANY random stock where breakout candle volume is significantly
higher than its 20-candle volume moving average produces positive expectancy.

Configurations tested:
1. Baseline Raw (Any random stock, no volume check)
2. Vol Surge 1.2x (Breakout Vol > 1.2 * SMA20_Vol)
3. Vol Surge 1.5x (Breakout Vol > 1.5 * SMA20_Vol)
4. Vol Surge 2.0x (Breakout Vol > 2.0 * SMA20_Vol)
5. Vol Surge 2.0x + ADX >= 20 (+DI >= 26)
6. Vol Surge 2.0x + ADX >= 20 + EMA Trend (EMA13 > EMA44)
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
from common.trap_adx_engine import calculate_dmi

def get_tiered_buffer(price):
    if price < 500:
        return 0.60
    elif price < 1000:
        return 1.00
    elif price < 2000:
        return 2.00
    else:
        return 4.00

def run_volume_study():
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    sync_stock_tokens(kite)

    # Broad universe of 50 diversified F&O stocks across sectors
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

    print(f"Fetching 30-day 5m data for {len(universe)} F&O symbols...")
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
                
                # 20-candle Volume Moving Average
                df['vol_sma20'] = df['volume'].rolling(window=20).mean()
                
                # Indicators
                plus_di, minus_di, adx = calculate_dmi(df, period=14)
                df['plus_di'] = plus_di
                df['minus_di'] = minus_di
                df['adx'] = adx
                df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()
                df['ema44'] = df['close'].ewm(span=44, adjust=False).mean()
                
                data_store[sym] = (df, lot)
        except Exception:
            continue

    print(f"Loaded {len(data_store)} valid symbols. Running volume simulation across 30 days...\n")

    configs = [
        {"name": "1. Baseline (Any stock, No Volume Rule)", "vol_mult": 0.0, "use_adx": False, "use_ema": False},
        {"name": "2. Vol Surge > 1.2x SMA20 (Breakout Vol > 1.2 * SMA20)", "vol_mult": 1.2, "use_adx": False, "use_ema": False},
        {"name": "3. Vol Surge > 1.5x SMA20 (Breakout Vol > 1.5 * SMA20)", "vol_mult": 1.5, "use_adx": False, "use_ema": False},
        {"name": "4. Vol Surge > 2.0x SMA20 (Institutional Vol Spike > 2.0x)", "vol_mult": 2.0, "use_adx": False, "use_ema": False},
        {"name": "5. Vol Surge > 2.0x + ADX >= 20 (+DI >= 26)", "vol_mult": 2.0, "use_adx": True, "use_ema": False},
        {"name": "6. Vol Surge > 2.0x + ADX >= 20 + EMA13 > EMA44", "vol_mult": 2.0, "use_adx": True, "use_ema": True}
    ]

    summary_rows = []

    for cfg in configs:
        trades = []
        for sym, (df, lot) in data_store.items():
            for t_date, group in df.groupby('trade_date'):
                group = group.reset_index(drop=True)
                # 45m opening range (09:15 to 10:00)
                opening = group[(group['date'].dt.time >= datetime.strptime("09:15", "%H:%M").time()) &
                                (group['date'].dt.time < datetime.strptime("10:00", "%H:%M").time())]
                if len(opening) < 8:
                    continue
                high_45m = opening['high'].max()

                subsequent = group[group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time()]
                for idx, row in subsequent.iterrows():
                    c_time = row['date'].time()
                    if c_time > datetime.strptime("12:30", "%H:%M").time():
                        break

                    c_open = row['open']
                    c_high = row['high']
                    c_low = row['low']
                    c_close = row['close']
                    c_vol = row['volume']
                    vol_sma20 = row['vol_sma20']
                    plus_di = row['plus_di']
                    minus_di = row['minus_di']
                    adx_val = row['adx']
                    ema13 = row['ema13']
                    ema44 = row['ema44']

                    # 1. 45m Breakout Condition
                    if c_close <= high_45m or c_close <= c_open:
                        continue

                    # 2. Volume relative to 20-candle SMA
                    if cfg['vol_mult'] > 0:
                        if pd.isna(vol_sma20) or vol_sma20 <= 0 or c_vol < (cfg['vol_mult'] * vol_sma20):
                            continue

                    # 3. ADX Filter
                    if cfg['use_adx']:
                        if plus_di < 26.0 or plus_di <= minus_di or adx_val < 20.0:
                            continue

                    # 4. EMA Trend
                    if cfg['use_ema']:
                        if ema13 <= ema44:
                            continue

                    # Determine SL
                    buffer = get_tiered_buffer(c_close)
                    past_slice = group.loc[:idx-1]
                    red_candles = past_slice[past_slice['close'] < past_slice['open']]
                    ref_sl = red_candles.iloc[-1]['low'] if not red_candles.empty else c_low
                    sl_price = round(ref_sl - buffer, 2)
                    risk_pts = round(c_close - sl_price, 2)

                    if risk_pts <= 0 or risk_pts > (c_close * 0.025) or risk_pts < (c_close * 0.002):
                        continue

                    target_1 = round(c_close + 1.5 * risk_pts, 2)

                    # Simulate trade outcome
                    remaining = subsequent.loc[idx+1:]
                    exit_p = None
                    exit_reason = None
                    for _, r_bar in remaining.iterrows():
                        b_low = r_bar['low']
                        b_high = r_bar['high']
                        b_time = r_bar['date'].time()
                        b_close = r_bar['close']

                        if b_low <= sl_price:
                            exit_p = sl_price
                            exit_reason = "SL"
                            break
                        if b_high >= target_1:
                            exit_p = target_1
                            exit_reason = "T1"
                            break
                        if b_time >= datetime.strptime("15:15", "%H:%M").time():
                            exit_p = b_close
                            exit_reason = "EOD"
                            break

                    if exit_p is None:
                        exit_p = subsequent.iloc[-1]['close']
                        exit_reason = "LIVE"

                    pnl_pts = round(exit_p - c_close, 2)
                    r_mult = round(pnl_pts / risk_pts, 2)
                    opt_pnl_pts = round(pnl_pts * 0.50, 2)
                    opt_pnl_rs = round(opt_pnl_pts * lot, 2)

                    trades.append({
                        "date": t_date,
                        "sym": sym,
                        "pnl_pts": pnl_pts,
                        "r_mult": r_mult,
                        "opt_pnl_rs": opt_pnl_rs,
                        "exit": exit_reason
                    })
                    break # Take 1 trade per symbol per day

        tdf = pd.DataFrame(trades)
        if not tdf.empty:
            total = len(tdf)
            wins = tdf[tdf['pnl_pts'] > 0]
            losses = tdf[tdf['pnl_pts'] < 0]
            be = tdf[tdf['pnl_pts'] == 0]
            win_rate = round((len(wins) / total) * 100, 1)
            gross_win = wins['opt_pnl_rs'].sum()
            gross_loss = abs(losses['opt_pnl_rs'].sum())
            p_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else 999.0
            net_pnl = tdf['opt_pnl_rs'].sum()
            avg_win = round(wins['opt_pnl_rs'].mean(), 0) if len(wins) > 0 else 0
            avg_loss = round(abs(losses['opt_pnl_rs'].mean()), 0) if len(losses) > 0 else 0
            avg_r = round(tdf['r_mult'].mean(), 2)

            tdf['cum_pnl'] = tdf['opt_pnl_rs'].cumsum()
            tdf['peak'] = tdf['cum_pnl'].cummax()
            tdf['dd'] = tdf['peak'] - tdf['cum_pnl']
            max_dd = round(tdf['dd'].max(), 0)

            summary_rows.append({
                "Configuration": cfg['name'],
                "Trades": total,
                "Win Rate": f"{win_rate}%",
                "Wins / Losses": f"{len(wins)}W / {len(losses)}L",
                "Profit Factor": p_factor,
                "Avg Win": f"₹{avg_win:,.0f}",
                "Avg Loss": f"₹{avg_loss:,.0f}",
                "Max DD": f"₹{max_dd:,.0f}",
                "Net P&L (1 Lot)": f"₹{net_pnl:+,.2f}"
            })

            print(f"[{cfg['name']}]")
            print(f"Trades: {total:3d} | Win Rate: {win_rate:4.1f}% ({len(wins)}W / {len(losses)}L)")
            print(f"Profit Factor: {p_factor:4.2f} | Avg R: {avg_r:+.2f}R | Max Drawdown: ₹{max_dd:,.0f}")
            print(f"Avg Win: ₹{avg_win:,.0f} | Avg Loss: ₹{avg_loss:,.0f} | Net P&L: ₹{net_pnl:+12,.2f}\n")

    print("=" * 90)
    print("FINAL COMPARISON TABLE (50 F&O STOCKS, 30 DAYS, 1 LOT PER TRADE)")
    print("=" * 90)
    sum_df = pd.DataFrame(summary_rows)
    print(sum_df.to_string(index=False))

if __name__ == "__main__":
    run_volume_study()
