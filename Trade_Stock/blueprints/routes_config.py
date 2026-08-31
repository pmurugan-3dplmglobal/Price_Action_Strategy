"""
routes_config.py — Configuration routes:
  /api/config/<prog_id>  (save config)
  /api/status            (status / programs / scan data)
  /api/live-execution/*
"""
from flask import Blueprint, request, jsonify, render_template_string

config_bp = Blueprint("config_bp", __name__)


def _get_app():
    import app_Stock_Trade as _app
    return _app


# ── main dashboard & status ───────────────────────────────────────────────────

@config_bp.route("/")
def dashboard():
    from flask import session
    _app = _get_app()
    import os
    with open(_app.TEMPLATE_PATH, encoding="utf-8") as _template_f:
        tpl = _template_f.read()
    return render_template_string(
        tpl,
        refresh=_app.REFRESH_SECONDS,
        programs=_app.PROGRAMS,
        user=session.get("user", ""),
        role=session.get("role", "")
    )


@config_bp.route("/api/status")
def api_status():
    _app = _get_app()
    from ema_engine import get_ema_engine_status, get_ema_scan_data
    with _app.data_lock:
        prog_status = {}
        for pid in _app.PROGRAMS:
            if pid == "ema_engine":
                pid_running = get_ema_engine_status(is_options_mode=False)
            else:
                pid_running = _app.get_pid_for_program(pid) is not None
            log_lines = _app.cached_data["log_tail"].get(pid, [])
            if not log_lines and _app.PROGRAMS[pid].get("log_file"):
                log_lines = _app.tail_log(_app.PROGRAMS[pid].get("log_file"))
            prog_status[pid] = {
                "running": pid_running,
                "scans": _app.cached_data["scans"].get(pid, []),
                "log_tail": log_lines,
                "scan_summary": _app.cached_data["scan_summary"].get(pid, {"anchors": {}, "abc_matches": {}})
            }
        cfg = _app.load_config()
        return jsonify({
            "programs": prog_status,
            "positions": _app.cached_data["positions"],
            "all_trades": _app.cached_data["all_trades"],
            "kite_positions": _app.cached_data["kite_positions"],
            "ltp": {str(k): v for k, v in _app.cached_data["ltp"].items()},
            "journal": _app.cached_data["journal"],
            "stats": _app.cached_data["stats"],
            "config": cfg,
            "scan_display": _app.cached_data["scan_display"],
            "ema_scan": get_ema_scan_data(is_options_mode=False),
            "live_execution": _app.cached_data["live_execution"],
            "live_execution_index": _app.cached_data["live_execution_index"],
            "executed_exits": _app.cached_data.get("executed_exits", {}),
            "expired_contracts": _app.cached_data.get("expired_contracts", [])
        })


# ── program config save ───────────────────────────────────────────────────────

@config_bp.route("/api/config/<prog_id>", methods=["POST"])
def api_save_config(prog_id):
    _app = _get_app()
    if prog_id not in _app.PROGRAMS:
        return jsonify({"ok": False, "error": "Unknown program"})
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False, "error": "Invalid JSON"})
    _app.save_config(prog_id, data)
    return jsonify({"ok": True})


# ── live execution flags ──────────────────────────────────────────────────────

@config_bp.route("/api/live-execution/nifty50", methods=["GET", "POST"])
def api_live_execution():
    import os
    _app = _get_app()
    if request.method == "POST":
        enabled = request.get_json(force=True, silent=True).get("enabled", False)
        flag_path = os.path.join(_app.BASE_DIR, _app.LIVE_EXECUTION_FLAG)
        if enabled:
            with open(flag_path, "w") as f:
                f.write("1")
        else:
            if os.path.exists(flag_path):
                os.remove(flag_path)
        with _app.data_lock:
            _app.cached_data["live_execution"] = enabled
        return jsonify({"ok": True, "enabled": enabled})
    return jsonify({"enabled": os.path.exists(os.path.join(_app.BASE_DIR, _app.LIVE_EXECUTION_FLAG))})


@config_bp.route("/api/live-execution/index", methods=["GET", "POST"])
def api_live_execution_index():
    import os
    _app = _get_app()
    if request.method == "POST":
        enabled = request.get_json(force=True, silent=True).get("enabled", False)
        flag_path = os.path.join(_app.BASE_DIR, _app.LIVE_EXECUTION_FLAG_INDEX)
        if enabled:
            with open(flag_path, "w") as f:
                f.write("1")
        else:
            if os.path.exists(flag_path):
                os.remove(flag_path)
        with _app.data_lock:
            _app.cached_data["live_execution_index"] = enabled
        return jsonify({"ok": True, "enabled": enabled})
    return jsonify({"enabled": os.path.exists(os.path.join(_app.BASE_DIR, _app.LIVE_EXECUTION_FLAG_INDEX))})
