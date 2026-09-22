import sys, os, pandas as pd, numpy as np
COMMON_DIR = r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy\common"
sys.path.insert(0, COMMON_DIR)
import paths
from session import load_kite_session
from kiteconnect import KiteConnect
from patterns_bull import (
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_trend_continuation_reentry
)
from patterns_bear import (
    find_anchor_bearish_engulfing,
    find_anchor_hh_sweep,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_trend_continuation_reentry_bearish
)
from targets import find_profit_targets, find_profit_targets_bearish

api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)

instruments = kite.instruments("NSE")
lookup = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}

targets = [
    ("NIACL", "2026-09-04", "Friday Session"),
    ("WELENT", "2026-09-04", "Friday Session"),
    ("TEJASNET", "2026-09-04", "Friday Session"),
    ("IFCI", "2026-09-04", "Friday Session"),
    ("SAILIFE", "2026-09-01", "1 Sept Session"),
    ("NIACL", "2026-09-02", "2 Sept Session"),
    ("GMMPFAUDLR", "2026-09-04", "4 Sept Session"),
    ("CAMS", "2026-08-31", "31 Aug Session"),
    ("IGL", "2026-09-04", "4 Sept Session"),
]

def analyze_stock(symbol, date_str, label):
    token = lookup.get(symbol)
    if not token:
        print(f"[{symbol}] Instrument token not found!")
        return

    target_dt = pd.to_datetime(date_str).date()
    from_d = (pd.to_datetime(date_str) - pd.Timedelta(days=12)).strftime("%Y-%m-%d")
    to_d = (pd.to_datetime(date_str) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        candles = kite.historical_data(token, from_d, to_d, "5minute")
    except Exception as e:
        print(f"[{symbol}] Failed to fetch candles: {e}")
        return

    df = pd.DataFrame(candles)
    if df.empty:
        print(f"[{symbol}] Empty candles returned.")
        return
    df["date"] = pd.to_datetime(df["date"])

    session_indices = df[df["date"].dt.date == target_dt].index.tolist()
    if not session_indices:
        print(f"[{symbol}] No trading bars on {date_str}!")
        return

    first_idx, last_idx = session_indices[0], session_indices[-1]
    s_open = df.loc[first_idx, "open"]
    s_close = df.loc[last_idx, "close"]
    s_high = df.loc[session_indices, "high"].max()
    s_low = df.loc[session_indices, "low"].min()
    pct_chg = (s_close - s_open) / s_open * 100

    print("=" * 85)
    print(f"  {symbol} ({label} - {date_str}) | 5-MIN TIMEFRAME")
    print(f"  Session OHLC: Open={s_open:.2f}, High={s_high:.2f}, Low={s_low:.2f}, Close={s_close:.2f} ({pct_chg:+.2f}%)")
    print("=" * 85)

    # 1. SCAN FOR BULLISH A-B-C-D SETUPS
    bull_anchors = [
        ("Engulfing", find_anchor_bullish_engulfing),
        ("LL_Sweep", find_anchor_ll_sweep),
        ("Hammer", find_anchor_hammer_baby),
        ("Harami", find_anchor_bullish_harami),
        ("Two_HH", find_anchor_two_higher_highs),
    ]

    bull_abcd_setups = []
    # Test candidate anchors: either created in the last 2 days or during today
    anchor_search_start = max(0, first_idx - 50)
    for a_idx in range(anchor_search_start, last_idx - 2):
        sub_df = df.iloc[:a_idx + 1]
        a_row = df.iloc[a_idx]
        a_time = a_row["date"]

        matched_anc = None
        matched_name = ""
        for name, fn in bull_anchors:
            m = fn(sub_df)
            if m and (m.get("CandleATime") == str(a_time) or m.get("date") == str(a_time)):
                matched_anc = m
                matched_name = name
                break

        if not matched_anc:
            continue

        benchmark = float(matched_anc.get("AnchorHigh", a_row["high"]))
        a_low = float(matched_anc.get("AnchorLow", a_row["low"]))
        sl = float(matched_anc.get("SL", a_low * 0.995))

        # Left-Side Rule: In preceding 100 bars, no close below a_low
        left_df = df.iloc[max(0, a_idx - 100): a_idx]
        left_side_ok = True
        if not left_df.empty and float(left_df["close"].min()) < a_low:
            left_side_ok = False

        # Forward scan for Point B, Point C, Point D
        remaining = df.iloc[a_idx + 1 : last_idx + 1]
        if len(remaining) < 3:
            continue

        # Point B: First candle closing above benchmark
        b_idx = None
        for j in range(len(remaining)):
            if float(remaining.iloc[j]["close"]) > benchmark:
                b_idx = a_idx + 1 + j
                break
        if b_idx is None:
            continue

        # Point C: First candle after B with red retest holding above a_low
        c_slice = df.iloc[b_idx + 1 : last_idx + 1]
        c_idx = None
        for j in range(len(c_slice)):
            c_row = c_slice.iloc[j]
            c_close = float(c_row["close"])
            c_open = float(c_row["open"])
            c_low = float(c_row["low"])
            is_red = c_close < c_open
            if (c_low <= benchmark and c_close >= a_low and is_red) or \
               (c_low <= a_low and c_close >= a_low and is_red):
                c_idx = b_idx + 1 + j
                break
        if c_idx is None:
            continue

        # Point D: First candle after C closing above benchmark
        d_slice = df.iloc[c_idx + 1 : last_idx + 1]
        d_idx = None
        for j in range(len(d_slice)):
            curr_d = d_slice.iloc[j]
            if float(curr_d["close"]) > benchmark:
                d_idx = c_idx + 1 + j
                break
        if d_idx is None:
            continue

        # Check floor invalidation between A and D
        between = df.iloc[a_idx + 1 : d_idx]
        if not between.empty and float(between["close"].min()) < a_low:
            continue

        # Only report if Point D triggered ON the target date
        d_date = df.loc[d_idx, "date"]
        if d_date.date() == target_dt:
            entry_p = float(df.loc[d_idx, "close"])
            t1, t2, t3 = find_profit_targets(df.iloc[:d_idx+1], entry_p, stop_loss=sl)
            risk = entry_p - sl
            rr = round((t1 - entry_p) / risk, 2) if (t1 and risk > 0) else 0.0
            bull_abcd_setups.append({
                "anchor": matched_name,
                "anchor_time": df.loc[a_idx, "date"].strftime("%d-%b %H:%M"),
                "b_time": df.loc[b_idx, "date"].strftime("%H:%M"),
                "c_time": df.loc[c_idx, "date"].strftime("%H:%M"),
                "d_time": df.loc[d_idx, "date"].strftime("%H:%M"),
                "bm": round(benchmark, 2),
                "sl": round(sl, 2),
                "entry": round(entry_p, 2),
                "t1": round(t1, 2) if t1 else None,
                "t2": round(t2, 2) if t2 else None,
                "rr": rr,
                "left_side": "PASSED" if left_side_ok else "BREACHED"
            })

    # 2. SCAN FOR BEARISH A-B-C-D SETUPS
    bear_anchors = [
        ("Bear_Engulf", find_anchor_bearish_engulfing),
        ("HH_Sweep", find_anchor_hh_sweep),
        ("ShootingStar", find_anchor_shooting_star_baby),
        ("Bear_Harami", find_anchor_bearish_harami),
        ("Two_LL", find_anchor_two_lower_lows),
    ]

    bear_abcd_setups = []
    for a_idx in range(anchor_search_start, last_idx - 2):
        sub_df = df.iloc[:a_idx + 1]
        a_row = df.iloc[a_idx]
        a_time = a_row["date"]

        matched_anc = None
        matched_name = ""
        for name, fn in bear_anchors:
            m = fn(sub_df)
            if m and (m.get("CandleATime") == str(a_time) or m.get("date") == str(a_time)):
                matched_anc = m
                matched_name = name
                break

        if not matched_anc:
            continue

        benchmark = float(matched_anc.get("AnchorLow", a_row["low"]))
        a_high = float(matched_anc.get("AnchorHigh", a_row["high"]))
        sl = float(matched_anc.get("SL", a_high * 1.005))

        left_df = df.iloc[max(0, a_idx - 100): a_idx]
        left_side_ok = True
        if not left_df.empty and float(left_df["close"].max()) > a_high:
            left_side_ok = False

        remaining = df.iloc[a_idx + 1 : last_idx + 1]
        if len(remaining) < 3:
            continue

        b_idx = None
        for j in range(len(remaining)):
            if float(remaining.iloc[j]["close"]) < benchmark:
                b_idx = a_idx + 1 + j
                break
        if b_idx is None:
            continue

        c_slice = df.iloc[b_idx + 1 : last_idx + 1]
        c_idx = None
        for j in range(len(c_slice)):
            c_row = c_slice.iloc[j]
            c_close = float(c_row["close"])
            c_open = float(c_row["open"])
            c_high = float(c_row["high"])
            is_green = c_close > c_open
            if (c_high >= benchmark and c_close <= a_high and is_green) or \
               (c_high >= a_high and c_close <= a_high and is_green):
                c_idx = b_idx + 1 + j
                break
        if c_idx is None:
            continue

        d_slice = df.iloc[c_idx + 1 : last_idx + 1]
        d_idx = None
        for j in range(len(d_slice)):
            curr_d = d_slice.iloc[j]
            if float(curr_d["close"]) < benchmark:
                d_idx = c_idx + 1 + j
                break
        if d_idx is None:
            continue

        between = df.iloc[a_idx + 1 : d_idx]
        if not between.empty and float(between["close"].max()) > a_high:
            continue

        d_date = df.loc[d_idx, "date"]
        if d_date.date() == target_dt:
            entry_p = float(df.loc[d_idx, "close"])
            t1, t2, t3 = find_profit_targets_bearish(df.iloc[:d_idx+1], entry_p, stop_loss=sl)
            risk = sl - entry_p
            rr = round((entry_p - t1) / risk, 2) if (t1 and risk > 0) else 0.0
            bear_abcd_setups.append({
                "anchor": matched_name,
                "anchor_time": df.loc[a_idx, "date"].strftime("%d-%b %H:%M"),
                "b_time": df.loc[b_idx, "date"].strftime("%H:%M"),
                "c_time": df.loc[c_idx, "date"].strftime("%H:%M"),
                "d_time": df.loc[d_idx, "date"].strftime("%H:%M"),
                "bm": round(benchmark, 2),
                "sl": round(sl, 2),
                "entry": round(entry_p, 2),
                "t1": round(t1, 2) if t1 else None,
                "t2": round(t2, 2) if t2 else None,
                "rr": rr,
                "left_side": "PASSED" if left_side_ok else "BREACHED"
            })

    # 3. D2 CONTINUATION RE-ENTRIES
    d2_list = []
    for idx in session_indices:
        sub_df = df.iloc[:idx + 1]
        bar_t = df.loc[idx, "date"]
        d2_b = scan_trend_continuation_reentry(sub_df, sub_df)
        if d2_b and str(d2_b.get("CandleTime")) == str(bar_t):
            d2_list.append(("BULL_D2", bar_t.strftime("%H:%M"), d2_b.get("Close"), d2_b.get("SL")))
        d2_bear = scan_trend_continuation_reentry_bearish(sub_df, sub_df)
        if d2_bear and str(d2_bear.get("CandleTime")) == str(bar_t):
            d2_list.append(("BEAR_D2", bar_t.strftime("%H:%M"), d2_bear.get("Close"), d2_bear.get("SL")))

    # PRINT SUMMARY
    if bull_abcd_setups:
        print(f"\n[+] BULLISH A-B-C-D BREAKOUTS ({len(bull_abcd_setups)}):")
        for s in bull_abcd_setups:
            print(f"  * D Trigger: {s['d_time']} | Anchor: {s['anchor']} ({s['anchor_time']}) | Left-Side: {s['left_side']}")
            print(f"    Sequence : B={s['b_time']} -> C Retest={s['c_time']} -> D Breakout={s['d_time']}")
            print(f"    Geometry : Benchmark={s['bm']} | Entry={s['entry']} | SL Floor={s['sl']} | T1={s['t1']} (RR {s['rr']}:1)")
    else:
        print("\n[-] No Bullish A-B-C-D breakout triggered during this session.")

    if bear_abcd_setups:
        print(f"\n[-] BEARISH A-B-C-D BREAKDOWN ({len(bear_abcd_setups)}):")
        for s in bear_abcd_setups:
            print(f"  * D Trigger: {s['d_time']} | Anchor: {s['anchor']} ({s['anchor_time']}) | Left-Side: {s['left_side']}")
            print(f"    Sequence : B={s['b_time']} -> C Retest={s['c_time']} -> D Breakdown={s['d_time']}")
            print(f"    Geometry : Benchmark={s['bm']} | Entry={s['entry']} | SL Ceiling={s['sl']} | T1={s['t1']} (RR {s['rr']}:1)")
    else:
        print("[-] No Bearish A-B-C-D breakdown triggered during this session.")

    if d2_list:
        print(f"\n[>] D2 TREND CONTINUATION PYRAMIDS ({len(d2_list)}):")
        for side, t, entry, sl in d2_list:
            print(f"  * {side} at {t} | Entry: {entry:.2f} | Trailing SL: {sl:.2f}")
    else:
        print("[-] No D2 Trend Continuation triggers during this session.")
    print()

for sym, dt_str, lbl in targets:
    analyze_stock(sym, dt_str, lbl)
