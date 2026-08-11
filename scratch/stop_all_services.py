import subprocess, os, json

def stop_all():
    my_pid = os.getpid()
    ps_cmd = 'powershell -Command "Get-CimInstance Win32_Process -Filter \\"name = \'python.exe\'\\" | Select-Object ProcessId, CommandLine | ConvertTo-Json"'
    try:
        raw = subprocess.check_output(ps_cmd, shell=True).decode("utf-8", errors="ignore")
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
    except Exception as e:
        print(f"Error listing processes via PowerShell: {e}")
        return

    killed = 0
    for item in data:
        pid = item.get("ProcessId")
        cmd = item.get("CommandLine") or ""
        if not pid or pid == my_pid:
            continue
        if any(k in cmd for k in ["Trade_", "scanner", "app_option", "app_Sock", "engine", "exporter"]):
            print(f"Stopping service PID {pid}: {cmd[:100]}")
            subprocess.run(f"powershell -Command \"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue\"", shell=True)
            killed += 1

    print(f"\nSuccessfully stopped {killed} running service process(es).")

if __name__ == "__main__":
    stop_all()
