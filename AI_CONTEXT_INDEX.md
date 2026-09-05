# AI_CONTEXT_INDEX.md — Read-This-First Guide for AI Sessions

Purpose: save tokens. Each code-change request should read **Tier 1** only.
Reference folders (Tier 2 / Tier 3) are optional and should be opened **only
when a task explicitly needs them**.

## App Context (distilled from MASTER_DOCUMENTATION.yaml / Notes.txt / ISSUE_MANAGEMENT.yaml)

- **What**: Price Action Trading system on Zerodha Kite Connect — "Price Action Unified
  Strategy System", Prod Code v02 (v2.1.0-stable). Architecture = Centralized Shared Core (`common/`) +
  Dual Workspaces (`Trade_Option`, `Trade_Stock`).
- **Strategy**: Unified ABC Bullish & Bearish Reversal Pattern Engine (Negation Theory).
  5 bullish + 5 bearish anchor patterns: Engulfing (ABCD), LL/HH Sweep, Two Higher/Lower
  Highs, Baby Candle/Shooting Star (Hammer), Harami (Inside Bar). Pattern priority 1-5,
  first valid pattern with R:R >= 1.88 triggers setup. Bull shorthands:
  BULL_ENG / BULL_LL / BULL_2HH / BULL_HAM / BULL_HAR / BULL_BASE; bear mirrors BEAR_*.
- **Coverage**: Index Options (NIFTY token 256265 lot 65, BANKNIFTY token 260105 lot 30,
  SENSEX token 265 lot 20 via **BFO** exchange — NIFTY/BANKNIFTY via NFO), Stock Options
  (Full NSE F&O Universe with 210+ constituent equities dynamically discovered), Stock Spot
  Bull (Long CNC/MIS) and Bear (Short MIS) reversals, plus a Stock EMA Engine
  (13 EMA / 44 EMA crossover, `common/ema_engine.py`, default SL=44EMA, T1=1.5RR, T2=2.5RR,
  T3=3.5RR; on 5050 scans stocks→ATM option contracts, on 5051 scans stock spot symbols).
- **Engines / config defaults**:
  - Index Options Engine (5050, BULL): entry TF `3minute`, anchor TF `15minute`, risk 1.0%, strike_range 1.
  - Stock Options Engine (5050, BULL/BEAR): entry `15minute`, anchor `30minute`, risk 10.0%, strike_range 1.
  - Stock Bull Scanner (5051): `daily` profile, entry/anchor `day`, lookback 2000 days, Long Cash Equity.
  - Stock Bear Scanner (5051): `bear_trade` profile, entry/anchor `day`, lookback 2000 days, Short Cash Equity (`PRODUCT_MIS` via SELL, cover via BUY ask * 1.005).
  - Stock EMA Engine (5050+5051): default TF `1d`, fast=13, slow=44, scan_interval 300s,
    target universe selector (ALL / NIFTY50 / NIFTY_NEXT_100 / NIFTY_MIDCAP_100 /
    NIFTY_SMALLCAP_250 / INDEX_OPTIONS). "ALL" aggregates 239 symbols.
- **Config precedence**: 1) Manual UI edits (sl_target_overrides.json /
  active_positions_db.json) → 2) Persistent config/DB (program_config.json, trades DB) →
  3) Adaptive defaults.
- **Timeframes**: native Kite minute/3m/5m/10m/15m/30m/60m/day; resampled 75min (from
  15m, offset='15min'), 4hr (from 60m, '240min'), week (W-FRI). Adaptive lookbacks:
  intraday 30-60d, hourly 180-365d, daily/weekly 2000d. **Trade_Stock scanners default
  strictly to 'day'** unless overridden.
- **Risk management**: SL buffer tiers by price (cheap <10: max(0.40, 10%); 10-50: max(0.60, 4%); 50-200:
  max(1.00, 2.0%); 200-500: max(1.50, 1.5%); index spot >=500: max(2.50, 0.5%)). Monitor
  every 2-5s: SL hit→full exit; T1→SL to Positive Breakeven (+BE: Entry + 2% Bull, Entry - 2% Bear, or full exit if T2/T3 N/A); T2→SL to T1;
  T3→full exit. Targets derived strictly from anchor TF candles. Anchor invalidation =
  any later anchor-TF candle closes below SL (closing basis for Bull, above SL for Bear), or T1 touched.
  Strict **closing-basis** evaluation (scanner trims the still-forming last candle).
- **Key invariants (don't break)**:
  - Benchmark/anchor_floor/direction persisted end-to-end; UI must NOT re-derive A.high/A.low from candle_a_time.
  - Option Long Buyer invariant: CE and PE options are both bought long via BUY orders; Cash Equity supports Long (BUY) and Short (SELL MIS, cover BUY MIS).
  - Option VWAP +2σ Overpay Guard: Intraday VWAP ± 2σ; overstretched contracts (> +2σ or >15%) penalized without starving trades.
  - D1/D2 Regime-Aware Spot Confluence: D1 Reversals require Spot Intraday VWAP reclaim/support hold (promotes to T1 Gold); D2 requires Spot EMA13/44 trend alignment.
  - VCP Metrics: ATR(3)/ATR(14) compression ratio (<= 0.60 indicates >= 40% squeeze) + TTM Squeeze (Bollinger Bands inside Keltner Channels).
  - Point C TWAP Stability: Absorption base tightness (std <= 0.25 * risk) qualifies setups for Tier 1 Gold.
  - Robust Contract Identification: is_option_contract verifies suffix CE/PE and digits, preventing equity collisions (PETRONET, PEL, PERSISTENT).
  - Datta & Minervini Law: SL as capital shield (outcome bias immunity); hitting SL exits immediate risk, not the symbol; objective D2 re-entry.
  - entry_time = true execution time (never candle time); canonical paths from `common/paths.py` only (PATH_SPLIT family).
  - trade_db rejects duplicate ACTIVE contracts & expired contracts; new features strictly isolated with zero regression.
- **Known failure families (see ISSUE_MANAGEMENT.yaml)**: PATH_SPLIT (fixed by `common/paths.py`), DATA_INTEGRITY (duplicate/expired/ghost DB rows), UI_SYNTAX (JS brace errors in templates), STOCK_OPTION_PARITY (short selling MIS order routing and PnL formulas), WINDOWS_FILE_LOCK (retry backoff and tmp isolation), IMPORT_MODULE_RESOLUTION (sys.path alignment for root imports). Always record fixes in ISSUE_MANAGEMENT.yaml with a `family:` marker.
- **Verification**: `scratch/run_full_regression_test.py` = 21 test suites passing 100%. Targeted unit suites: `scratch/test_institutional_enhancements.py` (5/5), `scratch/test_parity_alignment.py` (4/4), `scratch/test_vcp_metrics.py` (4/4), `scratch/test_spread_liquidity_reconciler.py` (7/7), `scratch/test_cve_fixes.py` (5/5), `scratch/test_vix_portfolio_volume.py` (47/47). Syntax: `ast.parse(...)` for .py, `node --check` for JS blocks.
- **Deploy**: Oracle Cloud Always Free (4 ARM cores/24GB RAM/Ubuntu 24.04), dashboards on
  5050/5051. Isolated credentials via `/etc/trading.env`. Token regenerated daily via root `Kite_Access_Token_gen.py`.

## Tier 1 — ALWAYS READ for code changes (core code)

| Path | What it is | When to read |
|---|---|---|
| `common/` | The "brain". `trading_core.py` is a re-export hub (do NOT alter core logic — dead-code removal only). Living logic: `swing_detection.py` (legs, VCP, Option VWAP, TWAP C), `resolve.py` (strikes, spot confluence, contract resolution), `position_monitor.py` (trailing, Spot SL guard, short equity exit), `pattern_funnel.py` (radar lifecycle A+/A/B), `vix_guard.py` (VIX gate), `portfolio_risk.py` (capital-scaled caps), `liquidity_guard.py`, `morning_reconciler.py`, `timeframe_utils.py`, `registries.py`, `session.py`, `targets.py`, `patterns_bull.py`, `patterns_bear.py`, `display_writer.py`, `ema_engine.py`, `paths.py` (canonical paths), `dashboard_sl_overrides.py`, `trade_db.py`, `daily_trade_journal.py`, `equity_universe.py` | Any strategy/engine/position/logic change |
| `Trade_Option/` | Options Dashboard engine (port 5050). `app_option_Trade.py`, `stock_options_trade_engine.py`, `index_options_trade_engine.py`, UI in `templates/index.html` | Options dashboard / option engines / UI on port 5050 |
| `Trade_Stock/` | Stock Trade Dashboard + scanners (port 5051). `app_Stock_Trade.py`, `stock_reversal_scanner.py` (single real impl, PROFILE-driven), wrappers `stock_bullish_reversal_scanner.py` / `stock_bearish_reversal_scanner.py`, UI in `templates/index.html` | Stock dashboard / scanners / UI on port 5051 |
| `AGENTS.md` | Technical code map (also loaded automatically as session instructions) | Always own the content; keep in sync when arch/ports change |
| `ISSUE_MANAGEMENT.yaml` | Active bug/feature tracker (active v2.1.0-stable; historical issues in `archive/ISSUE_HISTORY_ARCHIVE.yaml`) | After each fix/feature |
| `MASTER_DOCUMENTATION.yaml` | Master system doc — keep accurate | When behavior changes |
| `common/paths.py` | Canonical file paths | Any file-path reference — never hardcode paths |
| `Kite_Access_Token_gen.py` | Root-level token generator (single canonical copy) | Only when touching token flow |

## Tier 2 — REFERENCE ONLY (skip by default; high token cost)

Do **NOT** open these on routine code-change requests. Read only when the task
name/content explicitly mentions them.

| Path | What it is | When to use |
|---|---|---|
| `docs/` | System reports, strategy references, and `docs/LIVE_TRADING_EXPERIENCE_PLAYBOOK.md` (Daily live trade lessons & tactical knowledge base) | Post-trade reviews, live lessons, or deep strategy specs |
| `scratch/` | Diagnostic/regression scripts. `run_full_regression_test.py` (regression suite) is the one go-to. | Explicitly asked about past analysis; or to run regression |
| `backtest/` | Backtest scripts + `master_backtest_results.json` | Backtest work / results review only |
| `archive/` (incl. `ISSUE_HISTORY_ARCHIVE.yaml`, `Notes_Inputs_Completed_Archive.txt`, `legacy_backup.zip`) | Historical archives (issues, notes, legacy backups) — preserved for record | Only when investigating past versions |
| `Reference/` | Reference screenshots (JPEGs) | Only when user points at a specific image |
| `__pycache__/` | Compiled bytecode — ignore completely | Never |

## Tier 3 — RUNTIME/DEPLOY (rare)

| Path | What it is | When to use |
|---|---|---|
| `input/` | Secrets/config: `kite_access_token.txt` (daily token), `program_config.json` | Token refresh or config change only |
| `oracle/` | Oracle Cloud deployment scripts (`sync_to_oracle_cloud.py`, systemd/cron) + README | Cloud deployment tasks only |
| `output/monitor/` | Runtime state: scan_display*.json, trades_db.json, active_positions, trade_journal | Troubleshooting live trades / verifying scan output |

## Decision rules for the AI

1. Code-change request → read Tier 1 folders that touch the feature. Stop there.
2. Never read `__pycache__`, `archive/`, or `Reference/` unless explicitly asked.
3. Use `scratch/run_full_regression_test.py` to verify broad changes; use the
   syntax check from `AGENTS.md` for quick checks.
4. If a task mentions "backtest", "cloud", "token", or a specific debug script,
   read the corresponding Tier 2/3 folder. Otherwise don't.
5. Record every change in `ISSUE_MANAGEMENT.yaml`. Keep this index + AGENTS.md accurate.