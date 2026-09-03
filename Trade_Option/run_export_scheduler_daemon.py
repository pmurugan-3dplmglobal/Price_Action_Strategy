import os
import sys
import time
import logging
from datetime import datetime as dt

COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

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

# Scheduled slots and target times
TARGET_SLOTS = [
    {"slot": "09_16_AM_PREFLIGHT", "hour": 9, "minute": 16},
    {"slot": "10_30_AM", "hour": 10, "minute": 30},
    {"slot": "01_00_PM", "hour": 13, "minute": 0},
    {"slot": "03_15_PM", "hour": 15, "minute": 15},
]

executed_today = set()

def main():
    logging.info("Starting Automated Strategy Export & Pre-Flight Daemon...")
    print("=========================================================")
    print(" Automated Strategy Export & Pre-Flight Daemon Active")
    print(" Monitoring clock for slots: 09:16 AM (Pre-Flight), 10:30 AM, 1:00 PM, 3:15 PM")
    print("=========================================================")

    current_day = get_ist_now().strftime("%Y-%m-%d")

    while True:
        try:
            now = get_ist_now(naive=True)
            today_str = now.strftime("%Y-%m-%d")

            # Reset executed set at midnight
            if today_str != current_day:
                current_day = today_str
                executed_today.clear()
                logging.info(f"New day detected: {current_day}. Resetting schedule state.")

            for slot_info in TARGET_SLOTS:
                slot_key = f"{today_str}_{slot_info['slot']}"
                if slot_key in executed_today:
                    continue

                target_time = now.replace(hour=slot_info['hour'], minute=slot_info['minute'], second=0, microsecond=0)
                # If current time is past or within target window (up to 15 mins after target time)
                if now >= target_time and (now - target_time).total_seconds() < 900:
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
