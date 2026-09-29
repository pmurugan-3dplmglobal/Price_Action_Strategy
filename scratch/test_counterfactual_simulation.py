"""
scratch/test_counterfactual_simulation.py
=========================================
Unit and Invariant Verification Suite for Milestone M2:
Counterfactual Algo Simulation Against Current Production Rules.

Verifies:
  1. Dataset Ingestion & Synthetic Segregation (0 synthetic leakage).
  2. ISSUE-086 Volume Gate Filtering (SBICARD #1033, VOLTAS #1032, MAZDOCK #923).
  3. ISSUE-088 Spot-Anchored Candle-Close SL & Catastrophic Cap (-28.0% max loss).
  4. Single-Lot EXIT_AT_T1 & Profit Lock Ratchets (+15% -> +8%, +25% -> +15%).
  5. ISSUE-087 Atomic Debit Spread Risk/Reward & Theta Neutrality.
  6. Mathematical Consistency of Comparative Metrics & Strategy Expectancy.
  7. Output Deliverables Schema & Integrity (results & summary matrix JSONs).
"""

import os
import sys
import json
import unittest

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH_DIR = os.path.join(PROJ_ROOT, "scratch")
sys.path.insert(0, PROJ_ROOT)
sys.path.insert(0, SCRATCH_DIR)

import counterfactual_algo_simulator as sim


class TestCounterfactualSimulation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = sim.load_clean_data(sim.CLEAN_DATASET_PATH)
        cls.results_file = sim.RESULTS_OUTPUT_PATH
        cls.summary_file = sim.SUMMARY_OUTPUT_PATH
        
        # Ensure simulator has been run
        if not os.path.exists(cls.results_file) or not os.path.exists(cls.summary_file):
            sim.run_counterfactual_simulation()
            
        with open(cls.results_file, "r", encoding="utf-8") as f:
            cls.results_json = json.load(f)
            
        with open(cls.summary_file, "r", encoding="utf-8") as f:
            cls.summary_json = json.load(f)

    def test_01_clean_dataset_ingestion_invariants(self):
        """Verify clean dataset isolation: exactly 929 genuine trades, 0 synthetic leakage."""
        genuine = self.data["genuine_trades"]
        filled = self.data["genuine_filled"]
        cands = self.data["candidate_scans"]

        self.assertEqual(len(genuine), 929, "Must load exactly 929 genuine trades")
        self.assertEqual(len(filled), 607, "Must identify exactly 607 filled trades")
        self.assertEqual(len(cands), 657, "Must load exactly 657 candidate scans")
        
        # Invariant: Zero synthetic symbols in genuine dataset
        for t in genuine:
            self.assertFalse(t.get("is_synthetic", False), f"Synthetic leakage detected in trade {t.get('trade_id')}")
            sym = str(t.get("symbol", "")).upper()
            cnt = str(t.get("contract", "")).upper()
            self.assertNotIn("GHOST", sym)
            self.assertNotIn("GHOST", cnt)

    def test_02_issue086_dry_volume_filtering_named_cases(self):
        """
        Verify that ISSUE-086 Point D volume gate rejects named historical liquidity traps:
        SBICARD #1033, VOLTAS #1032, MAZDOCK #923, TATAPOWER #931/975.
        """
        sim_trades = {t["trade_id"]: t for t in self.results_json["simulated_trades"]}

        # 1. SBICARD #1033
        sbicard = sim_trades.get("DB_1033")
        self.assertIsNotNone(sbicard, "DB_1033 must exist in simulation")
        self.assertEqual(sbicard["taxonomy_verdict"], "REJECTED_BY_ISSUE086")
        self.assertFalse(sbicard["simulated_accepted"])
        self.assertEqual(sbicard["simulated_pnl_pct"], 0.0)
        self.assertEqual(sbicard["pnl_saved_pct"], 25.84, "Must save exactly 25.84% historical loss on SBICARD")

        # 2. VOLTAS #1032
        voltas = sim_trades.get("DB_1032")
        self.assertIsNotNone(voltas, "DB_1032 must exist in simulation")
        self.assertEqual(voltas["taxonomy_verdict"], "REJECTED_BY_ISSUE086")
        self.assertFalse(voltas["simulated_accepted"])
        self.assertEqual(voltas["pnl_saved_pct"], 13.80, "Must save exactly 13.80% historical loss on VOLTAS")

        # 3. MAZDOCK #923
        mazdock = sim_trades.get("DB_923")
        self.assertIsNotNone(mazdock, "DB_923 must exist in simulation")
        self.assertEqual(mazdock["taxonomy_verdict"], "REJECTED_BY_ISSUE086")
        self.assertFalse(mazdock["simulated_accepted"])
        self.assertIn("Point D", mazdock["taxonomy_description"])

        # 4. TATAPOWER #931 & #975
        tp_931 = sim_trades.get("DB_931")
        tp_975 = sim_trades.get("DB_975")
        self.assertEqual(tp_931["taxonomy_verdict"], "REJECTED_BY_ISSUE086")
        self.assertEqual(tp_975["taxonomy_verdict"], "REJECTED_BY_ISSUE086")
        self.assertEqual(tp_931["pnl_saved_pct"], 27.42)
        self.assertEqual(tp_975["pnl_saved_pct"], 27.42)

    def test_03_issue086_preserves_genuine_target_hits(self):
        """Verify that genuine institutional breakouts that expanded to target are accepted."""
        sim_trades = {t["trade_id"]: t for t in self.results_json["simulated_trades"]}

        # CIPLA #883 (reached +37.45%)
        cipla = sim_trades.get("DB_883")
        self.assertIsNotNone(cipla)
        self.assertTrue(cipla["simulated_accepted"])
        self.assertEqual(cipla["taxonomy_verdict"], "CLEAN_WIN_TARGET_HIT")
        self.assertEqual(cipla["simulated_pnl_pct"], 37.45)

        # BANKNIFTY #656 (reached +17.64%)
        bn = sim_trades.get("DB_656")
        self.assertIsNotNone(bn)
        self.assertTrue(bn["simulated_accepted"])
        self.assertEqual(bn["taxonomy_verdict"], "CLEAN_WIN_TARGET_HIT")
        self.assertEqual(bn["simulated_pnl_pct"], 17.64)

    def test_04_issue088_catastrophic_override_cap(self):
        """
        Verify that option losses exceeding -28% are capped at -28.0% by the emergency override.
        In August unhedged trading, losses reached -50% to -99.95%.
        """
        sim_trades = self.results_json["simulated_trades"]
        cat_trades = [t for t in sim_trades if t["taxonomy_verdict"] == "CATASTROPHIC_OVERRIDE_SAVED_LOSS"]
        
        self.assertGreater(len(cat_trades), 0, "Must have trades where catastrophic override saved loss")
        for t in cat_trades:
            self.assertEqual(t["simulated_pnl_pct"], -28.0, "Catastrophic loss must be strictly clamped to -28.0%")
            self.assertGreater(t["pnl_saved_pct"], 0.0, "Must record positive capital loss saved")

    def test_05_issue087_debit_spread_properties(self):
        """Verify that debit spreads cap maximum risk and reduce capital outlay by ~50%."""
        mock_trade = {"entry_price": 100.0, "rr": 2.5}
        spread = sim.model_debit_spread(mock_trade)
        
        self.assertEqual(spread["leg1_buy_premium"], 100.0)
        self.assertEqual(spread["leg2_sell_premium"], 55.0)
        self.assertEqual(spread["net_debit"], 45.0)
        self.assertEqual(spread["debit_discount_vs_naked_pct"], 55.0)
        self.assertEqual(spread["max_risk_amount"], 45.0)
        self.assertTrue(spread["theta_decay_neutralized"])

    def test_06_mathematical_expectancy_and_rr_consistency(self):
        """
        Verify mathematical formulation:
        E = (WR * RR) - ((1 - WR) * 1.0)
        Across SQLite 55 trades and full universe.
        """
        mat = self.summary_json
        
        # Test SQLite 55 accepted trades
        s_acc = mat["sqlite_production_focus_n55"]["simulated_accepted_trades_only"]
        wr = s_acc["win_rate_pct"] / 100.0
        rr = s_acc["realized_rr"]
        exp_manual = round((wr * rr) - ((1.0 - wr) * 1.0), 2)
        self.assertAlmostEqual(s_acc["expectancy"], exp_manual, places=2)
        
        # Verify SQLite 55 net P&L is positive (+33.14%) vs historical negative (-527.37%)
        self.assertGreater(mat["sqlite_production_focus_n55"]["simulated_current_algo"]["total_pnl_pct"], 0.0)
        self.assertGreater(mat["sqlite_production_focus_n55"]["delta_attribution"]["net_pnl_delta_pct"], 500.0)

    def test_07_deliverables_schema_compliance(self):
        """Verify output deliverables exist, match schema, and are non-empty."""
        self.assertTrue(os.path.exists(self.results_file))
        self.assertTrue(os.path.exists(self.summary_file))
        self.assertGreater(os.path.getsize(self.results_file), 100000)
        self.assertGreater(os.path.getsize(self.summary_file), 5000)

        # Invariant: All required keys present in summary matrix
        req_keys = [
            "metadata", "full_evaluated_universe_n445", "sqlite_production_focus_n55",
            "candidate_scans_summary", "pattern_breakdown", "taxonomy_distribution", "key_case_studies"
        ]
        for k in req_keys:
            self.assertIn(k, self.summary_json)


if __name__ == "__main__":
    unittest.main(verbosity=2)
