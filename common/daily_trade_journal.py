import os
import json
import csv
import logging
from datetime import datetime

import paths

BASE_DIR = paths.PROJECT_ROOT
WIN_JOURNAL_DIR = r"G:\Poovendan\AI\Trading\Share\Account_Status_leaning"
if os.path.exists(r"G:\Poovendan\AI\Trading\Share"):
    JOURNAL_DIR = WIN_JOURNAL_DIR
else:
    JOURNAL_DIR = os.path.join(BASE_DIR, "output", "journal")
os.makedirs(JOURNAL_DIR, exist_ok=True)
JOURNAL_CSV_PATH = os.path.join(JOURNAL_DIR, "daily_trade_journal.csv")
JOURNAL_JSON_PATH = os.path.join(JOURNAL_DIR, "daily_trade_journal.json")

CSV_HEADER = [
    "Date",
    "Engine",
    "Symbol",
    "Side",
    "Timeframe",
    "Pattern",
    "Tier",
    "Swing_Waves",
    "Entry_Time",
    "Entry_Price",
    "Exit_Time",
    "Exit_Price",
    "SL",
    "T1",
    "T2",
    "T3",
    "Quantity",
    "Lot_Size",
    "PnL_Rs",
    "PnL_Pct",
    "Outcome",
    "MFE_Pct",
    "MAE_Pct",
    "Attribution_Code",
    "Spot_VWAP_Dist_Pct",
    "Spot_RVOL",
    "Spot_EMA_Trend",
    "Spot_ATR_Ratio",
    "Opt_VCP_Ratio",
    "Analysis_Remarks",
    "Self_Learning_Lesson"
]

def init_journal_files():
    """Ensure Account_Status_leaning directory and CSV/JSON header exist."""
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    if not os.path.exists(JOURNAL_CSV_PATH):
        with open(JOURNAL_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)
    if not os.path.exists(JOURNAL_JSON_PATH):
        with open(JOURNAL_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

def load_journal_entries():
    """Load existing journal entries from JSON."""
    init_journal_files()
    try:
        with open(JOURNAL_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def clear_journal(create_backup=True):
    """
    Clear the daily trade journal JSON and CSV files.
    If create_backup is True, creates a timestamped backup before clearing.
    Returns (success: bool, backup_file: str or None, message: str).
    """
    init_journal_files()
    backup_file = None
    if create_backup:
        try:
            import shutil
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if os.path.exists(JOURNAL_JSON_PATH) and os.path.getsize(JOURNAL_JSON_PATH) > 10:
                backup_json = os.path.join(JOURNAL_DIR, f"daily_trade_journal_backup_{ts}.json")
                shutil.copy2(JOURNAL_JSON_PATH, backup_json)
                backup_file = backup_json
            if os.path.exists(JOURNAL_CSV_PATH) and os.path.getsize(JOURNAL_CSV_PATH) > 100:
                backup_csv = os.path.join(JOURNAL_DIR, f"daily_trade_journal_backup_{ts}.csv")
                shutil.copy2(JOURNAL_CSV_PATH, backup_csv)
                if not backup_file:
                    backup_file = backup_csv
        except Exception as e:
            logging.warning(f"Failed to create journal backup before clear: {e}")

    # Reset JSON to empty list
    with open(JOURNAL_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    # Reset CSV to header only
    with open(JOURNAL_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

    msg = "Journal cleared successfully." + (f" Backup saved to {os.path.basename(backup_file)}." if backup_file else "")
    return True, backup_file, msg

def classify_trade_attribution(trade_data, pnl_rs=0.0, outcome=""):
    """
    Classify trade outcome into a structured, machine-readable Attribution Code (FEATURE-041).
    Used for quantitative post-trade analysis, win/loss clustering, and strategy improvement.
    """
    try:
        pnl = float(pnl_rs or trade_data.get("PnL_Rs") or trade_data.get("pnl") or trade_data.get("pnl_rs") or 0.0)
    except (ValueError, TypeError):
        pnl = 0.0

    out = str(outcome or trade_data.get("Outcome") or trade_data.get("status") or "").upper()
    dna = trade_data.get("trade_dna") if isinstance(trade_data.get("trade_dna"), dict) else {}
    pattern = str(trade_data.get("Pattern") or trade_data.get("pattern") or "").upper()
    tier = str(trade_data.get("Tier") or trade_data.get("tier") or "").upper()
    side = str(trade_data.get("Side") or trade_data.get("side") or "").upper()
    exit_reason = str(trade_data.get("exit_reason") or trade_data.get("details") or "").upper()

    try:
        spot_atr = float(dna.get("spot_atr_ratio") or trade_data.get("Spot_ATR_Ratio") or 1.0)
    except (ValueError, TypeError):
        spot_atr = 1.0
    try:
        opt_vcp = float(dna.get("opt_vcp_ratio") or trade_data.get("Opt_VCP_Ratio") or 1.0)
    except (ValueError, TypeError):
        opt_vcp = 1.0
    spot_trend = str(dna.get("spot_ema_trend") or trade_data.get("Spot_EMA_Trend") or "").upper()
    try:
        opt_spread = float(dna.get("opt_spread_pct") or 0.0)
    except (ValueError, TypeError):
        opt_spread = 0.0

    is_active = "ACTIVE" in out or "CARRY" in out or trade_data.get("Exit_Time") in ("OPEN", "")

    if is_active:
        return "ACTIVE_IN_PROGRESS"

    if pnl > 0 or "TARGET" in out or "T1" in out or "T2" in out or "T3" in out or "PROFIT" in out:
        if spot_atr <= 0.85 and opt_vcp <= 0.85:
            return "WIN_DUAL_VCP_RUNNER"
        if "T1" in tier or "GOLD" in tier:
            return "WIN_D1_REVERSAL"
        if "D2" in pattern or "CONTINUATION" in pattern or "PYRAMID" in pattern:
            return "WIN_D2_PYRAMID"
        return "WIN_MOMENTUM_RUNNER"

    if pnl < 0 or "SL" in out or "STOP" in out or "LOSS" in out:
        # Check counter-trend trap
        if spot_trend == "BULL" and (side in ["PE", "SELL", "BEAR"]):
            return "LOSS_COUNTER_SPOT_TRAP"
        if spot_trend == "BEAR" and (side in ["CE", "BUY", "BULL"]):
            return "LOSS_COUNTER_SPOT_TRAP"
        if opt_spread >= 2.0:
            return "LOSS_SLIPPAGE_SPREAD"
        if "EMERGENCY" in exit_reason or "CAP" in exit_reason:
            return "LOSS_EMERGENCY_CAP"
        if "THETA" in exit_reason or "STAGNATION" in exit_reason:
            return "LOSS_THETA_DECAY"
        return "LOSS_DISCIPLINED_SL"

    return "EXIT_NEUTRAL"

def save_journal_entries(entries):
    """Save full list of journal entries to JSON and CSV."""
    init_journal_files()
    with open(JOURNAL_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

    with open(JOURNAL_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for e in entries:
            writer.writerow([
                e.get("Date", ""),
                e.get("Engine", ""),
                e.get("Symbol", ""),
                e.get("Side", ""),
                e.get("Timeframe", ""),
                e.get("Pattern", ""),
                e.get("Tier", ""),
                e.get("Swing_Waves", ""),
                e.get("Entry_Time", ""),
                e.get("Entry_Price", ""),
                e.get("Exit_Time", ""),
                e.get("Exit_Price", ""),
                e.get("SL", ""),
                e.get("T1", ""),
                e.get("T2", ""),
                e.get("T3", ""),
                e.get("Quantity", ""),
                e.get("Lot_Size", ""),
                e.get("PnL_Rs", ""),
                e.get("PnL_Pct", ""),
                e.get("Outcome", ""),
                e.get("MFE_Pct", ""),
                e.get("MAE_Pct", ""),
                e.get("Attribution_Code", ""),
                e.get("Spot_VWAP_Dist_Pct", ""),
                e.get("Spot_RVOL", ""),
                e.get("Spot_EMA_Trend", ""),
                e.get("Spot_ATR_Ratio", ""),
                e.get("Opt_VCP_Ratio", ""),
                e.get("Analysis_Remarks", ""),
                e.get("Self_Learning_Lesson", "")
            ])

def resolve_trade_tier_and_swings(symbol, contract="", pattern=""):
    """Resolve Stage 0 Tier Classification (🥇 T1 Gold, 🥈 T2 Core, 🥉 T3 Momentum) and Swing Wave Count."""
    clean_sym = str(symbol or contract).replace(" ", "").upper()
    tier_badge = "🥈 T2 Core"
    swing_waves = "2 Waves"

    # 1. Search scan_display files
    for path in [paths.SCAN_DISPLAY_FILE, paths.SCAN_DISPLAY_INDEX_FILE, paths.SCAN_DISPLAY_STOCK_FILE]:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for sec in ("staged_trades", "active_live", "carry_forward"):
                    for item in data.get(sec, []):
                        if isinstance(item, dict):
                            i_sym = str(item.get("symbol") or "").replace(" ", "").upper()
                            i_cnt = str(item.get("contract") or "").replace(" ", "").upper()
                            if clean_sym in (i_sym, i_cnt) or i_sym in clean_sym or i_cnt in clean_sym:
                                tb = item.get("tier_badge") or item.get("tier_label")
                                sw = item.get("swing_waves")
                                if tb:
                                    if "T1" in str(tb) or "GOLD" in str(tb):
                                        tier_badge = "🥇 T1 Gold"
                                    elif "T3" in str(tb) or "MOMENTUM" in str(tb):
                                        tier_badge = "🥉 T3 Momentum"
                                    else:
                                        tier_badge = "🥈 T2 Core"
                                if sw is not None:
                                    try:
                                        sw_int = int(sw)
                                        swing_waves = f"{sw_int} Waves" if sw_int < 3 else "3+ Waves (Multi-Swing)"
                                    except Exception:
                                        swing_waves = str(sw)
                                return tier_badge, swing_waves
            except Exception:
                pass

    # 2. Search trade_db
    try:
        from common.trade_db import get_all_trades
        for t in get_all_trades():
            t_sym = str(t.get("symbol") or t.get("contract") or "").replace(" ", "").upper()
            if clean_sym in t_sym or t_sym in clean_sym:
                tb = t.get("tier_badge") or t.get("tier_label") or t.get("tier")
                sw = t.get("swing_waves")
                if tb:
                    if str(tb) in ("1", "🥇 T1", "TIER_1_GOLD") or "T1" in str(tb):
                        tier_badge = "🥇 T1 Gold"
                    elif str(tb) in ("3", "🥉 T3", "TIER_3_MOMENTUM") or "T3" in str(tb):
                        tier_badge = "🥉 T3 Momentum"
                    else:
                        tier_badge = "🥈 T2 Core"
                if sw is not None:
                    try:
                        sw_int = int(sw)
                        swing_waves = f"{sw_int} Waves" if sw_int < 3 else "3+ Waves (Multi-Swing)"
                    except Exception:
                        swing_waves = str(sw)
                return tier_badge, swing_waves
    except Exception:
        pass

    # 3. Default fallback based on pattern name
    pat_str = str(pattern).upper()
    if "BASE_ABCD" in pat_str or "MANUAL" in pat_str or "DISCRETIONARY" in pat_str or "1CLICK" in pat_str:
        tier_badge = "🥉 T3 Momentum"
        swing_waves = "1 Wave / Direct"
    elif any(p in pat_str for p in ["LL_ABCD", "BE_ABCD", "HH_ABCD", "STAR_ABCD", "HAMMER_ABCD"]):
        tier_badge = "🥈 T2 Core"
        swing_waves = "2 Waves"

    return tier_badge, swing_waves


def resolve_trade_pattern(symbol, contract="", default_pat=None, is_manual=False):
    """Resolve the exact strategy pattern name for pattern analysis, even for manual entries based on scans."""
    if default_pat and default_pat not in ("N/A", "ZERODHA_ORDER", "KITE_EXECUTED", "KITE_ORDER_SYNC", "MANUAL_ENTRY"):
        return f"{default_pat} (Manual Entry)" if is_manual else default_pat

    clean_sym = str(symbol or contract).replace(" ", "").upper()

    # 1. Search scan_display JSON files (Option, Index, Bull Stock, Bear Stock)
    for path in [paths.SCAN_DISPLAY_FILE, paths.SCAN_DISPLAY_INDEX_FILE, paths.SCAN_DISPLAY_STOCK_FILE, paths.SCAN_DISPLAY_BEAR_FILE]:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for sec in ("staged_trades", "active_live", "carry_forward"):
                    for item in data.get(sec, []):
                        if isinstance(item, dict):
                            i_sym = str(item.get("symbol") or "").replace(" ", "").upper()
                            i_cnt = str(item.get("contract") or "").replace(" ", "").upper()
                            if clean_sym in (i_sym, i_cnt) or i_sym in clean_sym or i_cnt in clean_sym:
                                if item.get("pattern"):
                                    pat = item["pattern"]
                                    return f"{pat} (Manual Entry)" if is_manual else pat
            except Exception:
                pass

    # 2. Search trade_journal.csv (historical scan beats)
    j_path = paths.TRADE_JOURNAL_CSV
    if os.path.exists(j_path):
        try:
            with open(j_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="\t")
                for row in reversed(list(reader)):
                    if len(row) >= 3:
                        r_sym = str(row[1]).replace(" ", "").upper()
                        r_pat = row[2].strip()
                        if (clean_sym in r_sym or r_sym in clean_sym) and r_pat and r_pat not in ("N/A", "MANUAL_ENTRY", "SCAN_LINKED"):
                            return f"{r_pat} (Manual Entry)" if is_manual else r_pat
        except Exception:
            pass

    # 3. Search trades_db.json
    try:
        from common.trade_db import get_all_trades
        for t in get_all_trades():
            t_sym = str(t.get("symbol") or "").replace(" ", "").upper()
            t_cnt = str(t.get("contract") or "").replace(" ", "").upper()
            if clean_sym in (t_sym, t_cnt) or t_sym in clean_sym or t_cnt in clean_sym:
                pat = t.get("pattern")
                if pat and pat not in ("N/A", "ZERODHA_ORDER", "KITE_EXECUTED", "MANUAL_ENTRY"):
                    return f"{pat} (Manual Entry)" if is_manual else pat
    except Exception:
        pass

    return "MANUAL_ENTRY (Discretionary)" if is_manual else (default_pat or "MANUAL_ENTRY (Discretionary)")

def derive_trade_remarks_and_lesson(symbol, outcome, pnl_rs, pattern, trade_data=None):
    """Derive intelligent, data-driven analysis remarks and actionable self-learning lessons
    evaluating MFE, MAE, execution timing, structural spot validity, and microstructure DNA.
    Supports backward compatibility with signature (symbol, outcome, pnl_rs, pattern).
    """
    td = trade_data if isinstance(trade_data, dict) else {}
    dna = td.get("trade_dna") if isinstance(td.get("trade_dna"), dict) else {}

    # Extract metrics
    try:
        mfe_val = float(td.get("MFE_Pct") or td.get("mfe_pct") or 0.0)
    except (ValueError, TypeError):
        mfe_val = 0.0
    try:
        mae_val = float(td.get("MAE_Pct") or td.get("mae_pct") or 0.0)
    except (ValueError, TypeError):
        mae_val = 0.0
    try:
        pnl_val = float(pnl_rs if pnl_rs is not None else td.get("PnL_Rs") or td.get("pnl") or 0.0)
    except (ValueError, TypeError):
        pnl_val = 0.0

    entry_t = str(td.get("Entry_Time") or td.get("entry_time") or td.get("created_at") or "")
    exit_t = str(td.get("Exit_Time") or td.get("exit_time") or "")
    exit_reason = str(td.get("exit_reason") or td.get("details") or "").upper()
    tier = str(td.get("Tier") or td.get("tier") or "")
    spot_breached = td.get("spot_breached_on_close")

    # Parse time-of-day window
    time_window = "Normal"
    if entry_t and len(entry_t) >= 16:
        try:
            t_part = entry_t.split(" ")[-1][:5]
            hh, mm = map(int, t_part.split(":"))
            t_mins = hh * 60 + mm
            if 9 * 60 + 15 <= t_mins < 10 * 60:
                time_window = "Opening Velocity (09:15-10:00)"
            elif 10 * 60 <= t_mins < 11 * 60 + 30:
                time_window = "Morning Trend (10:00-11:30)"
            elif 11 * 60 + 30 <= t_mins < 13 * 60 + 30:
                time_window = "Midday Chop (11:30-13:30)"
            elif 13 * 60 + 30 <= t_mins <= 15 * 60 + 30:
                time_window = "Closing Momentum (13:30-15:30)"
        except Exception:
            pass

    # Volume & VCP indicators
    rvol_val = None
    rvol_raw = dna.get("spot_rvol") or td.get("Spot_RVOL")
    if rvol_raw not in (None, "", "UNKNOWN"):
        try:
            rvol_val = float(rvol_raw)
        except (ValueError, TypeError):
            rvol_val = None

    atr_ratio_val = None
    atr_raw = dna.get("spot_atr_ratio") or td.get("Spot_ATR_Ratio")
    if atr_raw not in (None, "", "UNKNOWN"):
        try:
            atr_ratio_val = float(atr_raw)
        except (ValueError, TypeError):
            atr_ratio_val = None

    is_winner = pnl_val > 0 or any(w in str(outcome).upper() for w in ["T1", "T2", "T3", "TARGET", "PROFIT"])
    is_loser = pnl_val < 0 or any(l in str(outcome).upper() for l in ["SL", "STOP", "LOSS"])
    is_active = ("ACTIVE" in str(outcome).upper() or outcome == "Carry Forward" or exit_t == "OPEN") and not (is_winner or is_loser)

    if is_active:
        remarks = f"{symbol} active position in progress on pattern [{pattern}] ({tier or 'Core'}). Monitored by Position Guardian."
        lesson = "Maintain trailing stop parameters and verify 15m/30m candle close boundaries against Anchor corridor."
        return remarks, lesson

    if is_winner:
        if mfe_val >= 25.0:
            remarks = f"Explosive momentum winner (+₹{pnl_val:.2f}) on [{pattern}]. Peak MFE reached +{mfe_val:.1f}% with disciplined drawdown (MAE {mae_val:.1f}%)."
            lesson = "Setup thesis validated: Multi-timeframe trend alignment and coiled VCP generated strong continuation velocity."
        elif mfe_val >= 15.0 and pnl_val > 0 and (td.get("PnL_Pct") and float(str(td.get("PnL_Pct")).replace("%","").replace("+","") or 0) < mfe_val * 0.5):
            pnl_pct_f = float(str(td.get("PnL_Pct")).replace("%","").replace("+","") or 0)
            left_on_table = mfe_val - pnl_pct_f
            remarks = f"Target captured (+₹{pnl_val:.2f}) on [{pattern}], peaking at +{mfe_val:.1f}% MFE before trailing exit (left ~{left_on_table:.1f}% on table)."
            lesson = "Profit-locking evolution: Consider partial profit booking (50% lots) at T1 / +20% spike to lock in peak excursion while trailing balance."
        elif abs(mae_val) <= 3.0 and mae_val <= 0:
            remarks = f"Flawless clean breakout (+₹{pnl_val:.2f}) on [{pattern}] with near-zero adverse excursion (MAE {mae_val:.1f}%)."
            lesson = "Optimal entry timing: Immediate volume expansion confirmed breakout without testing entry support."
        else:
            remarks = f"Target reached for {symbol} (+₹{pnl_val:.2f}) on pattern [{pattern}]. Profit realized."
            lesson = "Good execution. Trailed SL to breakeven after T1 hit to lock in gains and protect capital."
        return remarks, lesson

    if is_loser:
        if spot_breached is False or "SHAKEOUT" in exit_reason or "PREMATURE" in exit_reason:
            remarks = f"Premature option SL shakeout (-₹{abs(pnl_val):.2f}) on [{pattern}]. Spot held structural support inside Anchor corridor; option exited on premium IV/tick noise."
            lesson = "Execution Evolution: Enforce Spot 15m candle-close confirmation before triggering option SL on incubated setups to prevent premature theta/IV shakeouts."
        elif spot_breached is True or "STRUCTURAL" in exit_reason or "CANDLE_CLOSE_SL" in exit_reason:
            remarks = f"Structural invalidation SL (-₹{abs(pnl_val):.2f}). Spot closed beyond pattern Anchor boundary on [{pattern}]. Disciplined capital protection."
            lesson = "Capital shield verified: Prompt exit on structural invalidation preserved 80%+ capital against severe directional continuation."
        elif mfe_val >= 12.0:
            remarks = f"Round-trip loss (-₹{abs(pnl_val):.2f}) after surging to +{mfe_val:.1f}% peak MFE. Setup gave substantial initial expansion but reversed."
            lesson = "Trailing ratchet mandate: Setups achieving >= +12% MFE must have SL automatically ratcheted to Breakeven floor."
        elif time_window == "Midday Chop (11:30-13:30)":
            remarks = f"Midday consolidation trap (-₹{abs(pnl_val):.2f}) on [{pattern}]. Entered during low-liquidity midday chop ({entry_t[-8:] if entry_t else '11:30-13:30'})."
            lesson = "Midday Regime Gate: Require RVOL >= 1.8x and Spot EMA alignment for any discretionary or automated entry between 11:30 and 13:30 IST."
        elif rvol_val is not None and rvol_val < 1.0:
            remarks = f"Low volume breakout trap (-₹{abs(pnl_val):.2f}) on [{pattern}]. Entry RVOL ({rvol_val:.2f}x) lacked institutional volume sponsorship."
            lesson = "Volume Gate Evolution: Enforce breakout candle RVOL >= 1.2x to eliminate low-volume false breakouts."
        elif atr_ratio_val is not None and atr_ratio_val > 1.2:
            remarks = f"Volatility expansion failure (-₹{abs(pnl_val):.2f}) on [{pattern}]. Setup entered in uncompressed volatility regime (ATR ratio {atr_ratio_val:.2f} > 0.85)."
            lesson = "VCP Squeeze Evolution: Prioritize coiled setups with ATR3/ATR14 <= 0.85 to avoid buying at the end of volatility expansions."
        else:
            remarks = f"Stop Loss triggered for {symbol} (-₹{abs(pnl_val):.2f}) on pattern [{pattern}]."
            lesson = "Respect pattern SL strictly. Ensure TF closing candle check or emergency stop buffer is respected."
        return remarks, lesson

    return f"Trade executed for {symbol} on pattern [{pattern}].", "Review chart pattern and entry timing for future setups."

def generate_daily_journal(target_date=None, kite=None):
    """
    Generate or update the daily self-learning trade journal for a specific date (default today).
    Syncs trade_db, scan display files, and Zerodha Kite orders/positions.
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    init_journal_files()
    existing_entries = load_journal_entries()
    
    # Preserve past dates completely, and preserve custom user notes for target_date
    filtered = [e for e in existing_entries if e.get("Date") != target_date]
    existing_user_notes = {}
    for e in existing_entries:
        if e.get("Date") == target_date:
            sym = e.get("Symbol")
            if sym:
                existing_user_notes[sym] = {
                    "remarks": e.get("Analysis_Remarks"),
                    "lesson": e.get("Self_Learning_Lesson")
                }
    today_records = []
    processed_symbols = set()

    # 1. Parse Zerodha Kite completed orders if session provided
    if kite:
        try:
            orders = kite.orders()
            positions = kite.positions().get("net", [])
            
            # Group orders by tradingsymbol
            symbol_orders = {}
            for o in orders:
                if o.get("status") == "COMPLETE":
                    o_date = str(o.get("order_timestamp", ""))[:10]
                    if o_date == target_date:
                        sym = o.get("tradingsymbol", "")
                        symbol_orders.setdefault(sym, []).append(o)
                        
            # Reconstruct trades from Zerodha order history
            for sym, o_list in symbol_orders.items():
                buys = [o for o in o_list if o.get("transaction_type") == "BUY"]
                sells = [o for o in o_list if o.get("transaction_type") == "SELL"]
                
                net_pos = next((p for p in positions if p.get("tradingsymbol") == sym), {})
                net_qty = int(net_pos.get("quantity", 0)) if net_pos else 0
                net_pnl = float(net_pos.get("pnl", 0)) if net_pos else 0.0
                
                buy_qty = sum(int(o.get("quantity", 0)) for o in buys)
                buy_avg = sum(float(o.get("average_price", 0)) * int(o.get("quantity", 0)) for o in buys) / buy_qty if buy_qty > 0 else 0
                
                sell_qty = sum(int(o.get("quantity", 0)) for o in sells)
                sell_avg = sum(float(o.get("average_price", 0)) * int(o.get("quantity", 0)) for o in sells) / sell_qty if sell_qty > 0 else 0
                
                entry_time = str(buys[0].get("order_timestamp", "")) if buys else str(sells[0].get("order_timestamp", ""))
                exit_time = str(sells[-1].get("order_timestamp", "")) if (sells and net_qty == 0) else "OPEN"
                
                # Calculate PnL
                if net_qty == 0 and buy_qty > 0 and sell_qty > 0:
                    pnl_rs = round((sell_avg - buy_avg) * min(buy_qty, sell_qty), 2)
                    outcome = "SL Hit" if pnl_rs < 0 else "Target/Profit Hit"
                elif net_qty > 0:
                    pnl_rs = round(net_pnl, 2)
                    outcome = "ACTIVE (Carry Forward)"
                else:
                    pnl_rs = round(net_pnl, 2)
                    outcome = "Closed Position"

                pnl_pct_val = (pnl_rs / (buy_avg * max(1, buy_qty))) * 100 if (buy_avg > 0 and buy_qty > 0) else 0.0
                pnl_pct_str = f"{pnl_pct_val:+.2f}%"
                
                engine_type = "index" if ("NIFTY" in sym or "BANK" in sym or "SENSEX" in sym) else "nifty50"
                
                # Check if this order was manually placed
                is_manual = True if any(o.get("tag") in ("tfc_tv", None) for o in buys or sells) else False
                
                # Resolve exact pattern (e.g. BASE_ABCD (Manual Entry))
                pattern_name = resolve_trade_pattern(sym, sym, "ZERODHA_ORDER", is_manual=is_manual)
                
                trade_info = {
                    "Symbol": sym, "Outcome": outcome, "PnL_Rs": pnl_rs, "PnL_Pct": pnl_pct_str,
                    "Pattern": pattern_name, "Tier": tier_badge, "Entry_Time": entry_time,
                    "Exit_Time": exit_time, "MFE_Pct": 0.0, "MAE_Pct": 0.0
                }
                rem, les = derive_trade_remarks_and_lesson(sym, outcome, pnl_rs, pattern_name, trade_data=trade_info)
                if sym in existing_user_notes:
                    if existing_user_notes[sym].get("remarks"): rem = existing_user_notes[sym]["remarks"]
                    if existing_user_notes[sym].get("lesson"): les = existing_user_notes[sym]["lesson"]
                
                sl_t_levels = {}
                try:
                    from common.trading_core import lookup_scan_sl_target
                    sl_t_levels = lookup_scan_sl_target(sym, sym, engine_type, kite, buy_avg or sell_avg) or {}
                except Exception:
                    pass

                if not sl_t_levels.get("current_sl"):
                    try:
                        from common.trade_db import get_all_trades
                        for t in get_all_trades():
                            t_sym = str(t.get("symbol") or t.get("contract") or "").replace(" ", "").upper()
                            clean_sym = str(sym).replace(" ", "").upper()
                            if clean_sym in t_sym or t_sym in clean_sym:
                                sl_t_levels["current_sl"] = t.get("current_sl", 0)
                                sl_t_levels["t1"] = t.get("t1", 0)
                                sl_t_levels["t2"] = t.get("t2", 0)
                                sl_t_levels["t3"] = t.get("t3", 0)
                                break
                    except Exception:
                        pass

                tier_badge, swing_waves = resolve_trade_tier_and_swings(sym, sym, pattern_name)
                rec = {
                    "Date": target_date,
                    "Engine": engine_type,
                    "Symbol": sym,
                    "Side": "BUY" if buy_qty > 0 else "SELL",
                    "Timeframe": "75min" if engine_type == "nifty50" else "3min",
                    "Pattern": pattern_name,
                    "Tier": tier_badge,
                    "Swing_Waves": swing_waves,
                    "Entry_Time": entry_time,
                    "Entry_Price": round(buy_avg, 2),
                    "Exit_Time": exit_time,
                    "Exit_Price": round(sell_avg, 2) if sell_avg > 0 else "",
                    "SL": sl_t_levels.get("current_sl", 0),
                    "T1": sl_t_levels.get("t1", 0),
                    "T2": sl_t_levels.get("t2", 0),
                    "T3": sl_t_levels.get("t3", 0),
                    "Quantity": max(buy_qty, sell_qty, abs(net_qty)),
                    "Lot_Size": 1,
                    "PnL_Rs": pnl_rs,
                    "PnL_Pct": pnl_pct_str,
                    "Outcome": outcome,
                    "MFE_Pct": 0.0,
                    "MAE_Pct": 0.0,
                    "Attribution_Code": classify_trade_attribution({"PnL_Rs": pnl_rs, "Outcome": outcome, "Tier": tier_badge, "Pattern": pattern_name}),
                    "Spot_VWAP_Dist_Pct": "",
                    "Spot_RVOL": "",
                    "Spot_EMA_Trend": "",
                    "Spot_ATR_Ratio": "",
                    "Opt_VCP_Ratio": "",
                    "Analysis_Remarks": rem,
                    "Self_Learning_Lesson": les
                }
                today_records.append(rec)
                processed_symbols.add(sym)
        except Exception as ke:
            logging.warning(f"Kite order fetch for journal failed: {ke}")

    # 2. Sync remaining trades from trade_db
    try:
        try:
            from common.trade_db import get_all_trades
        except ImportError:
            from trade_db import get_all_trades
        trades = get_all_trades()

        # Build map of completed trade updates
        db_trade_map = {}
        for t in trades:
            c = str(t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()
            if c:
                db_trade_map[c] = t

        # Update existing records if completed in trade_db
        for e in filtered:
            sym = str(e.get("Symbol") or "").replace(" ", "").upper()
            if sym in db_trade_map:
                t = db_trade_map[sym]
                status = t.get("status", "ACTIVE")
                if status != "ACTIVE" and (e.get("Outcome") == "ACTIVE (Carry Forward)" or e.get("Exit_Time") in ("OPEN", "")):
                    pnl_rs = float(t.get("pnl") or t.get("pnl_rs") or 0)
                    pnl_pct = float(t.get("pnl_pct") or t.get("pnl_percent") or 0)
                    exit_px = t.get("exit_price") or t.get("current_sl") or 0
                    if not pnl_pct and float(t.get("entry_spot") or 0) > 0 and exit_px:
                        entry_px = float(t.get("entry_spot"))
                        pnl_pct = ((float(exit_px) - entry_px) / entry_px) * 100
                    
                    e["Outcome"] = status
                    e["Exit_Time"] = t.get("exit_time") or t.get("updated_at", "")
                    e["Exit_Price"] = exit_px
                    e["PnL_Rs"] = pnl_rs
                    e["PnL_Pct"] = f"{pnl_pct:+.2f}%" if pnl_pct else "0.00%"
                    if t.get("timeframe"):
                        e["Timeframe"] = t.get("timeframe")
                    if t.get("mfe_pct") is not None:
                        e["MFE_Pct"] = float(t.get("mfe_pct") or 0.0)
                    if t.get("mae_pct") is not None:
                        e["MAE_Pct"] = float(t.get("mae_pct") or 0.0)
                    e["Attribution_Code"] = t.get("attribution_code") or classify_trade_attribution(t, pnl_rs, status)
                    if isinstance(t.get("trade_dna"), dict):
                        tdna = t["trade_dna"]
                        e["Spot_VWAP_Dist_Pct"] = tdna.get("spot_vwap_dist_pct", "")
                        e["Spot_RVOL"] = tdna.get("spot_rvol", "")
                        e["Spot_EMA_Trend"] = tdna.get("spot_ema_trend", "")
                        e["Spot_ATR_Ratio"] = tdna.get("spot_atr_ratio", "")
                        e["Opt_VCP_Ratio"] = tdna.get("opt_vcp_ratio", "")
                    rem, les = derive_trade_remarks_and_lesson(sym, status, pnl_rs, e.get("Pattern", ""), trade_data=t)
                    e["Analysis_Remarks"] = rem
                    e["Self_Learning_Lesson"] = les

        for t in trades:
            c_date = (t.get("created_at") or t.get("entry_time") or "")[:10]
            sym = t.get("contract") or t.get("symbol") or "UNKNOWN"
            if c_date == target_date and sym not in processed_symbols:
                status = t.get("status", "ACTIVE")
                pnl_rs = float(t.get("pnl") or t.get("pnl_rs") or 0)
                pnl_pct = float(t.get("pnl_pct") or t.get("pnl_percent") or 0)
                exit_px = t.get("exit_price") or (t.get("current_sl") if status != "ACTIVE" else "")
                
                outcome = "ACTIVE (Carry Forward)" if status == "ACTIVE" else status
                pattern_name = resolve_trade_pattern(sym, t.get("contract", ""), t.get("pattern"))
                tier_badge, swing_waves = resolve_trade_tier_and_swings(sym, t.get("contract", ""), pattern_name)
                
                rem, les = derive_trade_remarks_and_lesson(sym, outcome, pnl_rs, pattern_name, trade_data=t)
                if sym in existing_user_notes:
                    if existing_user_notes[sym].get("remarks"): rem = existing_user_notes[sym]["remarks"]
                    if existing_user_notes[sym].get("lesson"): les = existing_user_notes[sym]["lesson"]
                if t.get("self_learning_lesson"):
                    les = t.get("self_learning_lesson")

                dna = t.get("trade_dna") if isinstance(t.get("trade_dna"), dict) else {}
                mfe_val = float(t.get("mfe_pct") or 0.0)
                mae_val = float(t.get("mae_pct") or 0.0)
                attr_code = t.get("attribution_code") or classify_trade_attribution(t, pnl_rs, outcome)
                
                rec = {
                    "Date": target_date,
                    "Engine": t.get("engine", "nifty50"),
                    "Symbol": sym,
                    "Side": t.get("side", "BUY"),
                    "Timeframe": t.get("timeframe", "30minute"),
                    "Pattern": pattern_name,
                    "Tier": tier_badge,
                    "Swing_Waves": swing_waves,
                    "Entry_Time": t.get("entry_time", t.get("created_at", "")),
                    "Entry_Price": t.get("entry_spot", 0),
                    "Exit_Time": t.get("exit_time", "") if status != "ACTIVE" else "OPEN",
                    "Exit_Price": exit_px,
                    "SL": t.get("current_sl", 0),
                    "T1": t.get("t1", 0),
                    "T2": t.get("t2", 0),
                    "T3": t.get("t3", 0),
                    "Quantity": t.get("position_size", 1),
                    "Lot_Size": t.get("lot_size", 1),
                    "PnL_Rs": pnl_rs,
                    "PnL_Pct": f"{pnl_pct:+.2f}%" if pnl_pct else "0.00%",
                    "Outcome": outcome,
                    "MFE_Pct": mfe_val,
                    "MAE_Pct": mae_val,
                    "Attribution_Code": attr_code,
                    "Spot_VWAP_Dist_Pct": dna.get("spot_vwap_dist_pct", ""),
                    "Spot_RVOL": dna.get("spot_rvol", ""),
                    "Spot_EMA_Trend": dna.get("spot_ema_trend", ""),
                    "Spot_ATR_Ratio": dna.get("spot_atr_ratio", ""),
                    "Opt_VCP_Ratio": dna.get("opt_vcp_ratio", ""),
                    "Analysis_Remarks": rem,
                    "Self_Learning_Lesson": les
                }
                today_records.append(rec)
                processed_symbols.add(sym)
    except Exception as e:
        logging.warning(f"Error reading trade_db for journal: {e}")

    # Combine and save
    final_entries = filtered + today_records
    save_journal_entries(final_entries)
    logging.info(f"Daily Trade Journal updated for {target_date}: {len(today_records)} trades recorded.")
    return today_records

def get_trade_journal_analytics(entries=None):
    """Compute detailed analytics and statistical metrics on trade journal entries, including Tier & Swing Wave breakdowns."""
    if entries is None:
        entries = load_journal_entries()

    total_trades = len(entries)
    if total_trades == 0:
        return {
            "summary": {
                "total_trades": 0,
                "closed_trades": 0,
                "active_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "breakeven_trades": 0,
                "win_rate_pct": 0.0,
                "total_pnl_rs": 0.0,
                "gross_profit_rs": 0.0,
                "gross_loss_rs": 0.0,
                "profit_factor": 0.0,
                "avg_pnl_per_trade_rs": 0.0,
                "avg_win_rs": 0.0,
                "avg_loss_rs": 0.0,
                "max_win_rs": 0.0,
                "max_loss_rs": 0.0
            },
            "by_pattern": {},
            "by_tier": {},
            "by_swing_waves": {},
            "by_timeframe": {},
            "by_engine": {},
            "by_outcome": {}
        }

    closed_trades = 0
    active_trades = 0
    winning_trades = 0
    losing_trades = 0
    breakeven_trades = 0

    total_pnl_rs = 0.0
    gross_profit_rs = 0.0
    gross_loss_rs = 0.0
    max_win_rs = 0.0
    max_loss_rs = 0.0

    by_pattern = {}
    by_tier = {}
    by_swing_waves = {}
    by_timeframe = {}
    by_engine = {}
    by_outcome = {}
    by_attribution = {}
    by_rvol_bucket = {}
    by_vcp_compression = {}

    mfe_list_winners = []
    mae_list_winners = []
    mfe_list_losers = []
    mae_list_losers = []

    for e in entries:
        outcome = str(e.get("Outcome", "")).strip()
        is_active = "ACTIVE" in outcome.upper() or outcome == "Carry Forward" or e.get("Exit_Time") in ("OPEN", "")

        try:
            pnl_rs = float(e.get("PnL_Rs") or 0.0)
        except (ValueError, TypeError):
            pnl_rs = 0.0

        pattern = str(e.get("Pattern") or "UNKNOWN").strip()
        
        # Dynamically resolve Tier & Swing Waves if missing from legacy records
        tier = e.get("Tier")
        swings = e.get("Swing_Waves")
        if not tier or not swings:
            resolved_t, resolved_sw = resolve_trade_tier_and_swings(e.get("Symbol"), e.get("Symbol"), pattern)
            tier = tier or resolved_t
            swings = swings or resolved_sw
            e["Tier"] = tier
            e["Swing_Waves"] = swings

        tf = str(e.get("Timeframe") or "UNKNOWN").strip()
        eng = str(e.get("Engine") or "UNKNOWN").strip()

        total_pnl_rs += pnl_rs

        # MFE / MAE parsing
        try:
            mfe_v = float(e.get("MFE_Pct") or 0.0)
        except (ValueError, TypeError):
            mfe_v = 0.0
        try:
            mae_v = float(e.get("MAE_Pct") or 0.0)
        except (ValueError, TypeError):
            mae_v = 0.0

        if is_active:
            active_trades += 1
        else:
            closed_trades += 1
            if pnl_rs > 0:
                winning_trades += 1
                gross_profit_rs += pnl_rs
                mfe_list_winners.append(mfe_v)
                mae_list_winners.append(mae_v)
                if pnl_rs > max_win_rs:
                    max_win_rs = pnl_rs
            elif pnl_rs < 0:
                losing_trades += 1
                gross_loss_rs += abs(pnl_rs)
                mfe_list_losers.append(mfe_v)
                mae_list_losers.append(mae_v)
                if pnl_rs < max_loss_rs:
                    max_loss_rs = pnl_rs
            else:
                breakeven_trades += 1

        # Outcome breakdown
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1

        # Helper to update breakdown dicts
        def update_breakdown(group_dict, key_val):
            if key_val not in group_dict:
                group_dict[key_val] = {
                    "total_trades": 0,
                    "closed_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl_rs": 0.0,
                    "win_rate_pct": 0.0,
                    "avg_pnl_rs": 0.0
                }
            g = group_dict[key_val]
            g["total_trades"] += 1
            g["total_pnl_rs"] += pnl_rs
            if not is_active:
                g["closed_trades"] += 1
                if pnl_rs > 0:
                    g["winning_trades"] += 1
                elif pnl_rs < 0:
                    g["losing_trades"] += 1

        update_breakdown(by_pattern, pattern)
        update_breakdown(by_tier, str(tier))
        update_breakdown(by_swing_waves, str(swings))
        update_breakdown(by_timeframe, tf)
        update_breakdown(by_engine, eng)

        # Attribution Breakdown
        attr_code = str(e.get("Attribution_Code") or classify_trade_attribution(e, pnl_rs, outcome))
        update_breakdown(by_attribution, attr_code)

        # RVOL bucket Breakdown
        rvol_raw = e.get("Spot_RVOL")
        if rvol_raw not in (None, "", "UNKNOWN"):
            try:
                rvol_f = float(rvol_raw)
                if rvol_f < 1.0:
                    rvol_bucket = "< 1.0 (Low Vol)"
                elif rvol_f < 1.5:
                    rvol_bucket = "1.0 - 1.5 (Normal)"
                else:
                    rvol_bucket = ">= 1.5 (High Inst)"
                update_breakdown(by_rvol_bucket, rvol_bucket)
            except (ValueError, TypeError):
                pass

        # VCP Compression Breakdown
        atr_ratio_raw = e.get("Spot_ATR_Ratio")
        if atr_ratio_raw not in (None, "", "UNKNOWN"):
            try:
                atr_f = float(atr_ratio_raw)
                vcp_bucket = "Coiled (ATR <= 0.85)" if atr_f <= 0.85 else "Expanding (ATR > 0.85)"
                update_breakdown(by_vcp_compression, vcp_bucket)
            except (ValueError, TypeError):
                pass

    # Finalize percentages and averages for groups
    def finalize_breakdown(group_dict):
        for k, v in group_dict.items():
            ct = v["closed_trades"]
            v["win_rate_pct"] = round((v["winning_trades"] / ct) * 100, 2) if ct > 0 else 0.0
            v["avg_pnl_rs"] = round(v["total_pnl_rs"] / v["total_trades"], 2) if v["total_trades"] > 0 else 0.0
            v["total_pnl_rs"] = round(v["total_pnl_rs"], 2)

    finalize_breakdown(by_pattern)
    finalize_breakdown(by_tier)
    finalize_breakdown(by_swing_waves)
    finalize_breakdown(by_timeframe)
    finalize_breakdown(by_engine)
    finalize_breakdown(by_attribution)
    finalize_breakdown(by_rvol_bucket)
    finalize_breakdown(by_vcp_compression)

    win_rate_pct = round((winning_trades / closed_trades) * 100, 2) if closed_trades > 0 else 0.0
    profit_factor = round(gross_profit_rs / gross_loss_rs, 2) if gross_loss_rs > 0 else (999.99 if gross_profit_rs > 0 else 0.0)
    avg_pnl_per_trade = round(total_pnl_rs / total_trades, 2) if total_trades > 0 else 0.0
    avg_win = round(gross_profit_rs / winning_trades, 2) if winning_trades > 0 else 0.0
    avg_loss = round(gross_loss_rs / losing_trades, 2) if losing_trades > 0 else 0.0

    return {
        "summary": {
            "total_trades": total_trades,
            "closed_trades": closed_trades,
            "active_trades": active_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "breakeven_trades": breakeven_trades,
            "win_rate_pct": win_rate_pct,
            "total_pnl_rs": round(total_pnl_rs, 2),
            "gross_profit_rs": round(gross_profit_rs, 2),
            "gross_loss_rs": round(gross_loss_rs, 2),
            "profit_factor": profit_factor,
            "avg_pnl_per_trade_rs": avg_pnl_per_trade,
            "avg_win_rs": avg_win,
            "avg_loss_rs": avg_loss,
            "max_win_rs": round(max_win_rs, 2),
            "max_loss_rs": round(max_loss_rs, 2),
            "avg_mfe_pct_winners": round(sum(mfe_list_winners) / len(mfe_list_winners), 2) if mfe_list_winners else 0.0,
            "avg_mae_pct_winners": round(sum(mae_list_winners) / len(mae_list_winners), 2) if mae_list_winners else 0.0,
            "avg_mfe_pct_losers": round(sum(mfe_list_losers) / len(mfe_list_losers), 2) if mfe_list_losers else 0.0,
            "avg_mae_pct_losers": round(sum(mae_list_losers) / len(mae_list_losers), 2) if mae_list_losers else 0.0
        },
        "by_pattern": by_pattern,
        "by_tier": by_tier,
        "by_swing_waves": by_swing_waves,
        "by_timeframe": by_timeframe,
        "by_engine": by_engine,
        "by_outcome": by_outcome,
        "by_attribution": by_attribution,
        "by_rvol_bucket": by_rvol_bucket,
        "by_vcp_compression": by_vcp_compression
    }


def update_cumulative_evolution_log(session_summary, directives, target_date):
    """Update append-only cumulative strategy evolution history and rolling performance metrics."""
    cum_json_path = os.path.join(JOURNAL_DIR, "cumulative_strategy_evolution_log.json")
    cum_md_path = os.path.join(JOURNAL_DIR, "cumulative_strategy_evolution_log.md")

    entries = []
    if os.path.exists(cum_json_path):
        try:
            with open(cum_json_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    # Filter out target_date if re-running on same date
    entries = [e for e in entries if e.get("date") != target_date]

    entry = {
        "date": target_date,
        "total_trades": session_summary.get("total_trades", 0),
        "closed_trades": session_summary.get("closed_trades", 0),
        "winning_trades": session_summary.get("winning_trades", 0),
        "losing_trades": session_summary.get("losing_trades", 0),
        "win_rate_pct": session_summary.get("win_rate_pct", 0.0),
        "net_pnl_rs": session_summary.get("net_pnl_rs", 0.0),
        "profit_factor": session_summary.get("profit_factor", 0.0),
        "avg_left_on_table_pct": session_summary.get("avg_left_on_table_pct", 0.0),
        "directives": directives,
        "updated_at": datetime.now().isoformat(),
    }
    entries.append(entry)
    entries.sort(key=lambda x: x.get("date", ""))

    try:
        with open(cum_json_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save cumulative evolution JSON: {e}")

    # Generate cumulative Markdown summary
    try:
        recent = entries[-10:]
        total_pnl = sum(float(e.get("net_pnl_rs", 0)) for e in entries)
        total_trades = sum(int(e.get("total_trades", 0)) for e in entries)
        total_closed = sum(int(e.get("closed_trades", 0)) for e in entries)
        total_wins = sum(int(e.get("winning_trades", 0)) for e in entries)
        overall_wr = round((total_wins / total_closed * 100), 2) if total_closed > 0 else 0.0

        md_lines = [
            "# 📈 CUMULATIVE STRATEGY EVOLUTION & LEARNING LOG",
            f"**Last Updated**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}` | **Total Sessions Tracked**: `{len(entries)}`",
            "",
            "## 1. Multi-Session Aggregate Performance",
            f"- **Cumulative Realized P&L**: `₹{total_pnl:,.2f}`",
            f"- **Cumulative Closed Trades**: `{total_closed}` (`{total_wins}` Wins, `{total_closed - total_wins}` Losses)",
            f"- **Aggregate Win Rate**: `{overall_wr:.1f}%`",
            "",
            "## 2. Recent Session Trajectory (Last 10 Sessions)",
            "| Date | Trades | Win Rate % | Net P&L (₹) | Profit Factor | Left on Table % | Top Evolutionary Directive |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
        ]
        for e in reversed(recent):
            top_dir = e.get("directives", ["N/A"])[0] if e.get("directives") else "N/A"
            if len(top_dir) > 80:
                top_dir = top_dir[:77] + "..."
            md_lines.append(
                f"| `{e.get('date')}` | {e.get('total_trades')} | {e.get('win_rate_pct'):.1f}% | ₹{e.get('net_pnl_rs'):,.2f} | {e.get('profit_factor')} | {e.get('avg_left_on_table_pct'):.1f}% | {top_dir} |"
            )

        md_lines.extend([
            "",
            "## 3. Active Algorithmic Evolution Directives (Latest Session)",
        ])
        for idx, d in enumerate(directives, 1):
            md_lines.append(f"{idx}. {d}")

        with open(cum_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines) + "\n")
    except Exception as e:
        logging.warning(f"Could not save cumulative evolution Markdown: {e}")


def generate_daily_session_learning_report(target_date=None, kite=None):
    """
    Generate an exhaustive, self-learning trade session report in both Markdown (.md) and JSON (.json)
    for a given date (default today).
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Sync journal first to capture latest states
    generate_daily_journal(target_date=target_date, kite=kite)

    # 2. Load all journal entries and filter for target_date
    all_entries = load_journal_entries()
    session_trades = [e for e in all_entries if e.get("Date") == target_date]

    # Also fetch trades from trade_db for deeper metadata
    trade_db_map = {}
    try:
        from common.trade_db import get_all_trades
        for t in get_all_trades():
            c = str(t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()
            if c:
                trade_db_map[c] = t
    except Exception:
        pass

    # Enrich session_trades with trade_db details if missing
    for e in session_trades:
        sym = str(e.get("Symbol") or "").replace(" ", "").upper()
        if sym in trade_db_map:
            t = trade_db_map[sym]
            if not e.get("MFE_Pct") and t.get("mfe_pct") is not None:
                e["MFE_Pct"] = float(t.get("mfe_pct") or 0.0)
            if not e.get("MAE_Pct") and t.get("mae_pct") is not None:
                e["MAE_Pct"] = float(t.get("mae_pct") or 0.0)
            if not e.get("Attribution_Code"):
                e["Attribution_Code"] = t.get("attribution_code") or classify_trade_attribution(t, e.get("PnL_Rs", 0), e.get("Outcome", ""))

    total_trades = len(session_trades)
    closed_trades = [e for e in session_trades if not ("ACTIVE" in str(e.get("Outcome","")).upper() or e.get("Exit_Time") in ("OPEN", ""))]
    active_trades = [e for e in session_trades if ("ACTIVE" in str(e.get("Outcome","")).upper() or e.get("Exit_Time") in ("OPEN", ""))]

    winning_trades = [e for e in closed_trades if float(e.get("PnL_Rs") or 0) > 0]
    losing_trades = [e for e in closed_trades if float(e.get("PnL_Rs") or 0) < 0]
    be_trades = [e for e in closed_trades if float(e.get("PnL_Rs") or 0) == 0]

    gross_profit = sum(float(e.get("PnL_Rs") or 0) for e in winning_trades)
    gross_loss = abs(sum(float(e.get("PnL_Rs") or 0) for e in losing_trades))
    net_pnl = gross_profit - gross_loss
    win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg_win = round(gross_profit / len(winning_trades), 2) if winning_trades else 0.0
    avg_loss = round(gross_loss / len(losing_trades), 2) if losing_trades else 0.0
    max_win = max([float(e.get("PnL_Rs") or 0) for e in winning_trades], default=0.0)
    max_loss = min([float(e.get("PnL_Rs") or 0) for e in losing_trades], default=0.0)

    # Opportunity Cost / MFE / MAE analysis
    mfe_winners = [float(e.get("MFE_Pct") or 0) for e in winning_trades]
    mae_winners = [float(e.get("MAE_Pct") or 0) for e in winning_trades]
    mfe_losers = [float(e.get("MFE_Pct") or 0) for e in losing_trades]
    mae_losers = [float(e.get("MAE_Pct") or 0) for e in losing_trades]

    avg_mfe_winners = round(sum(mfe_winners) / len(mfe_winners), 2) if mfe_winners else 0.0
    avg_mae_winners = round(sum(mae_winners) / len(mae_winners), 2) if mae_winners else 0.0
    avg_mfe_losers = round(sum(mfe_losers) / len(mfe_losers), 2) if mfe_losers else 0.0
    avg_mae_losers = round(sum(mae_losers) / len(mae_losers), 2) if mae_losers else 0.0

    # Left on Table (Peak MFE vs Realized Return on Winners)
    left_on_table_list = []
    for w in winning_trades:
        mfe_w = float(w.get("MFE_Pct") or 0)
        pnl_pct_w = float(str(w.get("PnL_Pct") or "0").replace("%", "").replace("+", "") or 0)
        left_on_table_list.append(max(0.0, mfe_w - pnl_pct_w))
    avg_left_on_table = round(sum(left_on_table_list) / len(left_on_table_list), 2) if left_on_table_list else 0.0

    # Groupings: Time of Day, Tier, Pattern, Attribution
    time_windows = {
        "Opening Velocity (09:15-10:00)": {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0},
        "Morning Trend (10:00-11:30)": {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0},
        "Midday Chop (11:30-13:30)": {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0},
        "Closing Momentum (13:30-15:30)": {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0},
        "Other / Unscheduled": {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0},
    }

    tier_breakdown = {}
    pattern_breakdown = {}
    attribution_breakdown = {}

    for e in session_trades:
        pnl = float(e.get("PnL_Rs") or 0)
        is_w = pnl > 0
        is_l = pnl < 0

        # Time Window
        ent = str(e.get("Entry_Time") or "")
        tw = "Other / Unscheduled"
        if ent and len(ent) >= 16:
            try:
                t_str = ent.split(" ")[-1][:5]
                hh, mm = map(int, t_str.split(":"))
                mins = hh * 60 + mm
                if 9 * 60 + 15 <= mins < 10 * 60:
                    tw = "Opening Velocity (09:15-10:00)"
                elif 10 * 60 <= mins < 11 * 60 + 30:
                    tw = "Morning Trend (10:00-11:30)"
                elif 11 * 60 + 30 <= mins < 13 * 60 + 30:
                    tw = "Midday Chop (11:30-13:30)"
                elif 13 * 60 + 30 <= mins <= 15 * 60 + 30:
                    tw = "Closing Momentum (13:30-15:30)"
            except Exception:
                pass
        time_windows[tw]["total"] += 1
        time_windows[tw]["pnl"] += pnl
        if is_w: time_windows[tw]["wins"] += 1
        elif is_l: time_windows[tw]["losses"] += 1

        # Tier
        tr = str(e.get("Tier") or "🥈 T2 Core")
        if tr not in tier_breakdown:
            tier_breakdown[tr] = {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        tier_breakdown[tr]["total"] += 1
        tier_breakdown[tr]["pnl"] += pnl
        if is_w: tier_breakdown[tr]["wins"] += 1
        elif is_l: tier_breakdown[tr]["losses"] += 1

        # Pattern
        pat = str(e.get("Pattern") or "UNKNOWN")
        if pat not in pattern_breakdown:
            pattern_breakdown[pat] = {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        pattern_breakdown[pat]["total"] += 1
        pattern_breakdown[pat]["pnl"] += pnl
        if is_w: pattern_breakdown[pat]["wins"] += 1
        elif is_l: pattern_breakdown[pat]["losses"] += 1

        # Attribution
        attr = str(e.get("Attribution_Code") or classify_trade_attribution(e, pnl, e.get("Outcome","")))
        attribution_breakdown[attr] = attribution_breakdown.get(attr, 0) + 1

    # Synthesize Evolutionary Rules
    directives = []

    # Rule 1: Win rate & profit factor calibration
    if closed_trades:
        if win_rate >= 60.0:
            directives.append(f"🥇 REGIME CONVICTION: High statistical edge confirmed ({win_rate:.1f}% win rate, Profit Factor {profit_factor:.2f}). Maintain full capital allocation (100% on T1 Gold, 70% on T2 Core).")
        elif win_rate < 40.0 and len(closed_trades) >= 2:
            directives.append(f"🛡️ REGIME DEFENSE: Sub-optimal win rate ({win_rate:.1f}%). Restrict automated entries strictly to 🥇 T1 Gold setups with R:R >= 2.0 and Spot EMA13/44 trend confirmation.")
        else:
            directives.append(f"⚖️ REGIME CALIBRATION: Balanced performance ({win_rate:.1f}% win rate). Prioritize setups with coiled VCP metrics (ATR3/ATR14 <= 0.85) to enhance trade follow-through.")
    else:
        directives.append("🛡️ CAPITAL PRESERVATION: No closed trades during session. Capital 100% shielded; scanners maintained surveillance.")

    # Rule 2: Midday Chop Window Rule
    midday_stats = time_windows["Midday Chop (11:30-13:30)"]
    if midday_stats["total"] > 0:
        if midday_stats["pnl"] < 0 or (midday_stats["total"] > 0 and midday_stats["wins"] == 0):
            directives.append(f"⏰ MIDDAY CHOP SHIELD: 11:30-13:30 IST window generated negative expectancy (-₹{abs(midday_stats['pnl']):.2f} across {midday_stats['total']} trade(s)). Strictly enforce 11:30 cutoff on 0DTE index options, and require RVOL >= 1.8x for stock options.")
        else:
            directives.append(f"⏰ MIDDAY DISCIPLINE: Midday setups generated ₹{midday_stats['pnl']:.2f}. Continue requiring high structural confluence during noon consolidation.")
    else:
        directives.append("⏰ TIME WINDOW COMPLIANCE: Zero midday chop trades executed. Adherence to 11:30 IST 0DTE cutoff successfully protected capital from theta burn.")

    # Rule 3: Left on Table / Profit Harvesting
    if avg_left_on_table >= 8.0:
        directives.append(f"💰 PROFIT HARVESTING: Average left on table was {avg_left_on_table:.1f}%. Implement partial profit scaling (lock 50% lots at Target 1 / +20% spike) while trailing remainder to eliminate profit round-trips.")
    elif winning_trades:
        directives.append(f"💰 TRAILING EFFICIENCY: Trailing ratchets executed cleanly ({avg_left_on_table:.1f}% avg left on table). Maintain current +15% -> +8% lock and +25% -> +15% lock rules.")

    # Rule 4: Structural vs Premature Shakeouts
    premature_shakeouts = attribution_breakdown.get("LOSS_COUNTER_SPOT_TRAP", 0) + attribution_breakdown.get("LOSS_THETA_DECAY", 0)
    if "PREMATURE_OPTION_SL_SHAKEOUT" in attribution_breakdown or premature_shakeouts > 0:
        directives.append("🔬 STRUCTURAL IMMUNITY: Premature option SL exits observed while Spot stayed inside Anchor corridor. Enforce Spot 15m candle-close confirmation before option SL execution.")
    else:
        directives.append("🛡️ DISCIPLINED RISK: Stop-losses executed per institutional rules. Zero unshielded runaway drawdowns observed.")

    # Rule 5: Volume & VCP Validation
    directives.append("📐 GEOMETRIC & VOLUME MANDATE: Breakout confirmation requires candle RVOL >= 1.2x and coiled VCP metric (ATR3/ATR14 <= 0.85). Reject uncompressed setups showing volatility exhaustion.")

    summary_dict = {
        "total_trades": total_trades,
        "closed_trades": len(closed_trades),
        "active_trades": len(active_trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "breakeven_trades": len(be_trades),
        "win_rate_pct": round(win_rate, 2),
        "net_pnl_rs": round(net_pnl, 2),
        "gross_profit_rs": round(gross_profit, 2),
        "gross_loss_rs": round(gross_loss, 2),
        "profit_factor": profit_factor,
        "avg_win_rs": avg_win,
        "avg_loss_rs": avg_loss,
        "max_win_rs": round(max_win, 2),
        "max_loss_rs": round(max_loss, 2),
        "avg_mfe_winners": avg_mfe_winners,
        "avg_mae_winners": avg_mae_winners,
        "avg_mfe_losers": avg_mfe_losers,
        "avg_mae_losers": avg_mae_losers,
        "avg_left_on_table_pct": avg_left_on_table,
    }

    # Build Markdown Report
    top_winner = max(session_trades, key=lambda x: float(x.get("PnL_Rs") or 0), default=None) if session_trades else None
    top_loser = min(session_trades, key=lambda x: float(x.get("PnL_Rs") or 0), default=None) if session_trades else None

    md_lines = [
        f"# 📊 DAILY TRADING SESSION LEARNING & EVOLUTION REPORT",
        f"**Session Date**: `{target_date}` | **Generated At**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}`",
        "",
        "---",
        "",
        "## 1. Executive Performance Dashboard",
        "",
        "| Performance Metric | Session Value | Status / Benchmark |",
        "| :--- | :---: | :--- |",
        f"| **Total Trades Recorded** | **{total_trades}** | {len(closed_trades)} Closed, {len(active_trades)} Active |",
        f"| **Win Rate** | **{win_rate:.1f}%** | Target >= 55.0% |",
        f"| **Net Realized P&L** | **₹{net_pnl:,.2f}** | {'🟢 Profitable' if net_pnl > 0 else ('🔴 Loss' if net_pnl < 0 else '⚪ Breakeven')} |",
        f"| **Gross Profit / Loss** | **+₹{gross_profit:,.2f} / -₹{gross_loss:,.2f}** | Profit Factor: **{profit_factor}** |",
        f"| **Average Win / Loss** | **₹{avg_win:,.2f} / ₹{avg_loss:,.2f}** | Payoff Ratio: **{round(avg_win / max(1, avg_loss), 2)}x** |",
        f"| **Max Single Win / Loss** | **₹{max_win:,.2f} / ₹{max_loss:,.2f}** | Risk Clamp Active |",
        f"| **Avg Winner Peak MFE** | **+{avg_mfe_winners:.1f}%** | Realized Excursion |",
        f"| **Avg Left on Table** | **{avg_left_on_table:.1f}%** | Peak MFE vs Realized Exit |",
        "",
        "---",
        "",
        "## 2. Multi-Dimensional Performance Breakdown",
        "",
        "### A. By Conviction Tier",
        "| Tier Classification | Trades | Wins | Losses | Win Rate % | Realized P&L (₹) |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |"
    ]

    for tr_k, tr_v in tier_breakdown.items():
        wr_tr = round(tr_v["wins"] / (tr_v["wins"] + tr_v["losses"]) * 100, 1) if (tr_v["wins"] + tr_v["losses"]) > 0 else 0.0
        md_lines.append(f"| **{tr_k}** | {tr_v['total']} | {tr_v['wins']} | {tr_v['losses']} | {wr_tr}% | ₹{tr_v['pnl']:,.2f} |")

    md_lines.extend([
        "",
        "### B. By Time-of-Day Execution Window",
        "| Execution Window | Trades | Wins | Losses | Net P&L (₹) | Expectancy Assessment |",
        "| :--- | :---: | :---: | :---: | :--- | :--- |"
    ])

    for tw_k, tw_v in time_windows.items():
        if tw_v["total"] > 0:
            assess = "🟢 High Expectancy" if tw_v["pnl"] > 0 else ("🔴 Negative / Avoid" if tw_v["pnl"] < 0 else "⚪ Neutral")
            md_lines.append(f"| **{tw_k}** | {tw_v['total']} | {tw_v['wins']} | {tw_v['losses']} | ₹{tw_v['pnl']:,.2f} | {assess} |")

    md_lines.extend([
        "",
        "### C. By Attribution Taxonomy",
        "| Attribution Code | Count | Strategy Significance |",
        "| :--- | :---: | :--- |"
    ])

    for att_k, att_cnt in attribution_breakdown.items():
        md_lines.append(f"| `{att_k}` | {att_cnt} | Systematic Audit Tag |")

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. Trade-by-Trade Forensic Audit Log",
        "",
        "| Symbol / Contract | Side | Pattern | Tier | Entry Price | Exit Price | PnL (₹) | Return % | MFE % | MAE % | Forensic Remarks & Actionable Lesson |",
        "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |"
    ])

    for t in session_trades:
        sym_c = t.get("Symbol") or "UNKNOWN"
        side_c = t.get("Side") or "BUY"
        pat_c = t.get("Pattern") or "UNKNOWN"
        tier_c = t.get("Tier") or "🥈 T2 Core"
        ep_c = t.get("Entry_Price") or 0.0
        xp_c = t.get("Exit_Price") or "-"
        pnl_c = float(t.get("PnL_Rs") or 0.0)
        pnl_pct_c = t.get("PnL_Pct") or "0.00%"
        mfe_c = float(t.get("MFE_Pct") or 0.0)
        mae_c = float(t.get("MAE_Pct") or 0.0)
        rem_c = t.get("Analysis_Remarks") or ""
        les_c = t.get("Self_Learning_Lesson") or ""
        combined_note = f"**Remark**: {rem_c}<br>**Lesson**: {les_c}"

        md_lines.append(
            f"| `{sym_c}` | {side_c} | `{pat_c}` | {tier_c} | ₹{ep_c} | ₹{xp_c} | ₹{pnl_c:,.2f} | {pnl_pct_c} | +{mfe_c:.1f}% | {mae_c:.1f}% | {combined_note} |"
        )

    # Section 4: Autopsy of Top Winner and Top Loser
    md_lines.extend([
        "",
        "---",
        "",
        "## 4. Session Autopsy: Case Studies",
        ""
    ])
    if top_winner and float(top_winner.get("PnL_Rs") or 0) > 0:
        md_lines.extend([
            f"### 🏆 Top Winner: `{top_winner.get('Symbol')}` (+₹{float(top_winner.get('PnL_Rs', 0)):,.2f})",
            f"- **Pattern & Tier**: `{top_winner.get('Pattern')}` | `{top_winner.get('Tier')}`",
            f"- **Entry & Exit**: Entry @ ₹{top_winner.get('Entry_Price')} ({top_winner.get('Entry_Time')}) ─── Exit @ ₹{top_winner.get('Exit_Price')} ({top_winner.get('Exit_Time')})",
            f"- **Peak Excursion**: MFE: `+{top_winner.get('MFE_Pct', 0.0)}%` | MAE: `{top_winner.get('MAE_Pct', 0.0)}%`",
            f"- **Key Takeaway**: {top_winner.get('Self_Learning_Lesson')}",
            ""
        ])
    else:
        md_lines.append("### 🏆 Top Winner: None (No winning trades recorded today)\n")

    if top_loser and float(top_loser.get("PnL_Rs") or 0) < 0:
        md_lines.extend([
            f"### 🛑 Top Risk Event / Loser: `{top_loser.get('Symbol')}` (-₹{abs(float(top_loser.get('PnL_Rs', 0))):,.2f})",
            f"- **Pattern & Tier**: `{top_loser.get('Pattern')}` | `{top_loser.get('Tier')}`",
            f"- **Entry & Exit**: Entry @ ₹{top_loser.get('Entry_Price')} ({top_loser.get('Entry_Time')}) ─── Exit @ ₹{top_loser.get('Exit_Price')} ({top_loser.get('Exit_Time')})",
            f"- **Peak Excursion**: MFE: `+{top_loser.get('MFE_Pct', 0.0)}%` | MAE: `{top_loser.get('MAE_Pct', 0.0)}%`",
            f"- **Root Cause & Remediation**: {top_loser.get('Analysis_Remarks')} | **Evolution Rule**: {top_loser.get('Self_Learning_Lesson')}",
            ""
        ])
    else:
        md_lines.append("### 🛑 Top Risk Event / Loser: None (Zero loss trades recorded today)\n")

    # Section 5: Evolutionary Directives
    md_lines.extend([
        "---",
        "",
        "## 5. Actionable Strategy Evolution Directives (Rules for Subsequent Sessions)",
        ""
    ])
    for idx, d in enumerate(directives, 1):
        md_lines.append(f"{idx}. {d}")

    md_lines.append("\n---\n*Report auto-generated by Price Action Self-Learning System.*")

    # File Paths
    report_md_path = os.path.join(JOURNAL_DIR, f"daily_learning_session_{target_date}.md")
    report_json_path = os.path.join(JOURNAL_DIR, f"daily_learning_session_{target_date}.json")

    # Write Markdown
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    # Build JSON
    report_json_content = {
        "ok": True,
        "session_date": target_date,
        "generated_at": datetime.now().isoformat(),
        "summary": summary_dict,
        "by_tier": tier_breakdown,
        "by_time_window": time_windows,
        "by_pattern": pattern_breakdown,
        "by_attribution": attribution_breakdown,
        "evolutionary_directives": directives,
        "trades": session_trades,
    }

    # Write JSON
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_json_content, f, indent=2)

    # Mirror to default output dir if JOURNAL_DIR points to G: drive
    local_journal_dir = os.path.join(BASE_DIR, "output", "journal")
    if local_journal_dir != JOURNAL_DIR:
        os.makedirs(local_journal_dir, exist_ok=True)
        local_md = os.path.join(local_journal_dir, f"daily_learning_session_{target_date}.md")
        local_json = os.path.join(local_journal_dir, f"daily_learning_session_{target_date}.json")
        try:
            with open(local_md, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines) + "\n")
            with open(local_json, "w", encoding="utf-8") as f:
                json.dump(report_json_content, f, indent=2)
        except Exception:
            pass

    # Update cumulative evolution tracker
    update_cumulative_evolution_log(summary_dict, directives, target_date)

    logging.info(f"Daily session learning report generated: {report_md_path} and {report_json_path}")
    return report_json_content


def get_latest_daily_learning_report():
    """Fetch the latest available daily session learning report."""
    import glob
    search_dirs = [JOURNAL_DIR, os.path.join(BASE_DIR, "output", "journal")]
    found_files = []
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            found_files.extend(glob.glob(os.path.join(s_dir, "daily_learning_session_*.json")))

    if not found_files:
        return {"ok": False, "message": "No session learning reports found."}

    # Pick the newest by date in filename
    found_files.sort(reverse=True)
    latest_file = found_files[0]
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["report_file"] = latest_file
            return data
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily Trade Journal & Strategy Evolution Engine")
    parser.add_argument("--date", type=str, help="Target date in YYYY-MM-DD format (default today)")
    parser.add_argument("--report", action="store_true", help="Generate daily session learning report (.md and .json)")
    parser.add_argument("--analytics", action="store_true", help="Print journal analytics")
    parser.add_argument("--clear", action="store_true", help="Clear journal files with automatic backup")
    args = parser.parse_args()

    if args.clear:
        ok, backup, msg = clear_journal()
        print(msg)
    elif args.report:
        rep = generate_daily_session_learning_report(target_date=args.date)
        print(f"Generated session learning report for {rep.get('session_date')}: {rep.get('summary', {}).get('total_trades', 0)} trades recorded.")
    elif args.analytics:
        an = get_trade_journal_analytics()
        print(json.dumps(an, indent=2))
    else:
        generate_daily_journal(target_date=args.date)


