#!/usr/bin/env python3
"""
tools/forensic_auditor.py — Reusable Multi-Target Forensic & Execution Audit Utility.

Single source of truth utility for auditing orders, executions, margins, and trades across
Local Kite broker session, local SQLite database, and remote Cloud VMs (VM1 & VM2).

Replaces repetitive one-off scripts like:
  - audit_motherson_sbilife_colpal.py
  - inspect_broker_and_state.py
  - inspect_order_guids.py
  - inspect_live_margins.py
  - cleanup_ghost_positions.py
  - query_*_vm*.py

Features:
  --symbol SYM          Audit specific symbol(s) (e.g. MOTHERSON, "SBILIFE,COLPAL") across local & VMs
  --contract CNT        Audit specific option contract (e.g. MOTHERSON26OCT165CE)
  --remote              Query remote VMs (VM1 Poovendan & VM2 Bhavani) in addition to local
  --today               Audit all broker orders and positions placed today
  --margins             Show live broker margins, liquid cash, and utilization headroom
  --clean-ghosts        Reconcile broker net positions against state file & SQLite, purging ghosts
  --deep                Run 8-dimensional forensic price action analysis (if symbol specified)

Usage Examples:
  python tools/forensic_auditor.py --symbol MOTHERSON --remote
  python tools/forensic_auditor.py --symbol "SBILIFE,COLPAL" --remote
  python tools/forensic_auditor.py --contract MOTHERSON26OCT165CE
  python tools/forensic_auditor.py --today
  python tools/forensic_auditor.py --margins
  python tools/forensic_auditor.py --clean-ghosts
"""

import os
import sys
import argparse
import json
import sqlite3
import subprocess
from datetime import datetime as dt

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
for p in [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "common")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from paths import TOKEN_FILE, monitor_file
from session import load_kite_session, ensure_kite_session
from kiteconnect import KiteConnect

DEFAULT_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VM_TARGETS = [
    {
        "id": 1,
        "name": "Poovendan VM1",
        "ip": "140.245.197.71",
        "user": "opc",
        "repo_dir": "/home/opc/Price_Action_Strategy",
        "py_cmd": "/home/opc/Price_Action_Strategy/venv/bin/python",
        "db_path": "/home/opc/Price_Action_Strategy/output/monitor/trades.sqlite3",
        "state_path": "/home/opc/Price_Action_Strategy/output/monitor/stock_positions_state.json"
    },
    {
        "id": 2,
        "name": "Bhavani VM2",
        "ip": "129.225.69.131",
        "user": "opc",
        "repo_dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "py_cmd": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python",
        "db_path": "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3",
        "state_path": "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/stock_positions_state.json"
    }
]


class ForensicAuditor:
    def __init__(self, key_path=None):
        self.key_path = key_path or DEFAULT_KEY
        self.kite = None
        self._init_kite()
        self.local_db = monitor_file("trades.sqlite3")
        self.local_state = monitor_file("stock_positions_state.json")

    def _init_kite(self):
        try:
            ak, at = load_kite_session(TOKEN_FILE)
            self.kite = KiteConnect(api_key=ak)
            self.kite.set_access_token(at)
            ensure_kite_session(self.kite)
        except Exception as e:
            print(f"[WARN] Local KiteConnect session unavailable: {e}")
            self.kite = None

    def _run_ssh(self, vm, command, timeout=25):
        cmd = [
            "ssh", "-i", self.key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{vm['user']}@{vm['ip']}",
            command
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()
        except Exception as e:
            return -1, "", str(e)

    def audit_today_orders(self):
        """Fetch and audit all broker orders placed today."""
        if not self.kite:
            print("❌ Cannot audit broker orders: Kite session not connected.")
            return

        print("\n" + "=" * 80)
        print("📑 TODAY'S BROKER ORDERBOOK & EXECUTION AUDIT")
        print("=" * 80)

        orders = self.kite.orders()
        today_str = dt.now().strftime("%Y-%m-%d")
        today_orders = [o for o in orders if str(o.get("order_timestamp", "")).startswith(today_str)]

        if not today_orders:
            print(f"No orders found for today ({today_str}). Total historical orders in book: {len(orders)}")
            return

        complete = [o for o in today_orders if o.get("status") == "COMPLETE"]
        rejected = [o for o in today_orders if o.get("status") == "REJECTED"]
        cancelled = [o for o in today_orders if o.get("status") == "CANCELLED"]
        open_orders = [o for o in today_orders if o.get("status") in ("OPEN", "TRIGGER PENDING")]

        print(f"\nOrder Summary: Total: {len(today_orders)} | ✅ Complete: {len(complete)} | ❌ Rejected: {len(rejected)} | 🚫 Cancelled: {len(cancelled)} | ⏳ Open: {len(open_orders)}")

        print("\n" + "-" * 80)
        print(f"{'Order ID':<16} {'Symbol':<22} {'Side':<5} {'Qty':<5} {'Price':<8} {'Status':<10} {'Origin / Tag':<25}")
        print("-" * 80)

        for o in today_orders:
            oid = str(o.get("order_id", ""))
            sym = str(o.get("tradingsymbol", ""))
            side = str(o.get("transaction_type", ""))
            qty = str(o.get("quantity", ""))
            px = f"{float(o.get('average_price') or o.get('price') or 0):.2f}"
            st = str(o.get("status", ""))
            tag = o.get("tag") or ""
            guid = o.get("guid") or ""

            if tag:
                origin = f"BOT ({tag})"
            elif guid:
                origin = f"MANUAL ({guid[:8]}..)"
            else:
                origin = "UNKNOWN"

            st_icon = "✅" if st == "COMPLETE" else ("❌" if st == "REJECTED" else "⏳")
            print(f"{oid:<16} {sym:<22} {side:<5} {qty:<5} {px:<8} {st_icon} {st:<8} {origin:<25}")
            if st == "REJECTED" and o.get("status_message"):
                print(f"   ↳ ⚠️ Reason: {o.get('status_message')}")

        # Net positions and P&L
        pos = self.kite.positions().get("net", [])
        active_pos = [p for p in pos if p.get("quantity", 0) != 0]
        closed_pos = [p for p in pos if p.get("quantity", 0) == 0]

        print("\n" + "=" * 80)
        print(f"💼 BROKER NET POSITIONS (Active: {len(active_pos)} | Closed Today: {len(closed_pos)})")
        print("=" * 80)

        total_realized = sum(float(p.get("pnl", 0)) for p in pos)
        total_m2m = sum(float(p.get("m2m", 0)) for p in pos)

        for p in pos:
            sym = p.get("tradingsymbol")
            q = p.get("quantity")
            buy_val = float(p.get("buy_value", 0))
            sell_val = float(p.get("sell_value", 0))
            pnl = float(p.get("pnl", 0))
            m2m = float(p.get("m2m", 0))
            ltp = float(p.get("last_price", 0))
            stat_icon = "🟢 ACTIVE" if q != 0 else "⚪ CLOSED"
            print(f"  • {sym:<22} | Qty: {q:<5} | LTP: ₹{ltp:<7.2f} | PnL: ₹{pnl:<9.2f} | M2M: ₹{m2m:<9.2f} | [{stat_icon}]")

        print("-" * 80)
        print(f"  TOTAL REALIZED P&L: ₹{total_realized:+.2f} | TOTAL M2M: ₹{total_m2m:+.2f}")
        print("=" * 80 + "\n")

    def audit_margins(self):
        """Audit live margins, liquid cash, collateral, and utilization."""
        if not self.kite:
            print("❌ Cannot audit margins: Kite session not connected.")
            return

        print("\n" + "=" * 80)
        print("💰 LIVE BROKER MARGINS & CAPITAL AUDIT")
        print("=" * 80)

        margins = self.kite.margins()
        eq = margins.get("equity", {})
        enabled = eq.get("enabled", False)
        net = float(eq.get("net", 0))
        avail = eq.get("available", {})
        live_bal = float(avail.get("live_balance", 0))
        cash = float(avail.get("cash", 0))
        collateral = float(avail.get("collateral", 0))
        util = eq.get("utilised", {})
        debits = float(util.get("debits", 0))
        span = float(util.get("span", 0))
        exposure = float(util.get("exposure", 0))
        opt_premium = float(util.get("option_premium", 0))

        # Net liquid cash calculation (matching portfolio_risk.py)
        net_liquid_cash = min(cash, max(0.0, live_bal - collateral))

        print(f"  • Equity Segment Enabled : {enabled}")
        print(f"  • Net Account Value (NAV): ₹{net:,.2f}")
        print(f"  • Cash Available         : ₹{cash:,.2f}")
        print(f"  • Collateral (Pledged)   : ₹{collateral:,.2f}")
        print(f"  • Live Balance           : ₹{live_bal:,.2f}")
        print(f"  • Liquid Cash (Unpledged): ₹{net_liquid_cash:,.2f}")
        print(f"  • Total Utilized Margin  : ₹{debits:,.2f}")
        print(f"    - Option Premium Bought: ₹{opt_premium:,.2f}")
        print(f"    - SPAN + Exposure      : ₹{(span + exposure):,.2f}")

        util_pct = (debits / (cash + collateral) * 100) if (cash + collateral) > 0 else 0
        print(f"  • Margin Utilization Rate: {util_pct:.1f}%")
        print("=" * 80 + "\n")

    def audit_symbol(self, symbols, check_remote=False):
        """Audit specific symbols or contracts across local Kite, local DB, and Cloud VMs."""
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

        for sym in sym_list:
            print("\n" + "=" * 85)
            print(f"🔍 FORENSIC AUDIT FOR SYMBOL / CONTRACT: {sym}")
            print("=" * 85)

            # 1. Local Broker Orders
            if self.kite:
                try:
                    orders = self.kite.orders()
                    matched_orders = [o for o in orders if sym in str(o.get("tradingsymbol", "")).upper()]
                    print(f"\n[1. LOCAL KITE ORDERS (Matched: {len(matched_orders)})]")
                    if matched_orders:
                        for o in matched_orders:
                            oid = o.get("order_id")
                            ts = o.get("tradingsymbol")
                            side = o.get("transaction_type")
                            qty = o.get("quantity")
                            px = o.get("price") or o.get("average_price")
                            st = o.get("status")
                            tag = o.get("tag")
                            guid = o.get("guid")
                            t_stamp = o.get("order_timestamp")
                            reason = o.get("status_message") or ""
                            print(f"  • Order #{oid} | {ts} | {side} {qty} @ ₹{px} | Status: {st} | Time: {t_stamp}")
                            print(f"    Tag: {tag} | GUID: {guid} | Message: {reason}")
                    else:
                        print(f"  (No Kite orders found matching '{sym}')")
                except Exception as e:
                    print(f"  Error fetching local Kite orders: {e}")

            # 2. Local SQLite DB
            if os.path.exists(self.local_db):
                print(f"\n[2. LOCAL SQLITE DB ({self.local_db})]")
                try:
                    conn = sqlite3.connect(self.local_db)
                    c = conn.cursor()
                    c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE ? OR contract LIKE ? ORDER BY id DESC LIMIT 5", (f"%{sym}%", f"%{sym}%"))
                    rows = c.fetchall()
                    if rows:
                        for r in rows:
                            tid, s, cnt, stat, cat, uat, dj_str = r
                            print(f"  • Trade #{tid} | {s} -> {cnt} | Status: {stat} | Created: {cat} | Updated: {uat}")
                            try:
                                dj = json.loads(dj_str) if dj_str else {}
                                print(f"    Pattern: {dj.get('pattern')} ({dj.get('timeframe')}) | Side: {dj.get('side')} | Tier: {dj.get('tier_label')}")
                                print(f"    Entry: ₹{dj.get('entry_price')} (Spot: {dj.get('entry_spot')}) | SL: ₹{dj.get('current_sl')} (Spot SL: {dj.get('spot_sl')})")
                                print(f"    Exit: ₹{dj.get('exit_price')} | Reason: {dj.get('exit_reason')} | PnL: ₹{dj.get('pnl')}")
                                print(f"    MFE: {dj.get('mfe_pct')}% | MAE: {dj.get('mae_pct')}% | Order ID: {dj.get('order_id')}")
                            except Exception:
                                pass
                    else:
                        print(f"  (No local SQLite records found for '{sym}')")
                    conn.close()
                except Exception as e:
                    print(f"  Error querying local DB: {e}")

            # 3. Local State File
            if os.path.exists(self.local_state):
                try:
                    st = json.load(open(self.local_state))
                    matched_state = {k: v for k, v in st.items() if sym in k or sym in str(v.get("contract", "")).upper()}
                    print(f"\n[3. LOCAL STATE FILE (Active: {len(matched_state)})]")
                    for k, v in matched_state.items():
                        print(f"  • {k} -> {v.get('contract')}: status={v.get('status')}, qty={v.get('quantity')}, entry={v.get('entry_price')}, sl={v.get('current_sl')}")
                except Exception as e:
                    print(f"  Error reading local state: {e}")

            # 4. Remote Cloud VMs (VM1 & VM2)
            if check_remote:
                for vm in VM_TARGETS:
                    print(f"\n[4. REMOTE: {vm['name']} ({vm['ip']})]")
                    remote_py = f"""
import sqlite3, json, os
db = '{vm['db_path']}'
st_f = '{vm['state_path']}'
if os.path.exists(db):
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute("SELECT id, symbol, contract, status, created_at, data_json FROM trades WHERE symbol LIKE '%{sym}%' OR contract LIKE '%{sym}%' ORDER BY id DESC LIMIT 5")
        rows = c.fetchall()
        print(f"  • SQLite Trades found: {{len(rows)}}")
        for r in rows:
            print(f"    - ID={{r[0]}} | {{r[1]}} -> {{r[2]}} | Status: {{r[3]}} | Created: {{r[4]}}")
            try:
                dj = json.loads(r[5])
                print(f"      Entry: Rs. {{dj.get('entry_price')}} | SL: Rs. {{dj.get('current_sl')}} | Exit: Rs. {{dj.get('exit_price')}} | Reason: {{dj.get('exit_reason')}} | PnL: Rs. {{dj.get('pnl')}}")
            except:
                pass
        conn.close()
    except Exception as e:
        print(f"  • DB Error: {{e}}")
else:
    print("  • DB file not found")

if os.path.exists(st_f):
    try:
        st = json.load(open(st_f))
        m = {{k: v for k, v in st.items() if '{sym}' in k or '{sym}' in str(v.get('contract', '')).upper()}}
        print(f"  • State file matching entries: {{len(m)}}")
        for k, v in m.items():
            print(f"    - {{k}} -> {{v.get('contract')}}: qty={{v.get('quantity')}}, status={{v.get('status')}}")
    except Exception as e:
        print(f"  • State Error: {{e}}")
"""
                    ssh_cmd = [
                        "ssh", "-i", self.key_path,
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=10",
                        f"{vm['user']}@{vm['ip']}",
                        f"{vm['py_cmd']} -"
                    ]
                    try:
                        res = subprocess.run(
                            ssh_cmd,
                            input=f"# -*- coding: utf-8 -*-\n{remote_py}".encode("utf-8"),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=25
                        )
                        out = (res.stdout.decode("utf-8", errors="replace") or "").strip()
                        err = (res.stderr.decode("utf-8", errors="replace") or "").strip()
                        if out:
                            print(out)
                        else:
                            print(f"  (Remote query returned empty or error: {err})")
                    except Exception as e:
                        print(f"  Remote query failed: {e}")

    def clean_ghosts(self):
        """Reconcile broker live positions against stock_positions_state.json and trades.sqlite3."""
        if not self.kite:
            print("❌ Cannot clean ghosts: Kite session not connected.")
            return

        print("\n" + "=" * 80)
        print("🧹 LOCAL GHOST POSITION RECONCILIATION & PURGE")
        print("=" * 80)

        # 1. Fetch live net positions from broker
        broker_net = self.kite.positions().get("net", [])
        held_positions = {p.get("tradingsymbol"): p.get("quantity") for p in broker_net if p.get("quantity", 0) != 0}
        print(f"Live broker held positions (qty != 0): {held_positions}")

        # 2. Clean state file
        state = {}
        if os.path.exists(self.local_state):
            try:
                with open(self.local_state, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception as e:
                print(f"Error loading state: {e}")

        cleaned_state = {}
        purged = []
        for sym, data in state.items():
            cnt = data.get("contract", "")
            if cnt in held_positions:
                data["quantity"] = held_positions[cnt]
                cleaned_state[sym] = data
                print(f"  ✅ KEEPING ACTIVE: {sym} -> {cnt} (qty={held_positions[cnt]})")
            else:
                purged.append((sym, cnt))
                print(f"  🗑️ PURGING GHOST: {sym} -> {cnt} (not held on broker)")

        with open(self.local_state, "w", encoding="utf-8") as f:
            json.dump(cleaned_state, f, indent=2)
        print(f"\nUpdated {self.local_state}: {len(cleaned_state)} active positions remaining ({len(purged)} purged).")

        # 3. Clean SQLite
        if os.path.exists(self.local_db):
            conn = sqlite3.connect(self.local_db)
            c = conn.cursor()
            c.execute("SELECT id, symbol, contract, status, data_json FROM trades WHERE status IN ('ACTIVE', 'OPEN')")
            active_trades = c.fetchall()
            updated = 0
            for r in active_trades:
                tid, s, cnt, stat, dj_str = r
                if cnt not in held_positions:
                    print(f"  Fixing SQLite trade ID={tid} ({s} / {cnt}): status '{stat}' -> 'FAILED'")
                    try:
                        dj = json.loads(dj_str) if dj_str else {}
                    except Exception:
                        dj = {}
                    dj["status"] = "FAILED"
                    dj["exit_reason"] = "BROKER_REJECTED_OR_PURGED_GHOST"
                    dj["pnl"] = 0.0
                    c.execute("UPDATE trades SET status='FAILED', data_json=? WHERE id=?", (json.dumps(dj), tid))
                    updated += 1
                else:
                    print(f"  Trade ID={tid} ({s} / {cnt}) is verified held on broker.")
            conn.commit()
            conn.close()
            print(f"SQLite update complete: {updated} ghost trades marked as FAILED.\n")


def main():
    parser = argparse.ArgumentParser(description="Multi-Target Forensic Trade & Execution Audit Utility")
    parser.add_argument("--symbol", type=str, help="Symbol or comma-separated symbols to audit (e.g. MOTHERSON, 'SBILIFE,COLPAL')")
    parser.add_argument("--contract", type=str, help="Option contract to audit (e.g. MOTHERSON26OCT165CE)")
    parser.add_argument("--remote", action="store_true", help="Query remote VMs (VM1 & VM2) in addition to local")
    parser.add_argument("--today", action="store_true", help="Audit all broker orders and positions placed today")
    parser.add_argument("--margins", action="store_true", help="Show live broker margins, liquid cash, and utilization")
    parser.add_argument("--clean-ghosts", action="store_true", help="Reconcile and purge ghost positions locally")
    parser.add_argument("--deep", action="store_true", help="Run 8-dimensional forensic price action analysis")

    args = parser.parse_args()
    auditor = ForensicAuditor()

    if args.today:
        auditor.audit_today_orders()
    elif args.margins:
        auditor.audit_margins()
    elif args.clean_ghosts:
        auditor.clean_ghosts()
    elif args.symbol or args.contract:
        target = args.contract or args.symbol
        auditor.audit_symbol(target, check_remote=args.remote)
        if args.deep:
            try:
                from common.forensic_trade_analyzer import ForensicTradeAnalyzer
                fta = ForensicTradeAnalyzer(kite=auditor.kite)
                res = fta.analyze_symbol(target)
                fta.print_diagnostic_report(res)
            except Exception as e:
                print(f"[WARN] Deep forensic analysis failed: {e}")
    else:
        # Default action: audit today
        auditor.audit_today_orders()


if __name__ == "__main__":
    main()
