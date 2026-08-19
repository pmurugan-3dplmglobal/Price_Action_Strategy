import subprocess, sys, os, time, urllib.request

ROOT = r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy"
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

print("Launching Options Dashboard on Port 5050...")
p1 = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "Trade_Option", "app_option_Trade.py")],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW
)
print(f"Options Dashboard PID: {p1.pid}")

print("Launching Stock Dashboard on Port 5051...")
p2 = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "Trade_Stock", "app_Sock_Trade.py")],
    cwd=os.path.join(ROOT, "Trade_Stock"),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW
)
print(f"Stock Dashboard PID: {p2.pid}")

time.sleep(3)

# Test endpoints
try:
    r1 = urllib.request.urlopen("http://127.0.0.1:5050/")
    print(f"[OK] Options Dashboard running on port 5050 (HTTP {r1.status})")
except Exception as e:
    print(f"[ERROR] Options Dashboard port 5050 check failed: {e}")

try:
    r2 = urllib.request.urlopen("http://127.0.0.1:5051/")
    print(f"[OK] Stock Dashboard running on port 5051 (HTTP {r2.status})")
except Exception as e:
    print(f"[ERROR] Stock Dashboard port 5051 check failed: {e}")

# Start index engine and nifty50 engine via Dashboard API
print("\nStarting Index and Nifty 50 engines via Dashboard API...")
try:
    req1 = urllib.request.Request("http://127.0.0.1:5050/api/programs/index/start", data=b"{}", headers={"Content-Type": "application/json"})
    res1 = urllib.request.urlopen(req1).read().decode("utf-8")
    print(f"Index Engine Start: {res1}")
except Exception as e:
    print(f"Index engine start failed: {e}")

try:
    req2 = urllib.request.Request("http://127.0.0.1:5050/api/programs/nifty50/start", data=b"{}", headers={"Content-Type": "application/json"})
    res2 = urllib.request.urlopen(req2).read().decode("utf-8")
    print(f"Nifty 50 Engine Start: {res2}")
except Exception as e:
    print(f"Nifty 50 engine start failed: {e}")
