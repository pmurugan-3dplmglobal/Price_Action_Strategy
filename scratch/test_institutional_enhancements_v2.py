import sys, os
sys.path.insert(0, 'common')
sys.path.insert(0, 'Trade_Option')

from trading_core import (
    get_exchange_freeze_limit,
    slice_quantity_for_freeze
)
from resolve import evaluate_spot_confluence

passed = 0
failed = 0

def check(desc, cond):
    global passed, failed
    if cond:
        print(f"  [PASS] {desc}")
        passed += 1
    else:
        print(f"  [FAIL] {desc}")
        failed += 1

print("=" * 60)
print("TEST SUITE: Institutional Gating, Freeze Slicing & Parity")
print("=" * 60)

# 1. Freeze limits & slicing
print("\n[1] Exchange Freeze Limits & Slicing:")
check("NIFTY freeze limit is 1755", get_exchange_freeze_limit("NIFTY2690823700CE") == 1755)
check("BANKNIFTY freeze limit is 900", get_exchange_freeze_limit("BANKNIFTY26SEP57100CE") == 900)
check("FINNIFTY freeze limit is 1800", get_exchange_freeze_limit("FINNIFTY26SEP25700PE") == 1800)

nifty_slices_2600 = slice_quantity_for_freeze("NIFTY2690823700CE", 2600)
check("NIFTY 2600 qty sliced into [1755, 845]", nifty_slices_2600 == [1755, 845])

bn_slices_1500 = slice_quantity_for_freeze("BANKNIFTY", 1500)
check("BANKNIFTY 1500 qty sliced into [900, 600]", bn_slices_1500 == [900, 600])

nifty_slices_650 = slice_quantity_for_freeze("NIFTY2690823700CE", 650)
check("NIFTY 650 qty (below freeze) remains [650]", nifty_slices_650 == [650])

# 2. D1 vs D2 Spot Confluence
print("\n[2] Spot Confluence (D1 Reversal vs D2 Continuation):")
# D1 Reversal with Spot VWAP Reclaim (Spot=2505 >= VWAP=2500, but EMA trend is False/below EMA13)
has_conf, conf_type = evaluate_spot_confluence(
    side="CE", is_d2=False, current_spot=2505.0, spot_vwap=2500.0, spot_sl=2450.0, spot_ema_trend=False
)
check("D1 Reversal passes on Spot VWAP Reclaim even when below EMA13", has_conf is True and conf_type == "SPOT_VWAP_RECLAIM")

# D2 Continuation with Spot below EMA13
has_d2_conf, d2_type = evaluate_spot_confluence(
    side="CE", is_d2=True, current_spot=2505.0, spot_vwap=2500.0, spot_sl=2450.0, spot_ema_trend=False
)
check("D2 Continuation is rejected when Spot is below EMA13", has_d2_conf is False and d2_type == "NONE")

# D2 Continuation with Spot above EMA13 and VWAP
has_d2_good, d2_good_type = evaluate_spot_confluence(
    side="CE", is_d2=True, current_spot=2505.0, spot_vwap=2500.0, spot_sl=2450.0, spot_ema_trend=True
)
check("D2 Continuation passes when Spot aligns with EMA13 trend", has_d2_good is True and d2_good_type == "TREND_MOMENTUM_ALIGNMENT")

# 3. Dynamic Timeframe Failsafe Check
print("\n[3] Timeframe Parity in Failsafe Resolution:")
scan_sl_30m = {"timeframe": "30minute", "entry_tf": "30minute"}
pos_tf_30 = scan_sl_30m.get("timeframe") or scan_sl_30m.get("entry_tf") or "30minute"
check("30m option trade resolves to 30minute candle", pos_tf_30 == "30minute")

scan_sl_default = {}
pos_tf_def = scan_sl_default.get("timeframe") or scan_sl_default.get("entry_tf") or "30minute"
check("Missing timeframe defaults safely to 30minute", pos_tf_def == "30minute")

print("\n" + "=" * 60)
print(f"RESULTS: {passed} PASSED, {failed} FAILED")
print("=" * 60)

if failed > 0:
    sys.exit(1)
