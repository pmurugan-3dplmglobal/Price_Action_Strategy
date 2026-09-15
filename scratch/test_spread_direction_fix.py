import os
import sys
import pandas as pd
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "common"))

from resolve import resolve_option_spread

def test_spread_direction_fidelity():
    records = []
    base_symbol = "MIDCPNIFTY"
    today = date.today().strftime("%Y-%m-%d")

    for strike in range(14400, 14800, 25):
        records.append({
            "name": base_symbol,
            "tradingsymbol": f"MIDCPNIFTY{strike}CE",
            "instrument_token": 100000 + strike,
            "instrument_type": "CE",
            "strike": float(strike),
            "expiry": today,
            "lot_size": 120
        })
        records.append({
            "name": base_symbol,
            "tradingsymbol": f"MIDCPNIFTY{strike}PE",
            "instrument_token": 200000 + strike,
            "instrument_type": "PE",
            "strike": float(strike),
            "expiry": today,
            "lot_size": 120
        })
    instruments = pd.DataFrame(records)

    # Test 1: PE candidate with direction="BULL" (Pattern breakout on PE chart)
    res_pe = resolve_option_spread(
        nfo_instruments=instruments,
        base_symbol="MIDCPNIFTY",
        spot_price=14600.0,
        step_size=25,
        direction="BULL",  # Breakout direction is BULL
        side="PE"          # But contract side is PE
    )
    assert res_pe is not None, "PE spread should be resolved"
    assert res_pe["spread_type"] == "BEAR_PUT_SPREAD", f"Expected BEAR_PUT_SPREAD, got {res_pe['spread_type']}"
    assert res_pe["leg1"]["option_type"] == "PE", f"Leg 1 option type must be PE, got {res_pe['leg1']['option_type']}"
    assert res_pe["leg2"]["option_type"] == "PE", f"Leg 2 option type must be PE, got {res_pe['leg2']['option_type']}"
    assert "PE" in res_pe["leg1"]["contract"], "Leg 1 contract must be PE"
    assert "PE" in res_pe["leg2"]["contract"], "Leg 2 contract must be PE"
    print("[PASS] Test 1: PE setup with direction='BULL' correctly resolves BEAR_PUT_SPREAD with PE contracts")

    # Test 2: CE candidate with direction="BULL"
    res_ce = resolve_option_spread(
        nfo_instruments=instruments,
        base_symbol="MIDCPNIFTY",
        spot_price=14575.0,
        step_size=25,
        direction="BULL",
        side="CE"
    )
    assert res_ce is not None, "CE spread should be resolved"
    assert res_ce["spread_type"] == "BULL_CALL_SPREAD", f"Expected BULL_CALL_SPREAD, got {res_ce['spread_type']}"
    assert res_ce["leg1"]["option_type"] == "CE", f"Leg 1 option type must be CE, got {res_ce['leg1']['option_type']}"
    assert res_ce["leg2"]["option_type"] == "CE", f"Leg 2 option type must be CE, got {res_ce['leg2']['option_type']}"
    assert "CE" in res_ce["leg1"]["contract"], "Leg 1 contract must be CE"
    assert "CE" in res_ce["leg2"]["contract"], "Leg 2 contract must be CE"
    print("[PASS] Test 2: CE setup correctly resolves BULL_CALL_SPREAD with CE contracts")

    # Test 3: PE setup with direction="BEAR"
    res_pe2 = resolve_option_spread(
        nfo_instruments=instruments,
        base_symbol="MIDCPNIFTY",
        spot_price=14600.0,
        step_size=25,
        direction="BEAR"
    )
    assert res_pe2 is not None and res_pe2["spread_type"] == "BEAR_PUT_SPREAD"
    print("[PASS] Test 3: direction='BEAR' resolves BEAR_PUT_SPREAD")

    print("\nALL SPREAD DIRECTION FIDELITY TESTS PASSED 100%!")

if __name__ == "__main__":
    test_spread_direction_fidelity()
