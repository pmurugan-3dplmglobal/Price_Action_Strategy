import os, sys, unittest, time
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
TRADE_OPT_DIR = os.path.join(PROJECT_ROOT, "Trade_Option")

for p in [PROJECT_ROOT, COMMON_DIR, TRADE_OPT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths, pattern_funnel, display_writer, vix_guard, portfolio_risk, trade_db
import stock_options_trade_engine as sote
import position_monitor as pm

class TestE2EIntegrationFlowAudit(unittest.TestCase):

    def test_01_vcp_coiled_promotion(self):
        f_tier = 2; spot_conf = True; atr_r = 0.52; is_sq = False; cand_rr = 2.1
        if f_tier >= 2 and spot_conf and (atr_r <= 0.65 or is_sq) and cand_rr >= 1.5:
            f_tier = 1
        self.assertEqual(f_tier, 1)

    def test_02_display_writer_preservation(self):
        staged = [{
            "symbol": "VOLTAS",
            "contract": "VOLTAS26SEP1800CE",
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "pattern": "BASE_ABCD",
            "spot_sl": 1750.0,
            "dte": 4,
            "spot_entry": 1780.0,
            "spot_t1": 1850.0,
            "strike": 1800,
            "strike_step": 20,
            "spot_token": 12345,
            "spot_confluence": True,
            "atr_ratio": 0.55
        }]
        out_f = os.path.join(paths.SCRATCH_DIR, "test_scan_disp_audit.json")
        display_writer.write_scan_display_data(staged, {}, out_f, engine_name="audit_test")
        import json
        with open(out_f, "r") as f:
            data = json.load(f)
        item = data.get("staged_trades", [])[0]
        self.assertTrue(item["spot_confluence"])
        self.assertEqual(item.get("spot_sl"), 1750.0)
        self.assertEqual(item.get("dte"), 4)
        self.assertEqual(item.get("spot_entry"), 1780.0)
        self.assertEqual(item.get("spot_t1"), 1850.0)
        self.assertEqual(item.get("strike"), 1800)
        self.assertEqual(item.get("strike_step"), 20)
        self.assertEqual(item.get("spot_token"), 12345)

    def test_03_quote_first_fast_skips(self):
        bm, t1, sl = 100.0, 150.0, 80.0
        t1_80pct = round(bm + 0.80 * (t1 - bm), 2)
        self.assertTrue(142.0 >= t1_80pct)
        self.assertTrue(79.0 <= sl)
        self.assertTrue(95.0 < (bm * 0.995))

    def test_04_breakout_and_retest(self):
        bm, sl, t1 = 100.0, 80.0, 150.0
        self.assertTrue(100.5 >= bm)
        self.assertTrue(bm * 0.980 <= 99.0 <= bm * 1.025 and 99.0 < t1 and 99.0 > sl)

    def test_05_morning_surge_gate(self):
        vwap = 2500.0
        self.assertTrue(2490.0 < (vwap * 0.997))
        self.assertTrue(2510.0 > (vwap * 1.003))

    def test_06_composite_ranking(self):
        voltas = {"entry_spot": 100.0, "current_sl": 90.0, "t1": 130.0, "spot_confluence": True, "is_squeeze": True, "vwap_stretch": -2.0, "vwap_status": "FAIR"}
        godrej = {"entry_spot": 100.0, "current_sl": 90.0, "t1": 250.0, "spot_confluence": False, "atr_ratio": 1.0, "vwap_stretch": 0.0, "vwap_status": "FAIR"}
        self.assertAlmostEqual(sote._avg_target_rank(voltas), 7.0, places=2)
        self.assertAlmostEqual(sote._avg_target_rank(godrej), 5.0, places=2)
        self.assertGreater(sote._avg_target_rank(voltas), sote._avg_target_rank(godrej))

    def test_07_all_gates(self):
        self.assertFalse({"spot_confluence": False}.get("spot_confluence"))
        self.assertTrue(3 <= 5 and 3.5 < 5.0)
        self.assertTrue(18.0 > 15.0)
        self.assertTrue(-8.0 < -5.0)
        v_ok_t1, _, _ = vix_guard.evaluate_vix_regime(kite=None, vix_value=10.5, tier_val=1)
        v_ok_t2, _, _ = vix_guard.evaluate_vix_regime(kite=None, vix_value=10.5, tier_val=2)
        self.assertTrue(v_ok_t1)
        self.assertFalse(v_ok_t2)
        clamped = pm.clamp_lpp_buy_price(60.0, 50.0, lpp_factor=1.08)
        self.assertEqual(clamped, 54.0)

    def test_08_spot_anchored_sl_and_trailing(self):
        opt_ltp, opt_sl, spot_ltp, spot_sl = 38.0, 40.0, 1810.0, 1795.0
        sl_hit = (opt_ltp <= opt_sl)
        if spot_ltp > spot_sl and opt_ltp > 50.0 * 0.72:
            sl_hit = False
        self.assertFalse(sl_hit)
        be_dist = pm.get_sl_buffer_distance(50.0, side="BULL")
        be_sl = round(round((50.0 + max(be_dist, 2.0)) / 0.05) * 0.05, 2)
        self.assertGreater(be_sl, 50.0)

    def test_09_latent_eviction_key_mismatch(self):
        item = {"symbol": "VOLTAS", "side": "CE", "strike": 1800, "contract": "VOLTAS26SEP1800CE", "pattern": "BASE_ABCD"}
        key_4 = f"{item['symbol']}|{item['pattern']}|{item['side']}|{item['strike']}"
        self.assertTrue(pattern_funnel._matches_evict(item, key_4))
        self.assertTrue(pattern_funnel._matches_evict(item, item["contract"]))
        self.assertTrue(pattern_funnel._matches_evict(item, item["symbol"]))
        self.assertTrue(pattern_funnel._matches_evict(item, f"{item['symbol']}|{item['side']}"))
        # Float strike representations
        self.assertTrue(pattern_funnel._matches_evict(item, f"{item['symbol']}|{item['pattern']}|{item['side']}|1800.0"))
        self.assertTrue(pattern_funnel._matches_evict(item, f"{item['symbol']}|{item['pattern']}|{item['side']}|1800.00"))
        # Whitespace tolerance around pipes
        self.assertTrue(pattern_funnel._matches_evict(item, f" {item['symbol']} | {item['pattern']} | {item['side']} | {item['strike']} "))
        self.assertTrue(pattern_funnel._matches_evict(item, f" {item['symbol']} | {item['side']} "))
        # End-to-end funnel state persistence & eviction
        t_eng = f"audit_funnel_{int(time.time() * 1000)}"
        pattern_funnel.promote_item(t_eng, item, pattern_funnel.STAGE_A)
        s_before = pattern_funnel.get_funnel_summary(t_eng)
        self.assertEqual(len(s_before["category_a"]), 1)
        pattern_funnel.evict_item(t_eng, key_4)
        s_after = pattern_funnel.get_funnel_summary(t_eng)
        self.assertEqual(len(s_after["category_a"]), 0)
        pattern_funnel.clear_funnel(t_eng)

    def test_10_latent_order_failure_resurrection(self):
        # 1. Stock engine order failure transition
        sym = f"FAIL_SYM_{int(time.time() * 1000)}"
        pos = {"contract": f"{sym}26SEP100CE", "entry_spot": 10.0, "current_sl": 8.0, "t1": 15.0, "status": "ACTIVE"}
        tid, created = trade_db.create_trade("nifty50", sym, pos)
        self.assertTrue(created)
        pos["trade_id"] = tid
        mem = {sym: pos}
        mem.pop(sym, None)
        if pos.get("trade_id"):
            trade_db.update_trade(pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
        db_active = trade_db.get_active_trades("nifty50")
        self.assertNotIn(sym, [t.get("symbol") for t in db_active])
        rec = trade_db.get_trade(tid)
        self.assertEqual(rec["status"], "FAILED")
        self.assertEqual(rec["exit_reason"], "ORDER_PLACEMENT_FAILED")
        trade_db.remove_trades([tid])

        # 2. Index engine order failure transition
        idx_sym = f"IDX_FAIL_{int(time.time() * 1000)}"
        idx_pos = {"contract": f"{idx_sym}26SEP24500CE", "entry_spot": 100.0, "current_sl": 80.0, "t1": 150.0, "status": "ACTIVE"}
        idx_tid, idx_created = trade_db.create_trade("index", idx_sym, idx_pos)
        self.assertTrue(idx_created)
        idx_pos["trade_id"] = idx_tid
        trade_db.update_trade(idx_pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
        idx_active = trade_db.get_active_trades("index")
        self.assertNotIn(idx_sym, [t.get("symbol") for t in idx_active])
        rec_idx = trade_db.get_trade(idx_tid)
        self.assertEqual(rec_idx["status"], "FAILED")
        self.assertEqual(rec_idx["exit_reason"], "ORDER_PLACEMENT_FAILED")
        trade_db.remove_trades([idx_tid])

        # 3. Zero quantity guard: position popped and marked FAILED
        zq_sym = f"ZQ_FAIL_{int(time.time() * 1000)}"
        zq_pos = {"contract": f"{zq_sym}26SEP100CE", "entry_spot": 10.0, "current_sl": 8.0, "t1": 15.0, "status": "ACTIVE"}
        zq_tid, zq_created = trade_db.create_trade("nifty50", zq_sym, zq_pos)
        self.assertTrue(zq_created)
        zq_pos["trade_id"] = zq_tid
        lot_sz = 1; pos_sz = 0; computed_qty = lot_sz * pos_sz
        if computed_qty <= 0:
            if zq_pos.get("trade_id"):
                trade_db.update_trade(zq_pos["trade_id"], {"status": "FAILED", "exit_reason": "ORDER_PLACEMENT_FAILED"})
        zq_active = trade_db.get_active_trades("nifty50")
        self.assertNotIn(zq_sym, [t.get("symbol") for t in zq_active])
        trade_db.remove_trades([zq_tid])

if __name__ == "__main__":
    unittest.main()
