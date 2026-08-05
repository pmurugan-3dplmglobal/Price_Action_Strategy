import os
import sys
import atexit
import signal
import logging

PID_DIR = "output/monitor"
_cleanup_done = False

def _cleanup_pid(engine_id):
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    pf = os.path.join(PID_DIR, f"{engine_id}.pid")
    try:
        if os.path.exists(pf):
            with open(pf) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(pf)
                    logging.info(f"PID file removed: {pf}")
    except Exception:
        pass

def _signal_handler(engine_id, signum, frame):
    logging.info(f"Received signal {signum}, shutting down {engine_id}...")
    _cleanup_pid(engine_id)
    sys.exit(0)

def check_pid_file(engine_id):
    os.makedirs(PID_DIR, exist_ok=True)
    pf = os.path.join(PID_DIR, f"{engine_id}.pid")
    if os.path.exists(pf):
        try:
            with open(pf) as f:
                old_pid = int(f.read().strip())
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x100000, False, old_pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    logging.warning(f"{engine_id} already running (PID {old_pid}), exiting")
                    sys.exit(0)
            else:
                os.kill(old_pid, 0)
                logging.warning(f"{engine_id} already running (PID {old_pid}), exiting")
                sys.exit(0)
        except (ValueError, ProcessLookupError, OSError):
            logging.info(f"Stale PID file {pf} removed")
            try:
                os.remove(pf)
            except Exception:
                pass
    with open(pf, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(_cleanup_pid, engine_id)
    signal.signal(signal.SIGTERM, lambda s, f: _signal_handler(engine_id, s, f))
    signal.signal(signal.SIGINT, lambda s, f: _signal_handler(engine_id, s, f))
    logging.info(f"PID {os.getpid()} registered: {pf}")

def is_pid_alive(engine_id):
    pf = os.path.join(PID_DIR, f"{engine_id}.pid")
    if not os.path.exists(pf):
        return False
    try:
        with open(pf) as f:
            pid = int(f.read().strip())
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False

def remove_pid_file(engine_id):
    pf = os.path.join(PID_DIR, f"{engine_id}.pid")
    try:
        if os.path.exists(pf):
            os.remove(pf)
    except Exception:
        pass

ENGINE_PID_NAMES = {
    "bull_index": "live-trade/bull_index_engine.py",
    "bear_index": "live-trade/bear_index_engine.py",
    "bull_nifty50": "live-trade/bull_nifty50_scanner.py",
    "bear_nifty50": "live-trade/bear_nifty50_scanner.py",
    "bull_daily": "live-trade/bull_nifty50_daily_scanner.py",
    "bear_daily": "live-trade/bear_nifty50_daily_scanner.py",
}

def get_running_engines():
    running = {}
    for eid, script in ENGINE_PID_NAMES.items():
        if is_pid_alive(eid):
            pf = os.path.join(PID_DIR, f"{eid}.pid")
            with open(pf) as f:
                running[eid] = int(f.read().strip())
    return running
