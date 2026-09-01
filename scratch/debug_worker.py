import sys, json, os, traceback, time

_ROOT = "/home/opc/Price_Action_Strategy"
sys.path.insert(0, f"{_ROOT}/common")
sys.path.insert(0, f"{_ROOT}/Trade_Option")

import paths
print("paths.TOKEN_FILE:", paths.TOKEN_FILE, "exists?", os.path.exists(paths.TOKEN_FILE))
print("paths.TRADES_DB:", paths.TRADES_DB, "exists?", os.path.exists(paths.TRADES_DB))

from session import load_kite_session
try:
    api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
    print("Loaded token:", api_k, acc_t[:10] + "...")
except Exception as e:
    print("load_kite_session error:", e)

from kiteconnect import KiteConnect
try:
    ks = KiteConnect(api_key=api_k)
    ks.set_access_token(acc_t)
    pos = ks.positions()
    print("Kite positions fetch SUCCESS! Total net rows:", len(pos.get("net", [])))
except Exception as e:
    print("KiteConnect positions error:", e)
    traceback.print_exc()

import trade_db
try:
    act = trade_db.get_active_trades()
    print("trade_db.get_active_trades():", len(act))
except Exception as e:
    print("trade_db error:", e)
