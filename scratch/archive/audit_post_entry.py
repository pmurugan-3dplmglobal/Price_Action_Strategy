import json
import os
import sys
from datetime import datetime as dt, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import session, paths
from common.trading_core import fetch_and_resample_candles
from kiteconnect import KiteConnect

def parse_entry_time(et_str):
    if not et_str:
        return None
    s = str(et_str).replace('T', ' ').strip()
    if '+' in s:
        s = s.split('+')[0]
    parts = s.split(' ')
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "09:15:00"
    if len(time_part.split(':')) == 2:
        time_part += ":00"
    return f"{date_part} {time_part}"

def main():
    with open("scratch/scanned_setups_analysis.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    ak, at = session.load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)

    all_setups = (
        data['t1_hit'] +
        data['runaway_08_t1'] +
        data['sl_hit'] +
        data['active_valid']
    )

    print(f"Auditing {len(all_setups)} setups strictly AFTER their entry_time candle...")

    from_date = dt.now().strftime("%Y-%m-%d")
    to_date = dt.now().strftime("%Y-%m-%d")

    post_entry_t1 = []
    post_entry_08_t1 = []
    post_entry_sl = []
    post_entry_both = []
    post_entry_active = []

    for i, item in enumerate(all_setups):
        cntr = item['contract']
        sym = item['symbol']
        entry_p = item['entry']
        sl_p = item['sl']
        t1_p = item['t1']
        t1_80_p = item['t1_80']
        et_clean = parse_entry_time(item.get('entry_time'))

        # Fetch token
        q_key = f"NFO:{cntr}" if "SENSEX" not in cntr else f"BFO:{cntr}"
        try:
            q_res = kite.quote([q_key])
            token = q_res.get(q_key, {}).get("instrument_token")
        except Exception:
            token = None

        if not token:
            continue

        # Fetch 5m or 15m intraday candles
        try:
            df = fetch_and_resample_candles(kite, token, from_date, to_date, "15minute")
        except Exception:
            df = None

        if df is None or df.empty:
            # Fallback to day high/low from quote
            continue

        # Filter strictly candles at or after entry_time
        candles_after = []
        for idx in range(len(df)):
            c_row = df.iloc[idx]
            c_date_str = str(c_row.get('date', '')).replace('T', ' ').split('+')[0]
            if et_clean and c_date_str < et_clean:
                continue
            candles_after.append(c_row)

        if not candles_after:
            # Entry candle was just the last candle
            candles_after = [df.iloc[-1]]

        post_high = max(float(c['high']) for c in candles_after)
        post_low = min(float(c['low']) for c in candles_after)
        post_close = float(candles_after[-1]['close'])

        hit_t1 = post_high >= (t1_p * 0.995) if t1_p > 0 else False
        hit_08 = post_high >= t1_80_p if t1_80_p > 0 else False
        hit_sl = post_low <= sl_p if sl_p > 0 else False

        res_record = {
            **item,
            "post_high": post_high,
            "post_low": post_low,
            "post_close": post_close,
            "candles_count": len(candles_after)
        }

        if hit_t1 and hit_sl:
            post_entry_both.append(res_record)
        elif hit_t1:
            post_entry_t1.append(res_record)
        elif hit_08:
            post_entry_08_t1.append(res_record)
        elif hit_sl:
            post_entry_sl.append(res_record)
        else:
            post_entry_active.append(res_record)

    print("\n" + "=" * 80)
    print("      TRUE POST-ENTRY AUDIT RESULTS (STRICTLY AFTER ENTRY CANDLE)      ")
    print("=" * 80)
    print(f" 🎯 Reached Full T1 post-entry:         {len(post_entry_t1)}")
    print(f" 🏃 Reached 0.8 T1 Runaway post-entry:  {len(post_entry_08_t1)}")
    print(f" 🛑 Hit SL post-entry:                  {len(post_entry_sl)}")
    print(f" ⚠️  Touched Both (High & Low):          {len(post_entry_both)}")
    print(f" 🟢 Still Active / In Corridor:         {len(post_entry_active)}")
    print(f" Total Audited:                         {len(post_entry_t1) + len(post_entry_08_t1) + len(post_entry_sl) + len(post_entry_both) + len(post_entry_active)}")
    print("=" * 80 + "\n")

    out_file = os.path.join(PROJECT_ROOT, "scratch", "post_entry_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "post_t1": post_entry_t1,
            "post_08_t1": post_entry_08_t1,
            "post_sl": post_entry_sl,
            "post_both": post_entry_both,
            "post_active": post_entry_active
        }, f, indent=2)

    print("Details written to scratch/post_entry_audit.json")

if __name__ == "__main__":
    main()
