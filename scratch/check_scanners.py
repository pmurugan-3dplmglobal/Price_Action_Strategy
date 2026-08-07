import json
import os
import sys

print("=== CHECKING LOGS FOR SCANNER RUNS ===")
log_path = 'Trade_Option/output/logs/bull_nifty50_scanner.log'
if os.path.exists(log_path):
    with open(log_path) as f:
        lines = f.readlines()
    print("Last 30 lines of bull_nifty50_scanner.log:")
    for l in lines[-30:]:
        print(l.strip())
else:
    print("log file not found:", log_path)

print("\n=== CHECKING INDEX SCANNER LOGS ===")
idx_log = 'Trade_Option/output/logs/bull_index_trade_engine.log'
if os.path.exists(idx_log):
    with open(idx_log) as f:
        lines = f.readlines()
    print("Last 30 lines of bull_index_trade_engine.log:")
    for l in lines[-30:]:
        print(l.strip())
else:
    print("log file not found:", idx_log)
