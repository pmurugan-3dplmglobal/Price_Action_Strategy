# AGENTS.md — Trading Control Center

## Quick Start

```bash
# 1. Generate Kite token (one-time, expires daily)
python Kite_Access_Token_gen.py

# 2. Check config
#    input/program_config.json — set _backtest: false for live, true for backtest

# 3. Launch dashboard
python app.py
# Open http://localhost:5050

# 4. Start engines from UI (click Start for each) OR manually:
python live-trade/bull_index_engine.py --live
python live-trade/bear_index_engine.py --live
python live-trade/bull_nifty50_scanner.py --live
python live-trade/bear_nifty50_scanner.py --live

# 5. Stop everything
.\shutdown.bat
```

## System Architecture

```
launcher.py → opens browser + subprocess.run(app.py)
                  │
                  ▼
            app.py (Flask, port 5050)
                  │
                  │ subprocess.Popen (via UI Start buttons)
                  ▼
     ┌──────────────────┬──────────────────┐
     │  Index Engines   │  Nifty50 Engines │
     │  bull_index      │  bull_nifty50    │
     │  bear_index      │  bear_nifty50    │
     └──────────────────┴──────────────────┘
                  │
                  ▼
         Kite API (real trades)
```

**Master/worker model**: `app.py` is the dashboard/API server. Engines run as **separate processes** spawned via `subprocess.Popen`. Communication is through shared files only (no IPC).

### Engine Lifecycle (PID file system)

| File | Path | Purpose |
|------|------|---------|
| `pid_util.py` | root + `shared/` | Shared PID file utilities |
| `bull_index.pid` | `output/monitor/` | PID for bull index engine |
| `bear_index.pid` | `output/monitor/` | PID for bear index engine |
| `bull_nifty50.pid` | `output/monitor/` | PID for bull nifty50 engine |
| `bear_nifty50.pid` | `output/monitor/` | PID for bear nifty50 engine |

**Start**: engine writes its PID to `output/monitor/<id>.pid`, registers `atexit` cleanup + `SIGTERM`/`SIGINT` handler.

**Duplicate prevention**: engine checks `.pid` file before starting — if PID is alive, exits immediately. `app.py` also checks `.pid` before spawning.

**Stop via dashboard**: sends `taskkill /PID` (SIGTERM on Linux) → waits 2s → `taskkill /F /T /PID` if still alive. Removes `.pid` file.

**Dashboard restart recovery**: on startup, `app.py` scans for orphaned `.pid` files and re-registers live PIDs in the `processes` dict.

### CLI Flags (all engines)

| Flag | Effect |
|------|--------|
| *(none)* | Reads `_backtest` from config; live or backtest |
| `--live` | Force live mode (skip backtest even if `_backtest: true`) |
| `--force-backtest` | Force backtest (even if `_backtest: false`) |
| `--date=YYYY-MM-DD` | Single-day backtest |
| `--backtest-range=START,END` | Multi-day backtest |
| `--anchor-only` | Run anchor scan once, then exit |

## Full Documentation

See **`LIVE_TRADE_FLOW.md`** for complete technical/functional reference covering:
- System architecture & file roles
- Config key reference
- Option-premium scanning (anchor detection + BCD confirmation)
- Pattern detection (all 10 patterns with candle conditions)
- Trade execution & position management
- Backtest engine architecture
- Dashboard API endpoints
- PID system & crash recovery

## File Layout

```
project_root/
├── shared/                   # Reusable modules
│   ├── config.py             # load_program_config, constants, registries
│   ├── kite_utils.py         # safe_historical, sync_instruments, NFO_INSTRUMENTS
│   ├── patterns.py           # detect_and_cache_a, find_bcd_forward, 10 anchor finders
│   ├── option_utils.py       # resolve_option_strikes, resolve_option_contract
│   ├── trade_db.py           # trades_db.json CRUD, executed patterns registry
│   ├── pid_util.py           # PID file lifecycle (startup, cleanup, recovery)
│   ├── journal.py            # log_to_journal (trade_journal.csv writer)
│   └── tiers.py              # calculate_tiered_rr
├── live-trade/               # Live trading engines
│   ├── bull_index_engine.py      # Bullish index options (CE)
│   ├── bear_index_engine.py      # Bearish index options (PE)
│   ├── bull_nifty50_scanner.py   # Bullish Nifty 50 stocks (CE)
│   ├── bear_nifty50_scanner.py   # Bearish Nifty 50 stocks (PE)
│   ├── bull_nifty50_daily_scanner.py  # Daily analysis (bullish, export only)
│   └── bear_nifty50_daily_scanner.py  # Daily analysis (bearish, export only)
├── backtest/                 # Backtest engines
│   ├── bull_index_backtest.py
│   ├── bear_index_backtest.py
│   ├── bull_nifty50_backtest.py
│   └── bear_nifty50_backtest.py
├── input/
│   ├── program_config.json       # API keys + per-engine settings
│   └── kite_access_token.txt     # Kite API session token
├── output/                   # Runtime data (gitignored)
├── app.py                    # Flask dashboard (subprocess manager)
├── launcher.py               # Opens browser → app.py
├── Kite_Access_Token_gen.py  # One-time token generator
├── pid_util.py               # Thin re-export → shared.pid_util
├── trade_db.py               # Thin re-export → shared.trade_db
├── shutdown.bat / shutdown.ps1
├── AGENTS.md                 # This file
├── LIVE_TRADE_FLOW.md        # Full technical/functional reference
└── .gitignore
```

## Config (`input/program_config.json`)

| Key | Engine | Default |
|-----|--------|---------|
| `_backtest` | All | `false` (live) |
| `index.timeframe` | Bull/Bear Index | `3minute` |
| `index.timeframe_anchor` | Bull/Bear Index | `10minute` |
| `nifty50.timeframe` | Bull/Bear Nifty50 | `15minute` |
| `nifty50.timeframe_anchor` | Bull/Bear Nifty50 | `30minute` |
| `daily.timeframe` | Daily scanners | `day` |
| `index.strike_range` | Bull/Bear Index | `2` / `3` |
| `nifty50.strike_range` | Bull Nifty50 | `1` |
| `bear_nifty50.strike_range` | Bear Nifty50 | `1` |

Valid TF values: `minute`, `3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `60minute`, `4hour`, `day`

## Key Files & Locations

### app.py
- `processes` dict: line 126
- `start_program()`: line 159 (checks `.pid` + spawns subprocess)
- `stop_program()`: line 183 (graduated kill + cleanup)
- `main()`: line 2394 (creates dirs, recovers orphans, starts Flask)

### shared/config.py
- `load_program_config()`: line 1
- All config constants exported

### shared/kite_utils.py
- `safe_historical()`: line 1
- `sync_instruments()`: line 1
- `NFO_INSTRUMENTS`: line 1

### shared/patterns.py
- `A_CACHE`, `_a_cache_key()`: line 1
- `detect_and_cache_a()`, `find_bcd_forward()`: line 1
- All anchor detectors, swing finders, pin bars, negation targets

### shared/option_utils.py
- `resolve_option_strikes()`, `resolve_option_contract()`: line 1
- `get_weekly_expiry()`: line 1

### live-trade/bull_index_engine.py
- `run_scan_cycle()`: option-premium scanning for NIFTY/BANKNIFTY CE
- `execute_highest_rr_trade()`: places BUY order for best RR
- `main()`: PID check + CLI flags + live loop

### 2026-07-14
- Created `LIVE_TRADE_FLOW.md` — comprehensive technical/functional reference
- Created `live-trade/bull_nifty50_daily_scanner.py` + `bear_nifty50_daily_scanner.py` (replaced missing daily scanner files)
- Added `.gitignore` — credentials + output + cache protected
- De-duplicated root `pid_util.py` / `trade_db.py` (thin re-exports to `shared/`)
- Fixed `shared/kite_utils.py` — `import json` moved to top
- Added `/api/trade/close` endpoint (Close button in dashboard now works)
- Updated `shared/pid_util.py` `ENGINE_PID_NAMES` — added daily scanner entries
- Removed stale debug scripts, outdated docs (`PROD_DOC_01.md`, `SETUP_STARTUP.md`, `Read_Me_Notes/`)
- Ran final syntax check on all modified files

## Position Monitoring System (2026-07-14)

All 4 live engines now include automatic SL/target monitoring for active positions:

### How it works
- `monitor_positions(kite)` runs every 3 seconds inside `run_live()`
- Batch-fetches LTP for all active option tokens via `kite.ltp([tokens])`
- Compares current premium against stored SL/T1/T2/T3 levels
- Auto-place MARKET SELL when SL/target is hit
- Updates `trades_db.json` (status, exit_time, pnl_percent)
- Logs to `trade_journal.csv`
- Removes from `ACTIVE_POSITIONS` and saves state

### Direction logic
| Side | SL hit (exit loss) | Target hit (exit profit) |
|------|-------------------|-------------------------|
| CE   | `ltp <= sl`       | `ltp >= t1/t2/t3` |
| PE   | `ltp >= sl`       | `ltp <= t1/t2/t3` |

### Trailing
- T1 hit → moves SL to breakeven (entry +0.2% CE / entry -0.2% PE)
- Updates `trailing_stage` in DB

### Crash recovery (3-tier)
1. **State JSON** (`*_state.json` per engine) — fast recovery
2. **Trades DB** (`trades_db.json`) — cross-check for orphaned ACTIVE trades on startup
3. **Kite positions** (future) — query `kite.positions()` as ultimate fallback

### Duplicate prevention
- `execute_highest_rr_trade()` now calls `record_executed_pattern()` in all 4 engines
- Prevents re-entry of same pattern-symbol-strike combination across restarts

## Changelog (2026-07-14)

### Phase 3: Position Monitoring & Carry-Forward
- Added `monitor_positions()` to all 4 live engines (bull/bear index + bull/bear nifty50)
- Updated `close_position()` in all 4 engines: accepts `reason` + `symbol`, updates DB, logs journal, removes from `ACTIVE_POSITIONS`
- Updated `load_state()` in all 4 engines: cross-checks `trade_db.get_active_trades()` for orphan recovery
- Updated `run_live()` in all 4 engines: calls `monitor_positions(kite)` every 3s
- Added `record_executed_pattern()` call in all 4 `execute_highest_rr_trade()` functions
- Added trailing SL logic: moves to breakeven on T1 hit

### Phase 2: Backtest fixes
- Fixed `sys.path` import in all 4 backtest files
- Added missing `INDEX_TF_FALLBACK` / `NIFTY50_TF_FALLBACK` to `shared/config.py`
- Added `sync_instruments` to `shared/kite_utils.py` and `shared/option_utils.py`
- Fixed `None` cache handling in Nifty50 backtest `run_scan_cycle`
- Added entry/exit timestamps to backtest output (`entry_ts`, `exit_ts`)

### Phase 1: Restructure (Pre-requisite for Option-Premium Scanning)
- Created `shared/` with 7 modules: config, kite_utils, patterns, option_utils, trade_db, pid_util, journal
- Created `live-trade/` with 4 engine files (bull/bear index + bull/bear nifty50)
- Created `backtest/` with 4 backtest engine files
- Updated `app.py` to spawn `live-trade/*.py`
- Updated PID file names in `shared/pid_util.py` and `pid_util.py`
- Deleted old monolithic engine files from root

### Phase 2: Option-Premium Scanning (Implemented)
- **Old (Spot Scanning)**: Detect patterns on stock/index spot charts → resolve ATM option → place order
- **New (Option-Premium Scanning)**: 
  1. Get spot LTP for each symbol
  2. Resolve option contracts: ATM ± `strike_range` × `step_size` (CE for bull, PE for bear)
  3. For EACH contract: fetch option premium data (entry TF + anchor TF)
  4. Run `detect_and_cache_a()` on option anchor TF premium charts
  5. Run `find_bcd_forward()` on option entry TF premium charts
  6. If match → stage trade with THIS specific option contract
  7. Pick highest RR from staged trades → execute

### Fixes
- All 4 engines: `calculate_position_size()` returns 1 (fixed lot sizing bug where tight SL caused 30000+ lot sizes)
- All 4 engines + app.py: PID file system (`shared/pid_util.py`) — duplicate prevention, graceful shutdown via signal handlers, dashboard restart recovery
- All 4 engines: added `--live` / `--force-backtest` CLI flags
- `app.py`: graduated kill (SIGTERM → wait → force) instead of instant `/F`
- `close_position` in all 4 engines: quantity hardcoded to 1 lot (`lot_size` only) — prevents exit with 316× lot_size from stale DB data
- Entry LIMIT orders: price validation (skip if `price ≤ 0`), safe dict access on quote response
- Config: `timeframe_anchor` now properly read from config for Nifty50 engines (was ignored, both TFs set to `timeframe`)
- Added `4hour` to valid TF options across all engines
- **Rule Change**: 1 lot per symbol — `position_size` forced to 1 across all engines