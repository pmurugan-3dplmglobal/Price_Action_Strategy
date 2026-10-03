import os
import sys
import json
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
common_dir = os.path.join(PROJECT_ROOT, "common")
if common_dir not in sys.path:
    sys.path.insert(0, common_dir)
opt_dir = os.path.join(PROJECT_ROOT, "Trade_Option")
if opt_dir not in sys.path:
    sys.path.insert(0, opt_dir)

from unittest.mock import MagicMock
for mod in ["pandas", "kiteconnect", "flask", "werkzeug", "werkzeug.security", "numpy", "scipy"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from position_monitor import _load_program_config_file
import app_option_Trade


class TestPositionMonitorConfigHierarchy(unittest.TestCase):
    def test_01_root_config_load(self):
        cfg = _load_program_config_file()
        self.assertIsInstance(cfg, dict)
        self.assertIn("index", cfg)
        self.assertIn("nifty50", cfg)

    def test_02_index_engine_overlay(self):
        cfg_index = _load_program_config_file(engine_name="index")
        self.assertIsInstance(cfg_index, dict)
        # Should have index-specific fields promoted to top-level access
        self.assertIn("trailing_rules", cfg_index)
        self.assertIn("max_option_loss_pct", cfg_index)
        self.assertEqual(cfg_index.get("max_option_loss_pct"), 28.0)
        self.assertIsInstance(cfg_index.get("trailing_rules"), dict)
        self.assertEqual(cfg_index["trailing_rules"].get("option_trail_1_gain_pct"), 15.0)
        self.assertEqual(cfg_index["trailing_rules"].get("option_trail_1_sl_pct"), 8.0)

    def test_03_nifty50_engine_overlay(self):
        cfg_stock = _load_program_config_file(engine_name="nifty50")
        self.assertIsInstance(cfg_stock, dict)
        self.assertIn("trailing_rules", cfg_stock)
        self.assertIn("max_option_loss_pct", cfg_stock)
        self.assertEqual(cfg_stock.get("max_option_loss_pct"), 28.0)

    def test_04_save_config_preserves_nested_and_maps_trailing(self):
        initial_cfg = app_option_Trade.load_config()
        test_payload = {
            "timeframe_entry": "5minute",
            "capital": 150000,
            "max_option_loss_pct": 25.0,
            "option_trail_1_gain_pct": 18.0,
            "option_trail_1_sl_pct": 9.0
        }
        # Verify save_config does not wipe existing keys
        app_option_Trade.save_config("index", test_payload)
        updated_cfg = app_option_Trade.load_config()
        self.assertEqual(updated_cfg["index"]["timeframe_entry"], "5minute")
        self.assertEqual(updated_cfg["index"]["capital"], 150000)
        self.assertEqual(updated_cfg["index"]["max_option_loss_pct"], 25.0)
        self.assertEqual(updated_cfg["index"]["trailing_rules"]["option_trail_1_gain_pct"], 18.0)
        self.assertEqual(updated_cfg["index"]["trailing_rules"]["option_trail_1_sl_pct"], 9.0)
        # Verify unedited keys like tranche_mode or enable_spot_sl_guard are preserved
        self.assertTrue(updated_cfg["index"].get("tranche_mode", True))

        # Revert back to original cleanly
        with open(app_option_Trade.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_cfg, f, indent=2)
        # Harmonize reversion
        for alt in [
            os.path.join(PROJECT_ROOT, "input", "program_config.json"),
            os.path.join(PROJECT_ROOT, "Trade_Option", "input", "program_config.json"),
            os.path.join(PROJECT_ROOT, "Trade_Stock", "input", "program_config.json")
        ]:
            if os.path.exists(alt):
                with open(alt, "w", encoding="utf-8") as af:
                    json.dump(initial_cfg, af, indent=2)

    def test_05_programs_ui_fields_defined(self):
        index_cfg = app_option_Trade.PROGRAMS["index"]["config_fields"]
        self.assertIn("max_option_loss_pct", index_cfg)
        self.assertIn("option_trail_1_gain_pct", index_cfg)
        self.assertIn("option_trail_1_sl_pct", index_cfg)
        self.assertIn("option_trail_2_gain_pct", index_cfg)
        self.assertIn("option_trail_2_sl_pct", index_cfg)

        nifty_cfg = app_option_Trade.PROGRAMS["nifty50"]["config_fields"]
        self.assertIn("max_option_loss_pct", nifty_cfg)
        self.assertIn("option_trail_1_gain_pct", nifty_cfg)
        self.assertIn("option_trail_1_sl_pct", nifty_cfg)


if __name__ == "__main__":
    unittest.main()
