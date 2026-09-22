"""Profit targets, SL buffers, position sizing, and RR calculations.
Contains both bullish and bearish target/SL helper functions.
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
from datetime import datetime as dt

def check_left_side_rule(df, anchor_low, setup_count=0, skip_adjacent=0, lookback_candles=100):
    """Verify no candle in the preceding lookback_candles has a CLOSE below anchor's low (tails/wicks permitted)."""
    if df is None or df.empty:
        return True
    end_idx = len(df) - (setup_count + skip_adjacent) if (setup_count + skip_adjacent) > 0 else len(df)
    start_idx = max(0, end_idx - lookback_candles)
    left = df.iloc[start_idx:end_idx] if end_idx > start_idx else pd.DataFrame()
    if not left.empty and anchor_low > float(left['close'].min()):
        return False
    return True

# Alias for backward compatibility
check_left_side = check_left_side_rule

def is_option_contract(contract_str):
    """
    Determine if a symbol/contract represents an Option contract (e.g. NIFTY24SEP25000CE, INFY24SEP1500PE).
    Cash equities (e.g. PETRONET, PEL, PERSISTENT, HDFCBANK, CENTRALBK) return False.
    """
    if not contract_str:
        return False
    c = str(contract_str).strip().upper()
    if ":" in c:
        c = c.split(":")[-1]
    return (c.endswith("CE") or c.endswith("PE")) and any(ch.isdigit() for ch in c)


def calculate_option_profit_targets(entry_premium, sl_price, dte=None, spot_t1=None):
    """
    DTE-Adaptive Option Profit Target Calculation.
    Decoupled from stale historical option charts. Derived adaptively from initial risk (R) and Days-To-Expiry:
    - 0DTE (dte <= 0): T1 = Entry + 1.5 * Risk
    - Short-Term (1 <= dte <= 5): T1 = Entry + 2.0 * Risk
    - Monthly (dte > 5 or None): T1 = Entry + 2.5 * Risk
    """
    ep = float(entry_premium or 0.0)
    sl = float(sl_price or 0.0)
    risk = round(abs(ep - sl), 2) if (sl > 0 and ep > sl) else max(round(ep * 0.08, 2), 1.0)

    if dte is not None and dte <= 0:
        t1 = round(ep + 1.5 * risk, 2)
        t2 = round(ep + 2.5 * risk, 2)
        t3 = round(ep + 3.5 * risk, 2)
    elif dte is not None and 1 <= dte <= 5:
        t1 = round(ep + 2.0 * risk, 2)
        t2 = round(ep + 3.0 * risk, 2)
        t3 = round(ep + 4.0 * risk, 2)
    else:
        # Monthly (dte > 5 or default when dte not specified)
        t1 = round(ep + 2.5 * risk, 2)
        t2 = round(ep + 3.5 * risk, 2)
        t3 = round(ep + 5.0 * risk, 2)

    return t1, t2, t3


def find_profit_targets(df_hist, entry_close, stop_loss=None, symbol=None, dte=None, is_option=None):
    """
    Timeframe & Asset class adaptive profit target finder.
    Handles Intraday Options (via DTE-adaptive risk multiplier) AND Daily/Weekly/Monthly Stock & Index charts.
    - Options: Decoupled from stale option chart wicks, uses DTE-adaptive risk multiples.
    - Cash Equities: Retains structural 5-bar swing high pivots, with realistic fallback spacing (1.5x Risk).
    """
    is_opt = is_option if is_option is not None else (is_option_contract(symbol) if symbol else False)
    if is_opt:
        return calculate_option_profit_targets(entry_close, stop_loss, dte=dte)

    if df_hist is None or len(df_hist) < 3:
        return None, None, None

    hist = df_hist.copy()

    # 1. Identify datetime column
    time_col = None
    for col in ['datetime', 'date', 'timestamp', 'time', 'date_time']:
        if col in hist.columns:
            time_col = col
            break

    is_higher_tf = False
    if time_col is not None:
        try:
            hist[time_col] = pd.to_datetime(hist[time_col])
            hist = hist.sort_values(time_col).reset_index(drop=True)
            time_diffs = hist[time_col].diff().dropna()
            if not time_diffs.empty:
                median_diff = time_diffs.median()
                # If candle spacing is >= 20 hours, it is a Daily, Weekly, or Monthly chart
                if median_diff >= pd.Timedelta(hours=20):
                    is_higher_tf = True
        except Exception:
            pass

    # 2. Adaptive lookback window based on Timeframe & Asset Type
    if time_col is not None:
        try:
            max_dt = hist[time_col].max()
            if is_higher_tf:
                # Daily / Weekly / Monthly charts: Look back up to 730 days (2 years) to capture major 52-week swing highs
                min_dt = max_dt - pd.Timedelta(days=730)
            else:
                # Intraday (1m, 3m, 5m, 15m, 60m): Look back 30 calendar days (~20 trading sessions)
                min_dt = max_dt - pd.Timedelta(days=30)
            
            sub_hist = hist[hist[time_col] >= min_dt]
            if len(sub_hist) >= 5:
                hist = sub_hist
        except Exception:
            pass

    # 3. Find lowest low in active dataset
    ll_idx = hist['low'].idxmin()

    # 4. Calculate ATR for dynamic capping & fallback target spacing
    high_low_diff = (hist['high'] - hist['low']).abs()
    atr = float(high_low_diff.tail(20).mean()) if len(hist) >= 5 else (entry_close * 0.02)
    if pd.isna(atr) or atr <= 0:
        atr = entry_close * 0.02

    # 5. Dynamic target cap & minimum start relative to entry price & asset type
    risk = (entry_close - stop_loss) if (stop_loss and stop_loss < entry_close) else max(atr * 1.5, entry_close * 0.03)

    if is_higher_tf:     # Daily/Weekly/Monthly Stock or Index (allows major 52-week peaks)
        max_target_cap = max(entry_close * 2.0, entry_close + 20 * atr)
        min_target_start = max(entry_close * 1.03, entry_close + 1.5 * risk)
        step_tol = 0.03
    else:                  # Intraday Spot Stock / Index
        max_target_cap = max(entry_close * 1.25, entry_close + 10 * atr)
        min_target_start = max(entry_close * 1.02, entry_close + 1.5 * risk)
        step_tol = 0.02

    # 6. Extract Non-Negated 5-bar structural swing high resistance pivots above min_target_start
    non_negated_targets = []
    n = len(hist)
    for i in range(n - 2, 1, -1):
        w = hist.iloc[max(0, i-2):min(n, i+3)]
        if len(w) >= 3 and hist.iloc[i]['high'] == w['high'].max():
            h_val = float(hist.iloc[i]['high'])
            if min_target_start <= h_val <= max_target_cap:
                # NEGATION THEORY RULE: Discard if price action after bar i closed above h_val prior to entry (Breached / Negated)
                subsequent_bars = hist.iloc[i+1:]
                if not subsequent_bars.empty:
                    max_subsequent_close = float(subsequent_bars['close'].max())
                    if max_subsequent_close > h_val * 1.005:
                        continue  # Negated target level -> Discarded
                non_negated_targets.append(h_val)

    if not non_negated_targets:
        for i in range(n - 1, 0, -1):
            h_val = float(hist.iloc[i]['high'])
            if min_target_start <= h_val <= max_target_cap:
                subsequent_bars = hist.iloc[i+1:]
                if not subsequent_bars.empty:
                    if float(subsequent_bars['close'].max()) > h_val * 1.005:
                        continue
                non_negated_targets.append(h_val)

    # Sort non-negated target levels ascending by price
    sorted_levels = sorted(list(set(non_negated_targets)))

    # Cluster non-negated levels within step_tol distance
    clustered = []
    for p in sorted_levels:
        if not clustered or (p - clustered[-1]) / clustered[-1] > step_tol:
            clustered.append(round(p, 2))

    t1 = clustered[0] if len(clustered) >= 1 else None
    t2 = clustered[1] if len(clustered) >= 2 else None
    t3 = clustered[2] if len(clustered) >= 3 else None

    # Strict Negation Theory Rule: T1, T2, T3 are strictly based on non-negated chart swing pivots.
    # For cash equities, fallback T1 is entry + 1.5 * risk (not +20%).
    if t1 is None:
        t1 = round(entry_close + 1.5 * risk, 2)

    if t2 is not None and t2 <= t1 * (1 + step_tol):
        t2 = round(t1 * (1 + step_tol * 2), 2)
    if t3 is not None and t2 is not None and t3 <= t2 * (1 + step_tol):
        t3 = round(t2 * (1 + step_tol * 2), 2)

    return t1, t2, t3

def calculate_position_size(spot_price, stop_loss, capital=100000.0, risk_percent=1.0, lot_size=1, is_option=False, tier=1, allow_zero=False, min_lots=1, allow_single_lot_conviction=True, max_single_lot_risk_pct=5.0):
    """
    Fixed-fractional position sizing with Conviction-Weighted Tier Scaling:
    - Sizing scaled by Setup Tier (Conviction Weighting):
        * Tier 1 (Gold): 100% Capital (multiplier 1.0)
        * Tier 2 (Core): 70% Capital (multiplier 0.70)
        * Tier 3 (Momentum): 50% Capital (multiplier 0.50)
    - For Cash Equities: units = max_risk_amount / abs(entry - sl)
    - For Options: lots = min(max_risk_amount / risk_per_lot, max_capital_lots)
      where max_capital_lots caps capital deployed in a single option to 25% of account.
    - High-Conviction 1-Lot Floor (allow_single_lot_conviction=True):
      Under indivisible F&O lot sizes on high-beta leaders (e.g. TITAN, BAJAJ-AUTO),
      1-lot risk may exceed 1% risk budget. For Tier 1 & 2 setups, allows an adaptive
      1-lot floor provided outlay <= 25% capital ceiling and risk per lot <= max_single_lot_risk_pct (default 5%).
    - Zero-lot sizing (allow_zero=True or min_lots=0): returns 0 if max_risk_amount < risk_per_lot
      and high-conviction 1-lot floor is not met.
    """
    try:
        sp = float(spot_price or 0.0)
        sl = float(stop_loss or 0.0)
        risk_per_unit = abs(sp - sl)
        if risk_per_unit <= 0:
            return 0 if (allow_zero or min_lots == 0) else 1
        cap_base = float(capital or 100000.0)
        if cap_base <= 0:
            cap_base = 100000.0
        try:
            tier_val = int(tier or 1)
        except (ValueError, TypeError):
            t_str = str(tier or "").upper()
            if "1" in t_str or "GOLD" in t_str or "T1" in t_str:
                tier_val = 1
            elif "2" in t_str or "CORE" in t_str or "T2" in t_str:
                tier_val = 2
            else:
                tier_val = 3
        tier_multiplier = 1.0 if tier_val == 1 else (0.70 if tier_val == 2 else 0.50)
        cap = cap_base * tier_multiplier
        risk_pct = float(risk_percent or 1.0)
        max_risk_amount = cap * (risk_pct / 100.0)

        if is_option:
            lot_sz = max(1, int(lot_size or 1))
            risk_per_lot = max(0.50, risk_per_unit) * lot_sz
            opt_premium = max(1.0, sp)
            capital_outlay_1lot = opt_premium * lot_sz
            account_cap_25pct = cap_base * 0.25
            max_capital_cap = cap * 0.25

            raw_lots = int(max_risk_amount / risk_per_lot)

            # High-Conviction 1-Lot Floor for indivisible F&O contracts:
            # High-beta market leaders may have 1-lot risk (₹1,500-₹5,000) exceeding 1% risk budget.
            # If allow_single_lot_conviction is True, tier is 1 or 2, capital outlay <= 25% account capital ceiling,
            # and risk per lot <= max_single_lot_risk_pct (default 5% of account capital), floor to 1 lot.
            is_high_conviction = (tier_val in [1, 2])
            max_single_lot_risk = cap_base * (float(max_single_lot_risk_pct) / 100.0)

            if raw_lots == 0 and allow_single_lot_conviction and is_high_conviction:
                if capital_outlay_1lot <= account_cap_25pct and risk_per_lot <= max_single_lot_risk:
                    raw_lots = 1

            if (allow_zero or min_lots == 0) and raw_lots == 0:
                return 0

            base_min_lots = 0 if (allow_zero or min_lots == 0) else max(1, int(min_lots))
            max_lots_risk = max(base_min_lots, raw_lots)
            # Capital ceiling: max 25% of account capital deployed into a single option strike
            effective_cap = account_cap_25pct if (allow_single_lot_conviction and is_high_conviction) else max_capital_cap
            max_lots_capital = max(base_min_lots, int(effective_cap / capital_outlay_1lot))
            return min(max_lots_risk, max_lots_capital)
        else:
            units = int(max_risk_amount / risk_per_unit)
            # Capital ceiling for Cash Equities: max 100% of capital deployed to a single stock
            # to prevent runaway leverage when stop-loss is very close to entry.
            base_min_units = 0 if (allow_zero or min_lots == 0) else 1
            max_units_capital = max(base_min_units, int(cap / max(1.0, sp)))
            return max(base_min_units, min(units, max_units_capital))
    except Exception:
        return 0 if (is_option and (allow_zero or min_lots == 0)) else (0 if is_option else 1)

def calculate_sl_buffer(price_level, side="BULL"):
    """
    Asset-adaptive & price-tiered Stop Loss buffer (Micro-Tick & Spread Shield):
    - For Micro / Penny Options (price < 5): max(0.40, price * 0.15) (at least 8 ticks / 0.40 pts buffer to avoid bid-ask spread whipsaws)
    - For Cheap Options (5 <= price < 15): max(0.60, price * 0.08) (at least 12 ticks / 0.60 pts buffer)
    - For Low-Mid Options (15 <= price < 50): max(0.80, price * 0.04) (0.80 - 2.00 pt buffer)
    - For Mid Options (50 <= price < 200): max(1.50, price * 0.02)
    - For High Options / Stock Spot (200 <= price < 500): max(2.50, price * 0.01)
    - For Index Spot / High Stocks (price >= 500): max(3.50, price * 0.005)
    """
    price = float(price_level)
    if price < 5:
        buffer = max(0.40, price * 0.15)
    elif price < 15:
        buffer = max(0.60, price * 0.08)
    elif price < 50:
        buffer = max(0.80, price * 0.04)
    elif price < 200:
        buffer = max(1.50, price * 0.02)
    elif price < 500:
        buffer = max(2.50, price * 0.01)
    else:
        buffer = max(3.50, price * 0.005)

    if str(side).upper() == "BEAR":
        return round(price + buffer, 2)
    else:
        return round(max(0.05, price - buffer), 2)


def get_sl_buffer_distance(price_level, side="BULL"):
    """
    Asset-adaptive Stop Loss buffer distance (delta offset in points).
    Returns abs(price_level - calculate_sl_buffer(price_level, side)).
    Protects callers against erroneously treating calculate_sl_buffer (which returns
    an absolute price floor/ceiling) as an additive delta offset.
    """
    p = float(price_level)
    return round(abs(p - calculate_sl_buffer(p, side=side)), 2)


def calculate_option_atr_sl(entry_price, geometric_sl, df_candles=None, atr=None, multiplier=2.0, side="BULL", max_risk_pct=0.28):
    """
    ATR-Based Minimum Stop Loss Floor for Option Contracts.
    Prevents premature stop-outs caused by option premium micro-volatility/spread noise.

    Invariants:
    - Applied ONLY to option contracts (never cash equities).
    - Enforces minimum SL risk distance = max(geometric_sl_distance, multiplier * ATR14, 8% entry floor).
    - For Long Options (BUY orders, side='BULL'):
      * SL price = entry_price - effective_risk_distance
      * Capped at max_risk_pct (default 28% of entry price) to avoid catastrophic loss.
      * Floored at 0.05 tick size.
    - Returns rounded to 0.05 tick size.
    """
    ep = float(entry_price or 0.0)
    geo_sl = float(geometric_sl or 0.0)
    if ep <= 0:
        return geo_sl

    # Determine ATR14
    atr_val = 0.0
    if atr is not None and float(atr) > 0:
        atr_val = float(atr)
    elif df_candles is not None and not df_candles.empty and len(df_candles) >= 3:
        try:
            highs = df_candles['high'].astype(float)
            lows = df_candles['low'].astype(float)
            closes = df_candles['close'].astype(float)
            prev_closes = closes.shift(1).fillna(closes.iloc[0])
            tr = pd.concat([highs - lows, (highs - prev_closes).abs(), (lows - prev_closes).abs()], axis=1).max(axis=1)
            atr_val = float(tr.tail(14).mean()) if len(tr) >= 14 else float(tr.mean())
        except Exception:
            atr_val = ep * 0.05
    else:
        atr_val = ep * 0.05

    if pd.isna(atr_val) or atr_val <= 0:
        atr_val = ep * 0.05

    atr_distance = round(atr_val * float(multiplier), 2)
    geo_distance = abs(ep - geo_sl) if geo_sl > 0 else atr_distance

    # Enforce minimum breathing room: at least multiplier * ATR distance
    effective_risk_dist = max(geo_distance, atr_distance)

    # Enforce 8.0% minimum floor distance
    effective_risk_dist = max(effective_risk_dist, ep * 0.08)

    # Cap maximum risk distance at max_risk_pct (default 28% of premium) to protect against excessive drawdown
    max_allowed_dist = round(ep * float(max_risk_pct), 2)
    effective_risk_dist = min(effective_risk_dist, max_allowed_dist)

    # Option buyers are long (CE or PE): SL is below entry premium
    new_sl = round(round((ep - effective_risk_dist) / 0.05) * 0.05, 2)
    new_sl = max(0.05, new_sl)

    if geo_sl > 0 and new_sl < geo_sl:
        logging.debug(f"[ATR_SL_WIDENED] Option SL widened from {geo_sl:.2f} to {new_sl:.2f} (Entry: {ep:.2f}, ATR: {atr_val:.2f}, {multiplier}xATR: {atr_distance:.2f})")

    return new_sl


def check_circuit_and_spread_shield(kite, symbol, exchange="NSE", side="BUY"):
    """
    Circuit Band & Liquidity Safety Shield:
    Checks if stock is locked at Upper or Lower Circuit before triggering order placement.
    Returns True if order is safe to execute, False if locked in circuit.
    """
    if kite is None or not symbol:
        return True
    try:
        q_key = f"{exchange}:{symbol}"
        q = kite.quote([q_key])
        q_data = q.get(q_key, {})
        if not q_data:
            return True
        
        ltp = float(q_data.get("last_price", 0))
        lower_circuit = float(q_data.get("lower_circuit_limit", 0))
        upper_circuit = float(q_data.get("upper_circuit_limit", 0))
        
        if ltp > 0:
            if str(side).upper() == "BUY" and upper_circuit > 0 and ltp >= upper_circuit:
                logging.warning(f"[CIRCUIT SHIELD] Buy blocked for {symbol}: Locked at Upper Circuit ({upper_circuit})")
                return False
            if str(side).upper() in ["SELL", "SHORT", "EXIT"] and lower_circuit > 0 and ltp <= lower_circuit:
                logging.warning(f"[CIRCUIT SHIELD] Sell blocked for {symbol}: Locked at Lower Circuit ({lower_circuit})")
                return False
        return True
    except Exception as e:
        logging.warning(f"Circuit check exception for {symbol}: {e}")
        return True


def calc_rr(entry, sl, t1, t2):
    if entry is None or sl is None or t1 is None:
        return 0
    risk = abs(entry - sl)
    if risk <= 0:
        return 0
    targets = [t1]
    if t2 is not None:
        targets.append(t2)
    return sum(abs(t - entry) / risk for t in targets) / len(targets)


def check_left_side_rule_bearish(df, anchor_high, setup_count=0, skip_adjacent=0, lookback_candles=100):
    """Verify no candle in preceding lookback_candles has a CLOSE above anchor's high (tails/wicks permitted)."""
    if df is None or df.empty:
        return True
    end_idx = len(df) - (setup_count + skip_adjacent) if (setup_count + skip_adjacent) > 0 else len(df)
    start_idx = max(0, end_idx - lookback_candles)
    left = df.iloc[start_idx:end_idx] if end_idx > start_idx else pd.DataFrame()
    if not left.empty and anchor_high < float(left['close'].max()):
        return False
    return True

check_left_side_bearish = check_left_side_rule_bearish

def find_profit_targets_bearish(df_hist, entry_close, stop_loss=None, symbol=None, dte=None, is_option=None):
    """
    Timeframe & Asset class adaptive profit target finder for BEARISH / Short setups.
    Scans historical 5-bar swing low support pivots below entry_close.
    Negation Theory Rule for Support Levels:
    A swing low support S is NEGATED if subsequent price closed below S prior to entry.
    Extracts non-negated support levels and sorts them descending (T1 is nearest support below entry).
    """
    is_opt = is_option if is_option is not None else (is_option_contract(symbol) if symbol else False)
    if is_opt:
        return calculate_option_profit_targets(entry_close, stop_loss, dte=dte)

    if df_hist is None or len(df_hist) < 3:
        return None, None, None

    hist = df_hist.copy()

    time_col = None
    for col in ['datetime', 'date', 'timestamp', 'time', 'date_time']:
        if col in hist.columns:
            time_col = col
            break

    is_higher_tf = False
    if time_col is not None:
        try:
            hist[time_col] = pd.to_datetime(hist[time_col])
            hist = hist.sort_values(time_col).reset_index(drop=True)
            time_diffs = hist[time_col].diff().dropna()
            if not time_diffs.empty:
                median_diff = time_diffs.median()
                if median_diff >= pd.Timedelta(hours=20):
                    is_higher_tf = True
        except Exception:
            pass

    if time_col is not None:
        try:
            max_dt = hist[time_col].max()
            if is_higher_tf:
                min_dt = max_dt - pd.Timedelta(days=730)
            else:
                min_dt = max_dt - pd.Timedelta(days=30)
            sub_hist = hist[hist[time_col] >= min_dt]
            if len(sub_hist) >= 5:
                hist = sub_hist
        except Exception:
            pass

    high_low_diff = (hist['high'] - hist['low']).abs()
    atr = float(high_low_diff.tail(20).mean()) if len(hist) >= 5 else (entry_close * 0.02)
    if pd.isna(atr) or atr <= 0:
        atr = entry_close * 0.02

    risk = (stop_loss - entry_close) if (stop_loss and stop_loss > entry_close) else max(atr * 1.5, entry_close * 0.03)

    if is_higher_tf:
        max_target_cap = max(entry_close * 0.5, entry_close - 20 * atr)
        min_target_start = min(entry_close * 0.97, entry_close - 1.5 * risk)
        step_tol = 0.03
    else:
        max_target_cap = max(entry_close * 0.75, entry_close - 10 * atr)
        min_target_start = min(entry_close * 0.98, entry_close - 1.5 * risk)
        step_tol = 0.02

    non_negated_targets = []
    n = len(hist)
    for i in range(n - 2, 1, -1):
        w = hist.iloc[max(0, i-2):min(n, i+3)]
        if len(w) >= 3 and hist.iloc[i]['low'] == w['low'].min():
            l_val = float(hist.iloc[i]['low'])
            if max_target_cap <= l_val <= min_target_start:
                subsequent_bars = hist.iloc[i+1:]
                if not subsequent_bars.empty:
                    min_subsequent_close = float(subsequent_bars['close'].min())
                    if min_subsequent_close < l_val * 0.995:
                        continue  # Negated support target level -> Discarded
                non_negated_targets.append(l_val)

    if not non_negated_targets:
        for i in range(n - 1, 0, -1):
            l_val = float(hist.iloc[i]['low'])
            if max_target_cap <= l_val <= min_target_start:
                subsequent_bars = hist.iloc[i+1:]
                if not subsequent_bars.empty:
                    if float(subsequent_bars['close'].min()) < l_val * 0.995:
                        continue
                non_negated_targets.append(l_val)

    # Sort non-negated target levels descending by price for short trades (T1 > T2 > T3)
    sorted_levels = sorted(list(set(non_negated_targets)), reverse=True)

    clustered = []
    for p in sorted_levels:
        if not clustered or (clustered[-1] - p) / clustered[-1] > step_tol:
            clustered.append(round(p, 2))

    t1 = clustered[0] if len(clustered) >= 1 else None
    t2 = clustered[1] if len(clustered) >= 2 else None
    t3 = clustered[2] if len(clustered) >= 3 else None

    # Strict Negation Theory Rule: T1, T2, T3 are strictly based on non-negated chart swing pivots.
    # For cash equities, fallback T1 is entry - 1.5 * risk.
    if t1 is None:
        t1 = round(entry_close - 1.5 * risk, 2)

    if t2 is not None and t2 >= t1 * (1 - step_tol):
        t2 = round(t1 * (1 - step_tol * 2), 2)
    if t3 is not None and t2 is not None and t3 >= t2 * (1 - step_tol):
        t3 = round(t2 * (1 - step_tol * 2), 2)

    return t1, t2, t3


def _avg_target_rank(trade):
    """Composite priority score for candidate ranking across options and index engines (ISSUE-071, ISSUE-073).

    Priority hierarchy (strongest -> weakest):
    1. Spot Confluence (mandatory for auto-entry, +2.0 bonus for ranking)
    2. VCP Compression (ATR ratio inversely scaled, squeeze bonus up to +1.5)
    3. Option VWAP discount (below VWAP = institutional accumulation, up to +0.5)
    4. Base R:R (capped at 5.0 to prevent distant-target inflation)
    5. VWAP overpay penalty (demote stretched contracts)
    """
    if not isinstance(trade, dict):
        return 0.0
    targets = [t for t in [trade.get("t1"), trade.get("t2"), trade.get("t3")] if t]
    if not targets:
        return 0.0
    avg_target = sum(targets) / len(targets)
    entry_spot = float(trade.get("entry_spot", 0) or 0)
    current_sl = float(trade.get("current_sl", 0) or 0)
    risk = abs(entry_spot - current_sl)
    if risk <= 0:
        return 0.0
    # Cap base R:R at 5.0 to prevent far-target inflation
    base_rr = min(abs(avg_target - entry_spot) / risk, 5.0)

    # Spot Confluence: dominant ranking factor (+2.0)
    spot_bonus = 2.0 if trade.get("spot_confluence") else 0.0

    # VCP Compression: inversely scaled ATR bonus (coiled spring = explosive breakout)
    vcp_bonus = 0.0
    atr_r = float(trade.get("atr_ratio", 1.0) or 1.0)
    if trade.get("is_squeeze"):
        vcp_bonus = 1.5
    elif atr_r <= 0.50:
        vcp_bonus = 1.2
    elif atr_r <= 0.65:
        vcp_bonus = 0.8
    elif atr_r <= 0.80:
        vcp_bonus = 0.4

    # Safe Option VWAP discount: buying in the sweet spot (-5% to 0%) = institutional accumulation price
    vwap_discount = 0.0
    v_str = float(trade.get("vwap_stretch", 0.0) or 0.0)
    if -5.0 <= v_str < 0.0:
        vwap_discount = 0.5  # sweet spot discount: near VWAP support without breakdown

    # Option Contract VWAP Overpay / Breakdown penalty: demote stretched or broken down contracts
    vwap_penalty = 0.0
    v_st = str(trade.get("vwap_status", "")).upper()
    if v_st == "STRETCHED" or v_str > 15.0:
        vwap_penalty = 1.5  # overstretched FOMO chase
    elif v_st == "EXPANDED" or v_str > 8.0:
        vwap_penalty = 0.4
    elif v_str < -5.0:
        vwap_penalty = 1.5  # falling knife / IV breakdown penalty

    return max(0.0, base_rr + spot_bonus + vcp_bonus + vwap_discount - vwap_penalty)


def _parse_candidate_tier(cand, default=2):
    """
    Safely extract integer tier (1, 2, or 3) from candidate dict regardless of type
    (handles None, int, or string representations like 'TIER_1_GOLD', '🥇 T1', 'TIER_2_CORE', '🥈 T2').
    """
    if not isinstance(cand, dict):
        return default
    raw_tier = cand.get("tier")
    if raw_tier is not None:
        try:
            return int(raw_tier)
        except (ValueError, TypeError):
            pass
    t_str = str(raw_tier or cand.get("tier_badge") or cand.get("tier_label") or "").upper()
    if "1" in t_str or "GOLD" in t_str or "T1" in t_str:
        return 1
    elif "2" in t_str or "CORE" in t_str or "T2" in t_str:
        return 2
    elif "3" in t_str or "MOMENTUM" in t_str or "T3" in t_str:
        return 3
    return default


# Aliases for clean architectural naming
calculate_composite_rank = _avg_target_rank
parse_candidate_tier = _parse_candidate_tier



