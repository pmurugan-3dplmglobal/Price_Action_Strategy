import json
import os

monitor = "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor"
funnel_p = os.path.join(monitor, "pattern_funnel.json")

with open(funnel_p) as f:
    d = json.load(f)

nifty = d.get("nifty50", {})
print("Categories in nifty50:", list(nifty.keys()))

all_items = []
for cat in ["category_a_plus", "category_a", "category_b"]:
    items = nifty.get(cat, [])
    print(f"Count in {cat}: {len(items)}")
    for item in items:
        item["_cat"] = cat
        all_items.append(item)

print(f"\nTotal items: {len(all_items)}")

sample_symbols = ["LT", "HDFCBANK", "JSWSTEEL", "BAJAJ-AUTO", "HINDALCO", "TITAN", "SOLARINDS", "ASTRAL", "MAZDOCK", "PAYTM", "PIIND", "MARICO", "TORNTPHARM"]

dates_count = {}
for i in all_items:
    dt_str = str(i.get("CandleTime") or i.get("candle_time") or i.get("created_at") or i.get("Anchor_Time") or "unknown")[:10]
    dates_count[dt_str] = dates_count.get(dt_str, 0) + 1

print("\nAll items in funnel grouped by candle date:", dates_count)

print("\nInspecting the evicted sample symbols:")
for i in all_items:
    sym = i.get("symbol")
    if sym in sample_symbols:
        print(f"  {sym:<12} | {i.get('contract')} | Cat: {i.get('_cat')} | CandleTime: {i.get('CandleTime')} | Anchor_Time: {i.get('Anchor_Time')} | BM: {i.get('benchmark')} | T1: {i.get('t1')} | SL: {i.get('current_sl')}")
