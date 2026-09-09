"""
Unit test suite verifying sys.path normalization and defensive import fallback.
Tests ISSUE-098: Isolating the problematic import / No module named 'common'.
"""
import os
import sys
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")

class TestSysPathNormalization(unittest.TestCase):

    def test_stock_options_trade_engine_sys_path(self):
        """Verify stock_options_trade_engine populates both PROJECT_ROOT and COMMON_DIR."""
        cmd = [
            sys.executable,
            "-c",
            "import sys; import stock_options_trade_engine; "
            "assert any(p.endswith('Price_Action_Strategy') for p in sys.path), 'PROJECT_ROOT not in sys.path'; "
            "assert any(p.endswith('common') for p in sys.path), 'COMMON_DIR not in sys.path'; "
            "from common.position_monitor import _get_nfo_cache; "
            "from common.resolve import resolve_option_spread; "
            "print('STOCK_OPTIONS_ENGINE_PATH_OK')"
        ]
        res = subprocess.run(cmd, cwd=os.path.join(PROJECT_ROOT, "Trade_Option"), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        self.assertIn("STOCK_OPTIONS_ENGINE_PATH_OK", res.stdout)

    def test_index_options_trade_engine_sys_path(self):
        """Verify index_options_trade_engine populates both PROJECT_ROOT and COMMON_DIR."""
        cmd = [
            sys.executable,
            "-c",
            "import sys; import index_options_trade_engine; "
            "assert any(p.endswith('Price_Action_Strategy') for p in sys.path), 'PROJECT_ROOT not in sys.path'; "
            "assert any(p.endswith('common') for p in sys.path), 'COMMON_DIR not in sys.path'; "
            "from common.position_monitor import _get_nfo_cache; "
            "print('INDEX_OPTIONS_ENGINE_PATH_OK')"
        ]
        res = subprocess.run(cmd, cwd=os.path.join(PROJECT_ROOT, "Trade_Option"), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        self.assertIn("INDEX_OPTIONS_ENGINE_PATH_OK", res.stdout)

    def test_paths_module_sys_path(self):
        """Verify importing paths guarantees PROJECT_ROOT and COMMON_DIR in sys.path."""
        cmd = [
            sys.executable,
            "-c",
            "import sys; import paths; "
            "assert any(p.endswith('Price_Action_Strategy') for p in sys.path), 'PROJECT_ROOT not in sys.path'; "
            "assert any(p.endswith('common') for p in sys.path), 'COMMON_DIR not in sys.path'; "
            "print('PATHS_MODULE_OK')"
        ]
        res = subprocess.run(cmd, cwd=COMMON_DIR, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        self.assertIn("PATHS_MODULE_OK", res.stdout)

    def test_stock_reversal_scanner_sys_path(self):
        """Verify stock scanners populate both PROJECT_ROOT and COMMON_DIR."""
        cmd = [
            sys.executable,
            "-c",
            "import sys; import stock_reversal_scanner; "
            "assert any(p.endswith('Price_Action_Strategy') for p in sys.path), 'PROJECT_ROOT not in sys.path'; "
            "assert any(p.endswith('common') for p in sys.path), 'COMMON_DIR not in sys.path'; "
            "from common.trading_core import is_market_open; "
            "print('STOCK_SCANNER_PATH_OK')"
        ]
        res = subprocess.run(cmd, cwd=os.path.join(PROJECT_ROOT, "Trade_Stock"), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        self.assertIn("STOCK_SCANNER_PATH_OK", res.stdout)

    def test_defensive_spread_import_fallback(self):
        """Simulate environment where common package is missing from sys.path to verify fallback."""
        code = '''
import sys
# Remove PROJECT_ROOT, keep only COMMON_DIR
common_dir = r"''' + COMMON_DIR.replace('\\', '/') + '''"
sys.path = [p for p in sys.path if "Price_Action_Strategy" not in p]
sys.path.insert(0, common_dir)

try:
    from common.position_monitor import _get_nfo_cache
    from common.resolve import resolve_option_spread
    imported_via = "PACKAGE"
except ModuleNotFoundError:
    from position_monitor import _get_nfo_cache
    from resolve import resolve_option_spread
    imported_via = "FALLBACK"

assert callable(_get_nfo_cache)
assert callable(resolve_option_spread)
print(f"DEFENSIVE_IMPORT_OK:{imported_via}")
'''
        cmd = [sys.executable, "-c", code]
        res = subprocess.run(cmd, cwd="C:\\", capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed with: {res.stderr}")
        self.assertIn("DEFENSIVE_IMPORT_OK:FALLBACK", res.stdout)

if __name__ == "__main__":
    unittest.main()
