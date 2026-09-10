# Price Action Trading Algorithm: Comprehensive System Specification & Audit Document
**System Version:** v2.1.0-stable  
**Target Market:** Indian Equities & Derivatives (NSE Cash Equities, NFO Stock Options, NFO Index Options, BFO Sensex Options)  
**Execution Broker:** Zerodha Kite Connect API (REST v3 + WebSocket `KiteTicker`)  
**Design Philosophy:** Pure Price Action Geometry (Datta Playbook & Minervini VCP Principles) with Quantitative Risk Governance & Liquidity Safeguards.

---

## 1. Executive Summary & Core Objective

The algorithm is an autonomous, end-to-end algorithmic trading system designed to trade institutional price action setups. Rather than relying on lagging indicators (like RSI or MACD), the system identifies **high-probability institutional accumulation/distribution bases** on higher timeframes (Anchor TF, typically 30m or Daily) and times precision breakouts, early entries, or retests on lower timeframes (Entry TF, typically 5m or 3m).

The engine operates with three strict mandates:
1. **Geometric Integrity Over Visual Labels**: Structural pattern boundaries (Anchor, Retest, Breakout) are computed mathematically from raw OHLCV candlestick geometry.
2. **Absolute Asymmetric Risk:Reward ($\ge 1.50:1$)**: Trades are executed only when the structural stop-loss permits a positive expectation ratio.
3. **Outcome Bias Immunity**: Risk discipline (stop-loss, trailing breakeven, and anti-chasing filters) takes precedence over market drift.

---

## 2. Theoretical Price Action Framework: The A-B-C-D Cycle

Every trade setup follows a strict 4-phase geometric lifecycle:

```
Price (₹)
      |                                              ▲ Target 1 (+50% to +100%)
      |             ▲ Point B (Initial Push)        /
BM    |-------------|--------------------------[D]-/--  <-- BENCHMARK LINE (Anchor High)
      |            / \                        /
      |      [A]--/   \                      /
      |      /         \                    /
      |     /           ▼ Point C (Retest) /
SL    |----[SL]---------------------------/-----------  <-- STRUCTURAL STOP-LOSS (Anchor Low - Buffer)
      +-----+-----------+-----------------+-----------
         Anchor A     Swing B          Retest C      Breakout D
```

### The 4 Phases Defined:
1. **Point A (Anchor Formation)**:
   * Identifies an institutional exhaustion or reversal event.
   * **5 Bullish Anchors**: Bullish Engulfing, Low-Low (LL) Sweep, Hammer Baby Candle, Bullish Harami (body ratio $\le 50\%$), Two Higher Highs.
   * **5 Bearish Anchors**: Bearish Engulfing, High-High (HH) Sweep, Shooting Star Baby Candle, Bearish Harami, Two Lower Lows.
   * **Base Anchors (`BASE_ABCD`)**: Horizontal consolidation boxes / volatility contraction ranges.
   * **Benchmark ($BM$)**: The breakout trigger boundary (Anchor High for Bullish, Anchor Low for Bearish).
   * **Stop-Loss ($SL$)**: Structural invalidation boundary (Anchor Low $-$ ATR Buffer for Bullish, Anchor High $+$ ATR Buffer for Bearish).

2. **Point B (Swing Push)**:
   * The first wave demonstrating buyer/seller dominance closing beyond the Benchmark ($Close > BM$).
   * Establishes the initial breakout attempt.

3. **Point C (Retest / Shakeout)**:
   * A counter-trend pullback (red candle for bullish setups) that retests the Benchmark level.
   * **Guards on C**:
     * *Spacing Guard*: Point C must form within 25 candles of Point B.
     * *Excursion Guard*: Price cannot exceed $1.5 \times \text{Risk}$ or touch Target 1 during Swing B; otherwise, the move is deemed exhausted.
     * *Invalidation Guard*: Point C must strictly hold above the Anchor Stop-Loss floor ($Low_C \ge SL$).

4. **Point D (Breakout Trigger & Execution)**:
   * The confirmed continuation bar closing beyond the Benchmark ($Close > BM$).
   * Classified into two distinct execution milestones:
     * **Marker D1**: Initial Base Breakout (`scan_anchor_bcd_breakout`).
     * **Marker D2**: Trend Continuation Re-Entry / Pyramid (`scan_trend_continuation_reentry` — Datta Playbook Page 16/17).

---

## 3. The Pattern Radar Funnel (3-Tier Incubation Architecture)

To monitor 200+ F&O symbols efficiently without API throttling or memory overload, setups pass through a multi-stage funnel:

```
[Full Market Universe: ~210 F&O Stocks + Indices]
                      │
                      ▼
┌────────────────────────────────────────────────────────┐
│ Category B: Anchor Base Incubator                      │
│ - Anchor A detected on Anchor TF (30m / Daily)         │
│ - SL and Benchmark lines established                   │
│ - Incubation stage: Awaiting Swing B & Retest C        │
└──────────────────────┬─────────────────────────────────┘
                      │ Swing B pushed + Retest C held
                      ▼
┌────────────────────────────────────────────────────────┐
│ Category A: Breakout Ready                             │
│ - A-B-C structure completed and mathematically intact   │
│ - Staged at Benchmark; awaiting Point D trigger bar    │
└──────────────────────┬─────────────────────────────────┘
                      │ Confirmed VCP squeeze / Top R:R
                      ▼
┌────────────────────────────────────────────────────────┐
│ Category A+ / Fast Radar (Surveillance Loop)           │
│ - Polled every 15 seconds via priority Kite API        │
│ - Real-time execution on D breakout or Post-D retest   │
└────────────────────────────────────────────────────────┘
```

### Funnel Eviction & Hygiene Rules:
* **Stop-Loss Breach (`c_now <= SL`)**: Permanently evicted from all pools.
* **Target 1 Achieved (`c_now >= T1 * 0.995`)**: Permanently evicted to prevent chasing expired moves.
* **Prior-Day Stale Setups (`date < today` & already ran)**: Evicted cleanly at market open.
* **Single Best-Strike Invariant**: Each underlying symbol is allotted a single active CE and PE contract to eliminate option-strike clutter.

---

## 4. Execution Triggers & In-Session Risk Guards

When a setup in Category A/A+ approaches the trigger price, the **Fast Surveillance Radar Loop** evaluates the tick against strict execution gates:

### Execution Trigger Types:
1. **`COMPLETED_BAR_D`**: A full Entry TF candle has closed above Benchmark.
2. **`80%_EARLY_D`**: An active forming candle is $\ge 80\%$ complete in its timeframe, closing $\ge BM \times 1.003$ with proportional volume ($\ge 60\%$ of 20-period average volume).
3. **`POST_D_RETEST`**:
   * If Point D broke out previously (e.g., yesterday or earlier today), price has **not** touched $T_1$, and $SL$ is intact.
   * Price pulls back into the benchmark support zone:
     $$\text{Benchmark} \times 0.980 \le \text{LTP} \le \text{Benchmark} \times 1.025$$
   * System recalculates $R:R$ dynamically from the retest price and executes as a primary setup.

### In-Session Entry Gates:
* **Anti-Chase Runaway Guard**: If LTP $> BM \times 1.08$ ($+8.0\%$ above Benchmark), the engine refuses to buy at market and logs `[RADAR STANDBY: RUNAWAY]`, holding the setup alive on the radar specifically to capture a subsequent `POST_D_RETEST`.
* **Intraday VWAP Support Gate**: Option premium must trade at or above intraday VWAP ($LTP \ge VWAP$).
* **VWAP Stretch Cap**: Option premium stretch must not exceed $+25\%$ above VWAP ($Stretch \le 25\%$) to avoid buying at the top of a parabolic wick.
* **Spot RVOL Confluence**: Validates that the underlying cash equity has above-average Relative Volume backing the option breakout.

---

## 5. In-Trade Position Management & Exit Governance

Once an order fills, position tracking is handed to a dual-layer monitoring engine:

### 1. High-Frequency Tick Monitor (`KiteTicker` WebSocket)
* Streams live tick LTP with sub-second latency.
* Transparent fallback to Kite REST quotes (`kite.quote()`) upon any WebSocket drop or timeout (Error `1006`).
* Failsafe morning freeze: Exit triggers paused before 09:45 AM to avoid opening auction spread traps.

### 2. Multi-Target Dynamic Scaling
* **Target 1 ($T_1$)**: Calculated via multi-candle swing expansion ($+50\%$ to $+100\%$ move). At $T_1$, partial profits ($50\%$) are booked, and Stop-Loss is automatically trailed to Breakeven $+ 2\%$ to lock in profit.
* **Target 2 ($T_2$) & Target 3 ($T_3$)**: Trailed via 13 EMA / Parabolic swing lows for runner lots.
* **Structural Stop-Loss**: Hard exit if price hits the Anchor Low invalidation line.

---

## 6. Options vs. Cash Equities Parity Rules

The system maintains strict architectural parity across asset classes:

| Parameter | Options Engine (`Trade_Option`) | Cash Equities Engine (`Trade_Stock`) |
| :--- | :--- | :--- |
| **Trade Direction** | Long Option Buyer (Buy CE for Bullish, Buy PE for Bearish) | Long (Buy CNC/MIS) or Short Sell (Sell MIS) |
| **Order Routing** | Always `BUY` to open, `SELL` to close | Bull: Buy CNC/MIS $\to$ Sell to exit.<br>Bear: Sell MIS $\to$ Buy to cover. |
| **Strike Selection** | Dynamic Delta/Moneyness (ATM or slight OTM, $\Delta \approx 0.45 - 0.55$) | Exact Equity Symbol (NSE Master) |
| **Theta Decay Protection** | Rollover at 85% of monthly expiry cycle; avoid far OTM | Not applicable |
| **Execution Price Cap** | Limit orders at $\text{Ask} \times 1.005$ to prevent slippage traps | Limit orders at $\text{Ask} \times 1.002$ |

---

## 7. System Architecture & Tech Stack

* **Language & Runtime:** Python 3.10+, SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL`), Flask Web UI.
* **Deployment Model:** Hybrid Local-to-Cloud Pipeline:
  * Local Dev $\to$ AST Syntax Check $\to$ Comprehensive 21-Suite Regression Test $\to$ Git Push $\to$ Cloud VM Pull (`systemd` daemon services).
* **Process Isolation:** Independent background daemons for Index Options (`index_options_trade_engine.py`), Stock Options (`stock_options_trade_engine.py`), and Equities (`stock_reversal_scanner.py`), decoupled from Flask dashboard servers.
* **Fault Tolerance:** Thread-safe singleton locks, state persistence in SQLite WAL databases (`trades.db`), and periodic JSON snapshots for zero-loss recovery upon daemon restart.

---

## 8. Specific Areas for External AI / Quant Review

When reviewing this algorithm, the external validator should specifically evaluate:
1. **Geometric Robustness**: Does the A-B-C-D state transition logic adequately filter false breakouts in choppy, range-bound regimes?
2. **Retest Logic (`POST_D_RETEST`)**: Is the $\pm 2.5\%$ Benchmark tolerance and $+8\%$ runaway standby threshold mathematically optimal for options volatility?
3. **Execution Slippage**: Does the limit-order buffer ($\text{Ask} \times 1.005$) adequately balance execution certainty against option bid-ask spread friction?
4. **Capital Allocation & Sizing**: Does the dynamic $R:R$ threshold ($\ge 1.50$) combined with structural anchor stop-loss prevent fat-tail drawdown during sharp market reversals?
