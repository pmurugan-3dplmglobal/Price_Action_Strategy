"""
routes_logs.py — Log streaming routes:
  /api/logs      (fetch logs for all programs)
  /api/log-tail  (alias used by UI)
"""
from flask import Blueprint, request, jsonify

logs_bp = Blueprint("logs_bp", __name__)


def _get_app():
    import app_Stock_Trade as _app
    return _app


@logs_bp.route("/api/logs")
def api_logs():
    _app = _get_app()
    prog_id = request.args.get("program")
    n = int(request.args.get("n", 200))
    with _app.data_lock:
        if prog_id:
            log_file = _app.PROGRAMS.get(prog_id, {}).get("log_file")
            lines = _app.tail_log(log_file, n) if log_file else _app.cached_data["log_tail"].get(prog_id, [])
            return jsonify({"lines": lines, "program": prog_id})
        all_logs = {}
        for pid in _app.PROGRAMS:
            log_file = _app.PROGRAMS[pid].get("log_file")
            all_logs[pid] = _app.tail_log(log_file, n) if log_file else _app.cached_data["log_tail"].get(pid, [])
        return jsonify(all_logs)


@logs_bp.route("/api/log-tail")
def api_log_tail():
    """Alias used by some UI calls — same behaviour as /api/logs."""
    _app = _get_app()
    prog_id = request.args.get("program")
    n = int(request.args.get("n", 200))
    with _app.data_lock:
        if prog_id:
            log_file = _app.PROGRAMS.get(prog_id, {}).get("log_file")
            lines = _app.tail_log(log_file, n) if log_file else _app.cached_data["log_tail"].get(prog_id, [])
            return jsonify({"lines": lines, "program": prog_id})
        all_logs = {}
        for pid in _app.PROGRAMS:
            log_file = _app.PROGRAMS[pid].get("log_file")
            all_logs[pid] = _app.tail_log(log_file, n) if log_file else _app.cached_data["log_tail"].get(pid, [])
        return jsonify(all_logs)
