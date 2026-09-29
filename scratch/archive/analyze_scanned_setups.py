import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import session, paths
from kiteconnect import KiteConnect

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

def fetch_vm_scan_display():
    # Download scan_display.json from Poovendan VM
    vm_ip = "140.245.197.71"
    remote_path = "/home/opc/Price_Action_Strategy/output/monitor/scan_display.json"
    local_target = os.path.join(PROJECT_ROOT, "scratch", "poovendan_scan_display.json")
    try:
        scp_cmd = ["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm_ip}:{remote_path}", local_target]
        ret = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=10)
        if ret.returncode == 0 and os.path.exists(local_target):
            print(f"Successfully downloaded {local_target} from VM ({vm_ip})")
            return local_target
    except Exception as e:
        print(f"Error fetching from VM: {e}")
    return None

def main():
    vm_file = fetch_vm_scan_display()
    
    # Check both local and VM files
    source_file = paths.SCAN_DISPLAY_FILE
    if vm_file and os.path.exists(vm_file):
        # Check which has more trades
        d_local = json.load(open(paths.SCAN_DISPLAY_FILE, encoding="utf-8")) if os.path.exists(paths.SCAN_DISPLAY_FILE) else {}
        d_vm = json.load(open(vm_file, encoding="utf-8"))
        count_local = len(d_local.get("staged_trades", []) + d_local.get("all_staged_today", []))
        count_vm = len(d_vm.get("staged_trades", []) + d_vm.get("all_staged_today", []))
        print(f"Trade counts: Local={count_local}, VM={count_vm}")
        if count_vm >= count_local:
            source_file = vm_file
            print(f"Using VM scan display: {source_file}")
        else:
            print(f"Using Local scan display: {source_file}")
    else:
        print(f"Using Local scan display: {source_file}")

    with open(source_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    staged = (
        data.get("staged_trades", []) +
        data.get("all_staged_today", []) +
        data.get("carry_forward", []) +
        data.get("active_live", [])
    )

    trade_map = {}
    for t in staged:
        sl = float(t.get("current_sl") or t.get("sl") or 0)
        t1 = float(t.get("t1") or 0)
        if sl <= 0 or t1 <= 0:
            continue
        cntr = (t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()
        if cntr and cntr not in trade_map:
            trade_map[cntr] = t

    total_setups = len(trade_map)
    print(f"\n=======================================================")
    print(f" Total Unique Staged Setups Loaded: {total_setups}")
    print(f"=======================================================\n")

    # Connect to Kite to get day's OHLC and live quote
    print("Authenticating with Kite Connect...")
    ak, at = session.load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)

    # Build quote symbols
    quote_keys = []
    for cntr, t in trade_map.items():
        sym = t.get("symbol", "")
        # Is option contract?
        if any(cntr.endswith(s) for s in ["CE", "PE"]):
            if "SENSEX" in cntr:
                quote_keys.append(f"BFO:{cntr}")
            else:
                quote_keys.append(f"NFO:{cntr}")
        else:
            quote_keys.append(f"NSE:{sym}")

    print(f"Fetching quotes for {len(quote_keys)} instruments...")
    quotes = {}
    # Batch in 200s
    for i in range(0, len(quote_keys), 200):
        chunk = quote_keys[i:i+200]
        try:
            q_res = kite.quote(chunk)
            quotes.update(q_res)
        except Exception as e:
            print(f"Quote chunk error: {e}")

    print(f"Received quotes for {len(quotes)} instruments.\n")

    # Analyze each setup
    t1_hit_list = []
    runaway_80_list = [] # Reached 0.8 T1 but not full T1
    sl_hit_list = []
    both_hit_list = []
    active_valid_list = []
    no_quote_list = []

    for cntr, t in trade_map.items():
        sym = t.get("symbol", "")
        side = t.get("side", "")
        entry = float(t.get("benchmark") or t.get("entry_price") or t.get("entry_spot") or 0)
        sl = float(t.get("current_sl") or t.get("sl") or 0)
        t1 = float(t.get("t1") or 0)
        t2 = float(t.get("t2") or 0)
        entry_time = t.get("entry_time", "")
        staged_time = t.get("staged_time", "")
        tier = t.get("tier", 2)
        pattern = t.get("pattern", "")

        q_key = f"NFO:{cntr}" if f"NFO:{cntr}" in quotes else (f"BFO:{cntr}" if f"BFO:{cntr}" in quotes else f"NSE:{sym}")
        q = quotes.get(q_key)
        if not q:
            no_quote_list.append((cntr, sym, entry, sl, t1))
            continue

        ltp = float(q.get("last_price", 0))
        ohlc = q.get("ohlc", {})
        day_high = float(ohlc.get("high", 0)) or ltp
        day_low = float(ohlc.get("low", 0)) or ltp
        day_open = float(ohlc.get("open", 0))
        day_close = float(ohlc.get("close", 0))

        # Calculate 0.8 T1 threshold
        # In Long options, profit increases as price rises
        if entry > 0 and t1 > entry:
            t1_80 = round(entry + 0.80 * (t1 - entry), 2)
        else:
            t1_80 = round(t1 * 0.80, 2)

        is_t1_hit = day_high >= (t1 * 0.995)
        is_08_t1_hit = day_high >= t1_80
        is_sl_hit = (day_low <= sl) if sl > 0 else False
        is_ltp_sl = (ltp <= sl) if sl > 0 else False

        item_res = {
            "symbol": sym,
            "contract": cntr,
            "side": side,
            "pattern": pattern,
            "tier": tier,
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "t1_80": t1_80,
            "ltp": ltp,
            "high": day_high,
            "low": day_low,
            "entry_time": entry_time,
            "staged_time": staged_time
        }

        if is_t1_hit and is_sl_hit:
            both_hit_list.append(item_res)
        elif is_t1_hit:
            t1_hit_list.append(item_res)
        elif is_08_t1_hit:
            runaway_80_list.append(item_res)
        elif is_sl_hit:
            sl_hit_list.append(item_res)
        else:
            active_valid_list.append(item_res)

    print(f"==========================================================================")
    print(f"                       BREAKDOWN OF 95 SCANNED SETUPS                      ")
    print(f"==========================================================================")
    print(f" 🎯 Full T1 Hit (Day High >= T1):             {len(t1_hit_list)}")
    print(f" 🏃 0.8 T1 Reached / Runaway (High >= 0.8T1):   {len(runaway_80_list)}")
    print(f" 🛑 SL Hit Only (Day Low <= SL):              {len(sl_hit_list)}")
    print(f" ⚠️  Both Reached (Touched High & Low):        {len(both_hit_list)}")
    print(f" 🟢 Still Active / In Corridor (Fresh):       {len(active_valid_list)}")
    print(f" ❓ Missing Quote:                            {len(no_quote_list)}")
    print(f" Total Analyzed:                              {len(trade_map)}")
    print(f"==========================================================================\n")

    # Dump details to JSON for comprehensive inspection
    summary_report = {
        "timestamp": datetime.now().isoformat(),
        "total": len(trade_map),
        "counts": {
            "t1_hit": len(t1_hit_list),
            "runaway_08_t1": len(runaway_80_list),
            "sl_hit": len(sl_hit_list),
            "both_hit": len(both_hit_list),
            "active_valid": len(active_valid_list),
            "no_quote": len(no_quote_list)
        },
        "t1_hit": t1_hit_list,
        "runaway_08_t1": runaway_80_list,
        "sl_hit": sl_hit_list,
        "both_hit": both_hit_list,
        "active_valid": active_valid_list
    }

    out_json = os.path.join(PROJECT_ROOT, "scratch", "scanned_setups_analysis.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2)
    print(f"Full analysis saved to {out_json}")

if __name__ == "__main__":
    main()
