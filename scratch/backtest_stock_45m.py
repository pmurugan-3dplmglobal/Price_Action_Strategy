"""
Backtest 45-Minute High Breakout Strategy
Testing peer's exact rules on CUMMINSIND, ADANIENT, and LAURUSLABS over the last 30 trading days.
"""
import sys
import os
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

def run_single_symbol_backtest(kite, symbol, token, lot_size, days=35):
    to_d = date.today()
    from_d = to_d - timedelta(days=days)
    
    candles = kite.historical_data(token, from_d, to_d, "5minute")
    if not candles:
        print(f"No candles found for {symbol}")
        return []

    df = pd.DataFrame(candles)
    df['date'] = pd.to_datetime(df['date'])
    # Calculate 9 EMA
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    
    # Group by trading date
    df['trade_date'] = df['date'].dt.date
    grouped = df.groupby('trade_date')
    
    trades = []

    for t_date, group in grouped:
        group = group.reset_index(drop=True)
        # We need candles between 09:15 and 10:00 (first 9 candles)
        # Filter by time
        opening_mask = (group['date'].dt.time >= datetime.strptime("09:15", "%H:%M").time()) & \
                       (group['date'].dt.time < datetime.strptime("10:00", "%H:%M").time())
        opening_candles = group[opening_mask]
        if len(opening_candles) < 8:
            continue
            
        high_45m = opening_candles['high'].max()
        low_45m = opening_candles['low'].min()
        
        # Scan from 10:00 AM onwards (up to 13:30 for new entries)
        trading_mask = (group['date'].dt.time >= datetime.strptime("10:00", "%H:%M").time())
        subsequent = group[trading_mask]
        
        in_trade = False
        trade = None

        for idx, row in subsequent.iterrows():
            candle_time = row['date'].time()
            c_open = row['open']
            c_high = row['high']
            c_low = row['low']
            c_close = row['close']
            c_vol = row['volume']
            ema9 = row['ema9']
            
            if not in_trade:
                # Only take new entry before 13:30
                if candle_time > datetime.strptime("13:30", "%H:%M").time():
                    break
                
                # Check 5m candle close above 45m high
                if c_close > high_45m and c_close > c_open: # Green candle breakout
                    # Find SL: lowest of previous red candle or EMA9
                    past_slice = group.loc[:idx-1]
                    red_candles = past_slice[past_slice['close'] < past_slice['open']]
                    if not red_candles.empty:
                        prev_red_low = red_candles.iloc[-1]['low']
                    else:
                        prev_red_low = c_low
                    
                    sl_ref = min(prev_red_low, ema9)
                    buffer = get_tiered_buffer(c_close)
                    sl_price = round(sl_ref - buffer, 2)
                    risk_pts = round(c_close - sl_price, 2)
                    
                    if risk_pts <= 0 or risk_pts > (c_close * 0.03):
                        continue
                    
                    target_1 = round(c_close + 1.5 * risk_pts, 2)
                    target_2 = round(c_close + 2.5 * risk_pts, 2)
                    
                    in_trade = True
                    trade = {
                        "date": str(t_date),
                        "symbol": symbol,
                        "lot_size": lot_size,
                        "entry_time": str(candle_time),
                        "high_45m": high_45m,
                        "entry_price": c_close,
                        "sl_price": sl_price,
                        "risk_pts": risk_pts,
                        "target_1": target_1,
                        "target_2": target_2,
                        "status": "OPEN",
                        "exit_price": c_close,
                        "exit_time": None,
                        "exit_reason": None,
                        "pnl_pts": 0.0,
                        "pnl_rs": 0.0,
                        "r_multiple": 0.0,
                        "max_favorable_pts": 0.0
                    }
                    continue
            else:
                # In trade, monitor exits
                favorable = c_high - trade["entry_price"]
                if favorable > trade["max_favorable_pts"]:
                    trade["max_favorable_pts"] = favorable
                
                # Check SL hit
                if c_low <= trade["sl_price"]:
                    trade["status"] = "SL_HIT"
                    trade["exit_price"] = trade["sl_price"]
                    trade["exit_time"] = str(candle_time)
                    trade["exit_reason"] = "STOP_LOSS"
                    trade["pnl_pts"] = -trade["risk_pts"]
                    trade["r_multiple"] = -1.0
                    break
                
                # Check Target 2 hit
                elif c_high >= trade["target_2"]:
                    trade["status"] = "TARGET_2_HIT"
                    trade["exit_price"] = trade["target_2"]
                    trade["exit_time"] = str(candle_time)
                    trade["exit_reason"] = "TARGET_2 (2.5R)"
                    trade["pnl_pts"] = round(trade["target_2"] - trade["entry_price"], 2)
                    trade["r_multiple"] = 2.5
                    break
                    
                # Check Target 1 hit -> Trail SL to Breakeven
                elif c_high >= trade["target_1"] and trade["sl_price"] < trade["entry_price"]:
                    trade["sl_price"] = trade["entry_price"]  # Breakeven stop
                
                # EOD Exit at 15:15
                if candle_time >= datetime.strptime("15:15", "%H:%M").time():
                    trade["status"] = "EOD_EXIT"
                    trade["exit_price"] = c_close
                    trade["exit_time"] = str(candle_time)
                    trade["exit_reason"] = "EOD_15:15"
                    trade["pnl_pts"] = round(c_close - trade["entry_price"], 2)
                    trade["r_multiple"] = round(trade["pnl_pts"] / trade["risk_pts"], 2)
                    break
        
        if trade:
            opt_pnl_pts = round(trade["pnl_pts"] * 0.50, 2)
            trade["opt_pnl_pts"] = opt_pnl_pts
            trade["opt_pnl_rs"] = round(opt_pnl_pts * lot_size, 2)
            trades.append(trade)
            
    return trades

if __name__ == "__main__":
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    sync_stock_tokens(kite)
    
    test_symbols = ["CUMMINSIND", "ADANIENT", "LAURUSLABS"]
    
    all_trades = []
    print(f"{'='*80}")
    print(f"45-MINUTE HIGH BREAKOUT BACKTEST — LAST 30 DAYS")
    print(f"{'='*80}")
    
    for sym in test_symbols:
        reg = STOCK_REGISTRY.get(sym, {})
        tok = reg.get("token")
        lot = reg.get("lot_size", 1)
        print(f"\nScanning {sym} (Token: {tok}, Lot: {lot})...")
        trades = run_single_symbol_backtest(kite, sym, tok, lot)
        all_trades.extend(trades)
        
        tdf = pd.DataFrame(trades)
        if not tdf.empty:
            cols = ["date", "entry_time", "entry_price", "sl_price", "risk_pts", "exit_price", "exit_reason", "pnl_pts", "opt_pnl_rs", "r_multiple"]
            print(tdf[cols].to_string(index=False))
            wins = len(tdf[tdf['pnl_pts'] > 0])
            losses = len(tdf[tdf['pnl_pts'] < 0])
            wr = round((wins / len(tdf)) * 100, 1) if len(tdf) > 0 else 0
            total_rs = tdf['opt_pnl_rs'].sum()
            print(f"-> Summary for {sym}: Trades: {len(tdf)}, Win Rate: {wr}% ({wins}W / {losses}L), Est. Option PnL: ₹{total_rs:,.2f}")
        else:
            print(f"-> No breakouts triggered for {sym} in this period.")
