"""
common/liquidity_guard.py
=========================
Bid-Ask Spread & Market Depth Liquidity Gate.

Protects automated engines and manual 1-Click Buy from illiquid option and equity contracts
where wide bid-ask spreads or thin order books cause severe execution slippage.

Invariants:
- Spread Ratio = (Best Ask - Best Bid) / LTP
- Max default allowed spread: 2.0% (0.02)
- Rejects contracts with insufficient book depth or excessive spread.
"""

import logging
from datetime import datetime
try:
    from common.position_monitor import is_market_open
except ImportError:
    from position_monitor import is_market_open


def check_bid_ask_spread_liquidity(
    kite,
    exchange: str,
    contract: str,
    max_spread_pct: float = 0.02,
    min_depth_qty: int = 1,
    bypass_when_closed: bool = True
):
    """
    Evaluates bid-ask spread liquidity for an option or equity contract before order routing.

    Args:
        kite: Active KiteConnect session instance.
        exchange: Exchange code ('NFO', 'NSE', 'BFO', 'BSE').
        contract: Trading symbol (e.g. 'NIFTY26SEP24500CE', 'RELIANCE').
        max_spread_pct: Maximum allowable (Ask - Bid) / LTP ratio (default 0.02 = 2.0%).
        min_depth_qty: Minimum cumulative shares/units on top 5 bid/ask depth (default 1).
        bypass_when_closed: When market is closed and off-hours testing or AMO, permit bypass.

    Returns:
        tuple: (is_liquid: bool, spread_pct: float, reason: str, details: dict)
    """
    if kite is None:
        return True, 0.0, "NO_KITE_SESSION_BYPASS", {}

    if bypass_when_closed and not is_market_open():
        return True, 0.0, "OFF_MARKET_HOURS_BYPASS", {}

    q_key = f"{exchange.strip().upper()}:{contract.strip().upper()}"
    try:
        quote_data = kite.quote([q_key])
        if not quote_data or q_key not in quote_data:
            return False, 1.0, f"No quote returned by broker for {q_key}", {}

        q = quote_data[q_key]
        ltp = float(q.get("last_price") or 0.0)
        depth = q.get("depth") or {}
        buy_depth = depth.get("buy") or []
        sell_depth = depth.get("sell") or []

        best_bid = float(buy_depth[0].get("price", 0.0)) if buy_depth else 0.0
        best_ask = float(sell_depth[0].get("price", 0.0)) if sell_depth else 0.0

        bid_qty = sum(int(item.get("quantity") or 0) for item in buy_depth)
        ask_qty = sum(int(item.get("quantity") or 0) for item in sell_depth)

        ref_price = ltp if ltp > 0 else (best_ask if best_ask > 0 else best_bid)
        if ref_price <= 0:
            return False, 1.0, f"Zero or negative reference price for {contract} (LTP={ltp})", {}

        # If one side of book is completely empty
        if best_bid <= 0 or best_ask <= 0:
            if bypass_when_closed and not is_market_open():
                return True, 0.0, "EMPTY_BOOK_OFF_HOURS", {"ltp": ltp, "best_bid": best_bid, "best_ask": best_ask}
            return False, 1.0, f"Empty order book side for {contract} (Bid={best_bid}, Ask={best_ask})", {
                "ltp": ltp, "best_bid": best_bid, "best_ask": best_ask
            }

        spread_abs = round(best_ask - best_bid, 2)
        spread_ratio = round(spread_abs / ref_price, 4)

        details = {
            "exchange": exchange,
            "contract": contract,
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_abs": spread_abs,
            "spread_pct": round(spread_ratio * 100, 2),
            "bid_depth_qty": bid_qty,
            "ask_depth_qty": ask_qty,
            "timestamp": datetime.now().isoformat()
        }

        # Check Depth Quantity
        if bid_qty < min_depth_qty or ask_qty < min_depth_qty:
            msg = f"Insufficient market depth for {contract} (Bid Qty={bid_qty}, Ask Qty={ask_qty} < min {min_depth_qty})"
            logging.warning(f"[LIQUIDITY_GATE] {msg}")
            return False, spread_ratio, msg, details

        # Check Spread Ratio
        if spread_ratio > max_spread_pct:
            msg = (
                f"Wide bid-ask spread for {contract}: {spread_ratio * 100:.2f}% > "
                f"{max_spread_pct * 100:.1f}% limit (Bid={best_bid}, Ask={best_ask}, LTP={ltp})"
            )
            logging.warning(f"[LIQUIDITY_GATE] {msg}")
            return False, spread_ratio, msg, details

        return True, spread_ratio, "LIQUID_OK", details

    except Exception as e:
        err_msg = f"Liquidity evaluation exception for {contract}: {e}"
        logging.error(f"[LIQUIDITY_GATE] {err_msg}")
        return False, 1.0, err_msg, {}
