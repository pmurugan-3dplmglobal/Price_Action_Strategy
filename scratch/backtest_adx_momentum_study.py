"""
30-Day Quantitative Backtest Study: ADX and Stock Momentum Integration
Evaluates 45-Minute Breakouts on F&O Stocks across the last 30 trading days (~35 calendar days).
Compares 6 distinct configurations:
1. Baseline Raw (No ADX, No Momentum)
2. ADX Filter Only (+DI >= 26.0, +DI > -DI)
3. ADX Trend Strength (+DI >= 26.0, ADX >= 25.0)
4. Stock Momentum Only (EMA13 > EMA44, Price > VWAP, RSI >= 55)
5. ADX + Stock Momentum Confluence (+DI >= 26, ADX >= 20, EMA13 > EMA44, Price > VWAP)
6. Full Institutional Synergy (ADX >= 20, +DI >= 26, EMA13 > EMA44, VWAP, Vol >= 1.5x, Morning Window)
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

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs)).fillna(50)

def calculate_intraday_vwap(df: pd.DataFrame) -> pd.Series:
    pv = (df['close'] * df['volume']).cumsum()
    vol = df['volume'].cumsum()
    return pv / vol.replace(0, np.nan)

def get_tiered_buffer(price):
    if price < 500:
        return 0.60
    elif price < 1000:
        return 1.00
    elif price < 2000:
        return 2.00
    else:
        return 4.00

def run_study():
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

    to_d = date.today()
    from_d = to_d - timedelta(days=35)

    print(f"Fetching 30-day 5m data for {len(target_universe)} symbols...")
    data_store = {}
    for sym in target_universe:
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
                
                # Indicators
                plus_di, minus_di, adx = calculate_dmi(df, period=14)
                df['plus_di'] = plus_di
                df['minus_di'] = minus_di
                df['adx'] = adx
                df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()
                df['ema44'] = df['close'].ewm(span=44, adjust=False).mean()
                df['rsi'] = calculate_rsi(df['close'], 14)
                
                # Calculate daily intraday VWAP per day
                df['vwap'] = df.groupby('trade_date', group_keys=False).apply(calculate_intraday_vwap)
                data_store[sym] = (df, lot)
        except Exception as e:
            continue

    print(f"Successfully processed {len(data_store)} liquid symbols.")
    print("=" * 85)
    print("30-DAY BACKTEST RESULTS: IMPACT OF ADX & STOCK MOMENTUM FILTERS")
    print("=" * 85)

    scenarios = [
        {
            "id": 1,
            "name": "1. Baseline Raw (Peer Rule: No ADX, No Momentum)",
            "use_adx": False,
            "adx_min": 0,
            "use_momentum": False,
            "use_vol": False,
            "max_time": "13:30"
        },
        {
            "id": 2,
            "name": "2. ADX Filter Only (+DI >= 26.0 and +DI > -DI)",
            "use_adx": True,
            "adx_min": 0,
            "use_momentum": False,
            "use_vol": False,
            "max_time": "13:30"
        },
        {
            "id": 3,
            "name": "3. ADX Trend Strength (+DI >= 26.0 and ADX >= 25.0)",
            "use_adx": True,
            "adx_min": 25,
            "use_momentum": False,
            "use_vol": False,
            "max_time": "13:30"
        },
        {
            "id": 4,
            "name": "4. Stock Momentum Only (EMA13 > EMA44 + Price > VWAP + RSI >= 55)",
            "use_adx": False,
            "adx_min": 0,
            "use_momentum": True,
            "use_vol": False,
            "max_time": "13:30"
        },
        {
            "id": 5,
            "name": "5. ADX + Stock Momentum Confluence (+DI >= 26, ADX >= 20, EMA13 > 44, VWAP)",
            "use_adx": True,
            "adx_min": 20,
            "use_momentum": True,
            "use_vol": False,
            "max_time": "13:30"
        },
        {
            "id": 6,
            "name": "6. Institutional Synergy (ADX >= 20, +DI >= 26, Momentum, Vol >= 1.5x, 10:00-11:15 AM)",
            "use_adx": True,
            "adx_min": 20,
            "use_momentum": True,
            "use_vol": True,
            "max_time": "11:15"
        }
    ]

    summary_rows = []

    for sc in scenarios:
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
                avg_vol = opening['volume'].mean()

                subsequent = group[group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time()]
                for idx, row in subsequent.iterrows():
                    c_time = row['date'].time()
                    if c_time > datetime.strptime(sc['max_time'], "%H:%M").time():
                        break

                    c_open = row['open']
                    c_high = row['high']
                    c_low = row['low']
                    c_close = row['close']
                    c_vol = row['volume']
                    plus_di = row['plus_di']
                    minus_di = row['minus_di']
                    adx_val = row['adx']
                    ema13 = row['ema13']
                    ema44 = row['ema44']
                    vwap_val = row['vwap']
                    rsi_val = row['rsi']

                    # 1. 45m Breakout Condition
                    if c_close <= high_45m or c_close <= c_open:
                        continue

                    # 2. ADX Filter
                    if sc['use_adx']:
                        if plus_di < 26.0 or plus_di <= minus_di:
                            continue
                        if sc['adx_min'] > 0 and adx_val < sc['adx_min']:
                            continue

                    # 3. Stock Momentum Filter
                    if sc['use_momentum']:
                        if ema13 <= ema44:
                            continue
                        if c_close <= vwap_val:
                            continue
                        if rsi_val < 55.0:
                            continue

                    # 4. Volume Surge Filter
                    if sc['use_vol']:
                        if avg_vol > 0 and c_vol < 1.5 * avg_vol:
                            continue

                    # Stop-Loss
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
                    r_multiple = round(pnl_pts / risk_pts, 2)
                    # Option translation (Delta ~ 0.50)
                    opt_pnl_pts = round(pnl_pts * 0.50, 2)
                    opt_pnl_rs = round(opt_pnl_pts * lot, 2)

                    trades.append({
                        "date": t_date,
                        "sym": sym,
                        "pnl_pts": pnl_pts,
                        "r_mult": r_multiple,
                        "opt_pnl_rs": opt_pnl_rs,
                        "exit": exit_reason
                    })
                    break # Take first breakout per symbol per day

        tdf = pd.DataFrame(trades)
        if not tdf.empty:
            total_trades = len(tdf)
            wins = tdf[tdf['pnl_pts'] > 0]
            losses = tdf[tdf['pnl_pts'] < 0]
            be = tdf[tdf['pnl_pts'] == 0]
            win_rate = round((len(wins) / total_trades) * 100, 1)
            gross_profit = wins['opt_pnl_rs'].sum()
            gross_loss = abs(losses['opt_pnl_rs'].sum())
            profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0
            net_pnl = tdf['opt_pnl_rs'].sum()
            avg_win = round(wins['opt_pnl_rs'].mean(), 0) if len(wins) > 0 else 0
            avg_loss = round(abs(losses['opt_pnl_rs'].mean()), 0) if len(losses) > 0 else 0
            avg_r = round(tdf['r_mult'].mean(), 2)

            # Max Drawdown calculation
            tdf['cum_pnl'] = tdf['opt_pnl_rs'].cumsum()
            tdf['peak'] = tdf['cum_pnl'].cummax()
            tdf['drawdown'] = tdf['peak'] - tdf['cum_pnl']
            max_dd = round(tdf['drawdown'].max(), 2)

            summary_rows.append({
                "Scenario": sc['name'],
                "Trades": total_trades,
                "Win Rate": f"{win_rate}%",
                "W / L / BE": f"{len(wins)} / {len(losses)} / {len(be)}",
                "Profit Factor": profit_factor,
                "Avg Win (₹)": f"₹{avg_win:,.0f}",
                "Avg Loss (₹)": f"₹{avg_loss:,.0f}",
                "Avg R": f"{avg_r:+.2f}R",
                "Max DD (₹)": f"₹{max_dd:,.0f}",
                "Net P&L (₹)": f"₹{net_pnl:+,.2f}"
            })

            print(f"\n[{sc['name']}]")
            print(f"Trades: {total_trades:3d} | Win Rate: {win_rate:4.1f}% ({len(wins)}W/{len(losses)}L/{len(be)}BE)")
            print(f"Profit Factor: {profit_factor:4.2f} | Avg R-Multiple: {avg_r:+.2f}R | Max Drawdown: ₹{max_dd:,.0f}")
            print(f"Avg Win: ₹{avg_win:,.0f} | Avg Loss: ₹{avg_loss:,.0f} | Net P&L: ₹{net_pnl:+12,.2f}")

    print("\n" + "=" * 85)
    print("EXECUTIVE SUMMARY TABLE (1 LOT PER TRADE)")
    print("=" * 85)
    sum_df = pd.DataFrame(summary_rows)
    print(sum_df[['Scenario', 'Trades', 'Win Rate', 'Profit Factor', 'Avg R', 'Max DD (₹)', 'Net P&L (₹)']].to_string(index=False))

if __name__ == "__main__":
    run_study()
