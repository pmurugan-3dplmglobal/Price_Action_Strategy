
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
sys.path.insert(0, '/home/opc/Price_Action_Strategy/Trade_Option')

import app_option_Trade as aot

print('Running single_run refresh_data...')
aot.refresh_data(single_run=True)
kpos = aot.cached_data.get('kite_positions', [])
print(f'Done! aot.cached_data[kite_positions] count: {len(kpos)}')
for p in kpos:
    print(f"  * {p.get('tradingsymbol') or p.get('contract')} | Qty: {p.get('quantity')} | LTP: {p.get('ltp')} | PnL: {p.get('pnl')}")
