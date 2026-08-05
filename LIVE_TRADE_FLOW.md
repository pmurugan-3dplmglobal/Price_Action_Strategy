# LIVE_TRADE_FLOW — Technical & Functional Reference

> Trading Control Center — Zerodha Kite Options Trading System
> Version: 2026-07-14

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    launcher.py (optional)                     │
│              opens browser → subprocess app.py               │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                      app.py (Flask, port 5050)                │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐   │
│  │ Dashboard   │  │ Process    │  │ Data Refresh Thread  │   │
│  │ (HTML/JS)  │  │ Manager    │  │ (5s poll → cache)    │   │
│  └────────────┘  └─────┬──────┘  └──────────────────────┘   │
│                         │ subprocess.Popen                    │
└─────────────────────────┼─────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
┌─────────▼──────┐ ┌──────▼───────┐ ┌────▼──────────┐
│ live-trade/    │ │ live-trade/  │ │ live-trade/   │
│ bull_index_    │ │ bull_nifty50_│ │ bull_nifty50_ │
│ engine.py      │ │ scanner.py   │ │ daily_scanner │
│ (CE)           │ │ (CE)         │ │ .py (analysis)│
└────────────────┘ └──────────────┘ └───────────────┘
┌─────────▼──────┐ ┌──────▼───────┐ ┌────▼──────────┐
│ live-trade/    │ │ live-trade/  │ │ live-trade/   │
│ bear_index_    │ │ bear_nifty50_│ │ bear_nifty50_ │
│ engine.py      │ │ scanner.py   │ │ daily_scanner │
│ (PE)           │ │ (PE)         │ │ .py (analysis)│
└────────────────┘ └──────────────┘ └───────────────┘
          │               │               │
          └───────────────┼───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │      Zerodha Kite API         │
          │   (REST + WebSocket)          │
          └───────────────────────────────┘
```

### Communication Model
- **Master/worker**: `app.py` is the dashboard/API server. Engines run as **separate processes** spawned via `subprocess.Popen`.
- **No IPC**: Engines communicate with the dashboard through **shared files only** (trade_journal.csv, trades_db.json, log files).
- **PID files**: Each engine registers itself via `shared/pid_util.py` → writes `output/monitor/<engine_id>.pid`.
- **Config**: All engines read from `input/program_config.json` at startup and on each scan cycle.

---

## 2. File Layout & Roles

### Root
| File | Role |
|------|------|
| `app.py` | Flask dashboard (port 5050). Renders UI, manages engine subprocesses, polls data every 5s, serves REST API. |
| `launcher.py` | Opens browser → runs `app.py`. |
| `Kite_Access_Token_gen.py` | One-time token generator. Exchanges OAuth `request_token` for `access_token`. |
| `pid_util.py` | **Thin re-export** of `shared.pid_util`. |
| `trade_db.py` | **Thin re-export** of `shared.trade_db`. |
| `AGENTS.md` | Assistant quick-start reference. |
| `LIVE_TRADE_FLOW.md` | This document. |
| `.gitignore` | Protects credentials, output, cache. |

### `shared/` — Reusable Modules
| File | Exports |
|------|---------|
| `config.py` | `load_program_config()`, `INDEX_REGISTRY`, `STOCK_REGISTRY`, `SUPER_STOCKS`, all config constants (`INDEX_TF_ENTRY`, `INDEX_STRIKE_RANGE`, etc.), file paths (`JOURNAL_FILE`, `TRADES_DB_FILE`, etc.) |
| `kite_utils.py` | `safe_historical()` (rate-limited + disk cache), `create_kite_client()`, `fetch_instruments()`, `is_market_hours()`, `NFO_INSTRUMENTS` DataFrame |
| `patterns.py` | All pattern detection: `detect_and_cache_a()`, `find_bcd_forward()`, `find_profit_targets_negation()`, 10 anchor finders, swing finders, pin bar finders, RR calculators |
| `option_utils.py` | `resolve_option_strikes()`, `resolve_option_contract()`, `get_weekly_expiry()`, `get_lot_size()`, `get_strike_step()` |
| `trade_db.py` | Trade database CRUD: `create_trade()`, `update_trade()`, `get_active_trades()`, `stage_cycle_trade()`, `is_pattern_executed()`, `record_executed_pattern()` |
| `pid_util.py` | PID file lifecycle: `check_pid_file()`, `is_pid_alive()`, `remove_pid_file()`, `get_running_engines()` |
| `journal.py` | `log_to_journal()` — write tab-delimited CSV row to `trade_journal.csv` |
| `tiers.py` | `calculate_tiered_rr()` — multi-tier risk-reward calculator |
| `__init__.py` | Re-exports all symbols from all modules for convenient `from shared import *` |

### `live-trade/` — Live Trading Engines
| File | Direction | Symbols | Contract Type | Entry TF | Anchor TF |
|------|-----------|---------|---------------|----------|-----------|
| `bull_index_engine.py` | Bullish | NIFTY, BANKNIFTY | CE | 3minute | 10minute |
| `bear_index_engine.py` | Bearish | NIFTY, BANKNIFTY | PE | 3minute | 10minute |
| `bull_nifty50_scanner.py` | Bullish | 47 Nifty 50 stocks | CE | 15minute | 30minute |
| `bear_nifty50_scanner.py` | Bearish | 47 Nifty 50 stocks | PE | 15minute | 30minute |
| `bull_nifty50_daily_scanner.py` | Bullish | 47 stocks + 2 indices | — (analysis) | day | day |
| `bear_nifty50_daily_scanner.py` | Bearish | 47 stocks + 2 indices | — (analysis) | day | day |

### `backtest/` — Backtest Engines
| File | Direction | Symbols |
|------|-----------|---------|
| `bull_index_backtest.py` | Bullish | NIFTY, BANKNIFTY CE |
| `bear_index_backtest.py` | Bearish | NIFTY, BANKNIFTY PE |
| `bull_nifty50_backtest.py` | Bullish | 47 Nifty 50 stocks CE |
| `bear_nifty50_backtest.py` | Bearish | 47 Nifty 50 stocks PE |

### `input/` — Configuration
| File | Content |
|------|---------|
| `program_config.json` | API keys + per-engine settings (`timeframe`, `strike_range`, `lookback_days`, etc.) |
| `kite_access_token.txt` | JSON: `{api_key, access_token, generated_at}` |

### `output/` — Runtime Data
| Path | Content |
|------|---------|
| `output/logs/*.log` | Engine log files (6 files, one per engine) |
| `output/monitor/trades_db.json` | Trade database (array of trade objects) |
| `output/monitor/trade_journal.csv` | Tab-delimited journal of all trade actions |
| `output/monitor/executed_patterns.json` | Registry of executed patterns (prevent re-execution) |
| `output/monitor/cycle_trades.json` | Staged trades from current scan cycle |
| `output/monitor/*.pid` | PID files (one per engine) |
| `output/monitor/*_state.json` | Crash recovery state (active positions) |
| `output/monitor/backtest_results_*.json` | Backtest summaries |
| `output/exports/*.xlsx` | Daily scanner Excel exports, trade archives |

---

## 3. Config Reference (`input/program_config.json`)

```json
{
  "api_key": "...",
  "api_secret": "...",
  "_backtest": false,
  "index": {
    "timeframe": "3minute",
    "timeframe_anchor": "10minute",
    "lookback_days": 100,
    "scan_interval": 15,
    "risk_percent": 1,
    "capital": 100000,
    "strike_range": 2
  },
  "nifty50": {
    "timeframe": "15minute",
    "timeframe_anchor": "30minute",
    "lookback_days": 200,
    "scan_interval": 30,
    "risk_percent": 10,
    "capital": 100000
  },
  "bear_index": {
    "timeframe": "3minute",
    "timeframe_anchor": "10minute",
    "lookback_days": 30,
    "scan_interval": 15,
    "risk_percent": 1,
    "capital": 100000,
    "strike_range": 3
  },
  "bear_nifty50": {
    "timeframe": "15minute",
    "timeframe_anchor": "30minute",
    "lookback_days": 30,
    "scan_interval": 300,
    "risk_percent": 1,
    "capital": 100000
  },
  "daily": {
    "lookback_days": 500
  }
}
```

### Key Reference

| Key | Used By | Effect |
|-----|---------|--------|
| `_backtest` | All engines | `true` = dry run (no real orders), `false` = LIVE |
| `*.timeframe` | Engine | Entry timeframe for BCD detection |
| `*.timeframe_anchor` | Engine | Anchor timeframe for A-pattern detection |
| `*.lookback_days` | Engine | How many days of historical data to fetch |
| `*.scan_interval` | Engine | Seconds between scan cycles |
| `*.risk_percent` | Engine | % of capital to risk per trade |
| `*.capital` | Engine | Total capital for position sizing |
| `*.strike_range` | Engine | Number of strikes ITM/OTM from ATM (e.g., 2 = ±2 strikes) |

### Valid Timeframes
`minute`, `3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `60minute`, `4hour`, `day`

---

## 4. Kite Token Flow

### Token Generation (`Kite_Access_Token_gen.py`)
1. Reads `api_key` / `api_secret` from `program_config.json`
2. Creates `KiteConnect(api_key)` → builds login URL
3. User logs in via browser, gets redirect with `?request_token=xxx`
4. User pastes redirect URL, script extracts `request_token`
5. Calls `kite.generate_session(request_token, api_secret)` → gets `access_token`
6. Saves as JSON to `input/kite_access_token.txt`

### Token Validation (in `app.py`)
- **Daily expiry**: Tokens expire at end of trading day
- `check_token_valid()` reads token file, checks `generated_at` date against today
- Dashboard banner shows: Valid (green), Expired (yellow), Missing (red)
- "Generate Token" button opens Kite login panel inline

### Session in Engines
Each engine creates its own Kite session:
```python
kite = create_kite_client()  # reads token file, sets access_token
fetch_instruments(kite)       # downloads NFO instrument list
```

---

## 5. PID System & Process Lifecycle

### Start Flow (dashboard Start button)
```
app.py start_program("index")
  → check_token_valid() — token must be valid
  → is_pid_alive("bull_index") — check PID file
  → subprocess.Popen([sys.executable, "live-trade/bull_index_engine.py"])
  → stores Popen object in processes dict
```

### Engine Startup
```
engine.py main()
  → argparse: --live, --force-backtest, --date, --backtest-range, --anchor-only
  → check_pid_file(ENGINE_ID)
      → if PID file exists & process alive → sys.exit(0)
      → else write current PID to output/monitor/<engine_id>.pid
      → register atexit cleanup + SIGTERM/SIGINT handler
  → create_kite_client()
  → fetch_instruments(kite)
  → if LIVE: run_live(kite)
  → else: run backtest or anchor scan
```

### Stop Flow (dashboard Stop button)
```
app.py stop_program("index")
  → subprocess.run(["taskkill", "/PID", pid])           # SIGTERM
  → time.sleep(2)
  → if process still alive → taskkill /F /T /PID        # Force kill
  → remove_pid_file("bull_index")                       # Cleanup PID file
```

### Crash Recovery (dashboard startup)
```
app.py main()
  → get_running_engines() — scans output/monitor/*.pid for alive PIDs
  → re-registers live PIDs in the processes dict (wrapped in _ProcessRef)
  → dashboard shows them as "Live" — no restart needed
```

### PID File Map
| Engine ID | File |
|-----------|------|
| `bull_index` | `output/monitor/bull_index.pid` |
| `bear_index` | `output/monitor/bear_index.pid` |
| `bull_nifty50` | `output/monitor/bull_nifty50.pid` |
| `bear_nifty50` | `output/monitor/bear_nifty50.pid` |

---

## 6. Live Engine Lifecycle

Every live engine follows this loop:

```
run_live(kite):
  load_state()          # recover active positions from last run
  while True:
    if not market hours → sleep 30s
    if scan_interval elapsed:
      1. run_scan_cycle(kite)      → detect patterns → stage trades
      2. execute_highest_rr(kite)  → pick best → place order
      3. clear_cycle_trades()      → flush temp storage
      4. monitor_positions()       → check SL/targets → trail SL
    sleep 1s
```

### Market Hours Check
```python
def is_market_hours():
    weekday = Mon-Thu (0-3) or Fri (4)
    time = 9:15 AM to 3:30 PM IST
```

---

## 7. Option-Premium Scanning (The Core Innovation)

This is the key difference from traditional spot-based scanning. Instead of detecting patterns on stock/index spot charts and then resolving an ATM option, the system detects patterns **directly on option premium charts**.

### Full Scan Cycle Flow

```
run_scan_cycle(kite):
  for each symbol in registry:
    ─────────────────────────────────────────────────────────
    STEP 1: Get spot LTP
    ─────────────────────────────────────────────────────────
    fetch historical data for spot token at entry timeframe
    spot_price = last close

    if symbol already has active position → skip

    ─────────────────────────────────────────────────────────
    STEP 2: Resolve option contracts ATM ± strike_range
    ─────────────────────────────────────────────────────────
    atm_strike = round(spot / step_size) * step_size
    for offset in -strike_range .. +strike_range:
      strike = atm + offset * step
      contract = lookup_instrument(name, strike, option_type, expiry)
      → list of {strike, token, tradingsymbol}

    Example (NIFTY @ 24500, step=50, range=2):
      Strikes: 24400, 24450, 24500, 24550, 24600
      5 CE contracts to scan

    ─────────────────────────────────────────────────────────
    STEP 3: Fetch option premium data (parallel)
    ─────────────────────────────────────────────────────────
    ThreadPoolExecutor(max_workers=5) for each contract:
      - entry_data = historical(token, from, to, ENTRY_TF)
      - anchor_data = historical(token, from, to, ANCHOR_TF)

    ─────────────────────────────────────────────────────────
    STEP 4: Phase A — Anchor Detection on ANCHOR TF premium
    ─────────────────────────────────────────────────────────
    cache_key = f"{contract_symbol}|{today}"
    if cache_key not in A_CACHE:
      detect_and_cache_a(anchor_data, contract_symbol, today, pattern_type)

    if A_PATTERN FOUND:
      # Cache contains: pattern_name, benchmark, SL, T1, T2, T3

    ─────────────────────────────────────────────────────────
    STEP 5: Phase B — BCD Confirmation on ENTRY TF premium
    ─────────────────────────────────────────────────────────
    if A pattern found and needs_bcd:
      bcd = find_bcd_forward(entry_data, anchor_timestamp, benchmark)
      if BCD found:
        entry_price = bcd.close
        validate targets (must be above entry)
        STAGE THIS TRADE

    ─────────────────────────────────────────────────────────
    STEP 6: Collect & Execute
    ─────────────────────────────────────────────────────────
    all_staged_trades = [...from all symbols]
    execute_highest_rr_trade(staged)  → picks 1 best trade
```

### Multi-Threading
- Spot price fetches: ThreadPoolExecutor (5 workers)
- Option premium fetches for each contract: ThreadPoolExecutor (5 workers)
- Total: ~15-20 concurrent API calls per scan cycle

### Rate Limiting
- `safe_historical()` enforces 0.4s minimum between calls (~2.5 req/s)
- Exponential backoff on 429 (Too Many Requests): 2s, 4s, 8s, 16s
- Disk cache for past dates (avoids re-fetching same data)

---

## 8. Anchor Pattern Detection (Phase A)

### Architecture

```
detect_and_cache_a(df_anchor, symbol, date, pattern_type):
  cache_key = symbol|date
  if cached → return cached result

  Run all anchor finders for this pattern_type on df_anchor:
    - For each finder: get list of index positions where pattern found
    - Collect all (index, pattern_name) pairs

  if any anchors found:
    pick LATEST anchor (highest index = most recent)
    extract: ref_price = open, benchmark = high/low, SL = low-1 / high+1
    check: _no_pa_left() — no pattern activity left of anchor
    compute: T1, T2, T3 via find_profit_targets_negation()
    cache & return result

  else:
    cache as None
```

### Bullish Anchor Patterns (for CE contracts)

#### 1. Bullish Engulfing (`find_anchor_bullish_engulfing`)
```python
# Candle i-1: red (close < open)
# Candle i: green (close > open)
# AND: open_i <= close_i-1 AND close_i >= open_i-1
```
Visual: `▅→▇` — Red candle fully engulfed by next green candle.

#### 2. LL Sweep (`find_anchor_ll_sweep`)
```python
# low_i-2 > low_i-1 > low_i  (three declining lows)
# AND: close_i > open_i      (green close on sweep candle)
```
Visual: `⤵⤵⤵✓` — Lower low with green close (liquidity grab + reversal).

#### 3. Hammer / Baby Candle (`find_anchor_hammer_baby`)
```python
# Lower wick >= 2 × body
# Upper wick <= 0.3 × range
# Green close (close > open)
```
Visual: `┴` — Small body at top, long lower tail.

#### 4. Bullish Harami (`find_anchor_bullish_harami`)
```python
# Candle i-1: red (close < open)
# Candle i: green (close > open)
# AND: open_i > close_i-1 AND close_i < open_i-1
```
Visual: `▅[▇]` — Small green candle completely inside previous red candle.

#### 5. Double Bottom (`find_swing_double_bottom`)
```python
# Two swing lows within 2% of each other
# Price breaks above the middle high between them
```
Visual: `W` — Classic double bottom breakout.

### Bearish Anchor Patterns (for PE contracts)

#### 6. Bearish Engulfing (`find_anchor_bearish_engulfing`)
```python
# Candle i-1: green (close > open)
# Candle i: red (close < open)
# AND: open_i >= close_i-1 AND close_i <= open_i-1
```
Visual: `▇→▅` — Green candle fully engulfed by next red candle.

#### 7. HH Sweep (`find_anchor_hh_sweep`)
```python
# high_i-2 < high_i-1 < high_i  (three rising highs)
# AND: close_i < open_i         (red close on sweep candle)
```
Visual: `⤴⤴⤴✗` — Higher high with red close (liquidity grab + reversal down).

#### 8. Shooting Star (`find_anchor_shooting_star`)
```python
# Upper wick >= 2 × body
# Lower wick <= 0.3 × range
# Red close (close < open)
```
Visual: `┬` — Small body at bottom, long upper tail.

#### 9. Bearish Harami (`find_anchor_bearish_harami`)
```python
# Candle i-1: green (close > open)
# Candle i: red (close < open)
# AND: open_i < close_i-1 AND close_i > open_i-1
```
Visual: `▇[▅]` — Small red candle completely inside previous green candle.

#### 10. Double Top (`find_swing_double_top`)
```python
# Two swing highs within 2% of each other
# Price breaks below the middle low between them
```
Visual: `M` — Classic double top breakdown.

### No-PA-Left Check

```python
_no_pa_left(df, a_idx, ref_price, n_a, is_bull):
    # Bullish: no candle left of anchor has close < ref_price
    # Bearish: no candle left of anchor has close > ref_price
    # Ensures the pattern is at a clean "uncontested" level
```

### Profit Targets (Negation Theory)

```
find_profit_targets_negation(df, entry_close, benchmark, pattern_type):
    Collect resistance/support levels from historical price action:

    For BULLISH:
      1. Swing highs within 5-bar window (nearest → farthest)
      2. Engulfing candle highs
      3. All-time high

    For BEARISH:
      1. Swing lows within 5-bar window
      2. Engulfing candle lows
      3. All-time low

    T1 = nearest level
    T2 = second nearest
    T3 = farthest (or all-time high/low)

    Return: (T1, T2, T3)
```

---

## 9. BCD Confirmation (Phase B)

After an anchor pattern is cached, the engine checks for BCD confirmation on the **entry timeframe** premium data.

### Logic (Bullish)

```python
find_bcd_forward(df_entry, a_ts, benchmark, pattern_type='bull'):
    # Filter: only candles AFTER the anchor timestamp
    df = df_entry[df_entry['date'] > a_ts]

    for each candle i:
        if close[i] > benchmark:
            return this candle  # BCD confirmed
    return None  # no confirmation yet
```

Visually:
```
Benchmark ────╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
Price     ╱╲  ╱╲  ╱╲    ╱╲╱╲    ╱╲  ╱╲  ╱╲    ╱╲
          ╲╱  ╲╱  ╲╱  ╲╱╲╱╲╱  ╲╱  ╲╱  ╲╱  ╲╱
          ↑ Anchor   ↑ B: break   ↑ D: entry!
          (A)          above       close > bench
                       bench
```

### Key Difference from Traditional BCD

The shared.patterns `find_bcd_forward()` is simplified compared to the app.py analyze endpoint version. The shared version:
- Only checks for **B** (breakout) and **D** (close above benchmark)
- Does NOT require a **C** (pullback) between B and D
- Returns the first candle that closes above benchmark

This makes it more sensitive (finds setups faster) but less selective (may have more false signals).

---

## 10. Trade Execution

### Picking the Best Trade

```python
execute_highest_rr_trade(kite, staged):
    if not staged: return
    best = max(staged, key=lambda s:
        (s.get("T3") or s.get("T1") or 0) - s.get("Entry", 0)
    )
    # Picks the trade with largest T3-Entry gap (biggest potential profit)
```

### Execution Steps

1. **Dedup check**: `is_pattern_executed()` → skip if this symbol|pattern|strike was already traded
2. **Order placement** (LIVE mode):
   ```
   exchange: NFO
   variety: REGULAR
   transaction_type: BUY (CE) / SELL (PE already negative)
   order_type: LIMIT at (ask OR ltp) × 1.005
   product: NRML
   quantity: lot_size × 1
   ```
3. **Price validation**: skip if `price ≤ 0` or `quantity ≤ 0`
4. **R:R check**: skip if risk-reward < 1.5
5. **Journal log**: `log_to_journal(sym, pattern, timeframe, "BUY", "SUCCESS", ...)`
6. **Trade DB record**: `create_trade(ENGINE_TYPE, sym, {...})`
7. **Pattern registry**: `record_executed_pattern(ENGINE_TYPE, key, ...)`

### Position Sizing
**Hardcoded to 1 lot** (`position_size = 1`). The `risk_percent` and `capital` config values are defined but overridden — all trades are 1 lot regardless.

---

## 11. Position Monitoring

After a trade is placed, the engine monitors the active position in the same loop:

```
monitor_active_positions(kite):
    for each active position:
        get current LTP of the option contract

        # SL Check
        if ltp <= current_sl:
            exit → log to journal → update DB → remove from ACTIVE_POSITIONS

        # Trailing (multiple stages: 0 → T1 reached → T2 reached)
        if trailing_stage == 0 and ltp >= t1:
            trail SL to t1_sl_level → stage = 1
        if trailing_stage == 1 and ltp >= t2:
            trail SL to t2_sl_level → stage = 2

        # T3 Exit
        if ltp >= t3 (bullish) or ltp <= t3 (bearish):
            exit → full target hit → log → update DB
```

### Exit Order
```
exchange: NFO
transaction_type: SELL (CE) / BUY (PE)
order_type: LIMIT at (bid OR ltp) × 0.995
product: NRML
quantity: lot_size × position_size
```

### Close Position (via Dashboard)
The `/api/trade/close` endpoint:
1. Accepts `symbol`, `token`, `engine`
2. Looks up active trade in DB
3. Places market SELL order for the contract
4. Updates trade status to `CLOSED`
5. Logs to journal

---

## 12. Backtesting

### Architecture
Backtest engines live in `backtest/` and mirror their live counterparts:
- Import same pattern detection from `shared.patterns`
- Use `safe_historical()` with disk cache (fast for repeated runs)
- No Kite orders — simulated P&L
- Date override via `BACKTEST_DATE` global

### Running
```
# Single day
python backtest/bull_index_backtest.py --date=2026-07-10

# Range
python backtest/bull_index_backtest.py --backtest-range=2026-01-01,2026-07-14
```

### Simulation Logic
```
simulate_trade_outcome(..., date):
    1. Fetch entry TF data UP TO date (avoid look-ahead bias)
    2. Run same anchor + BCD detection as live engine
    3. If trade triggers: calculate entry, SL, targets
    4. Simulate forward: check if SL hit, T1/T2/T3 hit, or open at day end
    5. Record: entry, exit, P&L, RR, win/loss
```

### Backtest Results
Written to `output/monitor/backtest_results_<engine>.json`:
```json
{
  "engine": "bull_index",
  "total_days": 100,
  "total_trades": 45,
  "wins": 28,
  "losses": 17,
  "win_rate": 62.2,
  "by_symbol": {
    "NIFTY": {"trades": 25, "wins": 16, "losses": 9},
    "BANKNIFTY": {"trades": 20, "wins": 12, "losses": 8}
  }
}
```

---

## 13. Dashboard API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Render HTML dashboard |
| `/api/status` | GET | All live data: positions, journal, stats, logs, config, LTP |
| `/api/token/check` | GET | Validate saved access token |
| `/api/token/url` | GET | Kite Connect login URL |
| `/api/token/exchange` | POST | Exchange request_token → access_token |
| `/api/backtest/mode` | GET/POST | Get/set `_backtest` global flag |
| `/api/scanner/config` | GET/POST | Get/set `disable_nopa` config |
| `/api/config/<prog_id>` | POST | Save per-engine config to `program_config.json` |
| `/api/programs/<prog_id>/start` | POST | Start engine subprocess |
| `/api/programs/<prog_id>/stop` | POST | Stop engine (graduated kill) |
| `/api/anchor/scan` | POST | Launch anchor-only scan (subprocess `--anchor-only`) |
| `/api/anchor/stop` | POST | Signal anchor scan to stop |
| `/api/anchor/status` | GET | Is anchor scan running? |
| `/api/trade/execute` | POST | Manual market order (from Best Trades tab) |
| `/api/trade/close` | POST | Close a position (from Positions tab) |
| `/api/analyze/entry` | POST | Single-symbol entry analysis (fetch + detect) |
| `/api/journal/clear` | POST | Wipe journal + backtest results + executed patterns |
| `/api/logs/clear` | POST | Truncate all log files |
| `/api/trades` | GET | Get trades (filter: `engine`, `active`) |
| `/api/export/monthly` | POST | Export completed trades to archive.xlsx |

### Data Refresh Cycle
- `app.py` runs a background thread every 5 seconds:
  1. Load positions from `trades_db.json`
  2. Load journal from `trade_journal.csv`
  3. Tail log files (last 200 lines)
  4. Parse scan lines for anchor/ABC matches
  5. Build pending trades list from staged trades
  6. Fetch LTP for active positions (every 30s)
  7. Fetch Kite positions (every 60s)
- Dashboard JS calls `/api/status` every 5s (configurable)

---

## 14. Data Files

### Trade Journal (`output/monitor/trade_journal.csv`)
Tab-delimited. Headers:
```
Timestamp	Symbol	Pattern	Timeframe	Action	Status	Entry	SL	Target	RR	Details	P&L %
```

### Trade DB (`output/monitor/trades_db.json`)
```json
{
  "next_id": 157,
  "trades": [
    {
      "id": 156,
      "engine": "bull_index",
      "symbol": "NIFTY",
      "status": "ACTIVE",
      "created_at": "2026-07-14 10:23:15",
      "contract": "NIFTY24JUL24600CE",
      "entry_spot": 45.5,
      "current_sl": 32.0,
      "t1": 55.0,
      "t2": 62.0,
      "t3": 75.0,
      "trailing_stage": 1,
      "lot_size": 65,
      "position_size": 1,
      "pattern": "BULL_ENGULF",
      "timeframe": "3minute",
      "side": "CE",
      "strike": 24600
    }
  ]
}
```

### Executed Patterns (`output/monitor/executed_patterns.json`)
```json
{
  "bull_index": {
    "NIFTY|BULL_ENGULF|CE|24600": {
      "executed_at": "2026-07-14 10:23:15"
    }
  }
}
```

### Cycle Trades (`output/monitor/cycle_trades.json`)
```json
{
  "bull_index": [
    {
      "Symbol": "NIFTY",
      "OptionSymbol": "NIFTY24JUL24600CE",
      "Pattern": "BULL_ENGULF",
      "Entry": 45.5
    }
  ]
}
```

---

## 15. CLI Flags (All Engines)

| Flag | Effect |
|------|--------|
| *(none)* | Reads `_backtest` from config; live or backtest |
| `--live` | Force live mode (skip backtest even if `_backtest: true`) |
| `--force-backtest` | Force backtest (even if `_backtest: false`) |
| `--date=YYYY-MM-DD` | Single-day backtest |
| `--backtest-range=START,END` | Multi-day backtest range |
| `--anchor-only` | Run anchor scan once, then exit |

---

## 16. Known Issues & Limitations

1. **Backtest speed**: ~3s per day due to Kite API rate limiting (2.5 req/s). 100 days ≈ 5 min.
2. **Position sizing**: Hardcoded to 1 lot. `risk_percent`/`capital` config values are effectively ignored.
3. **Nifty50 backtest**: Uses `dt.now()` (not backtest-fixed date) for position monitoring timestamps.
4. **Daily scanner**: No backtest mode — analysis-only, single-run via `--anchor-only`.
5. **Kite token**: Expires daily. Must regenerate before market open.
6. **NoPA check**: `disable_nopa` config exists but is experimental — left-side filter can suppress valid signals.
