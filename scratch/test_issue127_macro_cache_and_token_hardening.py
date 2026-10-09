#!/usr/bin/env python3
"""
scratch/test_issue127_macro_cache_and_token_hardening.py
Comprehensive Unit Test Suite for ISSUE-127:
1. Pre-market index delta zeroing before 09:15 AM IST (preventing yesterday's return poisoning).
2. Cache TTL staleness eviction (>120s) preventing stale crash lockouts.
3. Safe fallback when token fails/expires without crashing or blocking Call setups.
4. Detection and classification of auth/token exceptions.
5. Invalidation of pre-market cache upon 09:15 AM opening bell.
"""

import os
import sys
import time
from datetime import datetime as dt, time as dtime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import common.macro_gate as mg

tests_passed = 0
tests_total = 0


def record_result(test_name: str, passed: bool, detail: str = ""):
    global tests_passed, tests_total
    tests_total += 1
    if passed:
        tests_passed += 1
        print(f"  [PASS] {test_name} {detail}")
    else:
        print(f"  [FAIL] {test_name} {detail}")
        raise AssertionError(f"Test failed: {test_name} - {detail}")


def test_1_premarket_delta_zeroing():
    """Test 1: Before 09:15 AM IST, deltas must be 0.0% with ok=True."""
    print("\n--- Test 1: Pre-Market Delta Zeroing (< 09:15 AM IST) ---")
    orig_time_fn = mg._get_ist_time
    try:
        # Simulate 04:48 AM IST (when pre-market scan poisoned the cache with -1.64%)
        mg._get_ist_time = lambda: dtime(4, 48)
        mg._MACRO_CACHE["timestamp"] = 0.0
        mg._MACRO_CACHE["data"] = {}

        class DummyKite:
            def quote(self, insts):
                # Simulated pre-market quote comparing yesterday to day before yesterday
                return {
                    "NSE:NIFTY 50": {"last_price": 24000.0, "ohlc": {"close": 24400.0}},
                    "NSE:NIFTY BANK": {"last_price": 51000.0, "ohlc": {"close": 52000.0}}
                }

        deltas = mg.get_macro_index_deltas(DummyKite())
        record_result(
            "Pre-market delta is zeroed",
            deltas.get("NIFTY") == 0.0 and deltas.get("BANKNIFTY") == 0.0,
            f"NIFTY={deltas.get('NIFTY')}, BANKNIFTY={deltas.get('BANKNIFTY')}"
        )
        record_result(
            "Pre-market ok=True and pre_market=True flag set",
            deltas.get("ok") is True and deltas.get("pre_market") is True,
            f"ok={deltas.get('ok')}, pre_market={deltas.get('pre_market')}"
        )

        # Evaluate macro gate for Call (CE) option: must NOT be blocked!
        allowed, reason = mg.evaluate_macro_index_gate(DummyKite(), "CE", "RELIANCE")
        record_result(
            "Pre-market Call options are permitted",
            allowed is True and "PASSED" in reason,
            f"allowed={allowed}, reason={reason}"
        )

        # Evaluate macro gate for Put (PE) option: must NOT be blocked!
        pe_allowed, pe_reason = mg.evaluate_macro_index_gate(DummyKite(), "PE", "SBIN")
        record_result(
            "Pre-market Put options are permitted",
            pe_allowed is True and "PASSED" in pe_reason,
            f"allowed={pe_allowed}, reason={pe_reason}"
        )
    finally:
        mg._get_ist_time = orig_time_fn


def test_2_stale_cache_ttl_eviction():
    """Test 2: Cache older than 120s must NOT be used to assert market crashes."""
    print("\n--- Test 2: Cache Staleness TTL Eviction (> 120s) ---")
    orig_time_fn = mg._get_ist_time
    try:
        # Simulate market hours: 10:30 AM IST
        mg._get_ist_time = lambda: dtime(10, 30)

        # Plant a stale crash from 300 seconds ago (5 minutes ago)
        now = time.time()
        mg._MACRO_CACHE["timestamp"] = now - 300.0
        mg._MACRO_CACHE["data"] = {
            "NIFTY": -1.64,
            "NIFTY_LTP": 24000.0,
            "NIFTY_CLOSE": 24400.0,
            "BANKNIFTY": -2.10,
            "BANKNIFTY_LTP": 51000.0,
            "BANKNIFTY_CLOSE": 52000.0,
            "ok": True,
            "pre_market": False
        }

        # Simulate kite call failure (e.g. token expired, network outage, or kite=None)
        deltas = mg.get_macro_index_deltas(None)
        record_result(
            "Stale cache (>120s) returns ok=False and delta=0.0%",
            deltas.get("ok") is False and deltas.get("NIFTY") == 0.0 and deltas.get("stale") is True,
            f"deltas={deltas}"
        )

        # Now evaluate macro gate: must NOT block Call setup with a fake -1.64% crash lockout!
        allowed, reason = mg.evaluate_macro_index_gate(None, "CE", "RELIANCE")
        record_result(
            "Stale crash cache does NOT lock out Call option",
            allowed is True and reason == "MACRO_DATA_UNAVAILABLE_PERMITTED",
            f"allowed={allowed}, reason={reason}"
        )
    finally:
        mg._get_ist_time = orig_time_fn


def test_3_fresh_cache_retention():
    """Test 3: Cache within 20s TTL is retained during market hours."""
    print("\n--- Test 3: Fresh Cache Retention (< 20s) ---")
    orig_time_fn = mg._get_ist_time
    try:
        # Market hours: 11:00 AM IST
        mg._get_ist_time = lambda: dtime(11, 0)
        now = time.time()
        mg._MACRO_CACHE["timestamp"] = now - 10.0  # 10s old (< 20s)
        mg._MACRO_CACHE["data"] = {
            "NIFTY": 0.35,
            "NIFTY_LTP": 24500.0,
            "NIFTY_CLOSE": 24400.0,
            "BANKNIFTY": 0.45,
            "BANKNIFTY_LTP": 52200.0,
            "BANKNIFTY_CLOSE": 52000.0,
            "ok": True,
            "pre_market": False
        }

        deltas = mg.get_macro_index_deltas(None)
        record_result(
            "Fresh cache (< 20s) is retained",
            deltas.get("ok") is True and deltas.get("NIFTY") == 0.35,
            f"deltas={deltas}"
        )
    finally:
        mg._get_ist_time = orig_time_fn


def test_4_token_auth_exception_handling():
    """Test 4: TokenException detection and safe fallback."""
    print("\n--- Test 4: Token Exception Detection & Safe Fallback ---")
    orig_time_fn = mg._get_ist_time
    try:
        # Market hours: 09:30 AM IST
        mg._get_ist_time = lambda: dtime(9, 30)

        # Test auth error detection helper
        record_result(
            "Auth detector identifies 'TokenException'",
            mg.is_auth_or_token_error(Exception("TokenException: Token is invalid")),
            "detected"
        )
        record_result(
            "Auth detector identifies 'Incorrect `api_key` or `access_token`'",
            mg.is_auth_or_token_error(Exception("Incorrect `api_key` or `access_token`")),
            "detected"
        )
        record_result(
            "Auth detector identifies 403 Forbidden",
            mg.is_auth_or_token_error(Exception("403 Client Error: Forbidden for url")),
            "detected"
        )
        record_result(
            "Auth detector does NOT flag network timeout as auth error",
            not mg.is_auth_or_token_error(Exception("Connection timed out after 5000ms")),
            "correctly classified non-auth"
        )

        # Mock Kite that throws an expired token error
        class ExpiredTokenKite:
            def quote(self, insts):
                raise Exception("TokenException: Token is invalid or expired. Please re-authenticate.")

        # Cache is empty/stale
        mg._MACRO_CACHE["timestamp"] = 0.0
        mg._MACRO_CACHE["data"] = {}

        # Fetching deltas must NOT crash and must return ok=False
        deltas = mg.get_macro_index_deltas(ExpiredTokenKite())
        record_result(
            "Token exception returns safe fallback ok=False without raising exception",
            deltas.get("ok") is False and deltas.get("NIFTY") == 0.0,
            f"deltas={deltas}"
        )

        # Macro gate evaluation must permit trade
        allowed, reason = mg.evaluate_macro_index_gate(ExpiredTokenKite(), "CE", "TATAMOTORS")
        record_result(
            "Expired token allows trade through safety fallback",
            allowed is True and reason == "MACRO_DATA_UNAVAILABLE_PERMITTED",
            f"allowed={allowed}, reason={reason}"
        )
    finally:
        mg._get_ist_time = orig_time_fn


def test_5_premarket_cache_invalidation_at_open():
    """Test 5: Pre-market cache (< 09:15) must be discarded when market opens (>= 09:15)."""
    print("\n--- Test 5: Pre-Market Cache Invalidation at 09:15 Bell ---")
    orig_time_fn = mg._get_ist_time
    try:
        now = time.time()
        # Plant pre-market cache recorded at 09:14:55
        mg._MACRO_CACHE["timestamp"] = now - 10.0  # only 10s old
        mg._MACRO_CACHE["data"] = {
            "NIFTY": 0.0,
            "NIFTY_LTP": 0.0,
            "NIFTY_CLOSE": 0.0,
            "BANKNIFTY": 0.0,
            "BANKNIFTY_LTP": 0.0,
            "BANKNIFTY_CLOSE": 0.0,
            "ok": True,
            "pre_market": True
        }

        # Market has opened: 09:15:05 AM IST
        mg._get_ist_time = lambda: dtime(9, 15, 5)

        quote_called = [False]
        class LiveMarketKite:
            def quote(self, insts):
                quote_called[0] = True
                return {
                    "NSE:NIFTY 50": {"last_price": 24200.0, "ohlc": {"close": 24000.0}},
                    "NSE:NIFTY BANK": {"last_price": 51500.0, "ohlc": {"close": 51000.0}}
                }

        deltas = mg.get_macro_index_deltas(LiveMarketKite())
        record_result(
            "Pre-market cache is bypassed at >= 09:15 and live quotes queried",
            quote_called[0] is True and deltas.get("pre_market") is False,
            f"quote_called={quote_called[0]}, deltas={deltas}"
        )
        record_result(
            "Live market delta computed accurately (+0.83% NIFTY)",
            deltas.get("NIFTY") == 0.83 and deltas.get("ok") is True,
            f"NIFTY delta={deltas.get('NIFTY')}"
        )
    finally:
        mg._get_ist_time = orig_time_fn


if __name__ == "__main__":
    print("=" * 80)
    print("   RUNNING ISSUE-127 MACRO GATE CACHE & TOKEN HARDENING UNIT TESTS")
    print("=" * 80)

    test_1_premarket_delta_zeroing()
    test_2_stale_cache_ttl_eviction()
    test_3_fresh_cache_retention()
    test_4_token_auth_exception_handling()
    test_5_premarket_cache_invalidation_at_open()

    print("\n" + "=" * 80)
    print(f"   ALL {tests_passed}/{tests_total} UNIT TESTS PASSED SUCCESSFULLY (100%)")
    print("=" * 80)
