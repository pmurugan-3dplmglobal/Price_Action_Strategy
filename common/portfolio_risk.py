"""
portfolio_risk.py — Portfolio-Level Risk & Sector Exposure Governance.

Enforces cross-engine portfolio risk constraints before new trade entries:
1. Max Concurrent Positions: Caps total concurrent open/active positions (default: 6 across engines).
2. Max Daily Loss Limit: Halts new entries if cumulative realized + active unrealized loss for today
   exceeds a safety threshold (default: -3.0% of initial capital).
3. Max Same-Sector Positions: Prevents correlated portfolio failure by capping exposure to a single
   sector (default: max 2 positions in the same sector, e.g. BANKING_FINANCE, IT, AUTO).
"""

import logging
import json
import os
import time
from datetime import datetime as dt
import re
import paths
from timeframe_utils import get_ist_now
from registries import get_symbol_sector
import trade_db

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "BANKEX"}


def _extract_underlying_symbol(tradingsymbol):
    """
    Extract underlying symbol from an exchange tradingsymbol (option, future, or equity).
    E.g.:
    - 'ADANIENSOL26SEP1440CE' -> 'ADANIENSOL'
    - 'NIFTY2691523400CE'     -> 'NIFTY'
    - 'BANKNIFTY26SEP56400CE' -> 'BANKNIFTY'
    - 'SENSEX2691074700CE'    -> 'SENSEX'
    - 'INFY'                  -> 'INFY'
    """
    if not tradingsymbol:
        return None
    ts = str(tradingsymbol).strip().upper()

    # 1. Known index prefixes
    for idx in ["MIDCPNIFTY", "BANKNIFTY", "FINNIFTY", "NIFTY", "SENSEX", "BANKEX"]:
        if ts.startswith(idx):
            return idx

    # 2. Registered equities
    try:
        from registries import STOCK_REGISTRY
        if STOCK_REGISTRY:
            for reg_sym in sorted(STOCK_REGISTRY.keys(), key=len, reverse=True):
                if ts.startswith(reg_sym):
                    return reg_sym
    except Exception:
        pass

    # 3. Standard option/future contract format: letters before 2-digit year (e.g. 26)
    m = re.match(r"^([A-Z&-]+?)\d{2}[A-Z\d]+", ts)
    if m:
        return m.group(1)

    return ts


def _load_portfolio_risk_config(config=None, capital=None, engine=None):
    """Load portfolio risk configuration with safe defaults and dynamic capital scaling."""
    cfg_all = {}
    if os.path.exists(paths.PROGRAM_CONFIG_FILE):
        try:
            with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg_all = json.load(f)
        except Exception:
            cfg_all = {}

    if config is None:
        config = cfg_all.get("portfolio_risk", {})

    p_cfg = config.get("portfolio_risk", config) if isinstance(config, dict) else {}
    if not isinstance(p_cfg, dict):
        p_cfg = {}

    enable = bool(p_cfg.get("enable", True))
    raw_max_concurrent = p_cfg.get("max_concurrent_positions")
    has_explicit_concurrent = raw_max_concurrent not in [None, "auto", 0]
    dynamic_scaling = bool(p_cfg.get("dynamic_scaling", not has_explicit_concurrent))
    base_per_100k = float(p_cfg.get("base_positions_per_100k", 6.0))
    base_sector_per_100k = float(p_cfg.get("base_sector_positions_per_100k", 2.0))

    # Dynamic Capital Scaling Calculation
    effective_cap = float(capital or 100000.0)
    if (dynamic_scaling and not has_explicit_concurrent) or (not has_explicit_concurrent):
        # Scale dynamically based on capital (default: 6 per 100k capital, min 2)
        calc_max_concurrent = max(2, int(round((effective_cap / 100000.0) * base_per_100k)))
        calc_max_sector = max(1, int(round((effective_cap / 100000.0) * base_sector_per_100k)))
    else:
        calc_max_concurrent = int(raw_max_concurrent or 6)
        calc_max_sector = int(p_cfg.get("max_same_sector_positions", 2))

    # Index-specific concurrency cap (default 1 to stop correlated duplicate drawdowns)
    raw_max_index = None
    if isinstance(config, dict):
        if isinstance(config.get("index"), dict):
            raw_max_index = config["index"].get("max_concurrent_positions")
        if raw_max_index is None and isinstance(config.get("portfolio_risk"), dict):
            raw_max_index = config["portfolio_risk"].get("max_concurrent_index_positions")
        if raw_max_index is None:
            raw_max_index = config.get("max_concurrent_index_positions")
    if raw_max_index is None:
        raw_max_index = p_cfg.get("max_concurrent_index_positions")
    if raw_max_index is None and isinstance(cfg_all.get("index"), dict):
        raw_max_index = cfg_all["index"].get("max_concurrent_positions")
    if raw_max_index is None and isinstance(cfg_all.get("portfolio_risk"), dict):
        raw_max_index = cfg_all["portfolio_risk"].get("max_concurrent_index_positions")
    max_concurrent_index = int(raw_max_index) if raw_max_index is not None else 1

    # Resolve max_daily_loss_pct with full fallback hierarchy (Engine-specific -> Config -> Portfolio -> Default)
    daily_loss = None
    if engine and isinstance(cfg_all.get(engine), dict):
        daily_loss = cfg_all[engine].get("max_daily_loss_pct")
    if daily_loss is None:
        daily_loss = p_cfg.get("max_daily_loss_pct")
    if daily_loss is None and isinstance(config, dict):
        daily_loss = config.get("max_daily_loss_pct")
    if daily_loss is None and isinstance(cfg_all.get("portfolio_risk"), dict):
        daily_loss = cfg_all["portfolio_risk"].get("max_daily_loss_pct")
    if daily_loss is None:
        daily_loss = 3.0 if (engine == "index") else 5.0

    return {
        "enable": enable,
        "max_concurrent_positions": calc_max_concurrent,
        "max_concurrent_index_positions": max_concurrent_index,
        "max_daily_loss_pct": float(daily_loss),
        "max_same_sector_positions": calc_max_sector,
        "dynamic_scaling": dynamic_scaling,
        "effective_capital": effective_cap
    }


def check_portfolio_risk_caps(engine, symbol, candidate_tier=2, capital=100000.0, live_positions=None, config=None, include_db_trades=True, kite=None):
    """
    Check if a candidate trade passes all portfolio-level risk limits.

    Parameters:
    - engine: str (e.g. 'nifty50', 'index', 'daily', 'bear_trade')
    - symbol: str (e.g. 'RELIANCE', 'NIFTY', 'HDFCBANK')
    - candidate_tier: int (1 = TIER_1_GOLD, 2 = TIER_2_CORE, 3 = TIER_3_MOMENTUM)
    - capital: float (base trading capital, default 100,000 INR)
    - live_positions: dict or list or None (in-memory active positions if available)
    - config: dict or None (program config overrides)
    - include_db_trades: bool (whether to include active trades from trade_db, default True)
    - kite: KiteConnect session instance or None (queries live broker positions directly as ground truth)

    Returns:
    - (is_allowed: bool, reason: str, details: dict)
    """
    # ── RULE 0: Emergency Global Trading HALT Check ──
    try:
        from position_monitor import is_global_halt
        if is_global_halt():
            return False, "GLOBAL_HALT_ACTIVE (All new entries blocked via emergency HALT switch)", {
                "rule": "global_halt"
            }
    except Exception:
        pass

    cap_val = float(capital or 100000.0)
    if cap_val <= 0:
        try:
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                    cap_val = float(cfg_all.get(engine, {}).get("capital", 100000.0))
        except Exception:
            cap_val = 100000.0

    p_cfg = _load_portfolio_risk_config(config, capital=cap_val, engine=engine)
    if not p_cfg["enable"]:
        return True, "PORTFOLIO_RISK_GUARD_DISABLED", {}

    max_concurrent = p_cfg["max_concurrent_positions"]
    max_daily_loss_pct = p_cfg["max_daily_loss_pct"]
    max_same_sector = p_cfg["max_same_sector_positions"]

    # Normalize candidate symbol
    candidate_sym = _extract_underlying_symbol(symbol) or str(symbol).strip().upper()

    import trade_db

    # 1. Gather all active trades across engines from Broker, DB and in-memory
    active_symbols = set()
    active_contracts = set()
    active_index_symbols = set()
    sector_counts = {}

    # 1A. Live Broker Ground Truth (Kite net positions)
    broker_positions_fetched = False
    broker_active_contracts = set()
    broker_active_symbols = set()
    broker_holdings = set()

    if kite:
        try:
            net_pos = kite.positions().get("net", [])
            broker_positions_fetched = True
            for p in net_pos:
                nq = int(p.get("quantity", 0))
                if nq != 0:
                    cnt = str(p.get("tradingsymbol", "")).strip().upper()
                    if cnt:
                        active_contracts.add(cnt)
                        broker_active_contracts.add(cnt)
                        raw_sym = _extract_underlying_symbol(cnt)
                        if raw_sym:
                            active_symbols.add(raw_sym)
                            broker_active_symbols.add(raw_sym)
                            if raw_sym in INDEX_SYMBOLS:
                                active_index_symbols.add(raw_sym)
                            sec = get_symbol_sector(raw_sym)
                            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            # Also capture holdings for equity CNC positions
            # NOTE: Demat holdings are only stored in broker_holdings as a ground-truth lookup
            # for verifying active equity trades in trade_db (line 259). Personal long-term Demat
            # investments (e.g. SGB, GoldBees, ETFs) must NEVER be directly added to active_symbols /
            # active_contracts as active algo trading slots.
            try:
                h_list = kite.holdings()
                if isinstance(h_list, list):
                    for h in h_list:
                        hq = int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
                        if hq > 0:
                            h_sym = str(h.get("tradingsymbol", "")).strip().upper()
                            broker_holdings.add(h_sym)
            except Exception:
                pass
        except Exception as k_err:
            logging.warning(f"Portfolio risk: Failed to fetch live broker positions: {k_err}")

    # 1B. SQLite trade_db Active Records
    if include_db_trades:
        target_eng = str(engine).lower() if engine else None
        active_db_trades = trade_db.get_active_trades(engine=target_eng)
        now_dt = get_ist_now(naive=True)
        for t in active_db_trades:
            tid = t.get("id")
            sym = t.get("symbol")
            cnt = t.get("contract") or sym
            t_eng = str(t.get("engine", "")).lower()
            pos_type = str(t.get("position_type", "")).lower()
            c_str = str(cnt).strip().upper() if cnt else ""
            raw_sym = _extract_underlying_symbol(c_str or sym) or (str(sym).strip().upper() if sym else "")

            # If live broker positions were fetched, Kite is ground truth.
            # Stale DB trades with 0 quantity on broker must not block new trades.
            if broker_positions_fetched:
                is_equity = (pos_type == "stock")
                held_on_broker = (
                    c_str in broker_active_contracts
                    or raw_sym in broker_active_symbols
                    or (is_equity and (c_str in broker_holdings or raw_sym in broker_holdings))
                )
                if not held_on_broker:
                    # Allow 60s grace period for fresh in-flight orders
                    is_recent_fill = False
                    entry_t = t.get("entry_time") or t.get("created_at")
                    if entry_t:
                        try:
                            e_dt = dt.fromisoformat(str(entry_t).split("+")[0].replace("T", " "))
                            if (now_dt - e_dt).total_seconds() < 60.0:
                                is_recent_fill = True
                        except Exception:
                            pass
                    if not is_recent_fill:
                        # Auto-reconcile stale/ghost DB trade only for matching engine
                        if target_eng and t_eng and t_eng != target_eng:
                            continue
                        if tid:
                            try:
                                trade_db.update_trade_status(
                                    tid, "CLOSED_EXTERNALLY",
                                    details="Auto-reconciled: Zero quantity on broker during portfolio risk check"
                                )
                                logging.info(f"[PORTFOLIO_RISK_RECONCILE] Auto-closed stale trade #{tid} ({cnt or sym}) in trade_db (not held on broker)")
                            except Exception as rec_err:
                                logging.debug(f"Failed auto-closing stale trade #{tid}: {rec_err}")
                        continue  # Do NOT add ghost trade to active portfolio count!

            if sym:
                if raw_sym not in active_symbols:
                    active_symbols.add(raw_sym)
                    sec = get_symbol_sector(raw_sym)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                if raw_sym in INDEX_SYMBOLS or t_eng == "index":
                    active_index_symbols.add(raw_sym if raw_sym in INDEX_SYMBOLS else (sym or "INDEX"))
            if cnt:
                active_contracts.add(c_str)
                if raw_sym and raw_sym not in active_symbols:
                    active_symbols.add(raw_sym)
                    sec = get_symbol_sector(raw_sym)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                if raw_sym and (raw_sym in INDEX_SYMBOLS or t_eng == "index"):
                    active_index_symbols.add(raw_sym if raw_sym in INDEX_SYMBOLS else (sym or "INDEX"))

    # 1C. In-Memory Process State
    if isinstance(live_positions, dict):
        for k, v in live_positions.items():
            sym = v.get("symbol") or k
            cnt = v.get("contract") or sym
            c_str = str(cnt).strip().upper() if cnt else ""
            raw_sym = _extract_underlying_symbol(c_str or sym) or (str(sym).strip().upper() if sym else "")
            if broker_positions_fetched:
                held_on_broker = (
                    c_str in broker_active_contracts
                    or raw_sym in broker_active_symbols
                    or (c_str in broker_holdings or raw_sym in broker_holdings)
                )
                if not held_on_broker:
                    continue
            if raw_sym:
                if raw_sym not in active_symbols:
                    active_symbols.add(raw_sym)
                    sec = get_symbol_sector(raw_sym)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                if raw_sym in INDEX_SYMBOLS:
                    active_index_symbols.add(raw_sym)
            if c_str:
                active_contracts.add(c_str)
    elif isinstance(live_positions, list):
        for v in live_positions:
            if isinstance(v, dict):
                sym = v.get("symbol")
                cnt = v.get("contract") or sym
                c_str = str(cnt).strip().upper() if cnt else ""
                raw_sym = _extract_underlying_symbol(c_str or sym) or (str(sym).strip().upper() if sym else "")
                if broker_positions_fetched:
                    held_on_broker = (
                        c_str in broker_active_contracts
                        or raw_sym in broker_active_symbols
                        or (c_str in broker_holdings or raw_sym in broker_holdings)
                    )
                    if not held_on_broker:
                        continue
                if raw_sym:
                    if raw_sym not in active_symbols:
                        active_symbols.add(raw_sym)
                        sec = get_symbol_sector(raw_sym)
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    if raw_sym in INDEX_SYMBOLS:
                        active_index_symbols.add(raw_sym)
                if c_str:
                    active_contracts.add(c_str)

    # Count distinct active scripts (underlying symbols) across the entire portfolio
    total_active_count = len(active_symbols) if active_symbols else len(active_contracts)

    # ── RULE 1: Max Concurrent Positions Cap (Evaluated at Script Level) ──
    # If the candidate is an additional order on an existing held script, don't double count it towards script cap
    is_new_script = candidate_sym not in active_symbols
    if is_new_script and total_active_count >= max_concurrent:
        reason = f"MAX_CONCURRENT_POSITIONS_REACHED ({total_active_count}/{max_concurrent} active scripts across portfolio [Capital: Rs {cap_val:,.0f}])"
        return False, reason, {
            "rule": "max_concurrent_positions",
            "active_count": total_active_count,
            "active_scripts": list(active_symbols),
            "limit": max_concurrent,
            "capital": cap_val
        }

    # ── RULE 1B: Max Concurrent Index Positions Cap ──
    # Enforces max_concurrent_index_positions = 1 (default 1) across directional index trades
    # (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY, BANKEX) to stop correlated duplicate drawdowns.
    candidate_sector = get_symbol_sector(candidate_sym)
    is_index_candidate = (
        str(engine).lower() == "index" or
        candidate_sym in INDEX_SYMBOLS or
        candidate_sector == "INDICES"
    )
    if is_index_candidate:
        max_concurrent_index = p_cfg.get("max_concurrent_index_positions", 1)
        active_index_count = len(active_index_symbols)
        if active_index_count >= max_concurrent_index:
            reason = (f"MAX_INDEX_POSITIONS_REACHED ({active_index_count}/{max_concurrent_index} "
                      f"active index trade(s) across portfolio: {sorted(list(active_index_symbols))})")
            return False, reason, {
                "rule": "max_concurrent_index_positions",
                "active_index_count": active_index_count,
                "active_index_symbols": sorted(list(active_index_symbols)),
                "limit": max_concurrent_index
            }

    # ── RULE 2: Max Same-Sector Positions Cap ──
    candidate_sector = get_symbol_sector(candidate_sym)
    current_sector_count = sector_counts.get(candidate_sector, 0)

    # Indices (NIFTY/BANKNIFTY) and 'OTHER' are exempt from the strict single-industry limit
    # or treated with a generous cap
    is_exempt_sector = candidate_sector in ["INDICES", "OTHER"]

    if not is_exempt_sector and is_new_script and current_sector_count >= max_same_sector:
        reason = f"MAX_SECTOR_POSITIONS_REACHED ({current_sector_count}/{max_same_sector} active in sector '{candidate_sector}')"
        return False, reason, {
            "rule": "max_same_sector_positions",
            "sector": candidate_sector,
            "current_sector_count": current_sector_count,
            "limit": max_same_sector
        }

    # ── RULE 3: Max Daily Drawdown / Loss Limit (Realized + Unrealized) ──
    today_str = get_ist_now().strftime("%Y-%m-%d")
    today_realized_loss_inr = 0.0
    today_unrealized_loss_inr = 0.0
    if include_db_trades:
        all_trades = trade_db.get_all_trades(engine=None)
        for t in all_trades:
            created_at = str(t.get("created_at") or t.get("entry_time") or "")
            exit_time = str(t.get("exit_time") or "")
            status = t.get("status")

            # Determine correct price basis for INR PnL:
            # For options, use option_entry/entry_price (the premium paid);
            # for equities, use entry_spot (the stock price).
            lot_sz_raw = t.get("lot_size")
            lot_sz = int(lot_sz_raw) if (lot_sz_raw is not None and str(lot_sz_raw).isdigit()) else 1
            is_opt = bool(t.get("position_type") == "option" or lot_sz > 1)
            if is_opt:
                price_basis = float(t.get("option_entry") or t.get("entry_price") or t.get("entry_spot") or 0.0)
            else:
                price_basis = float(t.get("entry_spot") or t.get("entry_price") or 0.0)
            lot_sz = int(t.get("lot_size") or 1)
            pos_sz = int(t.get("position_size") or 1)

            if price_basis <= 0:
                continue

            # Closed/completed trades today → realized PnL
            if (today_str in created_at or today_str in exit_time) and status in ["COMPLETED", "SL_HIT", "CLOSED", "TARGET_HIT"]:
                pnl_pct_raw = t.get("pnl_percent")
                exit_reason = str(t.get("exit_reason") or t.get("details") or "").upper()
                # Exclude phantom trades (zero PnL created from unexecuted/cancelled broker reconciliation)
                if (pnl_pct_raw is None or float(pnl_pct_raw or 0.0) == 0.0) and any(k in exit_reason for k in ["RECONCIL", "NET_QTY_ZERO", "CANCEL", "EXPIRED", "UNFILLED"]):
                    continue
                if t.get("pnl_inr") is not None:
                    trade_inr_pnl = float(t["pnl_inr"])
                else:
                    pnl_pct = float(pnl_pct_raw or 0.0)
                    trade_inr_pnl = (pnl_pct / 100.0) * price_basis * lot_sz * pos_sz
                today_realized_loss_inr += trade_inr_pnl

            # Active trades opened today → unrealized floating PnL
            elif today_str in created_at and status == "ACTIVE":
                current_pnl_pct = float(t.get("pnl_percent") or t.get("current_pnl_pct") or 0.0)
                if current_pnl_pct < 0:
                    unrealized_inr = (current_pnl_pct / 100.0) * price_basis * lot_sz * pos_sz
                    today_unrealized_loss_inr += unrealized_inr

    total_daily_pnl_inr = today_realized_loss_inr + today_unrealized_loss_inr
    if kite:
        try:
            net_pos = kite.positions().get("net", [])
            live_broker_pnl = sum(float(p.get("pnl", 0.0)) for p in net_pos)
            if live_broker_pnl < 0 and live_broker_pnl < total_daily_pnl_inr:
                total_daily_pnl_inr = live_broker_pnl
        except Exception:
            pass
    cap_val = float(capital or 100000.0)
    max_loss_allowed_inr = -1.0 * (max_daily_loss_pct / 100.0) * cap_val

    if total_daily_pnl_inr < max_loss_allowed_inr:
        reason = (f"DAILY_DRAWDOWN_CAP_EXCEEDED (Today Realized: Rs {today_realized_loss_inr:.2f} + "
                  f"Unrealized: Rs {today_unrealized_loss_inr:.2f} = Rs {total_daily_pnl_inr:.2f} "
                  f"<= Max Allowed Loss: Rs {max_loss_allowed_inr:.2f} [{-max_daily_loss_pct:.1f}%])")
        return False, reason, {
            "rule": "max_daily_loss_pct",
            "today_realized_pnl_inr": today_realized_loss_inr,
            "today_unrealized_pnl_inr": today_unrealized_loss_inr,
            "today_total_pnl_inr": total_daily_pnl_inr,
            "max_loss_limit_inr": max_loss_allowed_inr,
            "capital": cap_val
        }

    return True, "PORTFOLIO_RISK_APPROVED", {
        "total_active_count": total_active_count,
        "max_concurrent": max_concurrent,
        "candidate_sector": candidate_sector,
        "sector_count": current_sector_count,
        "today_realized_pnl_inr": today_realized_loss_inr,
        "today_unrealized_pnl_inr": today_unrealized_loss_inr,
        "today_total_pnl_inr": today_realized_loss_inr + today_unrealized_loss_inr
    }


def find_weakest_swappable_position(live_positions, candidate_rr=3.0, kite=None, min_hold_minutes=45.0):
    """
    Identifies if an existing active position is eligible for Dynamic Slot Swap (ISSUE-079).
    Triggered when portfolio cap (MAX_CONCURRENT_POSITIONS_REACHED) blocks a pristine
    Tier 1 Gold candidate with high risk-reward (R:R >= 3.0, e.g. KEI).

    Eligibility Criteria for Incumbent to be Swapped Out:
    1. Held for at least min_hold_minutes (default 45 mins) - not freshly entered.
    2. Has NOT reached Target 1 or locked Breakeven (trailing_stage == 0).
    3. Flat or negative MTM (MTM <= +2% of premium, or broker net PnL <= 0).
    4. Candidate R:R is at least 1.5x the incumbent's original R:R.

    Returns:
        dict with swappable position details, or None if no candidate qualifies.
    """
    if not live_positions or candidate_rr < 3.0:
        return None

    now_dt = get_ist_now(naive=True)
    broker_pnl_map = {}
    if kite:
        try:
            net_pos = kite.positions().get("net", [])
            for p in net_pos:
                ts = str(p.get("tradingsymbol", "")).strip().upper()
                broker_pnl_map[ts] = float(p.get("pnl", 0.0))
        except Exception:
            pass

    swappable_candidates = []

    pos_items = live_positions.items() if isinstance(live_positions, dict) else [(v.get("symbol", ""), v) for v in live_positions if isinstance(v, dict)]

    for sym_key, pos in pos_items:
        if not isinstance(pos, dict):
            continue
        sym = pos.get("symbol") or sym_key
        contract = pos.get("contract") or sym
        c_str = str(contract).strip().upper()

        # Guard 1: Must be at trailing stage 0 (never exit runners that locked profit)
        stage = int(pos.get("trailing_stage") or 0)
        if stage > 0:
            continue

        # Guard 2: Must have been held for at least min_hold_minutes
        entry_time_val = pos.get("entry_time") or pos.get("staged_time") or pos.get("created_at")
        hold_minutes = 0.0
        if entry_time_val:
            try:
                if isinstance(entry_time_val, str):
                    clean_ts = entry_time_val.replace("T", " ")[:19]
                    e_dt = dt.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
                    hold_minutes = max(0.0, (now_dt - e_dt).total_seconds() / 60.0)
                elif hasattr(entry_time_val, "timestamp"):
                    hold_minutes = max(0.0, (time.time() - entry_time_val.timestamp()) / 60.0)
                elif isinstance(entry_time_val, (int, float)):
                    hold_minutes = max(0.0, (time.time() - entry_time_val) / 60.0)
            except Exception:
                hold_minutes = 0.0

        if hold_minutes < min_hold_minutes:
            continue

        # Guard 3: Broker MTM Check - must not be running in strong green
        net_pnl = broker_pnl_map.get(c_str, 0.0)
        entry_p = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
        ltp = float(pos.get("ltp") or pos.get("last_price") or entry_p)
        pnl_pct = ((ltp - entry_p) / entry_p * 100.0) if entry_p > 0 else 0.0

        # Disqualify if running in solid profit (> 3% or PnL > Rs 500)
        if pnl_pct > 3.0 or net_pnl > 500.0:
            continue

        # Guard 4: Candidate RR must be significantly higher
        incumbent_rr = float(pos.get("rr") or 1.5)
        if candidate_rr < (incumbent_rr * 1.5) and incumbent_rr >= 2.0:
            continue

        swappable_candidates.append({
            "symbol": sym,
            "contract": contract,
            "pos": pos,
            "pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "hold_minutes": hold_minutes,
            "incumbent_rr": incumbent_rr,
            "reason": f"{sym} ({contract}): Held {hold_minutes:.0f}m, MTM {pnl_pct:+.1f}% (Rs {net_pnl:+.1f}), Stage 0, Incumbent RR {incumbent_rr:.2f} < Candidate RR {candidate_rr:.2f}"
        })

    if not swappable_candidates:
        return None

    # Sort by lowest PnL first (weakest performer gets swapped)
    swappable_candidates.sort(key=lambda x: (x["pnl"], x["pnl_pct"]))
    return swappable_candidates[0]

