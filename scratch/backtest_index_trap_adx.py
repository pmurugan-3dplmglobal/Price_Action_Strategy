"""
30-Day Index Option Trap-ADX Backtest (NIFTY & BANKNIFTY)
Tests the peer's exact 3-condition Trap Strategy on 5-Minute Index Options:
Condition 1: Candle closes below rolling support low (Liquidity Sweep).
Condition 2: Immediate next candle closes GREEN back above support line (Reclaim).
Condition 3: DMI +DI >= 26.0 on the option chart and +DI > -DI.
Risk Cap: Strictly <= 20.0 points stop loss.
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
from common.trap_adx_engine import calculate_dmi, scan_index_option_trap

def backtest_index_traps(days=35):
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)

    nfo = pd.DataFrame(kite.instruments("NFO"))
    to_d = date.today()
    from_d = to_d - timedelta(days=days)

    print("Fetching active/recent NIFTY & BANKNIFTY weekly option contracts...")
    # Find active weekly options for NIFTY & BANKNIFTY
    contracts = []
    
    # Filter NIFTY options near ATM (e.g. 23300 to 23700)
    n_options = nfo[(nfo['name'] == 'NIFTY') & 
                    (nfo['instrument_type'].isin(['CE', 'PE'])) & 
                    (nfo['expiry'] >= to_d) & 
                    (nfo['expiry'] <= to_d + timedelta(days=14)) &
                    (nfo['strike'] >= 23200) & 
                    (nfo['strike'] <= 23800)]
    
    # Filter BANKNIFTY options near ATM (e.g. 50000 to 52000)
    bn_options = nfo[(nfo['name'] == 'BANKNIFTY') & 
                     (nfo['instrument_type'].isin(['CE', 'PE'])) & 
                     (nfo['expiry'] >= to_d) & 
                     (nfo['expiry'] <= to_d + timedelta(days=14)) &
                     (nfo['strike'] >= 50500) & 
                     (nfo['strike'] <= 52000)]

    selected = pd.concat([n_options.head(10), bn_options.head(10)])
    print(f"Selected {len(selected)} high-liquidity ATM contracts to backtest.")

    all_trades = []

    for _, row in selected.iterrows():
        tok = row['instrument_token']
        tsym = row['tradingsymbol']
        lot = row['lot_size']
        underlying = row['name']
        try:
            candles = kite.historical_data(tok, from_d, to_d, "5minute")
            if not candles or len(candles) < 50:
                continue
            df = pd.DataFrame(candles)
            df['date'] = pd.to_datetime(df['date'])
            df['trade_date'] = df['date'].dt.date
            
            pdi, mdi, adx = calculate_dmi(df, 14)
            df['plus_di'] = pdi
            df['minus_di'] = mdi
            df['adx'] = adx

            # Iterate over 5m candles to detect Trap setups
            for i in range(15, len(df) - 10):
                sub_df = df.iloc[:i+1]
                t_row = df.iloc[i]
                c_time = t_row['date'].time()
                
                # Trading window: 09:30 to 14:30
                if c_time < datetime.strptime("09:30", "%H:%M").time() or c_time > datetime.strptime("14:30", "%H:%M").time():
                    continue

                # Rolling support line: lowest close of previous 10 candles (excluding current 2)
                support_line = sub_df['close'].iloc[-12:-2].min()

                setup = scan_index_option_trap(sub_df, support_line=support_line, max_sl_points=20.0)
                if setup:
                    entry_price = setup['reclaim_close']
                    sl_price = setup['stop_loss']
                    risk_pts = setup['risk_pts']
                    t1_price = setup['target_1']
                    t2_price = setup['target_2']

                    # Check future candles for exit
                    future = df.iloc[i+1:]
                    exit_p = None
                    exit_r = None
                    for _, f_bar in future.iterrows():
                        f_low = f_bar['low']
                        f_high = f_bar['high']
                        f_time = f_bar['date'].time()
                        f_date = f_bar['date'].date()

                        # Exit if different day
                        if f_date != t_row['date'].date():
                            break

                        if f_low <= sl_price:
                            exit_p = sl_price
                            exit_r = "SL"
                            break
                        if f_high >= t1_price:
                            exit_p = t1_price
                            exit_r = "T1"
                            break
                        if f_time >= datetime.strptime("15:15", "%H:%M").time():
                            exit_p = f_bar['close']
                            exit_r = "EOD"
                            break

                    if exit_p is not None:
                        pnl_pts = round(exit_p - entry_price, 2)
                        pnl_rs = round(pnl_pts * lot, 2)
                        r_mult = round(pnl_pts / risk_pts, 2) if risk_pts > 0 else 0
                        all_trades.append({
                            "date": t_row['date'].date(),
                            "contract": tsym,
                            "underlying": underlying,
                            "entry_price": entry_price,
                            "sl_price": sl_price,
                            "risk_pts": risk_pts,
                            "plus_di": setup['plus_di'],
                            "adx": setup['adx'],
                            "exit_price": exit_p,
                            "exit_reason": exit_r,
                            "pnl_pts": pnl_pts,
                            "pnl_rs": pnl_rs,
                            "r_mult": r_mult
                        })
        except Exception as e:
            continue

    tdf = pd.DataFrame(all_trades)
    print("\n" + "=" * 85)
    print("30-DAY INDEX OPTION 5M TRAP-ADX BACKTEST RESULTS")
    print("=" * 85)
    if not tdf.empty:
        # Deduplicate trades occurring on the same candle
        tdf = tdf.drop_duplicates(subset=['date', 'contract'])
        wins = tdf[tdf['pnl_pts'] > 0]
        losses = tdf[tdf['pnl_pts'] < 0]
        tot = len(tdf)
        wr = round((len(wins) / tot) * 100, 1)
        tot_rs = tdf['pnl_rs'].sum()
        p_factor = round(wins['pnl_rs'].sum() / abs(losses['pnl_rs'].sum()), 2) if abs(losses['pnl_rs'].sum()) > 0 else 999.0
        avg_r = round(tdf['r_mult'].mean(), 2)

        print(f"Total Traps Triggered: {tot} ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Win Rate:              {wr}%")
        print(f"Profit Factor:         {p_factor}")
        print(f"Average R-Multiple:    {avg_r:+.2f}R")
        print(f"Avg Win / Loss (₹):    ₹{wins['pnl_rs'].mean():,.0f} / ₹{abs(losses['pnl_rs'].mean()):,.0f} (per 1 lot)")
        print(f"Total Net P&L:         ₹{tot_rs:+,.2f}")
        print("=" * 85)
    else:
        print("No valid trap setups found in selected sample.")

if __name__ == "__main__":
    backtest_index_traps()
