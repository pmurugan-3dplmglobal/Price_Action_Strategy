"""
routes_positions.py — Position management routes:
  /api/edit-lock
  /api/update-position
  /api/buy-scanned-trade
  /api/exit-position
  /api/exit-all-positions
"""
import os, json, logging
from flask import Blueprint, request, jsonify
from datetime import datetime as dt

positions_bp = Blueprint("positions_bp", __name__)


def _get_app():
    import app_Stock_Trade as _app
    return _app


# ── edit lock ─────────────────────────────────────────────────────────────────

@positions_bp.route("/api/edit-lock", methods=["POST"])
def api_edit_lock():
    _app = _get_app()
    data = request.json or {}
    sym = data.get("symbol")
    active = data.get("active", False)
    if sym:
        clean_s = str(sym).replace(" ", "").upper()
        if active:
            _app.ACTIVE_EDIT_LOCKS.add(clean_s)
            logging.info(f"[EDIT LOCK ON] Automated exit execution paused for {clean_s}")
        else:
            _app.ACTIVE_EDIT_LOCKS.discard(clean_s)
            logging.info(f"[EDIT LOCK OFF] Automated exit execution resumed for {clean_s}")
    return jsonify({"ok": True})


# ── update position (SL / targets override) ───────────────────────────────────

@positions_bp.route("/api/update-position", methods=["POST"])
def api_update_position():
    import trade_db
    from dashboard_sl_overrides import write_sl_overrides
    from trading_core import clear_executed_exit
    _app = _get_app()

    data = request.get_json(force=True, silent=True) or {}
    engine = data.get("engine", "nifty50")
    symbol = data.get("symbol", "")
    current_sl = data.get("current_sl")
    t1 = data.get("t1")
    t2 = data.get("t2")
    t3 = data.get("t3")
    entry_price = data.get("entry_price")
    if not symbol or (current_sl is None and t1 is None and t2 is None and t3 is None):
        return jsonify({"ok": False, "error": "symbol and at least one level required"}), 400
    vals = {}
    if current_sl is not None and str(current_sl).strip() != "": vals["current_sl"] = float(current_sl)
    if t1 is not None and str(t1).strip() != "": vals["t1"] = float(t1)
    if t2 is not None and str(t2).strip() != "": vals["t2"] = float(t2)
    if t3 is not None and str(t3).strip() != "": vals["t3"] = float(t3)
    if entry_price is not None and str(entry_price).strip() != "": vals["entry_spot"] = float(entry_price)
    vals["user_edited"] = True

    clean_target = str(symbol).replace(" ", "").upper()

    write_sl_overrides(engine, symbol, vals, (engine, "nifty50", "index", "daily"))

    clear_executed_exit(symbol)
    clear_executed_exit(clean_target)
    _app.ACTIVE_EDIT_LOCKS.discard(clean_target)

    matched = False

    def _is_match(item_sym, item_cnt):
        c_sym = str(item_sym or "").replace(" ", "").upper()
        c_cnt = str(item_cnt or "").replace(" ", "").upper()
        if not clean_target: return False
        if c_cnt and clean_target == c_cnt: return True
        if c_sym and clean_target == c_sym and (not c_cnt or c_cnt == c_sym): return True
        is_opt_tgt = ("CE" in clean_target or "PE" in clean_target) and any(c.isdigit() for c in clean_target)
        if not is_opt_tgt and c_sym == clean_target: return True
        return False

    with _app.data_lock:
        update_keys = list(vals.keys())

        # 1. Update in-memory all_trades
        for t in _app.cached_data.get("all_trades", []):
            if _is_match(t.get("symbol"), t.get("contract")):
                matched = True
                for k in update_keys: t[k] = vals[k]
                tid = t.get("id")
                if tid:
                    trade_db.update_trade(tid, vals)

        # 2. Update in-memory positions
        for pos_key, pos in (_app.cached_data.get("positions", {}).items() if isinstance(_app.cached_data.get("positions"), dict) else enumerate(_app.cached_data.get("positions", []))):
            if isinstance(pos, dict):
                if _is_match(pos.get("symbol"), pos.get("contract")):
                    matched = True
                    for k in update_keys: pos[k] = vals[k]
                    tid = pos.get("id")
                    if tid:
                        trade_db.update_trade(tid, vals)

        # 3. Update in-memory kite_positions so UI refreshes immediately
        for kp in _app.cached_data.get("kite_positions", []):
            if _is_match(kp.get("symbol"), kp.get("contract")):
                for k in update_keys: kp[k] = vals[k]

        if not matched:
            contract = symbol
            exchange = "NSE"
            for kp in _app.cached_data.get("kite_positions", []):
                if _is_match(kp.get("symbol"), kp.get("contract")):
                    contract = kp.get("contract", symbol)
                    exchange = kp.get("exchange", "NSE")
                    break
            is_stock = exchange == "NSE"
            trade_data = {"contract": contract, "entry_spot": vals.get("entry_spot", 0), "position_type": "stock" if is_stock else "option"}
            trade_data.update(vals)
            db_symbol = _app.resolve_underlying(symbol or contract, engine)
            tid, _created = trade_db.create_trade(engine, db_symbol, trade_data)
            entry = {"symbol": db_symbol, "contract": contract, "id": tid, "engine": engine, "status": "ACTIVE", "position_type": "stock" if is_stock else "option"}
            entry.update(vals)
            _app.cached_data["all_trades"].append(entry)
            _app.cached_data["positions"][symbol] = entry
            logging.info(f"[OVERRIDE] Created new DB trade for {engine}/{symbol}")
    logging.info(f"Position override queued: {engine}/{symbol} {vals}")
    return jsonify({"ok": True})


# ── 1-click buy ───────────────────────────────────────────────────────────────

@positions_bp.route("/api/buy-scanned-trade", methods=["POST"])
def api_buy_scanned_trade():
    import trade_db
    from trading_core import clear_executed_exit
    _app = _get_app()
    try:
        data = request.json or {}
        symbol = data.get("symbol")
        contract = data.get("contract") or symbol
        side = data.get("side", "CE")
        entry_spot = float(data.get("entry_spot") or 0)
        current_sl = float(data.get("current_sl") or data.get("sl") or 0)
        t1 = float(data.get("t1") or 0)
        t2 = float(data.get("t2") or 0)
        t3 = float(data.get("t3") or 0)
        engine = data.get("engine", "daily")

        if not symbol:
            return jsonify({"ok": False, "error": "symbol is required"}), 400

        c_str = str(contract).upper()
        if "SENSEX" in c_str or "BSE" in c_str:
            exch = "BFO"
        elif "CE" in c_str or "PE" in c_str or "NIFTY" in c_str or "BANK" in c_str:
            exch = "NFO"
        else:
            exch = "NSE"

        order_id = None
        ltp = 0
        if not _app._kite_session:
            try:
                from common.trading_core import load_kite_session
                api_k, acc_t = load_kite_session()
                if api_k and acc_t:
                    from kiteconnect import KiteConnect
                    _app._kite_session = KiteConnect(api_key=api_k)
                    _app._kite_session.set_access_token(acc_t)
            except Exception as init_err:
                logging.warning(f"1-Click Buy auto-init kite session failed: {init_err}")

        if _app._kite_session:
            try:
                q_key = f"{exch}:{contract}"
                q = _app._kite_session.quote([q_key])
                ltp = float(q.get(q_key, {}).get("last_price", 0))
                depth = q.get(q_key, {}).get("depth", {}).get("sell", [])
                bm = float(data.get("benchmark") or 0)
                if bm > 0:
                    price = round(bm * 1.005, 1)
                else:
                    ask = float(depth[0].get("price", 0)) if (depth and len(depth) > 0) else 0
                    price = round((ask if ask > 0 else ltp) * 1.005, 1)
                    if price <= 0:
                        price = round(entry_spot * 1.005, 1)

                from common.trading_core import STOCK_REGISTRY
                lot_size = STOCK_REGISTRY.get(symbol, {}).get("lot_size", 1) if exch != "NSE" else 1
                prod = _app._kite_session.PRODUCT_CNC if exch == "NSE" else _app._kite_session.PRODUCT_NRML

                order_id = _app._kite_session.place_order(
                    variety=_app._kite_session.VARIETY_REGULAR,
                    tradingsymbol=contract,
                    exchange=exch,
                    transaction_type=_app._kite_session.TRANSACTION_TYPE_BUY,
                    quantity=lot_size,
                    order_type=_app._kite_session.ORDER_TYPE_LIMIT,
                    price=price,
                    product=prod
                )
                logging.info(f"[1-CLICK BUY] Placed buy order for {contract} on {exch} (Order ID: {order_id})")
            except Exception as k_err:
                logging.warning(f"[1-CLICK BUY KITE ORDER WARNING] {contract}: {k_err}")
                return jsonify({"ok": False, "error": f"Kite Order Placement Failed: {k_err}"}), 400

        candle_a_time = data.get("candle_a_time") or data.get("CandleATime")
        benchmark = data.get("benchmark")
        anchor_floor = data.get("anchor_floor")
        direction = data.get("direction")

        if not candle_a_time:
            try:
                disp_backfill = _app.SCAN_DISPLAY_FILE
                if os.path.exists(disp_backfill):
                    with open(disp_backfill, "r", encoding="utf-8") as fh:
                        _sd = json.load(fh)
                    c_target = str(contract).replace(" ", "").upper()
                    for _cat in ["staged_trades", "all_staged_today", "carry_forward", "active_live"]:
                        for item in _sd.get(_cat) or []:
                            i_cnt = str(item.get("contract") or item.get("symbol") or "").replace(" ", "").upper()
                            if i_cnt == c_target:
                                candle_a_time = candle_a_time or item.get("candle_a_time") or item.get("CandleATime")
                                if benchmark is None:
                                    benchmark = item.get("benchmark")
                                if anchor_floor is None:
                                    anchor_floor = item.get("anchor_floor")
                                if not direction:
                                    direction = item.get("direction")
                                break
                        if candle_a_time:
                            break
            except Exception as bf_err:
                logging.warning(f"1-Click Buy display backfill skipped: {bf_err}")

        # Align option entry price with real execution/LTP price if spot price was passed or stale
        if exch != "NSE" and ltp > 0:
            if entry_spot <= 0 or (abs(entry_spot - ltp) / max(entry_spot, ltp) > 0.50):
                logging.info(f"[PRICE ALIGN] Overriding divergent entry_spot {entry_spot} with live option LTP {ltp} for {contract}")
                entry_spot = ltp

        trade_data = {
            "contract": contract,
            "entry_spot": entry_spot,
            "current_sl": current_sl,
            "t1": t1,
            "t2": t2,
            "t3": t3,
            "side": side,
            "pattern": "1CLICK_BUY",
            "position_type": "stock" if exch == "NSE" else "option",
            "user_edited": True,
            "entry_time": dt.now().isoformat()
        }
        if candle_a_time:
            trade_data["candle_a_time"] = candle_a_time
            trade_data["CandleATime"] = candle_a_time
        if benchmark is not None:
            trade_data["benchmark"] = benchmark
        if anchor_floor is not None:
            trade_data["anchor_floor"] = anchor_floor
        if direction:
            trade_data["direction"] = direction
        try:
            from trading_core import contract_is_expired
            if contract_is_expired(contract):
                return jsonify({"ok": False, "error": f"Contract {contract} is expired. Cannot place 1-Click Buy."}), 400
        except Exception as exp_check_err:
            logging.warning(f"1-Click Buy expiry check skipped: {exp_check_err}")
        symbol = _app.resolve_underlying(symbol or contract, engine)
        tid, _created = trade_db.create_trade(engine, symbol, trade_data)
        clear_executed_exit(contract)

        return jsonify({
            "ok": True,
            "message": f"Successfully placed 1-Click BUY for {contract}" + (f" (Order ID: {order_id})" if order_id else ""),
            "trade_id": tid
        })
    except Exception as e:
        logging.error(f"1-Click Buy API failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── manual exit (single & all) ────────────────────────────────────────────────

@positions_bp.route("/api/exit-position", methods=["POST"])
def api_exit_position():
    import trade_db
    _app = _get_app()
    try:
        data = request.json or {}
        symbol = data.get("symbol", "")
        contract = data.get("contract") or symbol

        if not symbol and not contract:
            return jsonify({"ok": False, "error": "Symbol or contract name required"}), 400

        target_str = str(contract or symbol).replace(" ", "").upper()
        now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")

        all_t = trade_db.get_all_trades()
        exited_ids = []
        for t in all_t:
            t_sym = str(t.get("symbol") or "").replace(" ", "").upper()
            t_cnt = str(t.get("contract") or "").replace(" ", "").upper()
            if t.get("status") == "ACTIVE" and (target_str in (t_sym, t_cnt) or t_sym in target_str or t_cnt in target_str):
                trade_db.update_trade(t["id"], {
                    "status": "USER_EXIT",
                    "exit_time": now_str,
                    "result": "USER_EXIT",
                    "updated_at": now_str
                })
                exited_ids.append(t["id"])

        if _app._kite_session:
            try:
                c_str = target_str
                if "SENSEX" in c_str or "BSE" in c_str:
                    exch = "BFO"
                elif "CE" in c_str or "PE" in c_str or "NIFTY" in c_str or "BANK" in c_str:
                    exch = "NFO"
                else:
                    exch = "NSE"

                pos_obj = {
                    "contract": contract,
                    "symbol": symbol,
                    "exchange": exch,
                    "quantity": data.get("quantity", 0)
                }
                from common.trading_core import close_position as shared_close
                shared_close(_app._kite_session, pos_obj, True)
            except Exception as k_err:
                logging.warning(f"Live exit execution warning for {contract}: {k_err}")

        for disp_path in [_app.SCAN_DISPLAY_FILE, _app.SCAN_DISPLAY_INDEX_FILE]:
            if os.path.exists(disp_path):
                try:
                    with open(disp_path, "r", encoding="utf-8") as f:
                        sd = json.load(f)
                    sd["active_positions"] = [p for p in sd.get("active_positions", []) if str(p.get("contract") or p.get("symbol")).replace(" ", "").upper() != target_str]
                    sd["active_live"] = [p for p in sd.get("active_live", []) if str(p.get("contract") or p.get("symbol")).replace(" ", "").upper() != target_str]
                    with open(disp_path, "w", encoding="utf-8") as f:
                        json.dump(sd, f, indent=2)
                except Exception:
                    pass

        return jsonify({"ok": True, "message": f"Manual EXIT executed for {contract or symbol}"})
    except Exception as e:
        logging.error(f"Manual Exit API failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@positions_bp.route("/api/exit-all-positions", methods=["POST"])
def api_exit_all_positions():
    import trade_db
    _app = _get_app()
    try:
        now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        all_t = trade_db.get_all_trades()
        exited_count = 0
        for t in all_t:
            if t.get("status") == "ACTIVE":
                trade_db.update_trade(t["id"], {
                    "status": "USER_EXIT",
                    "exit_time": now_str,
                    "result": "USER_EXIT",
                    "updated_at": now_str
                })
                exited_count += 1

        for disp_path in [_app.SCAN_DISPLAY_FILE, _app.SCAN_DISPLAY_INDEX_FILE]:
            if os.path.exists(disp_path):
                try:
                    with open(disp_path, "r", encoding="utf-8") as f:
                        sd = json.load(f)
                    sd["active_positions"] = []
                    sd["active_live"] = []
                    with open(disp_path, "w", encoding="utf-8") as f:
                        json.dump(sd, f, indent=2)
                except Exception:
                    pass

        return jsonify({"ok": True, "message": f"Successfully EXITED all ({exited_count}) active positions"})
    except Exception as e:
        logging.error(f"Exit All API failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
