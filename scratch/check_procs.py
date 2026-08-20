import subprocess
import json

ps_cmd = 'Get-CimInstance Win32_Process | Select-Object ProcessId, CommandLine | ConvertTo-Json'
res = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, text=True)

data = json.loads(res.stdout)
if isinstance(data, dict):
    data = [data]

engines = {}
for p in data:
    cmd = p.get('CommandLine') or ''
    pid = p.get('ProcessId')
    if 'index_options_trade_engine.py' in cmd:
        engines.setdefault('index_engine', []).append(pid)
    elif 'stock_options_trade_engine.py' in cmd:
        engines.setdefault('stock_engine', []).append(pid)
    elif 'automated_strategy_exporter.py' in cmd:
        engines.setdefault('exporter', []).append(pid)
    elif 'app_option_Trade.py' in cmd:
        engines.setdefault('app_option', []).append(pid)
    elif 'app_Stock_Trade.py' in cmd or 'app_Sock_Trade.py' in cmd:
        engines.setdefault('app_stock', []).append(pid)

print("=== ENGINE PROCESS DISCOVERY ===")
for name, pids in engines.items():
    print(f"{name}: {len(pids)} running PIDs -> {pids}")

killed_count = 0
for name, pids in engines.items():
    # Keep 1 instance for active engines/apps, kill all for one-off exporter runs
    keep_pid = pids[0] if name != 'exporter' else None
    for pid in pids:
        if pid != keep_pid:
            print(f"Killing duplicate/one-off {name} (PID {pid})...")
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
            killed_count += 1

print(f"\nCleanup Complete: Terminated {killed_count} duplicate/stale processes.")
