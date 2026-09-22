#!/usr/bin/env python3
"""
scratch/push_scans_to_vm.py — 1-Click Scan & Radar VM Sync Utility

Transfers local scan displays, radar incubation states, and watchlists from local machine
to Oracle Cloud VMs (Bhavani and Poovendan) via SCP in 1 network roundtrip without
restarting services.

Fast Radar loops on the VMs continuously poll pattern_funnel.json,
scan_display.json, and watchlist files every 15 seconds, so updated setups are picked up immediately.

SECURITY INVARIANT:
- Strictly excludes any token files (kite_access_token.txt) so accounts remain 100% isolated.
- Localhost (Poovendan) token will NEVER overwrite Bhavani VM's credentials.

Usage:
    python scratch/push_scans_to_vm.py [all|bhavani|bhavni|poovendan] [--target all|bhavani|bhavni|poovendan] [--key KEY_PATH]
"""

import os
import sys
import subprocess
import argparse
import tarfile
import time
import json
from datetime import datetime, timezone, timedelta

# Windows console encoding and ANSI color setup
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if os.name == "nt":
    os.system("")  # Enable VT100 escape codes

# Ensure project root is in sys.path for canonical common.paths import
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from common.paths import PROJECT_ROOT, MONITOR_DIR, SCRATCH_DIR, EXPORTS_DIR
except ImportError:
    MONITOR_DIR = os.path.join(PROJECT_ROOT, "output", "monitor")
    SCRATCH_DIR = os.path.join(PROJECT_ROOT, "scratch")
    EXPORTS_DIR = os.path.join(PROJECT_ROOT, "output", "exports")

DEFAULT_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

# Indian Standard Time (UTC+5:30) for consistent cross-VM timestamp normalization
IST = timezone(timedelta(hours=5, minutes=30))

SERVERS = {
    "bhavni": {
        "name": "Bhavani Oracle Cloud VM",
        "host": "opc@129.225.69.131",
        "public_ip": "129.225.69.131",
        "remote_dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
    },
    "bhavani": {
        "name": "Bhavani Oracle Cloud VM",
        "host": "opc@129.225.69.131",
        "public_ip": "129.225.69.131",
        "remote_dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
    },
    "poovendan": {
        "name": "Poovendan Oracle Cloud VM",
        "host": "opc@140.245.197.71",
        "public_ip": "140.245.197.71",
        "remote_dir": "/home/opc/Price_Action_Strategy",
    },
}

# ANSI colors
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_RED = "\033[91m"
CLR_GRAY = "\033[90m"
CLR_MAGENTA = "\033[95m"


def format_size(num_bytes):
    """Format bytes to human readable string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


def get_local_scan_files(project_root):
    """
    Identifies scan, radar, and watchlist files to sync.
    Returns relative paths from project_root (e.g. output/monitor/scan_display.json).

    Includes:
      - output/monitor/pattern_funnel.json
      - output/monitor/scan_display*.json
      - output/monitor/watchlist_live.json
      - input/watchlist.json (morning scanned symbols)
      - output/exports/ today's CSV files (if any)

    STRICT SECURITY INVARIANT:
      - Explicitly blocks and ignores any token files (kite_access_token.txt),
        sqlite databases, and lock files.
    """
    rel_files = []
    monitor_dir = os.path.join(project_root, "output", "monitor")

    if os.path.exists(monitor_dir):
        priority_order = [
            "pattern_funnel.json",
            "scan_display.json",
            "scan_display_stock.json",
            "scan_display_stock_bear.json",
            "scan_display_index.json",
            "scan_display_ema.json",
            "scan_display_trap_adx.json",
            "scan_display_ema_stock.json",
            "scan_display_stock_weekly.json",
            "scan_display_stock_weekly_bear.json",
            "watchlist_live.json",
        ]

        for fn in priority_order:
            p = os.path.join(monitor_dir, fn)
            if os.path.isfile(p):
                rel_p = os.path.join("output", "monitor", fn)
                rel_files.append(rel_p)

        # Detect any additional scan_display*.json not already included
        for fn in sorted(os.listdir(monitor_dir)):
            if fn.startswith("scan_display") and fn.endswith(".json"):
                rel_p = os.path.join("output", "monitor", fn)
                if rel_p not in rel_files:
                    p = os.path.join(monitor_dir, fn)
                    if os.path.isfile(p):
                        rel_files.append(rel_p)

    # Include input/watchlist.json if present
    watchlist_path = os.path.join(project_root, "input", "watchlist.json")
    if os.path.isfile(watchlist_path):
        rel_files.append(os.path.join("input", "watchlist.json"))

    # Include today's automated exports if present
    exports_dir = os.path.join(project_root, "output", "exports")
    if os.path.exists(exports_dir):
        today_str = datetime.now(tz=IST).strftime("%Y%m%d")
        for fn in os.listdir(exports_dir):
            if fn.endswith((".csv", ".xlsx")) and today_str in fn:
                rel_files.append(os.path.join("output", "exports", fn))

    # FINAL SECURITY FILTER: Never allow any token or sqlite files
    safe_files = []
    for rf in rel_files:
        low = rf.lower()
        if "token" in low or low.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".lock")):
            continue
        safe_files.append(rf)

    return safe_files


def inspect_file_details(project_root, rel_fn):
    """Inspect file content to provide high-value trading details."""
    p = os.path.join(project_root, rel_fn)
    fn = os.path.basename(rel_fn)

    if fn == "pattern_funnel.json":
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            counts = []
            if isinstance(data, dict):
                for eng, edata in data.items():
                    if isinstance(edata, dict):
                        a_plus = len(edata.get("category_a_plus", []))
                        a = len(edata.get("category_a", []))
                        b = len(edata.get("category_b", []))
                        if a_plus or a or b:
                            counts.append(f"{eng} [A+:{a_plus} A:{a} B:{b}]")
            return " | ".join(counts) if counts else "Empty funnel"
        except Exception:
            return ""
    elif fn.startswith("scan_display") and fn.endswith(".json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            staged = len(data.get("staged_trades", []))
            ts = data.get("timestamp", "")
            if staged > 0:
                return f"Staged Setups: {staged} (at {ts})" if ts else f"Staged Setups: {staged}"
            elif ts:
                return f"Updated: {ts}"
            return ""
        except Exception:
            return ""
    elif fn == "watchlist.json":
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return f"{len(data)} Watchlist Symbols"
            elif isinstance(data, dict):
                syms = len(data.get("symbols", data.get("watchlist", [])))
                return f"{syms} Watchlist Symbols"
            return ""
        except Exception:
            return ""
    return ""


def create_payload_archive(project_root, rel_files_to_sync, archive_path):
    """Packages the scan and watchlist files into a compact gzip tar archive."""
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for rel_p in rel_files_to_sync:
            # Enforce hard security invariant: No tokens
            if "token" in rel_p.lower():
                raise ValueError(f"SECURITY INVARIANT VIOLATION: Token file {rel_p} cannot be included in scan payload!")
            full_path = os.path.join(project_root, rel_p)
            # Store in tar with posix forward slashes
            arcname = rel_p.replace("\\", "/")
            tar.add(full_path, arcname=arcname)
    return os.path.getsize(archive_path)


def sync_to_server(target_key, srv, key_path, payload_path, rel_files_to_sync, local_stats):
    """
    Syncs the payload tar to a single Oracle Cloud VM via SCP and extracts it into the VM repo.
    Verifies remote files via SSH stat and returns True if successful.
    """
    print(f"\n{CLR_BOLD}{CLR_CYAN}{'=' * 75}{CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_CYAN} SYNCING TO: {srv['name']} ({srv['public_ip']}){CLR_RESET}")
    print(f"{CLR_GRAY} Remote Host: {srv['host']} | Directory: {srv['remote_dir']}{CLR_RESET}")
    print(f"{CLR_CYAN}{'=' * 75}{CLR_RESET}")

    remote_archive = f"{srv['remote_dir']}/.scans_sync_payload.tar.gz"

    # Step 1: Upload payload archive via SCP directly to project root
    print(f"\n{CLR_BOLD}[1/3] Uploading compressed scan payload ({format_size(os.path.getsize(payload_path))})...{CLR_RESET}")
    scp_cmd = [
        "scp", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        payload_path,
        f"{srv['host']}:{remote_archive}"
    ]
    t0 = time.time()
    res_scp = subprocess.run(scp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    upload_time = time.time() - t0
    if res_scp.returncode != 0:
        print(f" {CLR_RED}[ERROR] SCP upload failed ({res_scp.returncode}):{CLR_RESET}")
        print(f" {CLR_RED}{res_scp.stderr.strip()}{CLR_RESET}")
        return False
    print(f" {CLR_GREEN}-> Upload completed in {upload_time:.2f}s.{CLR_RESET}")

    # Step 2: Extract archive into remote project root and remove temporary archive
    print(f"\n{CLR_BOLD}[2/3] Extracting files into remote directory...{CLR_RESET}")
    extract_cmd = (
        f"mkdir -p {srv['remote_dir']}/output/monitor {srv['remote_dir']}/input {srv['remote_dir']}/output/exports && "
        f"tar -xzf {remote_archive} -C {srv['remote_dir']} && "
        f"rm -f {remote_archive}"
    )
    res_ext = subprocess.run(
        ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", srv["host"], extract_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if res_ext.returncode != 0:
        print(f" {CLR_RED}[ERROR] Extraction failed:{CLR_RESET}\n{res_ext.stderr.strip()}")
        return False
    print(f" {CLR_GREEN}-> Files extracted successfully in place without restarting services.{CLR_RESET}")

    # Step 3: Remote verification via SSH (query filename, size, and epoch seconds %Y)
    print(f"\n{CLR_BOLD}[3/3] Verifying synced files on remote VM...{CLR_RESET}")
    posix_files = [f.replace("\\", "/") for f in rel_files_to_sync]
    quoted_files = " ".join(f"'{f}'" for f in posix_files)
    verify_cmd = f"cd {srv['remote_dir']} && stat -c '%n|%s|%Y' {quoted_files}"
    res_ver = subprocess.run(
        ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", srv["host"], verify_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )

    remote_file_map = {}
    if res_ver.stdout:
        for line in res_ver.stdout.strip().splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 3:
                r_rel = parts[0].strip().lstrip("./")
                try:
                    r_size = int(parts[1].strip())
                    epoch_sec = int(parts[2].strip())
                    rem_dt = datetime.fromtimestamp(epoch_sec, tz=IST)
                    rem_time = rem_dt.strftime("%Y-%m-%d %H:%M:%S")
                    remote_file_map[r_rel] = {"size": r_size, "time": rem_time}
                except ValueError:
                    continue

    # Print verification table
    print(f"\n  {CLR_BOLD}{'Relative Path':<36} {'Local Size':>11} {'Remote Size':>12} {'Remote Modified (IST)':>22}  {'Status':>6}{CLR_RESET}")
    print(f"  {'-' * 36} {'-' * 11} {'-' * 12} {'-' * 22}  {'-' * 6}")
    all_matched = True
    for fn, posix_fn in zip(rel_files_to_sync, posix_files):
        loc_sz = local_stats[fn]["size"]
        loc_sz_str = format_size(loc_sz)
        rem_info = remote_file_map.get(posix_fn)
        if rem_info:
            rem_sz = rem_info["size"]
            rem_sz_str = format_size(rem_sz)
            rem_time = rem_info["time"]
            match = (loc_sz == rem_sz)
            if not match:
                all_matched = False
            status_str = f"{CLR_GREEN}OK{CLR_RESET}" if match else f"{CLR_YELLOW}DIFF{CLR_RESET}"
            print(f"  {posix_fn:<36} {loc_sz_str:>11} {rem_sz_str:>12} {rem_time:>22}  [{status_str}]")
        else:
            all_matched = False
            print(f"  {posix_fn:<36} {loc_sz_str:>11} {'MISSING':>12} {'-':>22}  [{CLR_RED}FAIL{CLR_RESET}]")

    # Check background service status (informational)
    svc_check_cmd = "systemctl is-active trading-options trading-stock"
    res_svc = subprocess.run(
        ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", srv["host"], svc_check_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    svc_status = res_svc.stdout.strip().replace("\n", ", ") if res_svc.returncode == 0 else "unknown"

    print(f"\n  {CLR_GRAY}Active Surveillance Daemons: {svc_status} (polling funnel every 15s){CLR_RESET}")
    if all_matched:
        print(f"  {CLR_GREEN}{CLR_BOLD}[SUCCESS] Synced {len(rel_files_to_sync)} scan/radar files to {srv['name']}!{CLR_RESET}")
    else:
        print(f"  {CLR_RED}{CLR_BOLD}[WARNING] One or more files failed verification on {srv['name']}!{CLR_RESET}")
    return all_matched


def main():
    parser = argparse.ArgumentParser(
        description="Price Action Strategy — Fast 1-Click Scan & Radar VM Sync"
    )
    parser.add_argument(
        "target_pos",
        nargs="?",
        choices=["bhavani", "bhavni", "poovendan", "all"],
        default=None,
        help="Target VM: bhavani (or bhavni), poovendan, or all (default: all)",
    )
    parser.add_argument(
        "--target",
        choices=["bhavani", "bhavni", "poovendan", "all"],
        default=None,
        help="Target VM: bhavani (or bhavni), poovendan, or all (default: all)",
    )
    parser.add_argument(
        "--key",
        default=DEFAULT_KEY,
        help="Path to SSH private key (default: G:\\Poovendan\\AI\\Trading\\Cloud\\Oracle_Cloud\\ssh-key-2026-08-05.key)",
    )

    args = parser.parse_args()
    raw_target = args.target or args.target_pos or "all"
    target = "bhavni" if raw_target.lower() in ["bhavni", "bhavani"] else raw_target.lower()
    key_path = os.path.abspath(args.key)

    print(f"{CLR_BOLD}{CLR_GREEN}{'=' * 75}{CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_GREEN}     PRICE ACTION STRATEGY — 1-CLICK SCAN & RADAR VM SYNC{CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_GREEN}{'=' * 75}{CLR_RESET}")
    print(f"{CLR_GRAY}  Target VMs:        {target.upper()}{CLR_RESET}")
    print(f"{CLR_GRAY}  Token Protection:  STRICT (Zero account tokens transferred){CLR_RESET}")

    # Validate SSH Key
    if not os.path.exists(key_path):
        print(f"\n{CLR_RED}[ERROR] SSH key not found at:{CLR_RESET} {key_path}")
        sys.exit(1)

    # Discover local scan and watchlist files
    files_to_sync = get_local_scan_files(PROJECT_ROOT)
    if not files_to_sync:
        print(f"\n{CLR_YELLOW}[WARNING] No scan, radar, or watchlist files found to sync.{CLR_RESET}")
        sys.exit(1)

    print(f"\n{CLR_BOLD}[LOCAL] Discovered {len(files_to_sync)} files to sync:{CLR_RESET}")
    local_stats = {}
    total_local_bytes = 0
    for fn in files_to_sync:
        fp = os.path.join(PROJECT_ROOT, fn)
        st = os.stat(fp)
        sz = st.st_size
        total_local_bytes += sz
        mtime_str = datetime.fromtimestamp(st.st_mtime, tz=IST).strftime("%Y-%m-%d %H:%M:%S")
        local_stats[fn] = {"size": sz, "mtime": mtime_str}
        details = inspect_file_details(PROJECT_ROOT, fn)
        detail_suffix = f" {CLR_GRAY}({details}){CLR_RESET}" if details else ""
        posix_name = fn.replace("\\", "/")
        print(f"  • {CLR_CYAN}{posix_name:<36}{CLR_RESET} {format_size(sz):>8}  {CLR_GRAY}[{mtime_str}]{CLR_RESET}{detail_suffix}")

    print(f"\n  Total Uncompressed: {CLR_BOLD}{format_size(total_local_bytes)}{CLR_RESET}")

    # Package into scratch archive
    payload_path = os.path.join(SCRATCH_DIR, "scans_sync_payload.tar.gz")
    try:
        archive_size = create_payload_archive(PROJECT_ROOT, files_to_sync, payload_path)
        print(f"  Compressed Payload: {CLR_BOLD}{format_size(archive_size)}{CLR_RESET} (Saved {100 - (archive_size / total_local_bytes * 100):.1f}%)")

        selected_targets = ["bhavni", "poovendan"] if target == "all" else [target]
        success_count = 0

        for t in selected_targets:
            srv = SERVERS[t]
            ok = sync_to_server(t, srv, key_path, payload_path, files_to_sync, local_stats)
            if ok:
                success_count += 1

    finally:
        # Clean up local temporary tar payload
        if os.path.exists(payload_path):
            try:
                os.remove(payload_path)
            except Exception:
                pass

    print(f"\n{CLR_BOLD}{CLR_CYAN}{'=' * 75}{CLR_RESET}")
    if success_count == len(selected_targets):
        print(f"{CLR_BOLD}{CLR_GREEN} ALL SYNCS COMPLETED SUCCESSFULLY ({success_count}/{len(selected_targets)} VMs synced)!{CLR_RESET}")
        print(f"{CLR_GRAY} The running Fast Surveillance Radars on both VMs are now live-monitoring{CLR_RESET}")
        print(f"{CLR_GRAY} the newly uploaded setups without any engine service interruptions.{CLR_RESET}")
        print(f"{CLR_BOLD}{CLR_CYAN}{'=' * 75}{CLR_RESET}\n")
        sys.exit(0)
    else:
        print(f"{CLR_BOLD}{CLR_RED} SYNC FAILED ON ONE OR MORE TARGETS ({success_count}/{len(selected_targets)} succeeded){CLR_RESET}")
        print(f"{CLR_BOLD}{CLR_CYAN}{'=' * 75}{CLR_RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
