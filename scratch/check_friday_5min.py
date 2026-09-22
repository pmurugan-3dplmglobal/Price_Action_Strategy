import os, sys, pandas as pd
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
symbols = ["NIACL", "WELENT", "TEJASNET", "IFCI"]
friday_date = pd.to_datetime("2026-09-04").date()

for sym in symbols:
    token = lookup.get(sym)
    candles = kite.historical_data(token, "2026-08-01", "2026-09-04 15:30:00", "5minute")
    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    friday_indices = df[df["date"].dt.date == friday_date].index.tolist()
    print("=" * 70)
    print(f"SYMBOL: {sym} | Friday 5m bars: {len(friday_indices)}")
    if not friday_indices:
        continue
    f_open = df.loc[friday_indices[0], "open"]
    f_close = df.loc[friday_indices[-1], "close"]
    f_high = df.loc[friday_indices, "high"].max()
    f_low = df.loc[friday_indices, "low"].min()
    pct = (f_close - f_open) / f_open * 100
    print(f"Friday Price Action -> Open: {f_open:.2f}, High: {f_high:.2f}, Low: {f_low:.2f}, Close: {f_close:.2f} ({pct:+.2f}%)")

    bull_triggers = []
    bear_triggers = []
    d2_triggers = []

    for idx in friday_indices:
        sub_df = df.iloc[:idx + 1].copy()
        bar_time = df.loc[idx, "date"]

        b_res = scan_anchor_bcd_breakout(sub_df, sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        if b_res and b_res.get("CandleTime") == str(bar_time):
            bull_triggers.append((bar_time, b_res))

        bear_res = scan_anchor_bcd_breakout_bearish(sub_df, sub_df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        if bear_res and bear_res.get("CandleTime") == str(bar_time):
            bear_triggers.append((bar_time, bear_res))

        d2_b = scan_trend_continuation_reentry(sub_df, sub_df)
        if d2_b and d2_b.get("CandleTime") == str(bar_time):
            d2_triggers.append(("BULL_D2", bar_time, d2_b))
        d2_bear = scan_trend_continuation_reentry_bearish(sub_df, sub_df)
        if d2_bear and d2_bear.get("CandleTime") == str(bar_time):
            d2_triggers.append(("BEAR_D2", bar_time, d2_bear))

    print(f"\n--- Bullish D1 Triggers ({len(bull_triggers)}) ---")
    for t, r in bull_triggers:
        print(f"  [{t.strftime('%H:%M')}] {r.get('Pattern')} ({r.get('anchor_type')}) | Entry: {r.get('Close'):.2f} | BM: {r.get('Benchmark'):.2f} | SL: {r.get('SL'):.2f} | T1: {r.get('T1')} | RR: {r.get('RR')}")

    print(f"\n--- Bearish D1 Triggers ({len(bear_triggers)}) ---")
    for t, r in bear_triggers:
        print(f"  [{t.strftime('%H:%M')}] {r.get('Pattern')} ({r.get('anchor_type')}) | Entry: {r.get('Close'):.2f} | BM: {r.get('Benchmark'):.2f} | SL: {r.get('SL'):.2f} | T1: {r.get('T1')} | RR: {r.get('RR')}")

    print(f"\n--- D2 Continuation Triggers ({len(d2_triggers)}) ---")
    for s, t, r in d2_triggers:
        print(f"  [{t.strftime('%H:%M')}] {s} | Entry: {r.get('Close'):.2f} | SL: {r.get('SL'):.2f}")

    # Inspect the Friday close lifecycle state
    sub_df_friday_close = df.iloc[:friday_indices[-1] + 1].copy()
    life_bull = scan_pattern_lifecycle_stage(sub_df_friday_close, sub_df_friday_close, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
    life_bear = scan_pattern_lifecycle_stage_bearish(sub_df_friday_close, sub_df_friday_close, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
    print(f"\n--- Friday 15:30 Lifecycle State ---")
    print(f"  Bull Stage: {life_bull.get('stage') if life_bull else 'None'} | Pattern: {life_bull.get('pattern') if life_bull else '-'}")
    print(f"  Bear Stage: {life_bear.get('stage') if life_bear else 'None'} | Pattern: {life_bear.get('pattern') if life_bear else '-'}")
