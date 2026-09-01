# -*- coding: utf-8 -*-
"""
Watchlist Monitor & Post-Trade Learning System (v1.0.0)
Monitors custom option contracts and underlying equities in real-time.
Tracks live Greek behavior, post-exit decay, hypothetical P&L, and saves
snapshots to output/monitor/watchlist_live.json for dashboard integration.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

# Adjust path for common imports
COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import paths
import session
from kiteconnect import KiteConnect

def load_watchlist_config():
    if os.path.exists(paths.WATCHLIST_CONFIG_FILE):
        try:
            with open(paths.WATCHLIST_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to load watchlist config: {e}")
    return []

def save_watchlist_config(data):
    os.makedirs(os.path.dirname(paths.WATCHLIST_CONFIG_FILE), exist_ok=True)
    with open(paths.WATCHLIST_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _safe_float(v):
    if v is None:
        return None
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "null", "None", "NaN", "undefined") else None
    except (TypeError, ValueError):
        return None

def _safe_int(v):
    if v is None:
        return None
    try:
        s = str(v).strip()
        return int(float(s)) if s not in ("", "null", "None", "NaN", "undefined") else None
    except (TypeError, ValueError):
        return None

def _extract_base_symbol(contract_str):
    import re
    c = str(contract_str).strip().upper()
    m = re.match(r"^([A-Z]+)", c)
    if m:
        base = m.group(1)
        for s in ["26SEP", "26AUG", "26OCT", "26NOV", "26DEC", "269", "268", "267"]:
            if s in c:
                base = c.split(s)[0]
                break
        return base
    return c

def add_watchlist_item(contract, base_symbol=None, entry_price=None, exit_price=None, lot_size=None, tag="MANUAL_WATCH", note=""):
    items = load_watchlist_config()
    contract_clean = contract.strip().upper()
    if not contract_clean:
        return
    
    ep = _safe_float(entry_price)
    xp = _safe_float(exit_price)
    lot = _safe_int(lot_size)
    tag_clean = str(tag or "MANUAL_WATCH").strip().upper()
    note_clean = str(note or "").strip()
    
    existing = next((item for item in items if item.get("contract", "").upper() == contract_clean), None)
    if existing:
        if base_symbol:
            existing["base_symbol"] = str(base_symbol).strip().upper()
        if ep is not None:
            existing["entry_price"] = ep
        if xp is not None:
            existing["exit_price"] = xp
        if lot is not None:
            existing["lot_size"] = lot
        if tag_clean:
            existing["tag"] = tag_clean
        if note_clean:
            existing["note"] = note_clean
        print(f"[OK] Updated watchlist item: {contract_clean}")
    else:
        base_clean = str(base_symbol).strip().upper() if base_symbol else _extract_base_symbol(contract_clean)
        items.append({
            "contract": contract_clean,
            "base_symbol": base_clean,
            "entry_price": ep,
            "exit_price": xp,
            "lot_size": lot,
            "tag": tag_clean,
            "note": note_clean
        })
        print(f"[OK] Added new watchlist item: {contract_clean} (Base: {base_clean})")
    save_watchlist_config(items)

def remove_watchlist_item(contract):
    items = load_watchlist_config()
    contract_clean = contract.strip().upper()
    new_items = [item for item in items if item.get("contract", "").upper() != contract_clean]
    if len(new_items) < len(items):
        save_watchlist_config(new_items)
        print(f"[OK] Removed {contract_clean} from watchlist.")
    else:
        print(f"[WARN] {contract_clean} not found in watchlist.")

def fetch_watchlist_live_data(kite=None):
    items = load_watchlist_config()
    if not items:
        return []

    if kite is None:
        api_key, access_token = session.load_kite_session()
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)

    query_symbols = []
    for item in items:
        contract = item.get("contract", "").strip().upper()
        base = item.get("base_symbol", "").strip().upper()
        if contract:
            query_symbols.append(f"NFO:{contract}")
        if base:
            if base in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]:
                if base == "SENSEX":
                    query_symbols.append("BSE:SENSEX")
                else:
                    query_symbols.append(f"NSE:{base} 50" if base == "NIFTY" else f"NSE:{base}")
            else:
                query_symbols.append(f"NSE:{base}")

    try:
        quotes = kite.quote(list(set(query_symbols)))
    except Exception as e:
        print(f"[ERROR] Failed to fetch quotes from Kite: {e}")
        quotes = {}

    results = []
    for item in items:
        contract = item.get("contract", "").strip().upper()
        base = item.get("base_symbol", "").strip().upper()
        entry_p = item.get("entry_price")
        exit_p = item.get("exit_price")
        lot = item.get("lot_size", 1) or 1
        tag = item.get("tag", "WATCH")
        note = item.get("note", "")

        opt_key = f"NFO:{contract}"
        opt_data = quotes.get(opt_key, {})
        opt_ohlc = opt_data.get("ohlc", {})
        opt_ltp = float(opt_data.get("last_price") or 0.0)
        opt_chg = float(opt_data.get("net_change") or 0.0)
        opt_vol = int(opt_data.get("volume") or 0)
        opt_high = float(opt_ohlc.get("high") or 0.0)
        opt_low = float(opt_ohlc.get("low") or 0.0)

        spot_ltp = 0.0
        spot_chg = 0.0
        for spot_key in [f"NSE:{base}", f"NSE:{base} 50", f"BSE:{base}"]:
            if spot_key in quotes:
                s_data = quotes[spot_key]
                spot_ltp = float(s_data.get("last_price") or 0.0)
                spot_chg = float(s_data.get("net_change") or 0.0)
                break

        pnl_entry_pts = round(opt_ltp - entry_p, 2) if entry_p and opt_ltp else None
        pnl_entry_pct = round((opt_ltp - entry_p) / entry_p * 100, 2) if entry_p and opt_ltp else None
        pnl_entry_val = round(pnl_entry_pts * lot, 2) if pnl_entry_pts is not None else None

        pnl_exit_pts = round(opt_ltp - exit_p, 2) if exit_p and opt_ltp else None
        pnl_exit_pct = round((opt_ltp - exit_p) / exit_p * 100, 2) if exit_p and opt_ltp else None
        pnl_exit_val = round(pnl_exit_pts * lot, 2) if pnl_exit_pts is not None else None

        verdict = ""
        if exit_p and opt_ltp > 0:
            if tag == "POST_EXIT_LEARNING":
                if opt_ltp <= exit_p:
                    saved_val = abs(exit_p - opt_ltp) * lot
                    verdict = f"Great Exit! Saved -INR {abs(exit_p - opt_ltp):.2f}/sh (-INR {saved_val:,.0f})"
                else:
                    rec_val = (opt_ltp - exit_p) * lot
                    verdict = f"Rebound: Bounced +INR {opt_ltp - exit_p:.2f}/sh (+INR {rec_val:,.0f}) from exit"
            elif tag == "POST_PROFIT_RUN":
                if opt_ltp < exit_p:
                    verdict = f"Top Profit Booked! Option dipped -INR {exit_p - opt_ltp:.2f}/sh from peak"
                else:
                    verdict = f"Extended Runner: Up another +INR {opt_ltp - exit_p:.2f}/sh beyond exit"
        elif entry_p and opt_ltp > 0:
            verdict = f"Active: {pnl_entry_pct:+.2f}% (P&L: INR {pnl_entry_val:+,.0f})"

        results.append({
            "contract": contract,
            "base_symbol": base,
            "opt_ltp": opt_ltp,
            "opt_chg_pct": opt_chg,
            "opt_high": opt_high,
            "opt_low": opt_low,
            "opt_volume": opt_vol,
            "spot_ltp": spot_ltp,
            "spot_chg_pct": spot_chg,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "lot_size": lot,
            "pnl_entry_pts": pnl_entry_pts,
            "pnl_entry_pct": pnl_entry_pct,
            "pnl_entry_val": pnl_entry_val,
            "pnl_exit_pts": pnl_exit_pts,
            "pnl_exit_pct": pnl_exit_pct,
            "pnl_exit_val": pnl_exit_val,
            "verdict": verdict,
            "tag": tag,
            "note": note,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    try:
        os.makedirs(os.path.dirname(paths.WATCHLIST_LIVE_FILE), exist_ok=True)
        with open(paths.WATCHLIST_LIVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": results}, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save watchlist live file: {e}")

    return results

def print_watchlist_table(data):
    if not data:
        print("\n[WATCHLIST] No items currently in watchlist. Use --add CONTRACT to add.\n")
        return

    print("\n" + "=" * 125)
    print(f" [WATCHLIST] LIVE PRICE ACTION WATCHLIST & POST-TRADE LEARNING MONITOR | {datetime.now().strftime('%H:%M:%S IST')} ")
    print("=" * 125)
    header = f"{ 'Contract':<22} | {'Opt LTP':<10} | {'Opt %':<8} | {'Spot LTP':<10} | {'Spot %':<8} | {'Entry':<7} | {'Exit':<7} | {'Post-Exit Learning / P&L Status':<40}"
    print(header)
    print("-" * 125)

    for item in data:
        c = item['contract']
        o_ltp = f"INR {item['opt_ltp']:.2f}" if item['opt_ltp'] else "-"
        o_chg = f"{item['opt_chg_pct']:+.2f}%"
        s_ltp = f"INR {item['spot_ltp']:.2f}" if item['spot_ltp'] else "-"
        s_chg = f"{item['spot_chg_pct']:+.2f}%"
        ep = f"{item['entry_price']:.2f}" if item['entry_price'] else "-"
        xp = f"{item['exit_price']:.2f}" if item['exit_price'] else "-"
        v = item['verdict'] or item.get('note', '')

        row = f"{c:<22} | {o_ltp:<10} | {o_chg:<8} | {s_ltp:<10} | {s_chg:<8} | {ep:<7} | {xp:<7} | {v:<40}"
        print(row)
    print("=" * 125 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Live Watchlist & Post-Trade Learning System")
    parser.add_argument("--add", type=str, help="Contract name to add (e.g. ABCAPITAL26SEP410CE)")
    parser.add_argument("--base", type=str, help="Base symbol (e.g. ABCAPITAL)")
    parser.add_argument("--entry", type=float, help="Reference entry price")
    parser.add_argument("--exit", type=float, help="Reference exit price")
    parser.add_argument("--lot", type=int, help="Lot size")
    parser.add_argument("--tag", type=str, default="MANUAL_WATCH", help="Tag (e.g. POST_EXIT_LEARNING, POST_PROFIT_RUN, ACTIVE_MONITOR)")
    parser.add_argument("--note", type=str, default="", help="Short custom note")
    parser.add_argument("--remove", type=str, help="Contract name to remove")
    parser.add_argument("--list", action="store_true", help="List all items in watchlist config")
    parser.add_argument("--loop", type=int, nargs="?", const=10, help="Run continuous monitoring loop (seconds interval, default 10)")
    parser.add_argument("--once", action="store_true", help="Fetch once, save snapshot, and print table")

    args = parser.parse_args()

    if args.add:
        add_watchlist_item(args.add, args.base, args.entry, args.exit, args.lot, args.tag, args.note)
        data = fetch_watchlist_live_data()
        print_watchlist_table(data)
    elif args.remove:
        remove_watchlist_item(args.remove)
    elif args.list:
        items = load_watchlist_config()
        print(json.dumps(items, indent=2))
    elif args.loop:
        interval = max(3, args.loop)
        print(f"[INFO] Starting continuous watchlist monitor (refresh every {interval}s). Press Ctrl+C to stop.")
        api_key, access_token = session.load_kite_session()
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        while True:
            try:
                data = fetch_watchlist_live_data(kite)
                print_watchlist_table(data)
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n[INFO] Watchlist monitor stopped by user.")
                break
            except Exception as e:
                print(f"[ERROR] Monitor loop exception: {e}")
                time.sleep(interval)
    else:
        data = fetch_watchlist_live_data()
        print_watchlist_table(data)

if __name__ == '__main__':
    main()
