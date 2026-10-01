import sys
import hashlib
import json
import os
import subprocess

api_key = "o8nnw6kxykvrsrhg"
api_secret = "9g7d5kktr38d7yvq11njsm4upz8kc6s1"

if len(sys.argv) < 2:
    print("Usage: exchange_token.py <request_token_or_url>")
    sys.exit(1)

raw_input = sys.argv[1].strip()
if "request_token=" in raw_input:
    req_token = raw_input.split("request_token=")[1].split("&")[0].strip()
else:
    req_token = raw_input

checksum = hashlib.sha256((api_key + req_token + api_secret).encode("utf-8")).hexdigest()

cmd = [
    "curl.exe", "-s", "-X", "POST", "https://api.kite.trade/session/token",
    "-H", "X-Kite-Version: 3",
    "-d", f"api_key={api_key}&request_token={req_token}&checksum={checksum}"
]

try:
    res_text = subprocess.check_output(cmd, text=True)
    res = json.loads(res_text)
    if res.get("status") == "success" and "data" in res:
        token = res["data"]["access_token"]
        user_name = res["data"].get("user_name", "User")
        user_id = res["data"].get("user_id", "")
        
        os.makedirs("input", exist_ok=True)
        with open("input/kite_access_token.txt", "w", encoding="utf-8") as f:
            f.write(token)
            
        print(f"SUCCESS: Authenticated as {user_name} ({user_id})")
        print(f"Token saved to input/kite_access_token.txt")
        sys.exit(0)
    else:
        print(f"FAIL: {res.get('message', res_text)}")
        sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
