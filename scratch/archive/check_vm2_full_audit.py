import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
ip = "129.225.69.131"

remote_script = """import sys, json, os, sqlite3
sys.path.insert(0, '/home/trade/Trade_Kite/Price_Action_Strategy')
sys.path.insert(0, '/home/trade/Trade_Kite/Price_Action_Strategy/common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

prof = kite.profile()
print(f'USER: {prof.get("user_id")} - {prof.get("user_name")}')

positions = kite.positions()
net = positions.get('net', [])
print(f'Total Net Positions on VM 2 Kite: {len(net)}')
tot_pnl = 0.0
for p in net:
    ts = p.get('tradingsymbol')
    qty = p.get('quantity')
    buy_p = p.get('average_price')
    sell_p = p.get('sell_price')
    ltp = p.get('last_price')
    pnl = p.get('pnl')
    tot_pnl += pnl
    status = 'OPEN' if qty != 0 else 'CLOSED'
    print(f'[{status}] {ts:25s} | Qty: {qty:5d} | Buy: {buy_p:8.2f} | Sell: {sell_p:8.2f} | LTP: {ltp:8.2f} | PnL: {pnl:10.2f}')
print(f'TOTAL KITE PNL ON VM 2: Rs {tot_pnl:,.2f}')

orders = kite.orders()
print(f'\\nTotal Orders on VM 2: {len(orders)}')
for o in orders:
    ts = o.get('tradingsymbol')
    status = o.get('status')
    ttype = o.get('transaction_type')
    qty = o.get('quantity')
    price = o.get('average_price') or o.get('price')
    reason = o.get('status_message') or ''
    otime = str(o.get('order_timestamp', ''))[:19]
    print(f'  {otime} | {ts:22s} | {ttype:4s} | Qty: {qty:4d} | P: {price:6.2f} | {status:9s} | {reason}')

db_path = '/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/trades.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE created_at LIKE '2026-09-22%' OR updated_at LIKE '2026-09-22%' ORDER BY id DESC")
    rows = cur.fetchall()
    print(f'\\n--- VM 2 TRADES DB TODAY ({len(rows)} trades) ---')
    for r in rows:
        d = json.loads(r['data_json']) if r['data_json'] else {}
        print(f"Trade #{r['id']} | {r['symbol']} ({r['contract']}) | {r['status']} | Entry: {d.get('entry_spot') or d.get('entry_price')} | SL: {d.get('current_sl')} | Exit: {d.get('exit_reason') or d.get('details')}")
"""

# Copy script to remote via stdin and run with venv python
proc = subprocess.Popen(
    ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}", "cat > /tmp/audit_vm2.py && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python /tmp/audit_vm2.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
stdout, stderr = proc.communicate(input=remote_script)
print(stdout or stderr)
