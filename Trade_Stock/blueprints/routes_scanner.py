"""
routes_scanner.py — Scanner process management routes:
  /api/programs/<prog_id>/start
  /api/programs/<prog_id>/stop
  /api/scan/clear
  /api/scan/ema/clear
  /api/scan/export
  /api/export/ema
  /api/export/monthly
  /api/anchor/scan
  /api/anchor/stop
  /api/anchor/status
  /api/logs/clear
"""
import os, json, csv, subprocess, sys
from flask import Blueprint, request, jsonify, Response
from datetime import datetime as dt

scanner_bp = Blueprint("scanner_bp", __name__)


def _get_app():
    import app_Stock_Trade as _app
    return _app


# ── scanner start/stop ────────────────────────────────────────────────────────

@scanner_bp.route("/api/programs/<prog_id>/start", methods=["POST"])
def api_start(prog_id):
    _app = _get_app()
    from ema_engine import start_ema_engine
    if prog_id not in _app.PROGRAMS:
        return jsonify({"ok": False, "error": "Unknown program"})
    token = _app.check_token_valid()
    if not token["valid"]:
        return jsonify({"ok": False, "error": token["reason"]})
    if prog_id == "ema_engine":
        cfg = _app.load_config()
        tf = cfg.get("ema_engine", {}).get("timeframe", "1d")
        tu = cfg.get("ema_engine", {}).get("target_universe", "ALL")
        interval = int(cfg.get("ema_engine", {}).get("scan_interval", 300))
        ok, msg = start_ema_engine(timeframe=tf, is_options_mode=False, scan_interval=interval, target_universe=tu)
        return jsonify({"ok": ok, "error": None if ok else msg})
    ok = _app.start_program(prog_id)
    return jsonify({"ok": ok, "error": None if ok else "Start failed"})


@scanner_bp.route("/api/programs/<prog_id>/stop", methods=["POST"])
def api_stop(prog_id):
    _app = _get_app()
    from ema_engine import stop_ema_engine
    if prog_id not in _app.PROGRAMS:
        return jsonify({"ok": False, "error": "Unknown program"})
    if prog_id == "ema_engine":
        ok, msg = stop_ema_engine(is_options_mode=False)
        return jsonify({"ok": ok, "error": None if ok else msg})
    ok = _app.stop_program(prog_id)
    return jsonify({"ok": ok})


# ── scan display clear ────────────────────────────────────────────────────────

@scanner_bp.route("/api/scan/clear", methods=["POST"])
def api_scan_clear():
    import paths
    import trade_db
    _app = _get_app()
    now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = dt.now().strftime("%Y-%m-%d")
    for f in [paths.SCAN_DISPLAY_FILE, paths.SCAN_DISPLAY_INDEX_FILE, paths.SCAN_DISPLAY_STOCK_FILE,
              paths.SCAN_DISPLAY_BEAR_FILE, paths.SCAN_DISPLAY_WEEKLY_FILE, paths.SCAN_DISPLAY_WEEKLY_BEAR_FILE]:
        try:
            empty_scan = {
                "date": today_str,
                "timestamp": now_str,
                "cleared_at": now_str,
                "staged_trades": [],
                "all_staged_today": [],
                "carry_forward": [],
                "active_live": []
            }
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(empty_scan, fh, indent=2)
        except Exception:
            pass
    try:
        if os.path.exists(paths.CYCLE_STORE_FILE):
            with open(paths.CYCLE_STORE_FILE, "w", encoding="utf-8") as fh:
                json.dump({}, fh)
    except Exception:
        pass
    try:
        for eng in ["daily", "bear_trade", "weekly", "weekly_bear", "nifty50", "index"]:
            trade_db.clear_cycle_trades(eng)
    except Exception:
        pass
    _app._file_mtime_cache.clear()
    _app._parsed_json_cache.clear()
    with _app.data_lock:
        for k in ["daily", "bear_trade", "weekly", "weekly_bear", "nifty50", "index"]:
            _app.cached_data["scan_display"][k] = {
                "staged_trades": [], "all_staged_today": [], "carry_forward": [],
                "active_live": [], "cleared_at": now_str
            }
    return jsonify({"ok": True})


@scanner_bp.route("/api/scan/ema/clear", methods=["POST"])
def api_scan_ema_clear():
    import paths
    _app = _get_app()
    now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    for ema_file in [paths.SCAN_DISPLAY_EMA_FILE, paths.SCAN_DISPLAY_EMA_STOCK_FILE]:
        try:
            empty_scan = {
                "ema_engine": {"staged_trades": [], "all_staged_today": [], "carry_forward": [], "active_live": []},
                "last_updated": now_str,
                "cleared_at": now_str
            }
            os.makedirs(os.path.dirname(ema_file), exist_ok=True)
            with open(ema_file, "w", encoding="utf-8") as fh:
                json.dump(empty_scan, fh, indent=2)
        except Exception:
            pass
    with _app.data_lock:
        _app.cached_data["ema_scan"] = {
            "ema_engine": {"staged_trades": [], "all_staged_today": [], "carry_forward": [], "active_live": []},
            "last_updated": now_str,
            "cleared_at": now_str
        }
    return jsonify({"ok": True})


# ── scan export ───────────────────────────────────────────────────────────────

@scanner_bp.route("/api/scan/export", methods=["POST"])
def api_scan_export():
    _app = _get_app()
    try:
        import io
        from spot_enricher import extract_underlying_symbol, evaluate_spot_trend_and_t1
        import paths
        from ema_engine import EMA_DISPLAY_FILE_STOCK
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Symbol", "Contract", "Side", "Tier", "Entry", "SL", "T1", "T2", "T3",
                         "AncherT", "EntryTime", "Result", "CF", "RR", "Engine", "Status",
                         "Spot_Trend", "Spot_T1_Target"])
        files = [
            ("Daily", _app.SCAN_DISPLAY_FILE),
            ("Bear", _app.SCAN_DISPLAY_BEAR_FILE),
            ("Weekly Bull", paths.SCAN_DISPLAY_WEEKLY_FILE),
            ("Weekly Bear", paths.SCAN_DISPLAY_WEEKLY_BEAR_FILE),
            ("Stock EMA", EMA_DISPLAY_FILE_STOCK)
        ]
        spot_eval_cache = {}
        for label, path in files:
            full = os.path.join(_app.BASE_DIR, path)
            if not os.path.exists(full):
                continue
            with open(full) as f:
                data = json.load(f)
            if isinstance(data, dict) and "ema_engine" in data:
                data = data["ema_engine"]
            for section_name, status_tag in [("staged_trades", "Staged"), ("active_live", "Active"), ("carry_forward", "CarryFwd")]:
                for t in data.get(section_name, []):
                    raw_sym = t.get("contract") or t.get("symbol") or ""
                    underlying = extract_underlying_symbol(raw_sym)
                    if underlying and underlying not in spot_eval_cache:
                        spot_eval_cache[underlying] = evaluate_spot_trend_and_t1(None, underlying)
                    spot_trend, spot_t1 = spot_eval_cache.get(underlying, ("N/A", "N/A"))
                    formatted_spot_t1 = _app._format_float(spot_t1) if isinstance(spot_t1, (int, float)) else str(spot_t1)

                    tb_raw = t.get("tier_badge") or t.get("tier_label")
                    if not tb_raw:
                        t_num = int(t.get("tier", 2))
                        tb_raw = "🥇 T1" if t_num == 1 else ("🥈 T2" if t_num == 2 else "🥉 T3")

                    writer.writerow([
                        t.get("symbol", ""),
                        t.get("contract", ""),
                        t.get("side", ""),
                        tb_raw,
                        _app._format_float(t.get("entry") or t.get("entry_spot")),
                        _app._format_float(t.get("sl") or t.get("current_sl")),
                        _app._format_float(t.get("t1")),
                        _app._format_float(t.get("t2")),
                        _app._format_float(t.get("t3")),
                        _app._format_timestamp(t.get("candle_a_time")),
                        _app._format_timestamp(t.get("entry_time")),
                        _app._format_pattern_result(t.get("pattern") or t.get("result")),
                        "Yes" if t.get("carry_forward") else "No",
                        _app._format_float(t.get("rr")),
                        label,
                        status_tag,
                        spot_trend,
                        formatted_spot_t1
                    ])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(csv_bytes, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=scan_export_{dt.now().strftime('%d_%m_%y_%H%M')}.csv"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@scanner_bp.route("/api/export/ema", methods=["POST"])
def api_export_ema():
    _app = _get_app()
    try:
        import io
        from ema_engine import EMA_DISPLAY_FILE_STOCK
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Symbol", "Contract", "Side", "Entry", "SL", "T1", "T2", "T3",
                         "Spot", "RR", "Timeframe", "Pattern", "AncherT", "EntryTime", "Status"])
        full = EMA_DISPLAY_FILE_STOCK if os.path.isabs(EMA_DISPLAY_FILE_STOCK) else os.path.join(_app.BASE_DIR, EMA_DISPLAY_FILE_STOCK)
        if os.path.exists(full):
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
            ema_payload = data.get("ema_engine", data) if isinstance(data, dict) else {}
            for section_name, status_tag in [("staged_trades", "Staged"), ("active_live", "Active"), ("carry_forward", "CarryFwd")]:
                for t in ema_payload.get(section_name, []):
                    side_val = t.get("side", "")
                    if not side_val:
                        cnt_str = str(t.get("contract") or t.get("symbol") or "").upper()
                        if "CE" in cnt_str:
                            side_val = "CE"
                        elif "PE" in cnt_str:
                            side_val = "PE"
                    writer.writerow([
                        t.get("symbol", ""),
                        t.get("contract", ""),
                        side_val,
                        _app._format_float(t.get("entry")),
                        _app._format_float(t.get("sl") or t.get("current_sl")),
                        _app._format_float(t.get("t1")),
                        _app._format_float(t.get("t2")),
                        _app._format_float(t.get("t3")),
                        _app._format_float(t.get("entry_spot")),
                        _app._format_float(t.get("rr")),
                        t.get("timeframe", ""),
                        t.get("pattern", ""),
                        _app._format_timestamp(t.get("candle_a_time")),
                        _app._format_timestamp(t.get("entry_time")),
                        status_tag
                    ])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(csv_bytes, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=ema_export_{dt.now().strftime('%d_%m_%y_%H%M')}.csv"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@scanner_bp.route("/api/export/monthly", methods=["POST"])
def api_export_monthly():
    _app = _get_app()
    result = _app.run_monthly_export()
    return jsonify({"ok": True, **result})


# ── anchor scan ───────────────────────────────────────────────────────────────

@scanner_bp.route("/api/anchor/scan", methods=["POST"])
def api_anchor_scan():
    import time
    _app = _get_app()
    data = request.get_json(silent=True) or {}
    engine = data.get("engine", "index")
    try:
        with _app.data_lock:
            _app.cached_data["anchor_status"]["running"] = True
            _app.cached_data["anchor_status"]["engine"] = engine
            _app.cached_data["anchor_status"]["requested_at"] = time.time()
        if os.path.exists(_app.ANCHOR_SCAN_STOP_FILE):
            os.remove(_app.ANCHOR_SCAN_STOP_FILE)
        script = _app.PROGRAMS.get(engine, {}).get("file")
        if script:
            script_path = os.path.join(_app.BASE_DIR, script)
            subprocess.Popen([sys.executable, script_path, "--anchor-only"],
                             cwd=_app.BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@scanner_bp.route("/api/anchor/stop", methods=["POST"])
def api_anchor_stop():
    _app = _get_app()
    try:
        os.makedirs(os.path.dirname(_app.ANCHOR_SCAN_STOP_FILE), exist_ok=True)
        with open(_app.ANCHOR_SCAN_STOP_FILE, "w") as f:
            f.write("stop")
        with _app.data_lock:
            _app.cached_data["anchor_status"]["running"] = False
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@scanner_bp.route("/api/anchor/status")
def api_anchor_status():
    _app = _get_app()
    with _app.data_lock:
        st = dict(_app.cached_data["anchor_status"])
    if not st.get("running"):
        still_running = os.path.exists(_app.ANCHOR_SCAN_REQUEST_FILE) and not os.path.exists(_app.ANCHOR_SCAN_STOP_FILE)
        if still_running:
            st["running"] = True
            if not st.get("engine"):
                try:
                    with open(_app.ANCHOR_SCAN_REQUEST_FILE) as f:
                        st["engine"] = f.read().strip()
                except Exception:
                    pass
    return jsonify(st)


# ── logs clear ────────────────────────────────────────────────────────────────

@scanner_bp.route("/api/logs/clear", methods=["POST"])
def api_logs_clear():
    _app = _get_app()
    log_files = [_app.DAILY_LOG_FILE, _app.BEAR_LOG_FILE, _app.EMA_LOG_FILE]
    for lf in log_files:
        try:
            if os.path.exists(lf):
                open(lf, "w").close()
        except Exception:
            pass
    with _app.data_lock:
        for pid in _app.PROGRAMS:
            _app.cached_data["log_tail"][pid] = []
            _app.cached_data["scans"][pid] = []
            _app.cached_data["scan_summary"][pid] = {"anchors": {}, "abc_matches": {}}
    return jsonify({"ok": True})
