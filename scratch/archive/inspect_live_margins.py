import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

margins = kite.margins()
print("=== LIVE KITE MARGINS ===")
print(json.dumps(margins, indent=2))
