import sys, json, os

_ROOT = "/home/opc/Price_Action_Strategy"
sys.path.insert(0, f"{_ROOT}/common")
sys.path.insert(0, f"{_ROOT}/Trade_Option")

from app_option_Trade import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess["user"] = "admin"
        sess["role"] = "admin"
    res = client.get("/api/status")
    data = res.get_json()
    print("=== /api/status RESPONSE ON 140.245.197.71 ===")
    print("Positions count:", len(data.get("positions", {})))
    print("Positions keys:", list(data.get("positions", {}).keys()))
    print("Kite positions count:", len(data.get("kite_positions", [])))
    print("Kite positions:", [p.get("tradingsymbol") for p in data.get("kite_positions", [])])
    print("LTP keys count:", len(data.get("ltp", {})))
    print("LTP sample:", {k: v for k, v in list(data.get("ltp", {}).items())[:5]})
