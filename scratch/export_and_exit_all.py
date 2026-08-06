import json, os, csv, time
from datetime import datetime

timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
date_file_str = datetime.now().strftime("%d_%m_%y_%H%M")

db_paths = [
    "Trade_Option/output/monitor/trades_db.json",
    "Trade_Stock/output/monitor/trades_db.json",
    "output/monitor/trades_db.json"
]

all_active = []

# 1. Gather all active positions
for path in db_paths:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            trades = data.get("trades", [])
            for t in trades:
                if t.get("status") == "ACTIVE":
                    t["_db_source"] = path
                    all_active.append(t)
        except Exception as e:
            print(f"Error reading {path}: {e}")

print(f"Found {len(all_active)} total active positions across all databases.")

# 2. Export to CSV
export_dir_option = "Trade_Option/output/exports"
export_dir_stock = "Trade_Stock/output/exports"
os.makedirs(export_dir_option, exist_ok=True)
os.makedirs(export_dir_stock, exist_ok=True)

csv_filename = f"active_positions_export_{date_file_str}.csv"
csv_path_option = os.path.join(export_dir_option, csv_filename)
csv_path_stock = os.path.join(export_dir_stock, csv_filename)

fieldnames = [
    "id", "engine", "symbol", "contract", "side", "entry_spot", "entry_price",
    "current_sl", "t1", "t2", "t3", "pattern", "timeframe", "lot_size",
    "entry_time", "created_at", "exit_time", "status"
]

def write_csv(filepath):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in all_active:
            row = dict(t)
            row["exit_time"] = timestamp_str
            row["status"] = "USER_EXIT"
            writer.writerow(row)

write_csv(csv_path_option)
write_csv(csv_path_stock)

print(f"Exported CSV to: {csv_path_option}")
print(f"Exported CSV to: {csv_path_stock}")

# 3. Perform EXIT ALL across all DB files
for path in db_paths:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            trades = data.get("trades", [])
            updated_count = 0
            for t in trades:
                if t.get("status") == "ACTIVE":
                    t["status"] = "USER_EXIT"
                    t["exit_time"] = timestamp_str
                    t["result"] = "USER_EXIT"
                    t["updated_at"] = timestamp_str
                    updated_count += 1
            
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            # Sync active_positions_db.json & journal_trades_db.json
            base_dir = os.path.dirname(path)
            active_db_file = os.path.join(base_dir, "active_positions_db.json")
            journal_db_file = os.path.join(base_dir, "journal_trades_db.json")
            
            active_trades = [t for t in trades if t.get("status") == "ACTIVE"]
            journal_trades = [t for t in trades if t.get("status") != "ACTIVE"]
            
            with open(active_db_file, "w", encoding="utf-8") as f:
                json.dump({"updated_at": timestamp_str, "positions": active_trades}, f, indent=2)
            
            with open(journal_db_file, "w", encoding="utf-8") as f:
                json.dump({"updated_at": timestamp_str, "journal_entries": journal_trades}, f, indent=2)

            print(f"Updated {path}: Exited {updated_count} active positions.")
        except Exception as e:
            print(f"Error updating {path}: {e}")

# 4. Clear scan display active positions
scan_display_files = [
    "Trade_Option/output/monitor/scan_display_data.json",
    "Trade_Option/output/monitor/scan_display_index.json",
    "Trade_Stock/output/monitor/scan_display_data.json",
    "Trade_Stock/output/monitor/scan_display_index.json",
    "output/monitor/scan_display_data.json",
    "output/monitor/scan_display_index.json"
]

for s_path in scan_display_files:
    if os.path.exists(s_path):
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                s_data = json.load(f)
            s_data["active_positions"] = []
            s_data["active_live"] = []
            s_data["timestamp"] = timestamp_str
            with open(s_path, "w", encoding="utf-8") as f:
                json.dump(s_data, f, indent=2)
            print(f"Cleared active positions in {s_path}")
        except Exception as e:
            print(f"Error clearing {s_path}: {e}")

print("=== EXIT ALL & EXPORT COMPLETED SUCCESSFULLY ===")
