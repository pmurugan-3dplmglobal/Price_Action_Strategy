import re

for fn in ['common/resolve.py', 'Trade_Option/index_options_trade_engine.py']:
    with open(fn, encoding='utf-8') as f:
        for i, l in enumerate(f):
            if re.search(r'[\'"]rr[\'"]\s*:', l):
                print(f"{fn}:{i+1}: {l.strip()}")
