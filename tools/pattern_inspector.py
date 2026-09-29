#!/usr/bin/env python3
"""
tools/pattern_inspector.py — Technical Pattern & Candlestick Geometry Diagnostic Utility.

Inspects live or recent price action candlestick geometry for any Indian equity or option contract:
  • Scans all 5 Bullish Anchors (Engulfing, LL Sweep, Hammer Baby, Harami, Two HH) + BASE_ABCD
  • Scans all 5 Bearish Anchors (Engulfing, HH Sweep, Star Baby, Harami, Two LL) + BASE_ABCD
  • Verifies exact A-B-C-D coordinates (Anchor -> Pullback -> Retracement -> Breakout Trigger)
  • Gating Audits:
      - ISSUE-086 Institutional Volume Confirmation at Point D (RVOL >= 1.2x of 20-period SMA)
      - EMA 13/44 Trend Alignment & Slope
      - Intraday VWAP Distance & Acceptance
      - Theory of Negation Targets (T1, T2, T3) and Structural Stop-Loss
      - Anti-Chase Gate & BASE_ABCD Chop Shield

Usage Examples:
  python tools/pattern_inspector.py --symbol COLPAL
  python tools/pattern_inspector.py --symbol SBILIFE --timeframe 15minute
  python tools/pattern_inspector.py --symbol MOTHERSON --timeframe 30minute --side BEAR
  python tools/pattern_inspector.py --symbol INFY --timeframe 5minute
  python tools/pattern_inspector.py --contract COLPAL26OCT1820PE
"""

import os
import sys
import argparse
from datetime import datetime as dt, timedelta
import pandas as pd
import numpy as np

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
for p in [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "common")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from paths import TOKEN_FILE
from session import load_kite_session, ensure_kite_session
from kiteconnect import KiteConnect
from registries import STOCK_REGISTRY, INDEX_REGISTRY
from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish
from targets import get_sl_buffer_distance, calculate_option_profit_targets

def compute_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


class PatternInspector:
    def __init__(self):
        self.kite = None
        self._init_kite()

    def _init_kite(self):
        try:
            ak, at = load_kite_session(TOKEN_FILE)
            self.kite = KiteConnect(api_key=ak)
            self.kite.set_access_token(at)
            ensure_kite_session(self.kite)
        except Exception as e:
            print(f"[WARN] Local KiteConnect session unavailable: {e}")
            self.kite = None

    def get_instrument_token(self, symbol):
        """Resolve instrument token for spot symbol."""
        sym_clean = symbol.upper().replace(" ", "")
        if sym_clean in STOCK_REGISTRY and STOCK_REGISTRY[sym_clean].get("token"):
            return STOCK_REGISTRY[sym_clean].get("token")
        if sym_clean in INDEX_REGISTRY and INDEX_REGISTRY[sym_clean].get("token"):
            return INDEX_REGISTRY[sym_clean].get("token")
        if sym_clean == "NIFTY":
            return INDEX_REGISTRY.get("NIFTY 50", {}).get("token", 256265)
        if sym_clean == "BANKNIFTY":
            return INDEX_REGISTRY.get("NIFTY BANK", {}).get("token", 260105)

        # Fallback to dynamic lookup via Kite
        if self.kite:
            try:
                insts = self.kite.instruments("NSE")
                for item in insts:
                    if item.get("tradingsymbol") == sym_clean:
                        return int(item.get("instrument_token"))
            except Exception as e:
                print(f"[WARN] Error in dynamic instrument token lookup: {e}")
        return None

    def fetch_candles(self, token, timeframe="15minute", days=15):
        """Fetch historical candles from Kite."""
        if not self.kite or not token:
            return pd.DataFrame()
        to_date = dt.now().strftime("%Y-%m-%d")
        from_date = (dt.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            raw = self.kite.historical_data(token, from_date, to_date, timeframe)
            df = pd.DataFrame(raw)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            print(f"[ERR] Failed to fetch candles: {e}")
            return pd.DataFrame()

    def inspect_symbol(self, symbol, timeframe="15minute", side_filter="BOTH"):
        print("\n" + "=" * 80)
        print(f"📊 PATTERN & CANDLESTICK AUDIT: {symbol.upper()} ({timeframe})")
        print("=" * 80)

        token = self.get_instrument_token(symbol)
        if not token:
            print(f"❌ Could not resolve token for '{symbol}'. Is it a valid listed F&O ticker?")
            return

        df = self.fetch_candles(token, timeframe=timeframe, days=20)
        if df.empty or len(df) < 25:
            print(f"❌ Insufficient candle data fetched ({len(df)} candles).")
            return

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        spot_ltp = float(latest["close"])

        # Compute Technical Indicators
        df["ema13"] = compute_ema(df["close"], 13)
        df["ema44"] = compute_ema(df["close"], 44)
        ema13_val = float(df["ema13"].iloc[-1])
        ema44_val = float(df["ema44"].iloc[-1])

        # Compute Intraday VWAP
        df_today = df[df["date"].dt.date == latest["date"].date()]
        if not df_today.empty:
            pv = (df_today["volume"] * ((df_today["high"] + df_today["low"] + df_today["close"]) / 3.0)).cumsum()
            vol = df_today["volume"].cumsum()
            vwap_val = float((pv / vol).iloc[-1]) if vol.iloc[-1] > 0 else spot_ltp
        else:
            vwap_val = spot_ltp

        vwap_diff_pct = ((spot_ltp - vwap_val) / vwap_val) * 100.0

        # Volume Profile
        avg_vol_20 = float(df["volume"].iloc[-21:-1].mean()) if len(df) >= 21 else 1.0
        cur_vol = float(latest["volume"])
        cur_rvol = (cur_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

        print(f"\n[SPOT PRICE & TECHNICAL INDICATORS]")
        print(f"  • Spot LTP        : ₹{spot_ltp:.2f}")
        print(f"  • Intraday VWAP   : ₹{vwap_val:.2f} ({vwap_diff_pct:+.2f}%)")
        print(f"  • EMA 13 / 44     : ₹{ema13_val:.2f} / ₹{ema44_val:.2f} ({'BULLISH (13 > 44)' if ema13_val >= ema44_val else 'BEARISH (13 < 44)'})")
        print(f"  • Current RVOL    : {cur_rvol:.2f}x (Vol: {int(cur_vol):,} vs 20-SMA: {int(avg_vol_20):,})")

        print(f"\n[LAST 4 CANDLES ({timeframe})]")
        for i in range(-4, 0):
            c = df.iloc[i]
            col = "🟢 GREEN" if c["close"] >= c["open"] else "🔴 RED  "
            v = c.get("volume", 0)
            t_str = c["date"].strftime("%Y-%m-%d %H:%M")
            print(f"  • {t_str} | O: {c['open']:<7.2f} H: {c['high']:<7.2f} L: {c['low']:<7.2f} C: {c['close']:<7.2f} | Vol: {int(v):<8} | {col}")

        # Scan Bullish Patterns
        bull_result = None
        if side_filter in ("BOTH", "BULL"):
            try:
                bull_result = scan_anchor_bcd_breakout(df, df, anchor_tf=timeframe, entry_tf=timeframe)
            except Exception as e:
                print(f"[WARN] Bull scan failed: {e}")

        # Scan Bearish Patterns
        bear_result = None
        if side_filter in ("BOTH", "BEAR"):
            try:
                bear_result = scan_anchor_bcd_breakout_bearish(df, df, anchor_tf=timeframe, entry_tf=timeframe)
            except Exception as e:
                print(f"[WARN] Bear scan failed: {e}")

        print("\n" + "-" * 80)
        print("🎯 GEOMETRIC PATTERN DETECTION RESULTS")
        print("-" * 80)

        found_any = False

        if bull_result:
            found_any = True
            p = bull_result
            rvol_d = p.get("vol_d_ratio", 1.0)
            rvol_pass = rvol_d >= 1.20
            print(f"\n🟢 BULLISH SETUP CONFIRMED: {p.get('Pattern')}")
            print(f"  • Point A (Anchor)   : Date: {p.get('AnchorTime')} | Low: ₹{p.get('AnchorLow'):.2f} | High: ₹{p.get('AnchorHigh'):.2f}")
            print(f"  • Point B (Pullback) : Date: {p.get('PullbackTime', 'N/A')} | Price: ₹{p.get('PullbackLow', 0):.2f}")
            print(f"  • Point C (Retrace)  : Date: {p.get('RetraceTime', 'N/A')} | Price: ₹{p.get('RetraceLow', 0):.2f}")
            print(f"  • Point D (Trigger)  : Date: {p.get('BreakoutTime', 'N/A')} | Trigger Close: ₹{p.get('EntrySpot', 0):.2f}")
            print(f"  • Benchmark Level    : ₹{p.get('Benchmark', 0):.2f}")
            print(f"  • RVOL at Point D    : {rvol_d:.2f}x ({'✅ CONFIRMED (>= 1.2x)' if rvol_pass else '❌ REJECTED (< 1.2x Dry Breakout)'})")
            print(f"  • Structural SL      : ₹{p.get('SL', 0):.2f}")
            print(f"  • Targets (T1/T2/T3) : ₹{p.get('T1', 0):.2f} / ₹{p.get('T2', 0):.2f} / ₹{p.get('T3', 0):.2f}")
            print(f"  • Reward:Risk (R:R)  : {p.get('RR', 0):.2f}x")

        if bear_result:
            found_any = True
            p = bear_result
            rvol_d = p.get("vol_d_ratio", 1.0)
            rvol_pass = rvol_d >= 1.20
            print(f"\n🔴 BEARISH SETUP CONFIRMED: {p.get('Pattern')}")
            print(f"  • Point A (Anchor)   : Date: {p.get('AnchorTime')} | Low: ₹{p.get('AnchorLow'):.2f} | High: ₹{p.get('AnchorHigh'):.2f}")
            print(f"  • Point B (Pullback) : Date: {p.get('PullbackTime', 'N/A')} | Price: ₹{p.get('PullbackHigh', 0):.2f}")
            print(f"  • Point C (Retrace)  : Date: {p.get('RetraceTime', 'N/A')} | Price: ₹{p.get('RetraceHigh', 0):.2f}")
            print(f"  • Point D (Trigger)  : Date: {p.get('BreakoutTime', 'N/A')} | Trigger Close: ₹{p.get('EntrySpot', 0):.2f}")
            print(f"  • Benchmark Level    : ₹{p.get('Benchmark', 0):.2f}")
            print(f"  • RVOL at Point D    : {rvol_d:.2f}x ({'✅ CONFIRMED (>= 1.2x)' if rvol_pass else '❌ REJECTED (< 1.2x Dry Breakdown)'})")
            print(f"  • Structural SL      : ₹{p.get('SL', 0):.2f}")
            print(f"  • Targets (T1/T2/T3) : ₹{p.get('T1', 0):.2f} / ₹{p.get('T2', 0):.2f} / ₹{p.get('T3', 0):.2f}")
            print(f"  • Reward:Risk (R:R)  : {p.get('RR', 0):.2f}x")

        if not found_any:
            print("\n⚪ NO ACTIVE BREAKOUT / BREAKDOWN CONFIRMED AT THIS TIME.")
            print(f"  The price action is currently in an unconfirmed accumulation/consolidation phase on the {timeframe} chart.")
            print("  Check if candles are respecting EMA 13/44 dynamic support or if Point D candle closed beyond benchmark.")

        print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Candlestick Geometry & Technical Pattern Inspector")
    parser.add_argument("--symbol", type=str, required=True, help="Symbol to inspect (e.g. COLPAL, SBILIFE, INFY, MOTHERSON)")
    parser.add_argument("--timeframe", choices=["5minute", "15minute", "30minute", "day"], default="15minute", help="Timeframe (default: 15minute)")
    parser.add_argument("--side", choices=["BOTH", "BULL", "BEAR"], default="BOTH", help="Side filter (default: BOTH)")
    parser.add_argument("--contract", type=str, help="Option contract to inspect (e.g. COLPAL26OCT1820PE)")

    args = parser.parse_args()
    inspector = PatternInspector()
    inspector.inspect_symbol(args.symbol, timeframe=args.timeframe, side_filter=args.side)


if __name__ == "__main__":
    main()
