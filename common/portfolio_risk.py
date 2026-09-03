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
import paths
from timeframe_utils import get_ist_now
from registries import get_symbol_sector


def _load_portfolio_risk_config(config=None, capital=None):
    """Load portfolio risk configuration with safe defaults and dynamic capital scaling."""
    if config is None:
        try:
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                    config = cfg_all.get("portfolio_risk", {})
        except Exception:
            config = {}

    p_cfg = config.get("portfolio_risk", config) if isinstance(config, dict) else {}
    if not isinstance(p_cfg, dict):
        p_cfg = {}

    enable = bool(p_cfg.get("enable", True))
    dynamic_scaling = bool(p_cfg.get("dynamic_scaling", True))
    raw_max_concurrent = p_cfg.get("max_concurrent_positions")
    base_per_100k = float(p_cfg.get("base_positions_per_100k", 6.0))
    base_sector_per_100k = float(p_cfg.get("base_sector_positions_per_100k", 2.0))

    # Dynamic Capital Scaling Calculation
    effective_cap = float(capital or 100000.0)
    if dynamic_scaling or raw_max_concurrent in [None, "auto", 0]:
        # Scale dynamically based on capital (default: 6 per 100k capital, min 2)
        calc_max_concurrent = max(2, int(round((effective_cap / 100000.0) * base_per_100k)))
        calc_max_sector = max(1, int(round((effective_cap / 100000.0) * base_sector_per_100k)))
    else:
        calc_max_concurrent = int(raw_max_concurrent or 6)
        calc_max_sector = int(p_cfg.get("max_same_sector_positions", 2))

    return {
        "enable": enable,
        "max_concurrent_positions": calc_max_concurrent,
        "max_daily_loss_pct": float(p_cfg.get("max_daily_loss_pct", 3.0)),
        "max_same_sector_positions": calc_max_sector,
        "dynamic_scaling": dynamic_scaling,
        "effective_capital": effective_cap
    }


def check_portfolio_risk_caps(engine, symbol, candidate_tier=2, capital=100000.0, live_positions=None, config=None, include_db_trades=True):
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

    Returns:
    - (is_allowed: bool, reason: str, details: dict)
    """
    cap_val = float(capital or 100000.0)
    if cap_val <= 0:
        try:
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                    cap_val = float(cfg_all.get(engine, {}).get("capital", 100000.0))
        except Exception:
            cap_val = 100000.0

    p_cfg = _load_portfolio_risk_config(config, capital=cap_val)
    if not p_cfg["enable"]:
        return True, "PORTFOLIO_RISK_GUARD_DISABLED", {}

    max_concurrent = p_cfg["max_concurrent_positions"]
    max_daily_loss_pct = p_cfg["max_daily_loss_pct"]
    max_same_sector = p_cfg["max_same_sector_positions"]

    import trade_db

    # 1. Gather all active trades across engines from DB and in-memory
    active_symbols = set()
    active_contracts = set()
    sector_counts = {}

    if include_db_trades:
        active_db_trades = trade_db.get_active_trades(engine=None)
        for t in active_db_trades:
            sym = t.get("symbol")
            cnt = t.get("contract") or sym
            if sym:
                active_symbols.add(sym)
                sec = get_symbol_sector(sym)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if cnt:
                active_contracts.add(str(cnt).strip().upper())

    if isinstance(live_positions, dict):
        for k, v in live_positions.items():
            sym = v.get("symbol") or k
            cnt = v.get("contract") or sym
            if sym and sym not in active_symbols:
                active_symbols.add(sym)
                sec = get_symbol_sector(sym)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if cnt:
                active_contracts.add(str(cnt).strip().upper())
    elif isinstance(live_positions, list):
        for v in live_positions:
            if isinstance(v, dict):
                sym = v.get("symbol")
                cnt = v.get("contract") or sym
                if sym and sym not in active_symbols:
                    active_symbols.add(sym)
                    sec = get_symbol_sector(sym)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                if cnt:
                    active_contracts.add(str(cnt).strip().upper())

    total_active_count = len(active_symbols)

    # ── RULE 1: Max Concurrent Positions Cap ──
    if total_active_count >= max_concurrent:
        reason = f"MAX_CONCURRENT_POSITIONS_REACHED ({total_active_count}/{max_concurrent} active trades across portfolio [Capital: Rs {cap_val:,.0f}])"
        return False, reason, {
            "rule": "max_concurrent_positions",
            "active_count": total_active_count,
            "limit": max_concurrent,
            "capital": cap_val
        }

    # ── RULE 2: Max Same-Sector Positions Cap ──
    candidate_sector = get_symbol_sector(symbol)
    current_sector_count = sector_counts.get(candidate_sector, 0)

    # Indices (NIFTY/BANKNIFTY) and 'OTHER' are exempt from the strict single-industry limit
    # or treated with a generous cap
    is_exempt_sector = candidate_sector in ["INDICES", "OTHER"]

    if not is_exempt_sector and current_sector_count >= max_same_sector:
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
            is_opt = bool(t.get("position_type") == "option" or t.get("lot_size", 1) > 1)
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
                pnl_pct = float(t.get("pnl_percent") or 0.0)
                trade_inr_pnl = (pnl_pct / 100.0) * price_basis * lot_sz * pos_sz
                today_realized_loss_inr += trade_inr_pnl

            # Active trades opened today → unrealized floating PnL
            elif today_str in created_at and status == "ACTIVE":
                current_pnl_pct = float(t.get("pnl_percent") or t.get("current_pnl_pct") or 0.0)
                if current_pnl_pct < 0:
                    unrealized_inr = (current_pnl_pct / 100.0) * price_basis * lot_sz * pos_sz
                    today_unrealized_loss_inr += unrealized_inr

    total_daily_pnl_inr = today_realized_loss_inr + today_unrealized_loss_inr
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
