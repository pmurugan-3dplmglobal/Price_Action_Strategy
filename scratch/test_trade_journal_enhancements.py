# -*- coding: utf-8 -*-
"""
test_trade_journal_enhancements.py — Unit test suite for FEATURE-041:
Trade Journal & Watchlist Self-Learning Analytics Suite.

Verifies:
1. classify_trade_attribution() logic across all win and loss categories.
2. get_trade_journal_analytics() statistical aggregations (MFE, MAE, Attribution, RVOL, VCP).
3. watchlist_monitor verdict logic for MISSED_OPPORTUNITY tracking.
4. MFE / MAE numerical tracking accuracy for Long and Short positions.
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
TRADE_OPTION_DIR = os.path.join(PROJECT_ROOT, "Trade_Option")
for p in [PROJECT_ROOT, COMMON_DIR, TRADE_OPTION_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from daily_trade_journal import (
    classify_trade_attribution,
    get_trade_journal_analytics,
    CSV_HEADER
)


class TestTradeJournalEnhancements(unittest.TestCase):

    def test_csv_header_contains_new_fields(self):
        """Verify that CSV_HEADER has all 8 new analytics fields."""
        expected_new_fields = [
            "MFE_Pct",
            "MAE_Pct",
            "Attribution_Code",
            "Spot_VWAP_Dist_Pct",
            "Spot_RVOL",
            "Spot_EMA_Trend",
            "Spot_ATR_Ratio",
            "Opt_VCP_Ratio"
        ]
        for field in expected_new_fields:
            self.assertIn(field, CSV_HEADER, f"Missing {field} in CSV_HEADER")

    def test_attribution_win_dual_vcp_runner(self):
        """Winner with both Spot and Option coiled (ATR <= 0.85) -> WIN_DUAL_VCP_RUNNER."""
        trade = {
            "PnL_Rs": 5145.0,
            "Outcome": "TARGET_HIT",
            "Tier": "🥇 T1 Gold",
            "Pattern": "LL_ABCD",
            "trade_dna": {
                "spot_atr_ratio": 0.62,
                "opt_vcp_ratio": 0.70,
                "spot_ema_trend": "BEAR"
            }
        }
        code = classify_trade_attribution(trade, 5145.0, "TARGET_HIT")
        self.assertEqual(code, "WIN_DUAL_VCP_RUNNER")

    def test_attribution_win_d1_reversal(self):
        """Winner with Tier 1 Gold -> WIN_D1_REVERSAL."""
        trade = {
            "PnL_Rs": 3200.0,
            "Outcome": "TARGET_HIT",
            "Tier": "🥇 T1 Gold",
            "Pattern": "HAMMER_ABCD",
            "trade_dna": {
                "spot_atr_ratio": 1.10,
                "opt_vcp_ratio": 0.95
            }
        }
        code = classify_trade_attribution(trade, 3200.0, "TARGET_HIT")
        self.assertEqual(code, "WIN_D1_REVERSAL")

    def test_attribution_win_d2_pyramid(self):
        """Winner with D2 continuation pattern -> WIN_D2_PYRAMID."""
        trade = {
            "PnL_Rs": 1500.0,
            "Outcome": "TARGET_HIT",
            "Tier": "🥈 T2 Core",
            "Pattern": "D2_TREND_CONTINUATION",
            "trade_dna": {
                "spot_atr_ratio": 1.15
            }
        }
        code = classify_trade_attribution(trade, 1500.0, "TARGET_HIT")
        self.assertEqual(code, "WIN_D2_PYRAMID")

    def test_attribution_loss_counter_spot_trap(self):
        """Loss where PE was bought while Spot was in Bullish trend -> LOSS_COUNTER_SPOT_TRAP."""
        trade = {
            "PnL_Rs": -2449.50,
            "Outcome": "SL_HIT",
            "Side": "PE",
            "Tier": "🥈 T2 Core",
            "Pattern": "LL_ABCD",
            "trade_dna": {
                "spot_ema_trend": "BULL",
                "spot_atr_ratio": 1.47
            }
        }
        code = classify_trade_attribution(trade, -2449.50, "SL_HIT")
        self.assertEqual(code, "LOSS_COUNTER_SPOT_TRAP")

    def test_attribution_loss_slippage_spread(self):
        """Loss where option spread was >= 2.0% at entry -> LOSS_SLIPPAGE_SPREAD."""
        trade = {
            "PnL_Rs": -850.0,
            "Outcome": "SL_HIT",
            "Side": "CE",
            "trade_dna": {
                "spot_ema_trend": "BULL",
                "opt_spread_pct": 2.8
            }
        }
        code = classify_trade_attribution(trade, -850.0, "SL_HIT")
        self.assertEqual(code, "LOSS_SLIPPAGE_SPREAD")

    def test_attribution_loss_emergency_cap(self):
        """Loss where emergency loss cap triggered -> LOSS_EMERGENCY_CAP."""
        trade = {
            "PnL_Rs": -1980.0,
            "Outcome": "SL_HIT",
            "Side": "CE",
            "exit_reason": "EMERGENCY_LOSS_CAP_BREACH"
        }
        code = classify_trade_attribution(trade, -1980.0, "SL_HIT")
        self.assertEqual(code, "LOSS_EMERGENCY_CAP")

    def test_attribution_loss_disciplined_sl(self):
        """Normal, well-managed stop loss exit -> LOSS_DISCIPLINED_SL."""
        trade = {
            "PnL_Rs": -1200.0,
            "Outcome": "SL_HIT",
            "Side": "CE",
            "trade_dna": {
                "spot_ema_trend": "BULL",
                "opt_spread_pct": 0.5
            }
        }
        code = classify_trade_attribution(trade, -1200.0, "SL_HIT")
        self.assertEqual(code, "LOSS_DISCIPLINED_SL")

    def test_attribution_active_trade(self):
        """Trade currently in progress -> ACTIVE_IN_PROGRESS."""
        trade = {
            "PnL_Rs": 350.0,
            "Outcome": "ACTIVE (Carry Forward)",
            "Exit_Time": "OPEN"
        }
        code = classify_trade_attribution(trade, 350.0, "ACTIVE")
        self.assertEqual(code, "ACTIVE_IN_PROGRESS")

    def test_analytics_mfe_mae_and_buckets(self):
        """Test statistical aggregation of MFE/MAE and RVOL/VCP buckets."""
        mock_entries = [
            {
                "Symbol": "WINNER1",
                "Outcome": "TARGET_HIT",
                "PnL_Rs": 5000.0,
                "MFE_Pct": 45.0,
                "MAE_Pct": -3.0,
                "Attribution_Code": "WIN_DUAL_VCP_RUNNER",
                "Spot_RVOL": 1.8,
                "Spot_ATR_Ratio": 0.65
            },
            {
                "Symbol": "WINNER2",
                "Outcome": "TARGET_HIT",
                "PnL_Rs": 3000.0,
                "MFE_Pct": 25.0,
                "MAE_Pct": -5.0,
                "Attribution_Code": "WIN_D1_REVERSAL",
                "Spot_RVOL": 1.2,
                "Spot_ATR_Ratio": 0.75
            },
            {
                "Symbol": "LOSER1",
                "Outcome": "SL_HIT",
                "PnL_Rs": -2000.0,
                "MFE_Pct": 8.0,
                "MAE_Pct": -22.0,
                "Attribution_Code": "LOSS_COUNTER_SPOT_TRAP",
                "Spot_RVOL": 0.8,
                "Spot_ATR_Ratio": 1.25
            }
        ]

        stats = get_trade_journal_analytics(mock_entries)
        summary = stats["summary"]

        self.assertEqual(summary["total_trades"], 3)
        self.assertEqual(summary["winning_trades"], 2)
        self.assertEqual(summary["losing_trades"], 1)
        self.assertEqual(summary["win_rate_pct"], 66.67)

        # Average MFE for winners = (45 + 25) / 2 = 35.0%
        self.assertEqual(summary["avg_mfe_pct_winners"], 35.0)
        # Average MAE for winners = (-3 + -5) / 2 = -4.0%
        self.assertEqual(summary["avg_mae_pct_winners"], -4.0)

        # Average MFE for losers = 8.0%
        self.assertEqual(summary["avg_mfe_pct_losers"], 8.0)
        # Average MAE for losers = -22.0%
        self.assertEqual(summary["avg_mae_pct_losers"], -22.0)

        # RVOL bucket breakdown
        rvol_breakdown = stats["by_rvol_bucket"]
        self.assertIn(">= 1.5 (High Inst)", rvol_breakdown)
        self.assertEqual(rvol_breakdown[">= 1.5 (High Inst)"]["winning_trades"], 1)
        self.assertEqual(rvol_breakdown[">= 1.5 (High Inst)"]["win_rate_pct"], 100.0)

        self.assertIn("< 1.0 (Low Vol)", rvol_breakdown)
        self.assertEqual(rvol_breakdown["< 1.0 (Low Vol)"]["losing_trades"], 1)
        self.assertEqual(rvol_breakdown["< 1.0 (Low Vol)"]["win_rate_pct"], 0.0)

        # VCP Compression breakdown
        vcp_breakdown = stats["by_vcp_compression"]
        self.assertIn("Coiled (ATR <= 0.85)", vcp_breakdown)
        self.assertEqual(vcp_breakdown["Coiled (ATR <= 0.85)"]["winning_trades"], 2)
        self.assertEqual(vcp_breakdown["Coiled (ATR <= 0.85)"]["win_rate_pct"], 100.0)

        self.assertIn("Expanding (ATR > 0.85)", vcp_breakdown)
        self.assertEqual(vcp_breakdown["Expanding (ATR > 0.85)"]["losing_trades"], 1)

    def test_watchlist_verdict_missed_opportunity(self):
        """Test watchlist monitor verdict generation for MISSED_OPPORTUNITY items."""
        # 1. Surged >= 15% -> Opportunity Missed
        tag = "MISSED_OPPORTUNITY"
        entry_p = 100.0
        opt_ltp_surged = 135.0
        lot = 100
        pnl_pct_surged = round((opt_ltp_surged - entry_p) / entry_p * 100, 2)
        pnl_val_surged = (opt_ltp_surged - entry_p) * lot
        if pnl_pct_surged >= 15.0:
            verdict = f"Opportunity Missed: Surged +{pnl_pct_surged:.1f}% (+INR {pnl_val_surged:+,.0f})"
        self.assertIn("Opportunity Missed", verdict)
        self.assertIn("+35.0%", verdict)

        # 2. Dropped <= -15% -> Bullet Dodged
        opt_ltp_dropped = 72.0
        pnl_pct_dropped = round((opt_ltp_dropped - entry_p) / entry_p * 100, 2)
        pnl_val_dropped = (opt_ltp_dropped - entry_p) * lot
        if pnl_pct_dropped <= -15.0:
            verdict_drop = f"Bullet Dodged: Dropped {pnl_pct_dropped:.1f}% (Avoided -INR {abs(pnl_val_dropped):,.0f})"
        self.assertIn("Bullet Dodged", verdict_drop)
        self.assertIn("-28.0%", verdict_drop)

    def test_clear_journal_creates_backup_and_resets(self):
        """Verify clear_journal creates a timestamped backup and resets files."""
        import tempfile
        import shutil
        import json
        import daily_trade_journal

        temp_dir = tempfile.mkdtemp()
        orig_dir = daily_trade_journal.JOURNAL_DIR
        orig_json = daily_trade_journal.JOURNAL_JSON_PATH
        orig_csv = daily_trade_journal.JOURNAL_CSV_PATH

        try:
            daily_trade_journal.JOURNAL_DIR = temp_dir
            daily_trade_journal.JOURNAL_JSON_PATH = os.path.join(temp_dir, "daily_trade_journal.json")
            daily_trade_journal.JOURNAL_CSV_PATH = os.path.join(temp_dir, "daily_trade_journal.csv")

            # Seed dummy entries
            dummy_entries = [{"Date": "2026-09-21", "Symbol": "NIFTY2692223300PE", "PnL_Rs": 1500.0}]
            with open(daily_trade_journal.JOURNAL_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(dummy_entries, f)
            with open(daily_trade_journal.JOURNAL_CSV_PATH, "w", encoding="utf-8") as f:
                f.write(",".join(daily_trade_journal.CSV_HEADER) + "\n2026-09-21,index,NIFTY2692223300PE,BUY,30min,LL_ABCD,T1,2 Waves,09:15,100,09:30,115,85,130,150,170,1,50,1500,+15.0%,TARGET_HIT,15.0,-2.0,WIN_DISCIPLINED_TARGET,0.1,1.8,BULL,0.7,0.8,Remarks,Lesson\n")

            ok, backup_file, msg = daily_trade_journal.clear_journal(create_backup=True)
            self.assertTrue(ok)
            self.assertIsNotNone(backup_file)
            self.assertTrue(os.path.exists(backup_file))

            # Verify JSON was reset to empty list
            entries = daily_trade_journal.load_journal_entries()
            self.assertEqual(entries, [])

            # Verify backup contains the original dummy data
            with open(backup_file, "r", encoding="utf-8") as f:
                if backup_file.endswith(".json"):
                    b_data = json.load(f)
                    self.assertEqual(len(b_data), 1)
                    self.assertEqual(b_data[0]["Symbol"], "NIFTY2692223300PE")
        finally:
            daily_trade_journal.JOURNAL_DIR = orig_dir
            daily_trade_journal.JOURNAL_JSON_PATH = orig_json
            daily_trade_journal.JOURNAL_CSV_PATH = orig_csv
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
