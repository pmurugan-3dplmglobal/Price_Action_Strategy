# 📐 Datta 10-Anchor & B-C-D Mathematical Reference Matrix

This reference documents the complete mathematical rules, geometry formulas, and classification constraints of the Datta Price Action Trading System.

---

## 1. The 10 Canonical Anchor Archetypes

### 🟢 Bullish Anchors (Long Reversals & Bottom Formations)

1. **`LL_SWEEP` (Two Lower Lows / Liquidity Sweep)**:
   * **Condition**: Two swing lows $L_1$ and $L_2$ where $L_2 < L_1$.
   * **Candle Color**: $L_2$ **MUST BE RED** (Image 22 rule).
   * **Spacing**: $\text{BarIndex}(L_2) - \text{BarIndex}(L_1) \ge 3$ (must have $> 2$ intermediate candles).
   * **Negation**: Any subsequent close below $L_2.\text{low}$ immediately negates the anchor.
   * **Stop-Loss**: $L_2.\text{low} - \text{SL\_BUFFER}$.

2. **`BULLISH_ENGULFING`**:
   * **Condition**: Bullish candle $C_0$ completely encloses previous candle $C_{-1}$ body and wicks.
   * **Stop-Loss**: $\min(C_0.\text{low}, C_{-1}.\text{low}) - \text{SL\_BUFFER}$.

3. **`HAMMER_BABY`**:
   * **Condition**: Bullish candle with lower wick $\ge 2.0 \times \text{body\_size}$ and upper wick $\le 0.3 \times \text{body\_size}$.
   * **Stop-Loss**: $\text{Hammer}.\text{low} - \text{SL\_BUFFER}$.

4. **`BULLISH_HARAMI`**:
   * **Condition**: Bullish candle $C_0$ body completely contained inside prior red candle $C_{-1}$ body.
   * **Stop-Loss**: $C_{-1}.\text{low} - \text{SL\_BUFFER}$.

5. **`TWO_HIGHER_HIGHS`**:
   * **Condition**: Two consecutive higher high candles with bullish closing momentum.
   * **Stop-Loss**: $\min(C_{-1}.\text{low}, C_0.\text{low}) - \text{SL\_BUFFER}$.

---

### 🔴 Bearish Anchors (Short Breakdowns & Topping Formations)

1. **`HH_SWEEP` (Two Higher Highs / Upward Liquidity Sweep)**:
   * **Condition**: Two swing highs $H_1$ and $H_2$ where $H_2 > H_1$.
   * **Candle Color**: $H_2$ **MUST BE GREEN** (Image 23 rule).
   * **Spacing**: $\ge 3$ intermediate candles between $H_1$ and $H_2$.
   * **Negation**: Any subsequent close above $H_2.\text{high}$ immediately negates the setup.
   * **Stop-Loss**: $H_2.\text{high} + \text{SL\_BUFFER}$.

2. **`BEARISH_ENGULFING`**:
   * **Condition**: Bearish candle $C_0$ completely engulfs previous candle $C_{-1}$.
   * **Stop-Loss**: $\max(C_0.\text{high}, C_{-1}.\text{high}) + \text{SL\_BUFFER}$.

3. **`SHOOTING_STAR_BABY`**:
   * **Condition**: Bearish candle with upper wick $\ge 2.0 \times \text{body\_size}$ and lower wick $\le 0.3 \times \text{body\_size}$.
   * **Stop-Loss**: $\text{ShootingStar}.\text{high} + \text{SL\_BUFFER}$.

4. **`BEARISH_HARAMI`**:
   * **Condition**: Small bearish body contained inside prior green mother candle.
   * **Stop-Loss**: $C_{-1}.\text{high} + \text{SL\_BUFFER}$.

5. **`TWO_LOWER_LOWS`**:
   * **Condition**: Two consecutive lower low candles with bearish closing momentum.
   * **Stop-Loss**: $\max(C_{-1}.\text{high}, C_0.\text{high}) + \text{SL\_BUFFER}$.

---

## 2. A-B-C-D Breakout Mechanics & Profit Target Formulation

### Profit Targets (Bullish):
* **$\text{Risk} = \text{Entry} - \text{SL}$**
* **$T_1$ (Initial Benchmark Target)**: First major overhead resistance swing high on the left side of the chart.
* **$T_2$ (Measured Expansion)**: $\text{Entry} + 2.0 \times \text{Risk}$.
* **$T_3$ (Macro Runner)**: $\text{Entry} + 3.0 \times \text{Risk}$ (or next major historical resistance swing).

### Profit Targets (Bearish):
* **$\text{Risk} = \text{SL} - \text{Entry}$**
* **$T_1$**: First major left-side support swing floor.
* **$T_2$**: $\text{Entry} - 2.0 \times \text{Risk}$.
* **$T_3$**: $\text{Entry} - 3.0 \times \text{Risk}$.

### Reward-to-Risk Calculation:
$$\text{R:R} = \frac{|T_1 - \text{Entry}|}{|\text{Entry} - \text{SL}|}$$

---

## 3. Left-Side Rule (Structural Integrity Guard)
For an Anchor to remain structurally active and un-negated:
1. **Bullish Left-Side Rule**: Look back over 100 historical candles prior to Anchor Point A. No candle close may exist below $\text{Anchor}.\text{low}$. If a prior close is lower, the anchor is considered a secondary continuation rather than a primary structural reversal floor.
2. **Bearish Left-Side Rule**: No candle in the prior 100 bars may have closed above $\text{Anchor}.\text{high}$.
