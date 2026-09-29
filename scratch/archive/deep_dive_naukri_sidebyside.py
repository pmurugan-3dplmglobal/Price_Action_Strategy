import sys, os
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect
from timeframe_utils import get_ist_now

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

now = get_ist_now(naive=True)
today = now.strftime('%Y-%m-%d')
from_dt = f'{today} 09:15:00'
to_dt = now.strftime('%Y-%m-%d %H:%M:%S')

spot_candles = kite.historical_data(3520257, from_dt, to_dt, '5minute')
opt_candles = kite.historical_data(24585730, from_dt, to_dt, '5minute')

opt_by_time = {c['date'].strftime('%H:%M'): c for c in opt_candles}

print(f"=== NAUKRI SPOT vs 1300 PE 5-MIN TIMELINE TODAY ({today}) ===")
print(f"Time  | Spot (Open   High    Low  Close   Vol ) | Option 1300 PE (Open   High    Low  Close   Vol )")
print("-" * 90)
for sc in spot_candles:
    t = sc['date'].strftime('%H:%M')
    oc = opt_by_time.get(t, {})
    s_str = f"{sc['open']:6.1f} {sc['high']:6.1f} {sc['low']:6.1f} {sc['close']:6.1f} {sc['volume']:6d}"
    if oc:
        o_str = f"{oc.get('open', 0):6.2f} {oc.get('high', 0):6.2f} {oc.get('low', 0):6.2f} {oc.get('close', 0):6.2f} {oc.get('volume', 0):7d}"
    else:
        o_str = "        -- no data --        "
    print(f"{t} | {s_str} | {o_str}")
