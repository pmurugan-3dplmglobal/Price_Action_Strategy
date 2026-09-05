"""
routes_charts.py — Chart data and negation analyzer routes:
  /api/get-chart-data
  /api/analyze-trade
"""
import logging
from flask import Blueprint, request, jsonify

charts_bp = Blueprint("charts_bp", __name__)


def _get_app():
    import app_Stock_Trade as _app
    return _app


# ── negation / trade analyzer ─────────────────────────────────────────────────

@charts_bp.route("/api/analyze-trade", methods=["POST"])
def api_analyze_trade():
    try:
        from trading_core import derive_sl_targets_for_contract, load_kite_session
        from kiteconnect import KiteConnect

        data = request.json or {}
        symbol = str(data.get("symbol", "")).strip().upper()
        entry_price = float(data.get("entry_price") or data.get("entry_spot") or 0.0)
        engine = str(data.get("engine", "daily")).strip()
        _app = _get_app()
        cfg = _app.load_config() if hasattr(_app, "load_config") else {}
        default_tf = cfg.get(engine, {}).get("timeframe") or cfg.get("daily", {}).get("timeframe") or "day"
        timeframe = str(data.get("timeframe") or default_tf).strip()

        if not symbol:
            return jsonify({"ok": False, "error": "Valid Symbol or Contract Name required"}), 400

        kite = None
        try:
            api_k, acc_t = load_kite_session()
            kite = KiteConnect(api_key=api_k, access_token=acc_t)
        except Exception:
            kite = None

        if timeframe in ["day", "week"]:
            timeframe_entry = timeframe
            timeframe_anchor = timeframe
        elif timeframe == "30minute":
            timeframe_entry = "30minute"
            timeframe_anchor = "30minute"
        else:
            timeframe_entry = "15minute" if timeframe in ["15minute", "75min", "60minute"] else timeframe
            timeframe_anchor = "75min" if timeframe in ["15minute", "75min"] else ("60minute" if timeframe == "60minute" else timeframe)

        analysis = derive_sl_targets_for_contract(kite, symbol, entry_price, timeframe_entry, timeframe_anchor)
        if not analysis:
            sl_val = round(entry_price * 0.90, 2) if entry_price > 0 else 0.0
            analysis = {
                "entry_price": entry_price,
                "current_sl": sl_val,
                "t1": None, "t2": None, "t3": None,
                "pattern": "NEGATION_ESTIMATED"
            }

        resolved_entry = float(analysis.get("entry_price") or entry_price or 0.0)
        sl_val = analysis.get("current_sl", round(resolved_entry * 0.90, 2) if resolved_entry > 0 else 0.0)
        t1_val = analysis.get("t1")
        t2_val = analysis.get("t2")
        t3_val = analysis.get("t3")

        risk = (resolved_entry - sl_val) if (resolved_entry > 0 and sl_val < resolved_entry) else 0
        rr = round((t1_val - resolved_entry) / risk, 2) if (t1_val and risk > 0) else 0.0

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "contract": symbol,
            "entry_price": resolved_entry,
            "current_sl": sl_val,
            "t1": t1_val if t1_val else "N/A",
            "t2": t2_val if t2_val else "N/A",
            "t3": t3_val if t3_val else "N/A",
            "rr": rr,
            "pattern": analysis.get("pattern", "NEGATION_DERIVED"),
            "engine": engine
        })
    except Exception as e:
        logging.error(f"Analyze Trade API failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── chart candle data ─────────────────────────────────────────────────────────

@charts_bp.route("/api/get-chart-data", methods=["GET"])
def api_get_chart_data():
    try:
        from trading_core import load_kite_session, fetch_and_resample_candles, STOCK_REGISTRY
        from kiteconnect import KiteConnect
        from datetime import datetime as dt, timedelta

        contract = str(request.args.get("symbol", "")).strip().upper()
        chart_type = str(request.args.get("type", "spot")).strip().lower()
        _app = _get_app()
        cfg = _app.load_config() if hasattr(_app, "load_config") else {}
        default_tf = cfg.get("daily", {}).get("timeframe") or "day"
        tf = str(request.args.get("timeframe") or default_tf).strip()

        if not contract:
            return jsonify({"ok": False, "error": "Symbol is required"}), 400

        api_k, acc_t = load_kite_session()
        kite = KiteConnect(api_key=api_k, access_token=acc_t)

        spot_symbol = contract
        spot_token = None

        if spot_symbol in STOCK_REGISTRY:
            spot_token = STOCK_REGISTRY[spot_symbol]["token"]
        elif spot_symbol in ["NIFTY", "NIFTY 50", "NIFTY50"]:
            spot_symbol = "NIFTY"
            spot_token = 256265
        elif spot_symbol in ["BANKNIFTY", "NIFTY BANK"]:
            spot_symbol = "BANKNIFTY"
            spot_token = 260105
        elif spot_symbol in ["SENSEX", "BSESN"]:
            spot_symbol = "SENSEX"
            spot_token = 265
        elif contract in STOCK_REGISTRY:
            spot_token = STOCK_REGISTRY[contract]["token"]
            spot_symbol = contract

        try:
            ltp_res = kite.ltp([f"NSE:{spot_symbol}"])
            if ltp_res and f"NSE:{spot_symbol}" in ltp_res:
                spot_token = ltp_res[f"NSE:{spot_symbol}"]["instrument_token"]
        except Exception:
            pass

        target_token = spot_token
        target_symbol = spot_symbol
        target_exchange = "NSE" if (spot_symbol in STOCK_REGISTRY or spot_symbol in ["NIFTY", "BANKNIFTY"]) else "BSE"

        if not target_token:
            return jsonify({"ok": False, "error": f"Instrument token not found for {contract}"}), 400

        ref_now = dt.now()
        from_date = (ref_now - timedelta(days=60)).strftime("%Y-%m-%d")
        to_date = ref_now.strftime("%Y-%m-%d")

        df_candles = fetch_and_resample_candles(kite, target_token, from_date, to_date, tf)
        if df_candles is None or df_candles.empty:
            return jsonify({"ok": False, "error": f"No candle data available for {target_symbol}"}), 400

        import pandas as pd
        candles = []
        for _, r in df_candles.iterrows():
            c_dt = pd.to_datetime(r['date'])
            ts = int(c_dt.timestamp())
            candles.append({
                "time": ts,
                "open": round(float(r['open']), 2),
                "high": round(float(r['high']), 2),
                "low": round(float(r['low']), 2),
                "close": round(float(r['close']), 2),
                "volume": int(r['volume']) if 'volume' in r else 0
            })

        kite_url = f"https://kite.zerodha.com/chart/ext/tvc/{target_exchange}/{target_symbol}/{target_token}"

        return jsonify({
            "ok": True,
            "symbol": target_symbol,
            "contract": contract,
            "spot_symbol": spot_symbol,
            "chart_type": chart_type,
            "exchange": target_exchange,
            "token": target_token,
            "timeframe": tf,
            "candles": candles,
            "kite_url": kite_url
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
