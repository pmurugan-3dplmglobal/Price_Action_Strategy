import os, sys, json
from datetime import datetime as dt, timedelta
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from session import load_kite_session
from kiteconnect import KiteConnect
from timeframe_utils import fetch_and_resample_candles
from patterns_bull import (
    find_anchor_ll_sweep,
    find_anchor_bullish_engulfing,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout
)
from patterns_bear import (
    find_anchor_hh_sweep,
    find_anchor_bearish_engulfing,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_anchor_bcd_breakout_bearish
)

def run_audit():
    api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
    kite = KiteConnect(api_key=api_k)
    kite.set_access_token(acc_t)

    instruments = kite.instruments("NSE")
    matches = [i for i in instruments if i["tradingsymbol"] == "POLYCAB"]
    if not matches:
        print("POLYCAB token not found", flush=True)
        return
    token = matches[0]["instrument_token"]

    quote = kite.quote("NSE:POLYCAB")["NSE:POLYCAB"]
    ltp = quote["last_price"]
    ohlc = quote["ohlc"]
    vol = quote["volume"]

    print("=" * 75, flush=True)
    print("               POLYCAB LIVE TELEMETRY & PRICE ACTION AUDIT", flush=True)
    print("=" * 75, flush=True)
    print(f"LTP: Rs. {ltp:.2f} | Open: {ohlc['open']:.2f} | High: {ohlc['high']:.2f} | Low: {ohlc['low']:.2f} | Prev Close: {ohlc['close']:.2f}", flush=True)
    print(f"Intraday Range: {ohlc['low']:.2f} - {ohlc['high']:.2f} ({((ohlc['high'] - ohlc['low'])/ohlc['low']*100):.2f}%)", flush=True)
    print(f"Volume: {vol:,} | Net Change: {quote['net_change']:.2f}%", flush=True)

    tf_configs = [
        ("day", 180),
        ("60minute", 15),
        ("15minute", 5),
        ("5minute", 2)
    ]

    for tf, days in tf_configs:
        to_d = dt.now().strftime("%Y-%m-%d")
        from_d = (dt.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = fetch_and_resample_candles(kite, token, from_d, to_d, tf)
        if df is None or df.empty:
            continue

        df["ema13"] = df["close"].ewm(span=13, adjust=False).mean()
        df["ema44"] = df["close"].ewm(span=44, adjust=False).mean()
        df["tr"] = np.maximum(df["high"] - df["low"], np.maximum(abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1))))
        df["atr14"] = df["tr"].rolling(14).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        ema_status = "BULLISH (13 > 44)" if last["ema13"] > last["ema44"] else "BEARISH (13 < 44)"
        ema_dist = (last["close"] - last["ema13"]) / last["ema13"] * 100

        print(f"\n--- TIMEFRAME: {tf.upper()} (Bars: {len(df)}) ---", flush=True)
        print(f"Current Bar: Open={last['open']} | High={last['high']} | Low={last['low']} | Close={last['close']}", flush=True)
        print(f"EMA 13: {last['ema13']:.2f} | EMA 44: {last['ema44']:.2f} | Trend Alignment: {ema_status}", flush=True)
        print(f"Distance to EMA13: {ema_dist:+.2f}% | ATR(14): Rs. {last['atr14']:.2f}", flush=True)

        # 10 Datta Anchors
        bull_anchors = []
        if find_anchor_ll_sweep(df): bull_anchors.append("LL Sweep (Datta Low-2)")
        if find_anchor_bullish_engulfing(df): bull_anchors.append("Bullish Engulfing")
        if find_anchor_hammer_baby(df): bull_anchors.append("Hammer Baby")
        if find_anchor_bullish_harami(df): bull_anchors.append("Bullish Harami")
        if find_anchor_two_higher_highs(df): bull_anchors.append("Two Higher Highs")

        bear_anchors = []
        if find_anchor_hh_sweep(df): bear_anchors.append("HH Sweep (Datta High-2)")
        if find_anchor_bearish_engulfing(df): bear_anchors.append("Bearish Engulfing")
        if find_anchor_shooting_star_baby(df): bear_anchors.append("Shooting Star Baby")
        if find_anchor_bearish_harami(df): bear_anchors.append("Bearish Harami")
        if find_anchor_two_lower_lows(df): bear_anchors.append("Two Lower Lows")

        print(f"Bullish Anchors Detected: {', '.join(bull_anchors) if bull_anchors else 'None'}", flush=True)
        print(f"Bearish Anchors Detected: {', '.join(bear_anchors) if bear_anchors else 'None'}", flush=True)

        # Breakout scans
        res_bull = scan_anchor_bcd_breakout(df, df, anchor_tf=tf, entry_tf=tf)
        if res_bull and res_bull.get("Pattern"):
            print(f" >>> [BULL A-B-C-D TRIGGERED]: {res_bull.get('Pattern')}", flush=True)
            print(f"     Anchor Time (A): {res_bull.get('Anchor_Time', res_bull.get('Candle_A_Time', 'N/A'))}", flush=True)
            print(f"     Benchmark Line : Rs. {res_bull.get('Benchmark', 0.0):.2f}", flush=True)
            print(f"     Floor / SL (A) : Rs. {res_bull.get('SL', 0.0):.2f}", flush=True)
            print(f"     Target 1 (T1)  : Rs. {res_bull.get('T1', res_bull.get('Target', 0.0)):.2f}", flush=True)
            print(f"     Target 2 (T2)  : Rs. {res_bull.get('T2', 0.0)}", flush=True)
            print(f"     Target 3 (T3)  : Rs. {res_bull.get('T3', 0.0)}", flush=True)
            print(f"     R:R Ratio      : {res_bull.get('RR', 0.0)}:1", flush=True)
            print(f"     Tier Rating    : {res_bull.get('tier_label', 'UNCLASSIFIED')} ({res_bull.get('tier_badge', '')})", flush=True)

        res_bear = scan_anchor_bcd_breakout_bearish(df, df, anchor_tf=tf, entry_tf=tf)
        if res_bear and res_bear.get("Pattern"):
            print(f" >>> [BEAR A-B-C-D TRIGGERED]: {res_bear.get('Pattern')}", flush=True)
            print(f"     Anchor Time (A): {res_bear.get('Anchor_Time', res_bear.get('Candle_A_Time', 'N/A'))}", flush=True)
            print(f"     Benchmark Line : Rs. {res_bear.get('Benchmark', 0.0):.2f}", flush=True)
            print(f"     Ceiling / SL(A): Rs. {res_bear.get('SL', 0.0):.2f}", flush=True)
            print(f"     Target 1 (T1)  : Rs. {res_bear.get('T1', res_bear.get('Target', 0.0)):.2f}", flush=True)
            print(f"     Target 2 (T2)  : Rs. {res_bear.get('T2', 0.0)}", flush=True)
            print(f"     R:R Ratio      : {res_bear.get('RR', 0.0)}:1", flush=True)
            print(f"     Tier Rating    : {res_bear.get('tier_label', 'UNCLASSIFIED')} ({res_bear.get('tier_badge', '')})", flush=True)

    print("\n" + "=" * 75, flush=True)

if __name__ == "__main__":
    run_audit()
