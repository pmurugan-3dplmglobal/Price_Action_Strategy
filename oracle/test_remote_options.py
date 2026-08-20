import sys, os, time
BASE_DIR = '/home/opc/Price_Action_Strategy'
for p in [BASE_DIR, os.path.join(BASE_DIR, 'Trade_Option'), os.path.join(BASE_DIR, 'common')]:
    if p not in sys.path:
        sys.path.insert(0, p)

print('1. Testing imports...')
import app_option_Trade
print('2. app_option_Trade imported successfully!')
print('3. Calling main startup functions...')
app_option_Trade.auto_export_if_new_month()
print('4. auto_export done. Calling refresh_data(single_run=True)...')
app_option_Trade.refresh_data(single_run=True)
print('5. refresh_data done! Everything works!')
