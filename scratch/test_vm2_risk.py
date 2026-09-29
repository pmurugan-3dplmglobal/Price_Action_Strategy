import json
import os
import sys

PROJECT_ROOT = "/home/trade/Trade_Kite/Price_Action_Strategy"
sys.path.insert(0, os.path.join(PROJECT_ROOT, "common"))
sys.path.insert(0, PROJECT_ROOT)

from kiteconnect import KiteConnect
from portfolio_risk import check_portfolio_risk_caps

tok_p = os.path.join(PROJECT_ROOT, "input", "kite_access_token.txt")
with open(tok_p) as f:
    tok_data = json.load(f)

kite = KiteConnect(api_key=tok_data["api_key"])
kite.set_access_token(tok_data["access_token"])

allowed, reason, diag = check_portfolio_risk_caps(
    engine="nifty50",
    symbol="INFY",
    candidate_tier=1,
    capital=100000.0,
    live_positions={},
    include_db_trades=True,
    kite=kite
)

print(f"=== VM 2 PORTFOLIO RISK TEST ===")
print(f"Candidate: INFY")
print(f"Is Allowed: {allowed}")
print(f"Reason: {reason}")
print(f"Active Scripts Count: {diag.get('active_count')}")
print(f"Active Scripts List: {diag.get('active_scripts')}")
