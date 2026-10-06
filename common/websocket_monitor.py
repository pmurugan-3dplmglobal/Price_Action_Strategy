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
    def __init__(self, api_key, access_token, failsafe_start_time="09:50"):
        self.api_key = api_key
        self.access_token = access_token
        self.failsafe_start_str = failsafe_start_time
        self.kws = None
        self.subscribed_tokens = set()
        self.radar_candidates = {}          # int_token -> candidate_dict (Category A+)
        self.radar_tokens = set()           # set of int tokens for Category A+ radar
        self.radar_callbacks = []           # list of callable(cand, live_price, tick_data)
        self.radar_triggered_tokens = set() # tokens already triggered to prevent duplicate execution
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

    def is_connected(self):
        """Check if underlying WebSocket is open and connected."""
        if not self.kws or not self.is_running:
            return False
        try:
            if hasattr(self.kws, "is_connected"):
                return bool(self.kws.is_connected()) and getattr(self.kws, "ws", None) is not None
            return getattr(self.kws, "ws", None) is not None
        except Exception:
            return False

    def on_ticks(self, ws, ticks):
        """KiteTicker tick handler: updates live LTP map and evaluates radar breakout triggers."""
        now_ts = time.time()
        triggered_cands = []
        with self._map_lock:
            for t in ticks:
                token = t.get("instrument_token")
                last_price = t.get("last_price")
                if token and last_price:
                    int_tok = int(token)
                    self.live_ltp_map[int_tok] = {
                        "ltp": float(last_price),
                        "timestamp": now_ts
                    }
                    # Check Category A+ Event-Driven Radar Triggers
                    if int_tok in self.radar_candidates and int_tok not in self.radar_triggered_tokens:
                        cand = self.radar_candidates[int_tok]
                        bm = float(cand.get("benchmark") or 0.0)
                        t1 = float(cand.get("t1") or 0.0)
                        if bm > 0 and float(last_price) >= bm:
                            # Anti-Exploded check: If tick already surged > 20% into T1, skip
                            t1_span = (t1 - bm) if (t1 > bm) else (bm * 0.15)
                            if (float(last_price) - bm) <= (0.20 * t1_span):
                                self.radar_triggered_tokens.add(int_tok)
                                triggered_cands.append((cand, float(last_price), t))

        for cand, ltp_val, tick_data in triggered_cands:
            logging.info(
                f"⚡ [WEBSOCKET RADAR TRIGGER] Sub-second breakout triggered for "
                f"{cand.get('contract') or cand.get('symbol')} at ₹{ltp_val:.2f} >= BM ₹{cand.get('benchmark')}! Dispatching callbacks..."
            )
            for cb in self.radar_callbacks:
                try:
                    threading.Thread(target=cb, args=(cand, ltp_val, tick_data), daemon=True).start()
                except Exception as cb_err:
                    logging.error(f"[WEBSOCKET RADAR] Callback execution failed: {cb_err}")

    def on_connect(self, ws, response):
        """KiteTicker connect handler: subscribes to active positions and radar candidates."""
        logging.info("[WEBSOCKET] KiteTicker connected successfully.")
        with self._map_lock:
            tokens_to_sub = list(self.subscribed_tokens | self.radar_tokens)
        if tokens_to_sub:
            try:
                ws.subscribe(tokens_to_sub)
                ws.set_mode(ws.MODE_FULL, tokens_to_sub)
                logging.info(f"[WEBSOCKET] Connected & subscribed to {len(tokens_to_sub)} active position + radar token(s): {tokens_to_sub}")
            except Exception as sub_err:
                logging.warning(f"[WEBSOCKET] Subscription in on_connect failed: {sub_err}")

    def start(self):
        """Initialize and start KiteTicker WebSocket connection in background thread."""
        if self.is_running and self.kws:
            return
        try:
            from kiteconnect import KiteTicker
            self.kws = KiteTicker(self.api_key, self.access_token)

            # Mute internal verbose kiteconnect.ticker ERROR logs for normal network blips/reconnects
            logging.getLogger("kiteconnect.ticker").setLevel(logging.CRITICAL)

            def on_close(ws, code, reason):
                logging.warning(f"[WEBSOCKET] KiteTicker closed: {code} - {reason}")

            def on_error(ws, code, reason):
                reason_str = str(reason)
                if "403" in reason_str or "Forbidden" in reason_str:
                    logging.warning(f"[WEBSOCKET] KiteTicker auth expired (403 Forbidden). Falling back to REST polling.")
                elif "timeout" in reason_str.lower() or code == 1006:
                    logging.warning(f"[WEBSOCKET] KiteTicker connection blip ({code}): {reason_str}. Retrying...")
                else:
                    logging.error(f"[WEBSOCKET] KiteTicker error: {code} - {reason}")

            def on_reconnect(ws, attempts_count):
                logging.info(f"[WEBSOCKET] Reconnecting KiteTicker (attempt {attempts_count})...")

            def on_noreconnect(ws):
                logging.warning("[WEBSOCKET] KiteTicker reconnection failed permanently. Operating in REST mode.")

            self.kws.on_ticks = self.on_ticks
            self.kws.on_connect = self.on_connect
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

        with self._map_lock:
            all_needed_before = self.subscribed_tokens | self.radar_tokens
            new_tokens = current_tokens - all_needed_before
            stale_tokens = (self.subscribed_tokens - current_tokens) - self.radar_tokens
            self.subscribed_tokens = current_tokens

        # If socket is not yet open (e.g. before initial handshake or during reconnection),
        # skip wire calls. on_connect will dispatch subscriptions when the socket connects.
        if not self.is_connected():
            return

        if new_tokens:
            try:
                self.kws.subscribe(list(new_tokens))
                self.kws.set_mode(self.kws.MODE_FULL, list(new_tokens))
                logging.info(f"[WEBSOCKET] Subscribed to {len(new_tokens)} active position token(s): {list(new_tokens)}")
            except AttributeError:
                # Underlying ws disconnected/reset mid-call
                pass
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Subscription failed: {e}")

        if stale_tokens:
            try:
                self.kws.unsubscribe(list(stale_tokens))
                logging.info(f"[WEBSOCKET] Unsubscribed from {len(stale_tokens)} completed token(s).")
            except AttributeError:
                # Underlying ws disconnected/reset mid-call
                pass
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Unsubscription failed: {e}")

    def update_radar_candidates(self, candidates):
        """
        Dynamically register Category A+ radar candidates with KiteTicker for sub-second tick execution.
        Subscribes tokens without disturbing active position subscriptions.
        """
        if not candidates:
            with self._map_lock:
                stale_tokens = self.radar_tokens - self.subscribed_tokens
                self.radar_tokens = set()
                self.radar_candidates = {}
            if self.is_connected() and stale_tokens:
                try:
                    self.kws.unsubscribe(list(stale_tokens))
                except Exception:
                    pass
            return

        new_radar_map = {}
        cand_list = candidates.values() if isinstance(candidates, dict) else candidates
        for item in cand_list:
            if not isinstance(item, dict):
                continue
            tok = item.get("option_token") or item.get("token") or item.get("spot_token")
            if tok:
                try:
                    new_radar_map[int(tok)] = item
                except Exception:
                    pass

        with self._map_lock:
            current_radar_tokens = set(new_radar_map.keys())
            all_needed_before = self.subscribed_tokens | self.radar_tokens
            new_tokens = current_radar_tokens - all_needed_before
            stale_tokens = (self.radar_tokens - current_radar_tokens) - self.subscribed_tokens
            self.radar_tokens = current_radar_tokens
            self.radar_candidates = new_radar_map

        if not self.is_connected():
            return

        if new_tokens:
            try:
                self.kws.subscribe(list(new_tokens))
                self.kws.set_mode(self.kws.MODE_FULL, list(new_tokens))
                logging.info(f"[WEBSOCKET] Subscribed to {len(new_tokens)} Category A+ radar token(s): {list(new_tokens)}")
            except AttributeError:
                pass
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Radar candidate subscription failed: {e}")

        if stale_tokens:
            try:
                self.kws.unsubscribe(list(stale_tokens))
                logging.info(f"[WEBSOCKET] Unsubscribed from {len(stale_tokens)} evicted radar token(s).")
            except AttributeError:
                pass
            except Exception as e:
                logging.warning(f"[WEBSOCKET] Radar candidate unsubscription failed: {e}")

    def register_radar_callback(self, callback):
        """Register a callback func(cand, live_tick_price, tick_data) invoked when a Category A+ candidate triggers."""
        if callback and callback not in self.radar_callbacks:
            self.radar_callbacks.append(callback)

    def clear_triggered_radar_token(self, token):
        """Allow re-triggering for a token if execution was rejected or trade reset."""
        with self._map_lock:
            self.radar_triggered_tokens.discard(int(token))

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


def get_global_ws_monitor(api_key=None, access_token=None, failsafe_start_time="09:50"):
    """Singleton getter / factory for ActivePositionWebSocketMonitor."""
    global _GLOBAL_WS_MONITOR
    with _WS_LOCK:
        if _GLOBAL_WS_MONITOR is None and api_key and access_token:
            _GLOBAL_WS_MONITOR = ActivePositionWebSocketMonitor(api_key, access_token, failsafe_start_time)
            _GLOBAL_WS_MONITOR.start()
        return _GLOBAL_WS_MONITOR

