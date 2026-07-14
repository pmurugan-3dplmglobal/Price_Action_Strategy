import os
import csv
import threading
from datetime import datetime as dt

JOURNAL_FILE = os.path.join("output", "monitor", "trade_journal.csv")
journal_lock = threading.Lock()

def log_to_journal(symbol, pattern, timeframe, action, status, details="", pnl_pct=0.0, entry="", sl="", target="", rr="", ts=None):
    """Write a row to trade_journal.csv."""
    file_exists = os.path.exists(JOURNAL_FILE)
    headers = ["Timestamp", "Symbol", "Pattern", "Timeframe", "Action", "Status", 
               "Entry", "SL", "Target", "RR", "Details", "P&L %"]
    row = [
        ts or dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        symbol, pattern, timeframe, action, status,
        f"{entry:.2f}" if isinstance(entry, (int, float)) and entry else str(entry) if entry else "",
        f"{sl:.2f}" if isinstance(sl, (int, float)) and sl else str(sl) if sl else "",
        f"{target:.2f}" if isinstance(target, (int, float)) and target else str(target) if target else "",
        f"{rr:.2f}" if isinstance(rr, (int, float)) and rr else str(rr) if rr else "",
        details,
        f"{pnl_pct:.2f}%" if pnl_pct != 0.0 else "-"
    ]
    with journal_lock:
        try:
            with open(JOURNAL_FILE, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter="\t")
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow(row)
        except Exception as e:
            print(f"Journal write failed: {e}")