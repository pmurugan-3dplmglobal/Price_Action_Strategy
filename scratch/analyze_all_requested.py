import sys, os, time, pandas as pd
COMMON_DIR = r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy\common"
sys.path.insert(0, COMMON_DIR)
import paths
from session import load_kite_session
from kiteconnect import KiteConnect
from patterns_bull import scan_anchor_bcd_breakout, scan_pattern_lifecycle_stage, scan_trend_continuation_reentry
from patterns_bear import scan_anchor_bcd_breakout_bearish, scan_pattern_lifecycle_stage_bearish, scan_trend_continuation_reentry_bearish

api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)

instruments = kite.instruments("NSE")
lookup = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}

targets = [
    # Initial request: Friday 4 Sept
    ("NIACL", "2026-09-04"),
    ("WELENT", "2026-09-04"),
    ("TEJASNET", "2026-09-04"),
    ("IFCI", "2026-09-04"),
    # Second request: Specific dates
    ("SAILIFE", "2026-09-01"),
    ("NIACL", "2026-09-02"),
    ("GMMPFAUDLR", "2026-09-04"),
    ("CAMS", "2026-08-31"),
    ("IGL", "2026-09-04"),
]

for sym, target_date_str in targets:
    token = lookup.get(sym)
    if not token:
        print(f"[ERROR] Token not found for {sym}")
        continue

    target_date = pd.to_datetime(target_date_str).date()
    # Fetch 5min candles with 15 days lookback prior to target date
    from_d = (pd.to_datetime(target_date_str) - pd.Timedelta(days=18)).strftime("%Y-%m-%d")
    to_d = (pd.to_datetime(target_date_str) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        candles = kite.historical_data(token, from_d, to_d, "5minute")
    except Exception as e:
        print(f"[ERROR] Historical fetch failed for {sym}: {e}")
        continue

    df = pd.DataFrame(candles)
    if df.empty:
        print(f"[ERROR] Empty candles for {sym}")
        continue
    df["date"] = pd.to_datetime(df["date"])

    session_indices = df[df["date"].dt.date == target_date].index.tolist()
    print("=" * 80)
    print(f"SYMBOL: {sym} | DATE: {target_date_str} (5-min Timeframe)")
    print("=" * 80)
    if not session_indices:
        print(f"No trading candles on {target_date_str} for {sym}")
        continue

    first_idx = session_indices[0]
    last_idx = session_indices[-1]
    s_open = df.loc[first_idx, "open"]
    s_close = df.loc[last_idx, "close"]
    s_high = df.loc[session_indices, "high"].max()
    s_low = df.loc[session_indices, "low"].min()
    s_vol = df.loc[session_indices, "volume"].sum()
    pct_chg = (s_close - s_open) / s_open * 100
    print(f"Session OHLC: Open={s_open:.2f}, High={s_high:.2f}, Low={s_low:.2f}, Close={s_close:.2f} ({pct_chg:+.2f}%) | Vol={s_vol:,}")

    triggers = []
    # Test each 5m candle of the target session
    for idx in session_indices:
        # Window of up to 180 bars before the current bar for Left-Side Rule (100) + anchor detection
        sub_df = df.iloc[max(0, idx - 180) : idx + 1].copy().reset_index(drop=True)
        bar_time = df.loc[idx, "date"]

        # Bullish D1 Breakout
        b_res = scan_anchor_bcd_breakout(sub_df, sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        if b_res and str(b_res.get("CandleTime")) == str(bar_time):
            triggers.append(("BULL_D1", bar_time, b_res))

        # Bearish D1 Breakout
        bear_res = scan_anchor_bcd_breakout_bearish(sub_df, sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        if bear_res and str(bear_res.get("CandleTime")) == str(bar_time):
            triggers.append(("BEAR_D1", bar_time, bear_res))

        # D2 Trend Continuation
        d2_b = scan_trend_continuation_reentry(sub_df, sub_df)
        if d2_b and str(d2_b.get("CandleTime")) == str(bar_time):
            triggers.append(("BULL_D2", bar_time, d2_b))

        d2_bear = scan_trend_continuation_reentry_bearish(sub_df, sub_df)
        if d2_bear and str(d2_bear.get("CandleTime")) == str(bar_time):
            triggers.append(("BEAR_D2", bar_time, d2_bear))

    if triggers:
        print(f"\n>>> DETECTED TRIGGERS ({len(triggers)}):")
        for kind, t, r in triggers:
            t_str = t.strftime("%H:%M")
            pat = r.get("Pattern", "Unknown")
            anc = r.get("anchor_type", r.get("Pattern", ""))
            anc_time = r.get("CandleATime", "")
            entry_p = r.get("Close", 0.0)
            bm = r.get("Benchmark", 0.0)
            sl = r.get("SL", 0.0)
            t1 = r.get("T1", 0.0)
            rr = r.get("RR", 0.0)
            tier = r.get("tier_badge", r.get("tier_label", ""))
            print(f"  [{t_str}] {kind} | Pattern: {pat} | Anchor: {anc} ({anc_time})")
            print(f"         Entry: {entry_p:.2f} | BM: {bm:.2f} | SL: {sl:.2f} | T1: {t1} | RR: {rr} | Tier: {tier}")
    else:
        print("\n>>> No D1 or D2 triggers during this session.")

    # Check End-of-Session Lifecycle Stage
    end_sub_df = df.iloc[max(0, last_idx - 180) : last_idx + 1].copy().reset_index(drop=True)
    bull_life = scan_pattern_lifecycle_stage(end_sub_df, end_sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
    bear_life = scan_pattern_lifecycle_stage_bearish(end_sub_df, end_sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)

    print(f"\nEnd-of-Session Structure (at 15:30):")
    if bull_life:
        print(f"  Bull Lifecycle: {bull_life.get('stage')} | Pattern: {bull_life.get('pattern')} | Anchor: {bull_life.get('candle_a_time')} | BM: {bull_life.get('benchmark')} | SL: {bull_life.get('sl')}")
    else:
        print("  Bull Lifecycle: No active stage")

    if bear_life:
        print(f"  Bear Lifecycle: {bear_life.get('stage')} | Pattern: {bear_life.get('pattern')} | Anchor: {bear_life.get('candle_a_time')} | BM: {bear_life.get('benchmark')} | SL: {bear_life.get('sl')}")
    else:
        print("  Bear Lifecycle: No active stage")
    print()
