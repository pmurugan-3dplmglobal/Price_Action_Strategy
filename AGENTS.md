# AGENTS.md — Technical Code Map & Operational Directives

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
   - Classifies trade setups using Stage 0 Parabolic Decay Soft Scoring (🥇 T1 Gold, 🥈 T2 Core, 🥉 T3 Momentum) and VCP metrics (ATR3/ATR14, TTM Squeeze).
3. **Quantitative Systems Engineer & Architecture Guardian**:
   - Maintains single source of truth across `common/`, zero-regression testing, and SQLite WAL database ACID integrity.
   - Autonomous execution: Proactively verifies AST syntax, runs the regression suite (`python scratch/run_full_regression_test.py`), logs issues in `ISSUE_MANAGEMENT.yaml`, and keeps `MASTER_DOCUMENTATION.yaml` synchronized.

## Ground Rules

- **READ `AI_CONTEXT_INDEX.md` FIRST** — it tiers every directory (Tier 1 core / Tier 2 reference / Tier 3 runtime).
  For routine code changes read ONLY Tier 1 folders touched by the task; avoid `archive/`, `Reference/`, `__pycache__/`, `backtest/`, or `scratch/` unless explicitly needed.
- **Autonomous Execution**: AGY is authorized to make file changes & run verification commands directly in this project without prompting for permission. Keep the user informed of all actions taken.
- **Strict Cloud VM Deployment Pipeline (`Local -> Test -> Git Push -> Git Pull on VM`)**:
  - **NEVER edit code directly on remote cloud VMs** (Oracle Cloud / AWS).
  - Workflow: 1. Local Dev -> 2. Local AST & Regression Test (100% pass) -> 3. Git Push `origin/master` -> 4. Git Pull on VM & restart systemd services (`sudo systemctl restart trading-options trading-stock trading-export`).
  - Machine-specific credentials (`input/kite_access_token.txt`, configs, `/etc/trading.env`) remain isolated per environment and are never cross-pollinated.
- Core strategy logic in `common/trading_core.py` must not change during cleanup/refactors — only remove dead code / alias duplicates.
- Always use canonical paths from `common/paths.py`. Never use CWD-relative paths (ISSUE-038 family).
- Record every bug fix / feature in `ISSUE_MANAGEMENT.yaml`; keep `MASTER_DOCUMENTATION.yaml` accurate. Commit to git with proper notes when asked.

## Domain Invariants (Price Action & Strategy Rules)

- **OHLCV Geometry Over Visual Labels**: Pattern structures are detected strictly from raw OHLCV candle data geometry, NOT from visual text annotations on chart images. Horizontal lines on charts correspond to AnchorLow/AnchorHigh boundaries computed from candlestick data.
- **BASE_ABCD Pattern Validity**: BASE_ABCD is a core valid anchor pattern. Charts showing horizontal accumulation/distribution support/resistance levels map directly to BASE_ABCD detected from underlying price action.
- **D1 vs D2 Lifecycle**: Multiple "D" markers on a chart represent the trade lifecycle:
  - **Marker D1**: Initial Base Breakout (`scan_anchor_bcd_breakout`).
  - **Marker D2**: Trend Continuation Re-Entry / Pyramid (`scan_trend_continuation_reentry` — Datta Playbook Page 16/17).
- **Option vs Stock Parity Invariants**:
  - *Options*: Long Option Buyer invariant (both CE and PE contracts are bought long via BUY orders, profit as premium rises, and exit via SELL).
  - *Cash Equities*: Long trades buy CNC/MIS; Bearish trades short sell via `PRODUCT_MIS` (profit as price falls, target exits trigger on $LTP \le Target$, breakeven trails down to $Entry \times 0.98$, and exits buy to cover via BUY MIS at ask * 1.005).
- **Option Contract VWAP +2σ Overpay Guard & D1/D2 Confluence**:
  - Option contracts evaluate intraday VWAP $\pm 2\sigma$; overstretched contracts ($> +2\sigma$ or $> 15\%$) receive ranking penalties without starving trades.
  - D1 Reversals verify Spot Intraday VWAP reclaim / structural support hold (promoting confirmed setups with $R:R \ge 2.0$ to 🥇 T1 Gold); D2 Continuations enforce Spot EMA13/44 trend momentum.
- **Robust Contract Identification**:
  - `is_option_contract` verifies suffix `CE`/`PE` AND containing digits, preventing false option classification on cash equities (e.g. `PETRONET`, `PEL`, `PERSISTENT`, `CENTRALBK`).
- **Datta & Minervini Law (Risk Discipline & Objective Re-Entry Mandate)**:
  - *Stop-Loss as Capital Shield (Outcome Bias Immunity)*: A triggered stop-loss (e.g. ABCAPITAL 410 CE @ 5.75 protecting against a plunge to 5.05/zero) is an absolute victory of risk management. Never judge an exit by subsequent market drift.
  - *SL Exits the Risk, NOT the Symbol*: Hitting an SL never disqualifies a ticker permanently. Premature timing $\ne$ bad setup. When a ticker forms a fresh institutional sweep base (e.g. Hammer / LL Sweep at key support) and gives a confirmed D2 breakout, re-entry must be executed objectively without ego or hesitation.
  - *Moneyness & Theta Preservation on Secondary Entries*: When re-entering following a multi-day recovery base, prioritize At-The-Money (ATM) or In-The-Money (ITM) strikes (e.g. 400/405 CE over 410 CE) to eliminate accumulated Theta drag and capture full spot delta velocity.
- **Dynamic F&O Universe Resolution**: F&O stock & option contracts are dynamically resolved from the NSE/NFO exchange master via `resolve.py` — NOT restricted to a hardcoded static list.
- **Unlisted Equities**: Symbols like HDBFS (unlisted/pre-IPO) are used for chart demonstrations only; live automated Kite execution only routes listed NSE/BSE cash and F&O symbols.

## Core System Architecture & Entry Points

| Subsystem | Port / Mode | Primary Files | Notes |
|---|---|---|---|
| **Options Dashboard** | Port 5050 | `Trade_Option/app_option_Trade.py` | UI templates in `Trade_Option/templates/index.html` |
| **Index Options Engine** | Background | `Trade_Option/index_options_trade_engine.py` | Intraday NIFTY, BANKNIFTY, SENSEX (BFO exchange) |
| **Stock Options Engine** | Background | `Trade_Option/stock_options_trade_engine.py` | 210+ F&O stocks, Fast Surveillance Radar loop |
| **Stock Dashboard** | Port 5051 | `Trade_Stock/app_Stock_Trade.py` | UI templates in `Trade_Stock/templates/index.html` |
| **Stock Scanners** | CLI / Daemon | `Trade_Stock/stock_reversal_scanner.py` | Single real impl driven by `PROFILE`. Wrappers: `stock_bullish_reversal_scanner.py`, `stock_bearish_reversal_scanner.py` |
| **Auto Exporter** | Scheduled | `Trade_Option/automated_strategy_exporter.py` | Invoked via `run_automated_export.bat` / daemon |
| **Shared Core** | Library | `common/` (`trading_core.py`, `paths.py`, `trade_db.py`, etc.) | Centralized re-export hub and domain logic |

- **UI Templates**: Rendered via external template files (`templates/index.html`). Modify HTML/JS directly without editing Python app code.
- **Canonical Paths**: Always import file targets from `common/paths.py` (`SCAN_DISPLAY_*`, `TRADES_DB`, `TOKEN_FILE`, etc.).
- **Process Isolation**: Dashboards launch scanners as separate processes. Never import both bull and bear scanner wrappers into the same Python process.

## Verification Commands

- **AST Syntax Check**: `python -c "import ast; ast.parse(open('FILE', encoding='utf-8').read())"`
- **Import Smoke Test**: `python -c "import Trade_Option.app_option_Trade, Trade_Stock.app_Stock_Trade, Trade_Option.index_options_trade_engine, Trade_Option.stock_options_trade_engine, common.trading_core"`
- **Unit Verification Suites**: `python scratch/test_institutional_enhancements.py` (5/5), `python scratch/test_parity_alignment.py` (4/4), `python scratch/test_vcp_metrics.py` (4/4), `python scratch/test_spread_liquidity_reconciler.py` (7/7), `python scratch/test_cve_fixes.py` (5/5), `python scratch/test_vix_portfolio_volume.py` (47/47).
- **Regression Suite**: `python scratch/run_full_regression_test.py` (Validates all 21 test suites: imports, Kite session, scanner configs, serializers, trade DB invariants, paths, and parity).
