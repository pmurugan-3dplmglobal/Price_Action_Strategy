import unittest

def compute_scan_priority(sym, spot_quotes, incubating_syms):
    score = 0.0
    if sym in incubating_syms:
        score += 10000.0

    q = spot_quotes.get(f"NSE:{sym}", {})
    lp = float(q.get("last_price") or 0.0)
    ohlc = q.get("ohlc") or {}
    prev_close = float(ohlc.get("close") or 0.0)
    vol = float(q.get("volume") or 0.0)

    if prev_close > 0 and lp > 0:
        pct_change = abs(lp - prev_close) / prev_close * 100.0
        score += pct_change * 100.0

    turnover_cr = (vol * lp) / 1e7
    score += min(turnover_cr * 5.0, 500.0)
    return score

class TestScanPriority(unittest.TestCase):
    def test_priority_ordering(self):
        base_symbols = ["AARTIIND", "ASTRAL", "ATHERENERG", "INFY", "RELIANCE", "TCS"]
        incubating_syms = {"INFY"}
        spot_quotes = {
            "NSE:INFY": {"last_price": 1850.0, "volume": 10000, "ohlc": {"close": 1850.0}}, # Incubating
            "NSE:ATHERENERG": {"last_price": 1624.0, "volume": 492000, "ohlc": {"close": 1660.0}}, # -2.17%, Heavy vol
            "NSE:ASTRAL": {"last_price": 1403.0, "volume": 52000, "ohlc": {"close": 1411.0}}, # -0.57%
            "NSE:AARTIIND": {"last_price": 450.0, "volume": 1000, "ohlc": {"close": 450.0}}, # Flat
            "NSE:RELIANCE": {"last_price": 2900.0, "volume": 500000, "ohlc": {"close": 2905.0}}, # 0.17%, High turnover
            "NSE:TCS": {"last_price": 4200.0, "volume": 500, "ohlc": {"close": 4200.0}}, # Flat
        }

        scan_order = sorted(base_symbols, key=lambda s: (-compute_scan_priority(s, spot_quotes, incubating_syms), s))
        
        # 1. INFY must be first because it is incubating
        self.assertEqual(scan_order[0], "INFY")
        
        # 2. ATHERENERG must beat ASTRAL, AARTIIND, TCS
        ather_idx = scan_order.index("ATHERENERG")
        astral_idx = scan_order.index("ASTRAL")
        aarti_idx = scan_order.index("AARTIIND")
        self.assertLess(ather_idx, astral_idx)
        self.assertLess(astral_idx, aarti_idx)
        print("Prioritized Order:", scan_order)

if __name__ == "__main__":
    unittest.main()
