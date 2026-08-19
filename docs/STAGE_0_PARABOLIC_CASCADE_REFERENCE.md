# Stage 0 Parabolic Cascade Filter — Technical Reference & Strategy Guide

**Document Version**: 1.0.0  
**Author**: Price Action & Derivatives Engineering  
**System**: Price Action Trading System (Zerodha Kite)  
**Target Audience**: Strategy Developers, Discretionary Traders & Automated Engines  

---

## Executive Summary

The **Stage 0 Parabolic Cascade Filter** is a pre-execution market structure gatekeeper designed to identify **institutional multi-wave exhaustion** before validating **Anchor (A-Formation)** and **A-B-C-D Breakout Cycles**.

While the filter provides exceptional trade quality and asymmetric Risk-to-Reward ($R:R > 8:1$), strict static constraints ($\ge 3$ waves on a single timeframe) can create blind spots in fast-trending, 2-wave consolidation, or V-reversal market environments.

This document outlines the mathematical foundation, candlestick mechanics, empirical trade audits, real-world limitations, and actionable architectural enhancements.

---

## 1. Mathematical & Structural Foundation

### 1.1 The Parabolic Exhaustion Model

In institutional order flow, true trend exhausts do not occur linearly; they form decaying polynomial curves as liquidity dries up:

$$\text{Curve Model: } y = ax^2 + bx + c$$

* **Bullish Bottom Exhaustion (Dome $\cap$)**: 
  - Defined by Highs & Closes ($y = \frac{\text{High} + \text{Close}}{2}$).
  - Requires negative curvature coefficient: $a < 0$.
* **Bearish Top Exhaustion (Cup $\cup$)**: 
  - Defined by Lows & Closes ($y = \frac{\text{Low} + \text{Close}}{2}$).
  - Requires positive curvature coefficient: $a > 0$.
* **Goodness of Fit ($R^2$)**:
  - $R^2 = 1 - \frac{SS_{\text{res}}}{SS_{\text{tot}}} \ge 0.55$ (quantifies how cleanly price action adheres to the parabolic arch).

```
                 STAGE 0 MULTI-WAVE PARABOLIC CASCADE
 
        [Wave 1 Parabolic Arch]       [Wave 2 Arch]       [Wave 3 Arch]
            (R² ≥ 0.55)                (R² ≥ 0.55)         (R² ≥ 0.55)
          ╭──────────────╮           ╭───────────╮       ╭───────────╮
         P0              P1         P1           P2     P2           P3 (Terminal Base)
                                                                      └───> Anchor A Allowed
```

---

### 1.2 Pipeline Execution Hierarchy

```mermaid
graph TD
    A[Raw Candle Stream: 30m / Day] --> B[Extract Swing Pivots: P0, P1, P2, P3]
    B --> C{Pivot Count >= 4?}
    C -- No --> X1[Disqualified: Insufficient Pivots]
    C -- Yes --> D{Wave Count >= 3 & R² >= 0.55?}
    D -- No --> X2[Disqualified: Failed Parabolic Cascade]
    D -- Yes --> E{Terminal Base Recency <= 15 bars?}
    E -- No --> X3[Disqualified: Terminal Swing Stale]
    E -- Yes --> F[Stage 0 PASSED -> Phase 1: Anchor A Detection]
    F --> G[Phase 2: Point B Breakout]
    G --> H[Phase 3: Point C Retest]
    H --> I[Phase 4: Point D Confirmation & R:R >= 1.88]
    I --> J[STAGED FOR LIVE EXECUTION]
```

---

## 2. Real-World Case Study: `BAJAJFINSV26AUG2100PE`

On **August 3, 2026**, the system captured a textbook execution on the 30-minute timeframe:

| Metric | Value | Technical Context |
| :--- | :--- | :--- |
| **Pattern** | `BASE_ABCD` | 4-Stage Base Breakout |
| **Entry Price** | **₹55.15** | Point D 30-minute confirmation close |
| **Stop Loss (SL)** | **₹47.48** | Buffered below Anchor A low ($48.45 - 0.97$) |
| **Target 1 (T1)** | **₹121.65** | Key macro liquidity pool |
| **Risk-to-Reward** | **8.67 : 1** | Mathematical edge $\gg 1.88$ requirement |
| **Outcome** | **₹115.15 Peak (+108.8%)** | Spot dropped from ₹2,082 to ₹2,008 |

```
Premium (₹)
 60 ───                                     [Point B: 56.70]          [Point D Entry: 55.15]
 55 ─── Benchmark Line: ₹54.90 ─────────────────────▲───────────────────────────────▲───────
 50 ───                        [Anchor A: 50.00]    │           [Point C: 50.00]    │
 45 ─── Invalidation SL: ₹47.48 ─── (A.Low: 48.45) ──│──────────────────▲────────────│───────
        ────────────────────────────────────────────┼──────────────────┼────────────┼───────
        Time (30m):                 11:15          12:15              13:15        14:45
```

---

## 3. Diagnostic Audit: Why 51 Nifty Stocks Were Filtered

Across a 51-stock Nifty 50 universe audit on daily and 30-min timeframes, the Stage 0 filter categorized rejections into 3 primary groups:

```
┌────────────────────────────────────────────────────────┬───────────────┐
│ Rejection Category / Gatekeeper                        │ Stock Count   │
├────────────────────────────────────────────────────────┼───────────────┤
│ 1. Failed Parabolic Multi-Swing Cascade (Unmatched)    │ 33 Stocks     │
│ 2. Terminal Swing Stale (>15 bars ago)                 │ 10 Stocks     │
│ 3. Insufficient Swing Pivots (Only 2–3 pivots, need 4) │  8 Stocks     │
├────────────────────────────────────────────────────────┼───────────────┤
│ TOTAL STOCKS FILTERED OUT                              │ 51 / 51       │
└────────────────────────────────────────────────────────┴───────────────┘
```

### The 8 Stocks Filtered by Pivot Scarcity (< 4 Pivots):
1. **`AXISBANK`** (3 pivots) — Lacked a 3rd distinct corrective swing.
2. **`BAJAJ-AUTO`** (2 pivots) — Powerful linear trend ($9,902 \rightarrow 11,607$) without multi-wave pullbacks.
3. **`EICHERMOT`** (3 pivots) — Steady staircase rally ($6,942 \rightarrow 8,018$) with only 2 shallow retracements.
4. **`ICICIBANK`** (2 pivots) — Directional impulse ($1,213 \rightarrow 1,430$) with 1-bar pause candles.
5. **`MAXHEALTH`** (2 pivots) — Single sharp selloff leg ($1,123 \rightarrow 981$) rather than a 3-wave decay.
6. **`SBILIFE`** (3 pivots) — Smooth upward channel ($1,700 \rightarrow 1,856$).
7. **`SUNPHARMA`** (3 pivots) — Tight range compression ($1,870\text{--}1,925$).
8. **`TRENT`** (3 pivots) — V-shape recovery ($2,680 \rightarrow 3,137 \rightarrow 2,836$).

---

## 4. Market Blind Spots & Limitations of Static 3-Wave Rules

While strict filtering protects capital during adverse market conditions, static constraints create four specific blind spots:

1. **Double Bottom / "W" Reversals**:
   - Classic double bottoms complete in **2 waves** ($P_0 \rightarrow P_1 \rightarrow P_2$). Requiring 3 waves rejects valid liquidity sweep bottoms.
2. **High-Momentum Flags & Pullbacks**:
   - Market leaders in strong trends pull back in **1 to 2 shallow waves** to dynamic EMAs. Rejection due to pivot scarcity misses early trend continuation.
3. **Stand-Alone High-Conviction Candlestick Formations**:
   - Formations like **Bullish Engulfing**, **Hammer / Baby Candle**, and **Lower Low Sweeps** possess built-in institutional confirmation on their own candle footprints.
4. **Timeframe Fractality Disconnect**:
   - A stock may display a clean 3-wave cascade on the 15m/30m timeframe, but fails on the Daily chart due to insufficient daily candles.

---

## 5. Strategic Recommendations & Optimization Proposals

### Proposal 1: Dynamic Wave Thresholding by Pattern Type (Recommended)
Scale the wave requirement based on the inherent conviction of the Anchor pattern:

$$\text{Wave Requirement} = 
\begin{cases} 
\mathbf{2\text{ Waves}} & \text{for High-Conviction Anchors (Engulfing, Hammer Baby, LL Sweep)} \\
\mathbf{3\text{ Waves}} & \text{for Base ABCD / Generic Consolidations}
\end{cases}$$

* **Advantage**: Unlocks Double Bottoms and Liquidity Sweeps while maintaining the 3-wave filter for ambiguous base setups.

---

### Proposal 2: Configurable Parameters via `program_config.json`
Engine parameters are centrally maintained in `input/program_config.json`. Setting `swing_min_waves` to `2` immediately unlocks $3\times\text{--}4\times$ more high-probability trade setups:

```json
{
  "nifty50": {
    "enable_swing_filter": true,
    "swing_min_waves": 2,
    "swing_min_r2": 0.50
  },
  "bear_trade": {
    "enable_swing_filter": true,
    "swing_min_waves": 2,
    "swing_min_r2": 0.50
  },
  "daily": {
    "enable_swing_filter": true,
    "swing_min_waves": 2,
    "swing_min_r2": 0.50
  }
}
```

---

### Proposal 3: Multi-Tiered Priority & Position Sizing
Instead of binary rejection (Stage 0 Reject vs Pass), classify trades into 3 execution tiers:

| Tier | Market Structure Criteria | Action / Sizing |
| :--- | :--- | :--- |
| **Tier 1 (Institutional Gold)** | 3 Parabolic Waves + Terminal Base + A-B-C-D ($R:R \ge 2.5$) | **Full Allocation (100% Risk)** |
| **Tier 2 (Core Reversal)** | 2 Parabolic Waves + High-Volume Anchor (Engulf/Sweep) | **Standard Allocation (70% Risk)** |
| **Tier 3 (Momentum / Re-Entry)** | Page 16/17 Trend Continuation / EMA Pullback | **Tactical Allocation (50% Risk)** |

---

## 6. Summary Reference Table

```
┌─────────────────────────┬──────────────────────────┬──────────────────────────┐
│ Feature                 │ Current Setup            │ Recommended Enhancement  │
├─────────────────────────┼──────────────────────────┼──────────────────────────┤
│ Min Waves (swings)      │ 3 Waves (4 Pivots)       │ Dynamic: 2 or 3 Waves    │
│ Curve Fit Metric        │ R² ≥ 0.55                │ R² ≥ 0.50                │
│ Anchor Pattern Synergy  │ Static across all        │ Adaptive by Anchor Type  │
│ Terminal Recency Limit  │ 15 bars                  │ 15 to 20 bars            │
│ Minimum Risk-to-Reward  │ R:R ≥ 1.88               │ R:R ≥ 1.88 (Maintained)  │
└─────────────────────────┴──────────────────────────┴──────────────────────────┘
```

Production Architecture & Mathematical Specification for Porting to Other Systems
  ──────
  ## 1. System Architecture Overview (3-Stage Pipeline)

  Instead of evaluating candlestick patterns in isolation, the engine runs a 3-Stage Hierarchical Pipeline:

     ┌──────────────────────────────────────────────────────────────────────────────────┐
     │ STAGE 0: Macro Multi-Swing Exhaustion & Liquid Volume Filter                    │
     │ • Filters out zero-volume / flatline phantom quotation steps.                   │
     │ • Fits 2nd-degree polynomial curve: y = ax² + bx + c.                          │
     │ • Evaluates wave decay, shortening of thrust (SOT), and terminal absorption base.│
     └──────────────────────────────────────┬───────────────────────────────────────────┘
                                            │ (Passes Soft Tier Metadata: T1 / T2 / T3)
                                            ▼
     ┌──────────────────────────────────────────────────────────────────────────────────┐
     │ STAGE 1: High-Conviction Candlestick Anchor (Point A)                           │
     │ • Bullish: Hammer Baby, Bullish Engulfing, LL Liquidity Sweep, Harami, 2HH.     │
     │ • Bearish: Shooting Star, Bearish Engulfing, HH Liquidity Sweep, Harami, 2LL.   │
     │ • Enforces Left-Side Rule (no breach in preceding lookback window).              │
     └──────────────────────────────────────┬───────────────────────────────────────────┘
                                            │ (Defines Benchmark Price & SL Floor)
                                            ▼
     ┌──────────────────────────────────────────────────────────────────────────────────┐
     │ STAGE 2: Micro Execution Trigger (Points B ➔ C ➔ D Breakout)                     │
     │ • Point B: First candle closing across the Anchor Benchmark.                    │
     │ • Point C: Pullback / Retest candle holding the sequence integrity floor.        │
     │ • Point D: Final Breakout confirmation candle (Close > Benchmark for CE/Bull;   │
     │            Close < Benchmark for PE/Bear) + R:R ≥ 1.88.                          │
     └──────────────────────────────────────────────────────────────────────────────────┘
  ──────
  ## 2. Mathematical Curve Fitting & Parabolic Decay Equations

  ### A. Polynomial Curvature Model

  For any price series segment y (where

        High + Close
    y = ────────────
             2

  for Bullish bottoms, or

        Low + Close
    y = ───────────
             2

  for Bearish tops) across N bars (x = 0,1,2,…,N - 1):

  1. 2nd-Degree Polynomial Regression:

    y(x) = ax² + bx + c

  2. Curvature Direction:
      • Bullish Reversal (Bottom Dome ∩): Requires a < 0 (concave downward, decelerating descent).
      • Bearish Reversal (Top Cup ∪): Requires a > 0 (concave upward, decelerating ascent).
  3. Vertex (Apex) Position:

            b
    xᵥ = - ────
            2a

  • Constraint: Vertex must lie inside the middle structural window:

    0.15 × N ≤ xᵥ ≤ 0.85 × N

  4. Goodness of Fit (R² Score):

             ∑(yᵢ - ŷᵢ)²
    R² = 1 - ─────────── ≥ 0.50
                      2
              ⎛     ‾⎞
             ∑⎝yᵢ - y⎠
  ──────
  ## 3. Multi-Tier Soft Scoring Engine (Proposal C)

  Do not use binary hard rejections (e.g. if waves < 3: return None), which kill valid high-probability 2-wave double bottoms and V-shaped liquidity sweeps.

    ┌──────────────┬───────────────────────────────┬──────────────────────────────┬──────────────┐
    │ Tier Class   │ Market Structure Qualification│ Pattern & Risk Profile       │ Position Size│
    ├──────────────┼───────────────────────────────┼──────────────────────────────┼──────────────┤
    │ 🥇 TIER 1    │ ≥ 3 Parabolic Waves (R²≥0.55) │ Extreme Wyckoff Exhaustion   │ 100% Capital │
    │   (GOLD)     │ + Terminal Base Absorption    │ + A-B-C-D Trigger (R:R ≥ 2.5)│ (Max Risk)   │
    ├──────────────┼───────────────────────────────┼──────────────────────────────┼──────────────┤
    │ 🥈 TIER 2    │ ≥ 2 Waves (Double Bottoms)    │ High-Conviction Sweeps       │ 70% Capital  │
    │   (CORE)     │ OR 1-Wave Liquidity Flush     │ (LL_ABCD / Engulfing, R:R≥1.88)│ (Standard)   │
    ├──────────────┼───────────────────────────────┼──────────────────────────────┼──────────────┤
    │ 🥉 TIER 3    │ Single Wave Momentum Retest   │ Trend Continuation / Flag    │ 50% Capital  │
    │  (MOMENTUM)  │ (Page 16/17 Re-entry)         │ Retest Breakout (R:R ≥ 1.88) │ (Scalp/Light)│
    └──────────────┴───────────────────────────────┴──────────────────────────────┴──────────────┘
  ──────
  ## 4. Liquid Volume & Phantom Step Filtering (Options Protection)

  Far-month / deep ITM option contracts frequently print flat horizontal "phantom steps" with zero volume that fool naive algorithms into counting fake swings.

  ### Algorithm to Clean Option Data:

    def clean_liquid_candles(df):
        """Strips zero-volume quotation flatlines before swing analysis."""
        if 'volume' in df.columns:
            # Keep only bars with actual traded volume OR real price spread
            is_liquid = (df['volume'] > 0) | (df['high'] != df['low'])
            if is_liquid.any():
                first_valid_idx = is_liquid.idxmax()
                return df.iloc[first_valid_idx:].reset_index(drop=True)
        return df
  ──────
  ## 5. Derivative Symmetry: The "One-Sided Buyer" Principle

  When buying options, both Call (CE) and Put (PE) trades are bottom-exhaustion breakouts on their respective contract charts:

    ─────────────────────────────────────────────────────────────────────────────────────────────
                                 2-SIDED REVERSAL EXECUTION MATRIX
    ─────────────────────────────────────────────────────────────────────────────────────────────
     MARKET REGIME       UNDERLYING SPOT PRICE ACTION         DERIVATIVE OPTION CONTRACT ACTION
    ───────────────────  ───────────────────────────────────  ───────────────────────────────────
     CASE 1: DOWNTREND   Macro Downtrend (3–4 Swings Down)    BUY CALL OPTION (CE)
     EXHAUSTION          ➔ Absorbs at Base Floor              ➔ CE Premium at 3–4 Wave Bottom
                         ➔ Bullish Anchor A ➔ BCD Breakout    ➔ CE Premium Breaks Out Upward
    ───────────────────  ───────────────────────────────────  ───────────────────────────────────
     CASE 2: UPTREND     Macro Uptrend (3–4 Swings Up)        BUY PUT OPTION (PE)
     EXHAUSTION          ➔ Rejects at Inverted Top Arch       ➔ PE Premium at 3–4 Wave Bottom
                         ➔ Bearish Anchor A ➔ BCD Breakdown   ➔ PE Premium Breaks Out Upward
    ─────────────────────────────────────────────────────────────────────────────────────────────
  ──────
  ## 6. Strike Resolution & Dynamic Range (strike_range: 1)
  • Problem: Scanning only strike_range = 0 (strict ATM) misses setups that form on adjacent strikes (e.g. 50-pt OTM strikes like NIFTY 24100 CE when Spot is at 24,058).
  • Rule: Always configure the resolution engine to scan:

    Strikes Scanned = { ATM - (Range × Step),…,ATM,…,ATM + (Range × Step)}

  • Index: Range ≥1 (ATM ±1 strike = 3 strikes total).
  • F&O Equities: Range ≥1 (ATM ±1 strike).
  ──────
  ## 7. Universal Algorithmic Flowchart (Python / Pseudocode)

    def scan_trade_setup(df_entry, df_anchor, side="BULL", strike_range=1):
        # Step 1: Filter illiquid quotation dead bars
        df_clean = clean_liquid_candles(df_anchor)

        # Step 2: Compute Parabolic Multi-Swings & Tier Classification (Stage 0)
        swing_info = detect_parabolic_multi_swings(df_clean, side=side)
        tier_meta = {
            "tier": swing_info.get("tier", 2),
            "tier_label": swing_info.get("tier_label", "TIER_2_CORE"),
            "tier_badge": swing_info.get("tier_badge", "🥈 T2")
        }

        # Step 3: Scan for Candlestick Anchors (Stage 1)
        anchors = find_anchor_candidates(df_entry, side=side)
        if not anchors:
            return None

        # Step 4: Validate Sequence & B -> C -> D Breakout (Stage 2)
        for anchor in reversed(anchors):
            # Enforce sequence: Anchor must form at/after confirmed terminal base
            if swing_info.get("has_terminal_base") and anchor.time < swing_info.get("terminal_date"):
                continue

            bcd_trade = find_bcd_trigger(df_entry, anchor, side=side)
            if bcd_trade and bcd_trade.rr >= 1.88:
                bcd_trade.update(tier_meta)
                return bcd_trade  # Staged for Execution

        return None