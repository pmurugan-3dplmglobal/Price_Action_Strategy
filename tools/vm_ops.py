#!/usr/bin/env python3
"""
tools/vm_ops.py — Unified Cloud VM Operations & Lifecycle Manager.

Single source of truth utility for managing Oracle Cloud VMs (VM1 Poovendan, VM2 Bhavani).
Replaces multiple redundant deploy_*, check_*_vm*, restart_*, and copy_token_* scripts.

Features:
  --status              Check systemd services, python processes, disk, and git commit
  --deploy              Stash, git pull origin master, run AST smoke test, clean ghosts, restart services
  --restart [SERVICE]   Restart services (options, stock, export, or all)
  --sync-token          Push local Kite access token to VM1 (Poovendan) & verify auth
  --sync-config         Push local input/program_config.json to VMs
  --logs [SERVICE]      View journalctl logs (--lines N, --grep PATTERN)
  --clean-ghosts        Reconcile and purge ghost positions on VMs
  --exec "COMMAND"      Run an arbitrary shell command on the VM(s)
  --vm [1|2|all]        Target specific VM (default: all for status/deploy, 1 for sync-token)

Usage Examples:
  python tools/vm_ops.py --status
  python tools/vm_ops.py --status --vm 1
  python tools/vm_ops.py --deploy
  python tools/vm_ops.py --restart all
  python tools/vm_ops.py --restart options --vm 1
  python tools/vm_ops.py --sync-token
  python tools/vm_ops.py --sync-config
  python tools/vm_ops.py --logs options --lines 50
  python tools/vm_ops.py --clean-ghosts
"""

import os
import sys
import argparse
import subprocess
import time

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
for p in [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "common")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from paths import TOKEN_FILE, PROGRAM_CONFIG_FILE

DEFAULT_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VM_CONFIGS = {
    1: {
        "id": 1,
        "name": "Poovendan VM1",
        "ip": "140.245.197.71",
        "user": "opc",
        "repo_dir": "/home/opc/Price_Action_Strategy",
        "py_cmd": "/home/opc/Price_Action_Strategy/venv/bin/python",
        "services": ["trading-options", "trading-stock", "trading-export"]
    },
    2: {
        "id": 2,
        "name": "Bhavani VM2",
        "ip": "129.225.69.131",
        "user": "opc",
        "repo_dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "py_cmd": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python",
        "services": ["trading-options", "trading-stock", "trading-export"]
    }
}


class VmOperations:
    def __init__(self, key_path=None):
        self.key_path = key_path or DEFAULT_KEY
        if not os.path.exists(self.key_path):
            print(f"[WARN] SSH Key not found at {self.key_path}")

    def _run_ssh(self, vm, command, timeout=60):
        """Execute a remote command via SSH."""
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
        except subprocess.TimeoutExpired:
            return -1, "", f"SSH command timed out after {timeout}s"
        except Exception as e:
            return -1, "", str(e)

    def _run_scp(self, local_path, vm, remote_path, timeout=60):
        """Upload a file to remote VM via SCP."""
        cmd = [
            "scp", "-i", self.key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            local_path,
            f"{vm['user']}@{vm['ip']}:{remote_path}"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()
        except Exception as e:
            return -1, "", str(e)

    def _run_ssh_python(self, vm, python_code, timeout=60):
        """Execute a Python script on the remote VM via stdin, avoiding shell escaping issues."""
        cmd = [
            "ssh", "-i", self.key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{vm['user']}@{vm['ip']}",
            f"{vm['py_cmd']} -"
        ]
        try:
            res = subprocess.run(
                cmd,
                input=f"# -*- coding: utf-8 -*-\n{python_code}".encode("utf-8"),
                capture_output=True,
                timeout=timeout
            )
            out = (res.stdout.decode("utf-8", errors="replace") or "").strip()
            err = (res.stderr.decode("utf-8", errors="replace") or "").strip()
            return res.returncode, out, err
        except subprocess.TimeoutExpired:
            return -1, "", f"Remote Python script timed out after {timeout}s"
        except Exception as e:
            return -1, "", str(e)

    def get_target_vms(self, vm_arg):
        """Resolve VM targets based on argument ('1', '2', or 'all')."""
        if vm_arg in ("1", 1):
            return [VM_CONFIGS[1]]
        elif vm_arg in ("2", 2):
            return [VM_CONFIGS[2]]
        return [VM_CONFIGS[1], VM_CONFIGS[2]]

    def status(self, vm_targets):
        """Check services, python processes, git commit, and disk on target VMs."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"📊 SYSTEM STATUS: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            # 1. Systemd Services
            svc_list = " ".join(vm["services"])
            rc, out, err = self._run_ssh(vm, f"systemctl is-active {svc_list}")
            print("\n[SERVICES]")
            if rc == 0:
                lines = out.split("\n")
                for s, st in zip(vm["services"], lines):
                    icon = "🟢" if st.strip() == "active" else "🔴"
                    print(f"  {icon} {s:20}: {st.strip()}")
            else:
                print(f"  ⚠️ Status check returned: {out or err}")

            # 2. Python Processes
            rc, out, err = self._run_ssh(vm, "ps aux | grep -E 'python.*(engine|Trade|scanner|export)' | grep -v grep")
            print("\n[ACTIVE PYTHON PROCESSES]")
            if out:
                for line in out.split("\n"):
                    print(f"  • {line[:100]}")
            else:
                print("  (No trading python processes running)")

            # 3. Git Status & Last Commit
            rc, out, err = self._run_ssh(vm, f"cd {vm['repo_dir']} && git log -1 --oneline && git status -s")
            print("\n[GIT HEAD & DIRTY STATE]")
            if out:
                for line in out.split("\n"):
                    print(f"  {line}")
            else:
                print("  (Clean git working tree)")

            # 4. Disk Usage
            rc, out, err = self._run_ssh(vm, "df -h / | tail -1")
            print("\n[DISK USAGE]")
            print(f"  {out}")

    def deploy(self, vm_targets):
        """Stash, git pull, AST smoke test, clean ghosts, and restart services."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"🚀 DEPLOYING LATEST TO: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            # 1. Stash and Pull
            print("1. Pulling latest code from origin/master...")
            pull_cmd = f"cd {vm['repo_dir']} && sudo git stash --include-untracked && sudo git pull origin master"
            rc, out, err = self._run_ssh(vm, pull_cmd, timeout=45)
            print(f"   Git pull: {out or err}")
            if rc != 0:
                print(f"   ❌ Git pull failed on {vm['name']}! Skipping deploy.")
                continue

            # 2. AST Smoke Check on VM
            print("2. Verifying AST syntax on VM Python environment...")
            smoke_py = f"""
import sys, ast
sys.path.insert(0, '{vm['repo_dir']}')
files = [
    'common/macro_gate.py', 'common/portfolio_risk.py',
    'common/position_monitor.py', 'Trade_Option/stock_options_trade_engine.py',
    'Trade_Option/index_options_trade_engine.py'
]
for f in files:
    with open(f"{vm['repo_dir']}/" + f, encoding='utf-8') as fp:
        ast.parse(fp.read(), filename=f)
print("AST OK")
"""
            rc, out, err = self._run_ssh_python(vm, smoke_py, timeout=30)
            if "AST OK" in out:
                print("   ✅ AST syntax checks passed on VM.")
            else:
                print(f"   ❌ AST smoke check failed: {out or err}")

            # 3. Clean Ghost Positions
            print("3. Reconciling and purging ghost positions...")
            self.clean_ghosts([vm])

            # 4. Restart Services
            print("4. Restarting systemd services...")
            svc_list = " ".join(vm["services"])
            rc, out, err = self._run_ssh(vm, f"sudo systemctl restart {svc_list}", timeout=40)
            time.sleep(3)

            # 5. Check Service Status
            rc, out, err = self._run_ssh(vm, f"systemctl is-active {svc_list}", timeout=20)
            lines = out.split("\n")
            print("5. Service statuses post-deploy:")
            for s, st in zip(vm["services"], lines):
                icon = "🟢" if st.strip() == "active" else "🔴"
                print(f"   {icon} {s:20}: {st.strip()}")

    def restart(self, vm_targets, service="all"):
        """Restart services cleanly."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"🔄 RESTARTING SERVICES: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            if service == "all":
                target_svcs = vm["services"]
            elif service in ("options", "option"):
                target_svcs = ["trading-options"]
            elif service in ("stock", "stocks"):
                target_svcs = ["trading-stock"]
            elif service in ("export", "exporter"):
                target_svcs = ["trading-export"]
            else:
                target_svcs = [service]

            svc_str = " ".join(target_svcs)
            print(f"Executing: sudo systemctl restart {svc_str}")
            rc, out, err = self._run_ssh(vm, f"sudo systemctl restart {svc_str}", timeout=40)
            time.sleep(2)

            rc, out, err = self._run_ssh(vm, f"systemctl is-active {svc_str}", timeout=20)
            lines = out.split("\n")
            for s, st in zip(target_svcs, lines):
                icon = "🟢" if st.strip() == "active" else "🔴"
                print(f"  {icon} {s:20}: {st.strip()}")

    def sync_token(self, vm_targets):
        """Push local Kite token to VM1 (Poovendan) and verify session."""
        if not os.path.exists(TOKEN_FILE):
            print(f"❌ Local token file not found at {TOKEN_FILE}")
            return

        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"🔑 SYNCING KITE TOKEN TO: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            remote_token_dest = f"{vm['repo_dir']}/input/kite_access_token.txt"
            print(f"1. Uploading {TOKEN_FILE} -> {remote_token_dest}...")
            rc, out, err = self._run_scp(TOKEN_FILE, vm, remote_token_dest)
            if rc != 0:
                print(f"   ❌ SCP failed: {out or err}")
                continue
            print("   ✅ Token uploaded.")

            # Copy to engine subdirectories if needed
            print("2. Syncing token to Trade_Option/input and Trade_Stock/input...")
            copy_cmd = (
                f"cp {remote_token_dest} {vm['repo_dir']}/Trade_Option/input/kite_access_token.txt 2>/dev/null || true; "
                f"cp {remote_token_dest} {vm['repo_dir']}/Trade_Stock/input/kite_access_token.txt 2>/dev/null || true"
            )
            self._run_ssh(vm, copy_cmd)

            # Validate Kite session on VM
            print("3. Validating Kite session authentication on VM...")
            verify_py = f"""
import sys
sys.path.insert(0, '{vm['repo_dir']}')
from kiteconnect import KiteConnect
from common.session import load_kite_session
ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
p = kite.profile()
print(f"AUTH_OK: User {{p.get('user_id')}} ({{p.get('user_name')}})")
"""
            rc, out, err = self._run_ssh_python(vm, verify_py, timeout=30)
            if "AUTH_OK" in out:
                print(f"   ✅ {out}")
            else:
                print(f"   ❌ Auth verification failed: {out or err}")

            # Restart services
            print("4. Restarting services with refreshed session...")
            self.restart([vm], "all")

    def sync_config(self, vm_targets):
        """Push local input/program_config.json to VMs."""
        if not os.path.exists(PROGRAM_CONFIG_FILE):
            print(f"❌ Local config file not found at {PROGRAM_CONFIG_FILE}")
            return

        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"⚙️ SYNCING PROGRAM CONFIG TO: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            remote_dest = f"{vm['repo_dir']}/input/program_config.json"
            print(f"Uploading {PROGRAM_CONFIG_FILE} -> {remote_dest}...")
            rc, out, err = self._run_scp(PROGRAM_CONFIG_FILE, vm, remote_dest)
            if rc == 0:
                print("   ✅ Config uploaded successfully.")
                self.restart([vm], "all")
            else:
                print(f"   ❌ SCP failed: {out or err}")

    def logs(self, vm_targets, service="trading-options", lines=50, grep_pattern=None):
        """View journalctl logs from VMs."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"📜 LOGS ({service}): {vm['name']} ({vm['ip']})")
            print("=" * 70)

            svc_name = service if service.startswith("trading-") else f"trading-{service}"
            cmd = f"journalctl -u {svc_name} -n {lines} --no-pager"
            if grep_pattern:
                cmd += f" | grep -i '{grep_pattern}'"

            rc, out, err = self._run_ssh(vm, cmd, timeout=30)
            if out:
                print(out)
            else:
                print(f"(No logs found or error: {err})")

    def clean_ghosts(self, vm_targets):
        """Run ghost position cleanup on target VMs."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"🧹 PURGING GHOST POSITIONS: {vm['name']} ({vm['ip']})")
            print("=" * 70)

            clean_py = f"""
import sys, json, sqlite3, os
sys.path.insert(0, '{vm['repo_dir']}')
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE, monitor_file

try:
    ak, at = load_kite_session(TOKEN_FILE)
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    ensure_kite_session(kite)
    held = {{p.get('tradingsymbol'): p.get('quantity') for p in kite.positions().get('net', []) if p.get('quantity', 0) != 0}}
    print(f'Held on broker: {{held}}')

    st_p = monitor_file('stock_positions_state.json')
    st = json.load(open(st_p)) if os.path.exists(st_p) else {{}}
    purged = [s for s, d in st.items() if d.get('contract') not in held]
    cleaned = {{s: d for s, d in st.items() if d.get('contract') in held}}
    with open(st_p, 'w') as f:
        json.dump(cleaned, f, indent=2)
    print(f'Purged {{len(purged)}} ghost positions from state file: {{purged}}')

    db_p = monitor_file('trades.sqlite3')
    if os.path.exists(db_p):
        conn = sqlite3.connect(db_p)
        c = conn.cursor()
        c.execute("SELECT id, symbol, contract FROM trades WHERE status IN ('ACTIVE', 'OPEN')")
        rows = c.fetchall()
        updated = 0
        for r in rows:
            if r[2] not in held:
                c.execute("UPDATE trades SET status='FAILED' WHERE id=?", (r[0],))
                updated += 1
        conn.commit()
        conn.close()
        print(f'Marked {{updated}} ghost SQLite trades as FAILED.')
except Exception as e:
    print(f'Ghost purge error: {{e}}')
"""
            rc, out, err = self._run_ssh_python(vm, clean_py, timeout=30)
            if out:
                print(out)
            if err:
                print(f"[STDERR] {err}")

    def exec_cmd(self, vm_targets, command):
        """Run an arbitrary shell command on target VMs."""
        for vm in vm_targets:
            print("\n" + "=" * 70)
            print(f"💻 EXEC ON: {vm['name']} ({vm['ip']}) -> {command}")
            print("=" * 70)
            rc, out, err = self._run_ssh(vm, command, timeout=40)
            print(out or err)


def main():
    parser = argparse.ArgumentParser(description="Unified Cloud VM Operations & Lifecycle Manager")
    parser.add_argument("--vm", choices=["1", "2", "all"], default="all", help="Target VM (1=Poovendan, 2=Bhavani, all=Both)")
    parser.add_argument("--key", type=str, default=DEFAULT_KEY, help="Path to SSH private key")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Check status, processes, and git HEAD on VMs")
    group.add_argument("--deploy", action="store_true", help="Pull latest master, test AST, clean ghosts, restart services")
    group.add_argument("--restart", nargs="?", const="all", default=None, help="Restart services (all, options, stock, export)")
    group.add_argument("--sync-token", action="store_true", help="Sync local Kite token to VM1 and verify")
    group.add_argument("--sync-config", action="store_true", help="Sync local program_config.json to VMs and restart")
    group.add_argument("--logs", nargs="?", const="options", default=None, help="View journalctl logs (options, stock, export)")
    group.add_argument("--clean-ghosts", action="store_true", help="Reconcile and purge ghost positions on VMs")
    group.add_argument("--exec", type=str, dest="exec_cmd", help="Run arbitrary command on target VMs")

    parser.add_argument("--lines", type=int, default=50, help="Number of lines for log display (default: 50)")
    parser.add_argument("--grep", type=str, default=None, help="Grep filter pattern for logs")

    args = parser.parse_args()
    ops = VmOperations(key_path=args.key)

    # By default, sync-token should only target VM 1 unless explicitly requested
    if args.sync_token and args.vm == "all":
        targets = ops.get_target_vms("1")
    else:
        targets = ops.get_target_vms(args.vm)

    if args.status:
        ops.status(targets)
    elif args.deploy:
        ops.deploy(targets)
    elif args.restart is not None:
        ops.restart(targets, service=args.restart)
    elif args.sync_token:
        ops.sync_token(targets)
    elif args.sync_config:
        ops.sync_config(targets)
    elif args.logs is not None:
        ops.logs(targets, service=args.logs, lines=args.lines, grep_pattern=args.grep)
    elif args.clean_ghosts:
        ops.clean_ghosts(targets)
    elif args.exec_cmd:
        ops.exec_cmd(targets, args.exec_cmd)
    else:
        # Default action: show status
        ops.status(targets)


if __name__ == "__main__":
    main()
