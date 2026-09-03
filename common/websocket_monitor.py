# KiteTicker WebSocket Monitor for Active Positions
# Integrates sub-second tick feeds, 09:45 AM opening volatility guard & UI Active Edit Lock
import logging
import threading
import time
from datetime import datetime as dt, time as datetime_time
from timeframe_utils import get_ist_now

_GLOBAL_WS_MONITOR = None
_WS_LOCK = threading.Lock()

class ActivePositionWebSocketMonitor:
    """
    WebSocket streaming tick monitor for active positions using KiteTicker.
    Performs real-time tick-level monitoring with 09:45 AM Opening Market Volatility Guard,
    automatic token subscription synchronization, and graceful fallback to REST.
    """
    def __init__(self, api_key, access_token, failsafe_start_time="09:45"):
        self.api_key = api_key
        self.access_token = access_token
        self.failsafe_start_str = failsafe_start_time
        self.kws = None
        self.subscribed_tokens = set()
        self.live_ltp_map = {}  # token -> {"ltp": float, "timestamp": float}
        self.is_running = False
        self._thread = None
        self.edit_locks = set()
        self._map_lock = threading.Lock()
        
        try:
            f_h, f_m = map(int, failsafe_start_time.split(":"))
            self.fs_start_t = datetime_time(f_h, f_m)
        except Exception:
            self.fs_start_t = datetime_time(9, 45)

    def set_ui_edit_lock(self, symbol, is_locked=True):
        """Set or clear UI edit lock for a specific symbol."""
        clean_s = str(symbol).strip().upper()
        if is_locked:
            self.edit_locks.add(clean_s)
        else:
            self.edit_locks.discard(clean_s)

    def get_ltp(self, token, max_age_seconds=15.0):
        """
        Retrieve latest WebSocket LTP for token if fresh.
        Returns: (ltp_float, is_fresh_bool)
        """
        if not token:
            return 0.0, False
        tok = int(token)
        with self._map_lock:
            info = self.live_ltp_map.get(tok)
            if not info:
                return 0.0, False
            age = time.time() - info.get("timestamp", 0)
            is_fresh = (age <= max_age_seconds)
            return float(info.get("ltp", 0.0)), is_fresh

    def start(self):
        """Initialize and start KiteTicker WebSocket connection in background thread."""
        if self.is_running and self.kws:
            return
        try:
            from kiteconnect import KiteTicker
            self.kws = KiteTicker(self.api_key, self.access_token)
            
            def on_ticks(ws, ticks):
                now_ts = time.time()
                with self._map_lock:
                    for t in ticks:
                        token = t.get("instrument_token")
                        last_price = t.get("last_price")
                        if token and last_price:
                            self.live_ltp_map[int(token)] = {
                                "ltp": float(last_price),
                                "timestamp": now_ts
                            }

            def on_connect(ws, response):
                logging.info("[WEBSOCKET] KiteTicker connected successfully.")
                if self.subscribed_tokens:
                    ws.subscribe(list(self.subscribed_tokens))
                    ws.set_mode(ws.MODE_FULL, list(self.subscribed_tokens))

            def on_close(ws, code, reason):
                logging.warning(f"[WEBSOCKET] KiteTicker closed: {code} - {reason}")

            def on_error(ws, code, reason):
                logging.error(f"[WEBSOCKET] KiteTicker error: {code} - {reason}")

            def on_reconnect(ws, attempts_count):
                logging.info(f"[WEBSOCKET] Reconnecting KiteTicker (attempt {attempts_count})...")

            def on_noreconnect(ws):
                logging.warning("[WEBSOCKET] KiteTicker reconnection failed permanently.")

            self.kws.on_ticks = on_ticks
            self.kws.on_connect = on_connect
            self.kws.on_close = on_close
            self.kws.on_error = on_error
            self.kws.on_reconnect = on_reconnect
            self.kws.on_noreconnect = on_noreconnect

            self.kws.connect(threaded=True)
            self.is_running = True
            logging.info("[WEBSOCKET] Active position tick monitor started in background.")
        except Exception as e:
            logging.warning(f"[WEBSOCKET] Failed to initialize KiteTicker (falling back to REST): {e}")

    def update_subscriptions(self, active_positions):
        """Subscribe or unsubscribe tokens dynamically based on active positions dict."""
        if not self.kws or not self.is_running:
            return
        
        current_tokens = set()
        for sym, pos in active_positions.items():
            tok = pos.get("option_token") or pos.get("token")
            if tok:
                try:
                    current_tokens.add(int(tok))
                except Exception:
                    pass

        new_tokens = current_tokens - self.subscribed_tokens
        stale_tokens = self.subscribed_tokens - current_tokens

        if new_tokens:
            try:
                self.kws.subscribe(list(new_tokens))
                self.kws.set_mode(self.kws.MODE_FULL, list(new_tokens))
                self.subscribed_tokens.update(new_tokens)
                logging.info(f"[WEBSOCKET] Subscribed to {len(new_tokens)} active position token(s): {list(new_tokens)}")
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Subscription failed: {e}")

        if stale_tokens:
            try:
                self.kws.unsubscribe(list(stale_tokens))
                self.subscribed_tokens.difference_update(stale_tokens)
                logging.info(f"[WEBSOCKET] Unsubscribed from {len(stale_tokens)} completed token(s).")
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Unsubscription failed: {e}")

    def can_execute_exit(self, symbol):
        """
        Safety Checks before executing tick-level position exit:
        1. Checks 09:45 AM Opening Market Volatility Guard.
        2. Checks UI Active Edit Lock.
        """
        if get_ist_now().time() < self.fs_start_t:
            logging.info(f"[WEBSOCKET FLEX PAUSE BEFORE {self.failsafe_start_str} AM] Exit check paused for {symbol}.")
            return False

        clean_s = str(symbol).strip().upper()
        if clean_s in self.edit_locks:
            logging.info(f"[WEBSOCKET EDIT LOCK PAUSE] Position {clean_s} is currently being edited on UI.")
            return False

        return True

    def stop(self):
        """Stop WebSocket connection cleanly."""
        if self.kws:
            try:
                self.kws.close()
                self.is_running = False
                logging.info("[WEBSOCKET] Active position tick monitor stopped.")
            except Exception:
                pass


def get_global_ws_monitor(api_key=None, access_token=None, failsafe_start_time="09:45"):
    """Singleton getter / factory for ActivePositionWebSocketMonitor."""
    global _GLOBAL_WS_MONITOR
    with _WS_LOCK:
        if _GLOBAL_WS_MONITOR is None and api_key and access_token:
            _GLOBAL_WS_MONITOR = ActivePositionWebSocketMonitor(api_key, access_token, failsafe_start_time)
            _GLOBAL_WS_MONITOR.start()
        return _GLOBAL_WS_MONITOR

