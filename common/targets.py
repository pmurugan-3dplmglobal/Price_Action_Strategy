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

def find_profit_targets(df_hist, entry_close, stop_loss=None):
    """
    Timeframe & Asset class adaptive profit target finder.
    Handles Intraday Options (1m, 3m, 5m, 15m, 30m, 60m) AND Daily/Weekly/Monthly Stock & Index charts.
    - Daily/Weekly/Monthly TFs: Scans up to 730 days (2 years) to extract major 52-week & multi-month swing highs.
    - Intraday Option TFs: Scans active 30 days window to ignore ancient decaying option contract highs.
    """
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

    if entry_close < 300:  # Option contract premium
        max_target_cap = max(entry_close * 3.5, entry_close + 15 * atr)
        min_target_start = max(entry_close * 1.20, entry_close + 1.5 * risk)
        step_tol = 0.04
    elif is_higher_tf:     # Daily/Weekly/Monthly Stock or Index (allows major 52-week peaks)
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
    # If a 2nd or 3rd non-negated swing level does not exist on the chart, keep T2/T3 as None (N/A).
    if t1 is None:
        t1 = round(entry_close + max(1.5 * risk, entry_close * 0.20), 2)

    if t2 is not None and t2 <= t1 * (1 + step_tol):
        t2 = round(t1 * (1 + step_tol * 2), 2)
    if t3 is not None and t2 is not None and t3 <= t2 * (1 + step_tol):
        t3 = round(t2 * (1 + step_tol * 2), 2)

    return t1, t2, t3

def calculate_position_size(spot_price, stop_loss, capital=100000.0, risk_percent=1.0, lot_size=1, is_option=False):
    """
    Fixed-fractional position sizing:
    - For Cash Equities: units = max_risk_amount / abs(entry - sl)
    - For Options: lots = min(max_risk_amount / risk_per_lot, max_capital_lots)
      where max_capital_lots caps capital deployed in a single option to 25% of account.
    """
    try:
        sp = float(spot_price or 0.0)
        sl = float(stop_loss or 0.0)
        risk_per_unit = abs(sp - sl)
        if risk_per_unit <= 0:
            return 1
        cap = float(capital or 100000.0)
        risk_pct = float(risk_percent or 1.0)
        max_risk_amount = cap * (risk_pct / 100.0)

        if is_option and int(lot_size or 1) > 1:
            lot_sz = int(lot_size)
            risk_per_lot = max(0.50, risk_per_unit) * lot_sz
            max_lots_risk = max(1, int(max_risk_amount / risk_per_lot))
            # Capital ceiling: max 25% of capital deployed into a single option strike
            opt_premium = max(1.0, sp)
            max_lots_capital = max(1, int((cap * 0.25) / (opt_premium * lot_sz)))
            return min(max_lots_risk, max_lots_capital)
        else:
            units = int(max_risk_amount / risk_per_unit)
            # Capital ceiling for Cash Equities: max 100% of capital deployed to a single stock
            # to prevent runaway leverage when stop-loss is very close to entry.
            max_units_capital = max(1, int(cap / max(1.0, sp)))
            return max(1, min(units, max_units_capital))
    except Exception:
        return 1

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
    risk = entry - sl
    if risk <= 0:
        return 0
    targets = [t1]
    if t2 is not None:
        targets.append(t2)
    return sum((t - entry) / risk for t in targets) / len(targets)


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

def find_profit_targets_bearish(df_hist, entry_close, stop_loss=None):
    """
    Timeframe & Asset class adaptive profit target finder for BEARISH / Short setups.
    Scans historical 5-bar swing low support pivots below entry_close.
    Negation Theory Rule for Support Levels:
    A swing low support S is NEGATED if subsequent price closed below S prior to entry.
    Extracts non-negated support levels and sorts them descending (T1 is nearest support below entry).
    """
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

    if entry_close < 300:
        max_target_cap = max(entry_close * 0.3, entry_close - 15 * atr)
        min_target_start = min(entry_close * 0.80, entry_close - 1.5 * risk)
        step_tol = 0.04
    elif is_higher_tf:
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
    # If a 2nd or 3rd non-negated swing level does not exist on the chart, keep T2/T3 as None (N/A).
    if t1 is None:
        t1 = round(entry_close - max(1.5 * risk, entry_close * 0.05), 2)

    if t2 is not None and t2 >= t1 * (1 - step_tol):
        t2 = round(t1 * (1 - step_tol * 2), 2)
    if t3 is not None and t2 is not None and t3 >= t2 * (1 - step_tol):
        t3 = round(t2 * (1 - step_tol * 2), 2)

    return t1, t2, t3


