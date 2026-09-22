import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

d = json.load(open('scratch/poovendan_scan_display.json', encoding="utf-8"))
staged = d.get('staged_trades', []) + d.get('all_staged_today', []) + d.get('carry_forward', []) + d.get('active_live', [])

targets = ["LTM", "WAAREEENER", "VOLTAS", "SWIGGY", "HCLTECH", "TMPV", "KPITTECH"]

found = {}
for t in staged:
    sym = t.get("symbol")
    if sym in targets and sym not in found:
        found[sym] = t

print(f"Found {len(found)} target setups:")
for sym, t in found.items():
    print("=" * 80)
    print(f"Symbol: {sym} | Contract: {t.get('contract')} ({t.get('side')})")
    print(f"Pattern: {t.get('pattern')} | Tier: {t.get('tier')} ({t.get('tier_label')}) | RR: {t.get('rr')}")
    print(f"Timeframe: {t.get('timeframe')} | Anchor Time: {t.get('candle_a_time')} | Entry Time: {t.get('entry_time')}")
    print(f"Benchmark: {t.get('benchmark')} | SL: {t.get('current_sl')} | T1: {t.get('t1')} | T2: {t.get('t2')}")
    print(f"Spot Confluence: {t.get('spot_confluence')} ({t.get('spot_confluence_type')}) | Spot VWAP: {t.get('spot_vwap')}")
    print(f"Option VWAP: {t.get('vwap')} | Status: {t.get('vwap_status')} | Stretch: {t.get('vwap_stretch')}%")
    print(f"VCP Tier: {t.get('vcp_tier')} ({t.get('vcp_badge')}) | ATR Ratio: {t.get('atr_ratio')}")
    print(f"RVOL: {t.get('rvol')} ({t.get('rvol_badge')}) | Daily Breakout: {t.get('is_daily_breakout')}")
