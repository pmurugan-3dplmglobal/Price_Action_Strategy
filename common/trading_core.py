"""
trading_core.py — Backward-Compatible Canonical Re-Export Hub.

All core trading logic is decomposed into focused sub-modules under common/:
  - timeframe_utils.py: Timeframe resampling, adaptive lookback, next candle time, candle fetching
  - registries.py: STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, token syncing
  - session.py: Kite session, rate limiting, market hours, weekly expiry, journal logging
  - targets.py: Target finding (bull/bear), Left-Side rule, SL buffers, RR calculation
  - patterns_bull.py: 5 Bullish Anchor detectors, BCD breakout, trend continuation
  - patterns_bear.py: 5 Bearish Anchor detectors, BCD breakout, generic dispatcher
  - position_monitor.py: Active position monitoring, trailing stops, order execution, market open check
  - display_writer.py: write_scan_display_data, timestamp sanitation, config loading
  - resolve.py: Strike resolution, symbol scanning, SL/target derivation, reconciliation
  - swing_detection.py: Multi-swing parabolic cascade detection & polynomial fitting
  - daily_trade_journal.py: Trade journal logging
  - dashboard_sl_overrides.py: SL/target override management
  - ema_engine.py: 13/44 EMA trend engine
  - trade_db.py: SQLite-backed WAL trade database

Consumers importing from `trading_core` receive the authoritative implementations.
"""

import os
import json
import logging
import csv
import time
import threading
from datetime import datetime as dt, timedelta, time as datetime_time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

import paths

# ── Canonical File Paths ──
TOKEN_FILE = paths.TOKEN_FILE
JOURNAL_FILE = paths.TRADE_JOURNAL_CSV

# ── timeframe_utils ──
from timeframe_utils import (
    LOOKBACK_LIMITS,
    get_next_candle_start_time,
    get_adaptive_lookback,
    resample_timeframe,
    get_fetch_timeframe,
    trading_days_between,
    cap_lookback_days,
    fetch_and_resample_candles,
    fetch_option_data,
    get_ist_now,
    get_ist_date,
    get_ist_time,
    _HISTORICAL_CANDLE_CACHE,
    _CACHE_TTL_SECONDS
)

# ── registries ──
from registries import (
    STOCK_REGISTRY,
    INDEX_REGISTRY,
    SUPER_STOCKS,
    SECTOR_MAP,
    get_symbol_sector,
    sync_stock_tokens,
    sync_fno_stock_registry,
    match_registry_symbol,
    extract_underlying_symbol
)

# ── session ──
from session import (
    TokenBucketRateLimiter,
    _GLOBAL_KITE_RATE_LIMITER,
    load_kite_session,
    ensure_kite_session,
    get_best_token_file,
    safe_kite_call,
    get_weekly_expiry,
    log_to_journal
)

# ── targets ──
from targets import (
    find_profit_targets,
    find_profit_targets_bearish,
    check_left_side_rule,
    check_left_side_rule_bearish,
    check_left_side,
    check_left_side_bearish,
    calculate_sl_buffer,
    calc_rr,
    check_circuit_and_spread_shield
)

# ── patterns_bull ──
from patterns_bull import (
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout,
    scan_pattern_lifecycle_stage,
    scan_trend_continuation_reentry
)

# ── patterns_bear ──
from patterns_bear import (
    find_anchor_bearish_engulfing,
    find_anchor_hh_sweep,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_anchor_bcd_breakout_bearish,
    scan_pattern_lifecycle_stage_bearish,
    scan_trend_continuation_reentry_bearish,
    scan_anchor_bcd_breakout_generic
)

# ── pattern_funnel ──
import pattern_funnel
from pattern_funnel import (
    STAGE_A_PLUS,
    STAGE_A,
    STAGE_B,
    load_funnel_state,
    save_funnel_state,
    update_funnel,
    promote_item,
    evict_item,
    clear_funnel,
    get_funnel_summary
)

# ── position_monitor ──
from position_monitor import (
    NFO_CACHE_FILE,
    EXECUTED_EXITS_FILE,
    EXECUTED_EXITS,
    ACTIVE_POSITIONS,
    position_lock,
    live_execution_enabled,
    get_option_lot_size,
    contract_is_expired,
    close_stock_position,
    load_executed_exits,
    save_executed_exit,
    is_contract_exit_executed,
    clear_executed_exit,
    is_new_entry_allowed,
    is_market_open,
    close_position,
    monitor_active_positions,
    sanitize_entry_time,
    is_candle_before_entry,
    _get_nfo_cache,
    _nfo_cache_df,
    _nfo_cache_mtime,
    _EXECUTED_EXITS_MTIME,
    _CONTRACT_EXPIRY_RE,
    _load_program_config_file
)

# ── display_writer ──
from display_writer import (
    write_scan_display_data,
    clean_timestamp
)

# ── resolve ──
from resolve import (
    resolve_option_strikes,
    resolve_option_spread,
    scan_symbol,
    derive_sl_targets_for_contract,
    derive_sl_targets_for_symbol,
    reconcile_positions,
    sync_kite_positions,
    is_anchor_valid_and_active,
    find_newest_valid_anchor,
    get_anchor_invalidation_reason,
    lookup_scan_sl_target,
    get_override_paths,
    simulate_trade_outcome,
    calculate_position_size,
    is_setup_already_completed,
    load_program_config_for_engine
)

# ── swing_detection ──
from swing_detection import (
    detect_parabolic_multi_swings,
    extract_swing_pivots,
    validate_parabolic_cascade_structure,
    is_parabolic_arch_enhanced
)

# ── trade_db ──
import trade_db

# ── dashboard_sl_overrides ──
from dashboard_sl_overrides import (
    read_sl_overrides,
    write_sl_overrides,
    sanitize_sl_and_entry,
    clean_stale_overrides,
    purge_sl_override
)

# ── vix_guard ──
from vix_guard import (
    get_india_vix,
    evaluate_vix_regime
)

# ── portfolio_risk ──
from portfolio_risk import (
    check_portfolio_risk_caps
)

# ── liquidity_guard ──
from liquidity_guard import (
    check_bid_ask_spread_liquidity
)

# ── morning_reconciler ──
from morning_reconciler import (
    run_preflight_reconciliation,
    is_preflight_window
)




