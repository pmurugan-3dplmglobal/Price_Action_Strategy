import os, sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

def search_log(log_path, keywords):
    print(f"=== SEARCHING {os.path.basename(log_path)} ===")
    if not os.path.exists(log_path):
        print(f"File not found: {log_path}")
        return
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if '2026-09-29' in line:
                if any(k.upper() in line.upper() for k in keywords):
                    # print safely without unicode crashes
                    clean_line = line.strip().encode('ascii', errors='backslashreplace').decode('ascii')
                    print(clean_line)

print("--- SEARCHING STOCK ENGINE LOG ---")
search_log('output/logs/bull_nifty50_scanner.log', ['INFY', 'SHRIRAMFIN', 'DABUR', 'CROMPTON', 'AMBER', 'ORDER', 'EXECUT', 'REJECT', 'PLACED'])

print("\n--- SEARCHING INDEX ENGINE LOG ---")
search_log('output/logs/bull_index_trade_engine.log', ['NIFTY', 'ORDER', 'EXECUT', 'REJECT', 'PLACED'])
