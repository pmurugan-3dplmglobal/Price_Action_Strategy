import os
import sys
COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'common'))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import stock_reversal_scanner as _scanner

_scanner.configure_weekly_bear()

PROFILE = _scanner.PROFILE
TARGET_INDEX = _scanner.TARGET_INDEX
LOOKBACK_DAYS = _scanner.LOOKBACK_DAYS
TIMEFRAME_ENTRY = _scanner.TIMEFRAME_ENTRY
TIMEFRAME_ANCHOR = _scanner.TIMEFRAME_ANCHOR
OUTPUT_FILE = _scanner.OUTPUT_FILE
ACTIVE_POSITIONS = _scanner.ACTIVE_POSITIONS
position_lock = _scanner.position_lock
SCAN_DISPLAY_FILE = _scanner.SCAN_DISPLAY_FILE

run_scan = _scanner.run_scan
export_results = _scanner.export_results
run_anchor_scan = _scanner.run_anchor_scan
print_summary = _scanner.print_summary
load_program_config = _scanner.load_program_config
main = _scanner.main

if __name__ == '__main__':
    main()
