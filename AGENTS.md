# AGENTS.md — Technical Code Map

Price Action Trading system (Zerodha Kite) — v2.1.0-stable.
Canonical root: `G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy`

## Defined Agent Roles & Behavioral Persona

AGY operates with three integrated identities across all tasks:
1. **Stock Market Expert (Indian Equities & F&O Domain Mastery)**:
   - Evaluates macro market regimes (NIFTY/BANKNIFTY/SENSEX, sector trends, 13/44 EMA alignment).
   - Deep mastery of option Greeks, Theta time decay, Delta/moneyness (ATM vs OTM selection), 85% Expiry Rollover thresholds, and bid-ask spread liquidity traps.
   - Audits order executions, trade lifecycle events, slippage, and portfolio risk.
2. **Lead Price Action Pattern Analyser (Geometric & Candlestick Specialist)**:
   - Detects and validates 5 Bullish Anchors (Bullish Engulfing, LL Sweep, Hammer Baby, Bullish Harami, Two Higher Highs) and 5 Bearish Anchors (Bearish Engulfing, HH Sweep, Shooting Star Baby, Bearish Harami, Two Lower Lows).
   - Validates A-B-C-D breakout geometry (A=Anchor, B=Pullback, C=Retracement higher low, D=Breakout trigger).
   - Classifies trade setups using Stage 0 Parabolic Decay Soft Scoring (🥇 T1 Gold, 🥈 T2 Core, 🥉 T3 Momentum).
3. **Quantitative Systems Engineer & Architecture Guardian**:
   - Maintains single source of truth across `common/`, zero-regression testing, and SQLite WAL database ACID integrity.
   - Autonomous execution: Proactively verifies AST syntax, runs the 13-test regression suite, logs issues in `ISSUE_MANAGEMENT.yaml`, and keeps `MASTER_DOCUMENTATION.yaml` synchronized.

## Ground Rules

- **READ `AI_CONTEXT_INDEX.md` FIRST** — it tiers every directory (core / reference-only / runtime).
  For routine code changes read ONLY the Tier 1 folders touched by the task; do not read
  `archive/`, `Reference/`, `__pycache__/`, `backtest/`, or `scratch/` unless the task demands it.
- **Autonomous Execution**: AGY is authorized to make file changes & run verification commands directly in this project without prompting for permission. Keep the user informed of all actions taken.
- **Strict Cloud VM Deployment Pipeline (`Local -> Test -> Git Push -> Git Pull on VM`)**:
  - **NEVER edit code directly on remote cloud VMs** (Oracle Cloud / AWS).
  - All bug fixes, enhancements, UI changes, and refactors must strictly follow:
    1. **Local Development**: Edit code exclusively in the local Windows environment.
    2. **Local Test & Verification**: Run AST checks and the 14-test regression suite (`python scratch/run_full_regression_test.py`) to confirm 100% pass.
    3. **Git Push**: Commit and push clean changes to `origin/master`.
    4. **VM Pull & Reload**: Execute `git pull origin master` on the VM followed by restarting systemd services (`sudo systemctl restart trading-options trading-stock trading-export`).
    5. **Account Credentials Isolation**: Machine-specific tokens (`input/kite_access_token.txt`) and configs remain isolated per environment and are never cross-pollinated.
- Core strategy logic in `common/trading_core.py` must not change during cleanup/refactors — only remove dead code / alias duplicates.
- Always use canonical paths from `common/paths.py`. Never use CWD-relative paths (ISSUE-038 family).
- Record every bug fix / feature in `ISSUE_MANAGEMENT.yaml`; keep `MASTER_DOCUMENTATION.yaml` accurate.
- Commit to git with proper notes when asked.

## Domain Invariants (Price Action & Strategy Rules)

- **OHLCV Geometry Over Visual Labels**: The trading engine detects pattern structures strictly from raw OHLCV candle data geometry, NOT from visual text annotations on chart images. Horizontal lines on charts correspond to AnchorLow/AnchorHigh boundaries computed from candlestick data.
- **BASE_ABCD Pattern Validity**: BASE_ABCD is a core valid anchor pattern. Charts showing horizontal accumulation/distribution support/resistance levels map directly to BASE_ABCD detected from underlying price action.
- **D1 vs D2 Lifecycle**: Multiple "D" markers on a chart represent the trade lifecycle:
  - **Marker D1**: Initial Base Breakout (`scan_anchor_bcd_breakout`).
  - **Marker D2**: Trend Continuation Re-Entry / Pyramid (`scan_trend_continuation_reentry` — Datta Playbook Page 16/17).
- **Dynamic F&O Universe Resolution**: F&O stock & option contracts are dynamically resolved from the NSE/NFO exchange master via `resolve.py` — NOT restricted to a hardcoded static list.
- **Unlisted Equities**: Symbols like HDBFS (unlisted/pre-IPO) are used for chart demonstrations only; live automated Kite execution only routes listed NSE/BSE cash and F&O symbols.

## Architecture Overview

```
common/                       # shared logic (the "brain")
  trading_core.py (3288)      # Backward-compatible re-export hub. Consumers import unchanged.
                              # All logic now lives in focused sub-modules below (2026-08-11 decomp).
  timeframe_utils.py          # LOOKBACK_LIMITS, get_fetch_timeframe, resample_timeframe, get_adaptive_lookback
  registries.py               # STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, sync_stock_tokens
  session.py                  # load_kite_session, ensure_kite_session, get_best_token_file, safe_kite_call
  targets.py                  # find_profit_targets (bull+bear), check_left_side_rule*, calc_sl_buffer, calc_rr
  patterns_bull.py            # 5 bullish anchor detectors + scan_anchor_bcd_breakout + trend_continuation_reentry
  patterns_bear.py            # 5 bearish anchor detectors + scan_anchor_bcd_breakout_bearish + generic dispatcher
  position_monitor.py         # monitor_active_positions, close_position, close_stock_position, exit guards
  display_writer.py           # write_scan_display_data, clean_timestamp, sanitize_entry_time
  resolve.py                  # resolve_option_strikes, scan_symbol, derive_sl_targets*, reconcile_positions
  ema_engine.py               # 13/44 EMA strategy engine (stock spot + option contracts)
  paths.py (49)               # single source of truth for all file paths
  dashboard_sl_overrides.py   # shared read/write of user-edited SL/T1/T2/T3 overrides (dashboards) [atomic write]
  trade_db.py                 # SQLite-backed trade DB (WAL mode, ACID). Auto-migrates from trades_db.json.
  daily_trade_journal.py      # trade journal CSV/db [hardcoded remarks removed 2026-08-11]
  equity_universe.py          # stock universe for scanning
  spot_enricher.py            # spot price enrichment for symbols
  websocket_monitor.py        # (optional) live websocket
  __init__.py                 # marks common/ as a Python package


Trade_Option/                 # Options Dashboard + engines (port 5050)
  app_option_Trade.py (1866)  # Flask dashboard; HTML/JS in templates/index.html
  stock_options_trade_engine.py (801)   # Stock Options engine (thin wrapper over trading_core)
  index_options_trade_engine.py (571)   # Index Options engine (thin wrapper over trading_core)
  templates/index.html (2030) # dashboard HTML/JS (loaded at import)
  automated_strategy_exporter.py
  run_export_scheduler_daemon.py
  launcher.py

Trade_Stock/                  # Stock Trade Dashboard + scanners (port 5051)
  app_Stock_Trade.py (1668)   # Flask dashboard; HTML/JS in templates/index.html
  stock_reversal_scanner.py (375)   # merged BULL/BEAR parameterized scanner (PROFILE-driven)
  stock_bullish_reversal_scanner.py (25)  # thin wrapper: configure_bull() + re-export
  stock_bearish_reversal_scanner.py (24)  # thin wrapper: configure_bear() + re-export
  templates/index.html (1995) # dashboard HTML/JS (loaded at import)

Kite_Access_Token_gen.py      # root-level token generator (single canonical copy; oracle/*.sh reference it)
archive/                      # decommissioned code (moved from legacy_backup/)

scratch/                      # diagnostic/regression scripts
  run_full_regression_test.py # 10-test regression suite (imports both scanners + apps)

backtest/                     # backtest scripts
oracle/                       # deployment scripts (systemd, token check)
input/                        # kite_access_token.txt, program_config.json, flags
output/monitor/               # runtime state: scan_display*.json, trades_db.json, etc.
output/logs/                  # engine/scanner logs
```

## Entry Points & Ports

| Purpose | File | Port / invocation |
|---|---|---|
| Options Dashboard | `Trade_Option/app_option_Trade.py` | 5050 |
| Stock Dashboard | `Trade_Stock/app_Stock_Trade.py` | 5051 |
| Stock Bull scanner | `Trade_Stock/stock_bullish_reversal_scanner.py` | direct: `python ...` |
| Stock Bear scanner | `Trade_Stock/stock_bearish_reversal_scanner.py` | direct: `python ...` |
| Auto export | `run_automated_export.bat` | calls exporter/daemon |
| Kill all | `kill_all.ps1` | matches `app_option_Trade` / `app_Stock_Trade` cmdline |

Dashboards launch scanners as **separate processes** (`python stock_<side>_reversal_scanner.py`).
Because `configure_bull()` / `configure_bear()` mutate the same shared `PROFILE` dict, never import
both wrappers in one process and expect both configurations — the last-configured side wins.
`run_full_regression_test.py` only checks the `SCAN_DISPLAY_FILE` snapshots, so it is safe.

## Scanner Merge (BULL/BEAR)

- `stock_reversal_scanner.py` = the single real implementation (parameterized by `PROFILE`).
- Bull: `config_section='daily'`, `handle_anchor_flag=True`, `display_file=paths.SCAN_DISPLAY_STOCK_FILE`,
  log `bull_daily_scanner.log`, journal tag `SCAN_MATCH`.
- Bear: `config_section='bear_trade'`, `handle_anchor_flag=False`, `display_file=paths.SCAN_DISPLAY_BEAR_FILE`,
  log `bull_bear_daily_scanner.log`, journal tag `SCAN_MATCH_BEAR`.
- Wrapper files re-export module-level names (`PROFILE`, `TARGET_INDEX`, `SCAN_DISPLAY_FILE`, `run_scan`,
  `export_results`, `main`, ...) after calling `configure_*()`, so `from stock_bullish_reversal_scanner import
  SCAN_DISPLAY_FILE` reflects the configured side.

## Dashboards & Templates

- HTML/JS no longer lives inline in `app_*.py`. Both apps read their template at import:
  `with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates/index.html')) ...`
  then still use `render_template_string(HTML_TEMPLATE, refresh=..., programs=...)`.
- To edit dashboard UI, edit `Trade_Option/templates/index.html` or `Trade_Stock/templates/index.html`
  (option 2030 lines / stock 1995 lines), then restart the dashboard — no Python edit needed.

## trading_core.py Key Functions

Session/data: `load_kite_session`, `ensure_kite_session`, `get_best_token_file`, `safe_kite_call`,
`fetch_and_resample_candles`, `fetch_option_data`, `resample_timeframe`, `get_fetch_timeframe`.

Anchors/patterns (bull): `find_anchor_bullish_engulfing`, `find_anchor_ll_sweep`, `find_anchor_hammer_baby`,
`find_anchor_bullish_harami`, `find_anchor_two_higher_highs`, `scan_anchor_bcd_breakout`.

Anchors/patterns (bear): `find_anchor_bearish_engulfing`, `find_anchor_hh_sweep`, `find_anchor_shooting_star_baby`,
`find_anchor_bearish_harami`, `find_anchor_two_lower_lows`, `scan_anchor_bcd_breakout_bearish`.

Shared: `scan_anchor_bcd_breakout_generic(df, side=...)`, `scan_trend_continuation_reentry(+_bearish)`,
`find_newest_valid_anchor`, `is_anchor_valid_and_active`, `get_anchor_invalidation_reason`,
`find_profit_targets(+_bearish)`, `check_left_side_rule(+_bearish)`, `calc_rr`.

Position mgmt: `close_position` (real exit path), `close_stock_position`, `monitor_active_positions`,
`reconcile_positions`, `sync_kite_positions`, `derive_sl_targets_for_contract`,
`derive_sl_targets_for_symbol`, `lookup_scan_sl_target`, `sanitize_entry_time`.

Display/persistence: `write_scan_display_data`, `load_executed_exits`/`save_executed_exit`/`clear_executed_exit`,
`is_contract_exit_executed`, `contract_is_expired`, `get_option_lot_size`, `live_execution_enabled`.

Market: `is_market_open`.

## Canonical File Paths (common/paths.py)

- `SCAN_DISPLAY_FILE` → `output/monitor/scan_display.json` (nifty50 options)
- `SCAN_DISPLAY_INDEX_FILE` → `output/monitor/scan_display_index.json` (index options)
- `SCAN_DISPLAY_STOCK_FILE` → `output/monitor/scan_display_stock.json` (bull stock scans)
- `SCAN_DISPLAY_BEAR_FILE` → `output/monitor/scan_display_stock_bear.json` (bear stock scans)
- `SCAN_DISPLAY_EMA_FILE` / `SCAN_DISPLAY_EMA_STOCK_FILE` → EMA scan displays
- `TRADES_DB` → `output/monitor/trades_db.json`; `ACTIVE_POSITIONS_DB` → `output/monitor/active_positions_db.json`
- `CYCLE_STORE_FILE` → `output/monitor/cycle_trades.json`; `EXECUTED_STORE_FILE` → `output/monitor/executed_patterns.json`
- `TOKEN_FILE` → `input/kite_access_token.txt`; `PROGRAM_CONFIG_FILE` → `input/program_config.json`
- `JOURNAL_TRADES_DB` → `output/monitor/journal_trades_db.json`; `TRADE_JOURNAL_CSV` → `output/monitor/trade_journal.csv`
- `NIFTY50_LOG_FILE` → `output/logs/bull_nifty50_scanner.log`; `INDEX_LOG_FILE` → `output/logs/bull_index_trade_engine.log`; `EMA_LOG_FILE` → `output/logs/ema_engine.log`

## Verification

- Syntax: `python -c "import ast; ast.parse(open('FILE', encoding='utf-8').read())"`
- Import smoke test: import `app_option_Trade`, `app_Stock_Trade`, `index_options_trade_engine`,
  `stock_options_trade_engine`, both scanner wrappers, `trading_core`.
- Regression: `python scratch/run_full_regression_test.py` (10 tests: imports, Kite auth, scanners,
  display serializers, dashboard API, trade_db, path consistency, DB invariants, engine path alignment,
  entry_time invariants).
- Note: tests hitting live Kite API (Test 2/3/5) need a valid `input/kite_access_token.txt`.
