import os
import sys
import time
import json
import logging
from datetime import datetime as dt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
from timeframe_utils import get_ist_now
from automated_strategy_exporter import execute_scheduled_export

log_p = paths.log_file("export_scheduler_daemon.log")
os.makedirs(os.path.dirname(log_p), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_p, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

STATE_FILE = os.path.join(paths.MONITOR_DIR, "export_scheduler_state.json")

# Scheduled slots and target times
TARGET_SLOTS = [
    {"slot": "09_16_AM_PREFLIGHT", "hour": 9, "minute": 16},
    {"slot": "10_30_AM", "hour": 10, "minute": 30},
    {"slot": "01_00_PM", "hour": 13, "minute": 0},
    {"slot": "03_15_PM", "hour": 15, "minute": 15},
]

def _load_scheduler_state(today_str: str) -> set:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    slots = set(data.get("executed_slots", []))
                    logging.info(f"[SCHEDULER STATE] Loaded {len(slots)} persisted executed slot(s) for {today_str}: {sorted(slots)}")
                    return slots
    except Exception as e:
        logging.warning(f"[SCHEDULER STATE] Could not load scheduler state from {STATE_FILE}: {e}")
    return set()

def _save_scheduler_state(today_str: str, executed_slots: set):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "date": today_str,
                "executed_slots": sorted(list(executed_slots)),
                "updated_at": dt.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        logging.warning(f"[SCHEDULER STATE] Could not persist scheduler state to {STATE_FILE}: {e}")

executed_today = set()

def main():
    global executed_today
    logging.info("Starting Automated Strategy Export & Pre-Flight Daemon...")
    print("=========================================================")
    print(" Automated Strategy Export & Pre-Flight Daemon Active")
    print(" Monitoring clock for slots: 09:16 AM (Pre-Flight), 10:30 AM, 1:00 PM, 3:15 PM")
    print("=========================================================")

    current_day = get_ist_now().strftime("%Y-%m-%d")
    executed_today = _load_scheduler_state(current_day)

    while True:
        try:
            now = get_ist_now(naive=True)
            today_str = now.strftime("%Y-%m-%d")

            # Reset executed set at midnight
            if today_str != current_day:
                current_day = today_str
                executed_today.clear()
                _save_scheduler_state(current_day, executed_today)
                logging.info(f"New day detected: {current_day}. Resetting schedule state.")

            for slot_info in TARGET_SLOTS:
                slot_key = f"{today_str}_{slot_info['slot']}"
                if slot_key in executed_today:
                    continue

                target_time = now.replace(hour=slot_info['hour'], minute=slot_info['minute'], second=0, microsecond=0)
                # Narrow catch-up trigger window to 120s (2 minutes) to prevent rogue re-executions on service restart
                if now >= target_time and (now - target_time).total_seconds() < 120:
                    slot_name = slot_info['slot']
                    if slot_name == "09_16_AM_PREFLIGHT":
                        logging.info(f"[DAEMON TRIGGER] Triggering 09:16 AM Pre-Flight Market Open Reconciliation at {now.strftime('%H:%M:%S')}")
                        try:
                            from morning_reconciler import run_preflight_reconciliation
                            run_preflight_reconciliation()
                        except Exception as pf_err:
                            logging.error(f"[DAEMON ERROR] Pre-flight reconciliation failed: {pf_err}")
                    else:
                        logging.info(f"[DAEMON TRIGGER] Triggering export for slot [{slot_name}] at {now.strftime('%H:%M:%S')}")
                        execute_scheduled_export(slot_name=slot_name)
                    executed_today.add(slot_key)
                    _save_scheduler_state(today_str, executed_today)

            time.sleep(10)
        except KeyboardInterrupt:
            logging.info("Export daemon stopped by user.")
            print("\nExport daemon stopped.")
            break
        except Exception as e:
            logging.error(f"Daemon loop error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    main()
