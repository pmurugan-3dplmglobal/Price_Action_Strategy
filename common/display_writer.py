"""
Scan display data writer — formats and persists scan results to JSON display files
consumed by Flask dashboards.
Extracted from trading_core.py (2026-08-11).
"""
import os
import json
import logging
from datetime import datetime as dt
import paths
from timeframe_utils import get_ist_now
from position_monitor import contract_is_expired

def clean_timestamp(ts):
    """Clean ISO timestamp string by stripping timezone offsets (+05:30), seconds, and T separator."""
    if not ts or ts == '-':
        return ""
    s = str(ts).split('+')[0].split('.')[0].replace('T', ' ').strip()
    p = s.split(' ')
    if len(p) == 2:
        date_part, time_part = p[0], p[1]
        t_parts = time_part.split(':')
        if len(t_parts) >= 2:
            return f"{date_part} {t_parts[0]}:{t_parts[1]}"
    return s

# ──────────────────────────────────────────────
#  ANCHOR (A-FORMATION) DETECTION — 5 PATTERNS
# ──────────────────────────────────────────────


def write_scan_display_data(staged, active, display_file, engine_name=None):
    try:
        now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
        today = get_ist_now().strftime("%Y-%m-%d")
        import trade_db
        db_trades = trade_db.get_all_trades(engine_name) if engine_name else []
        db_map = {}
        for dbt in db_trades:
            if dbt.get("status") in ["ACTIVE", "OPEN"]:
                c = str(dbt.get("contract") or dbt.get("symbol") or "").replace(" ", "").upper()
                if c: db_map[c] = dbt

        def build_trade(t, result, entry_time, exit_time, is_staged=False):
            contract = t.get("contract") or t.get("symbol") or ""
            c_clean = str(contract).replace(" ", "").upper()
            db_record = db_map.get(c_clean) if not is_staged else None
            entry = t.get("entry_spot") if (is_staged or not db_record or db_record.get("entry_spot") is None) else db_record.get("entry_spot")
            sl = t.get("current_sl") if (is_staged or not db_record or not db_record.get("current_sl")) else db_record.get("current_sl")
            t1 = t.get("t1") if (is_staged or not db_record or not db_record.get("t1")) else db_record.get("t1")
            t2 = t.get("t2") if (is_staged or not db_record or not db_record.get("t2")) else db_record.get("t2")
            t3 = t.get("t3") if (is_staged or not db_record or not db_record.get("t3")) else db_record.get("t3")
            pattern = t.get("pattern") if (is_staged or not db_record or not db_record.get("pattern")) else db_record.get("pattern", "")
            rr_val = t.get("rr") if t.get("rr") is not None else t.get("RR")
            if rr_val is None and entry is not None and sl is not None and t1 is not None:
                try:
                    risk = abs(float(entry) - float(sl))
                    risk_min = max(0.01, abs(float(entry)) * 0.005)
                    rr_val = (abs(float(t1) - float(entry)) / risk) if risk >= risk_min else 0.0
                except Exception:
                    rr_val = 0.0
            rr_num = float(rr_val) if (rr_val is not None and str(rr_val).strip() != "") else 0.0

            side_val = t.get("side", "")
            if not side_val:
                cnt = str(contract).upper()
                if "CE" in cnt:
                    side_val = "CE"
                elif "PE" in cnt:
                    side_val = "PE"

            ca_time = t.get("candle_a_time") or t.get("CandleATime")
            if not ca_time:
                try:
                    import trade_db
                    cnt_key = str(contract or t.get("symbol") or "").replace(" ", "").upper()
                    if cnt_key:
                        for db_tr in trade_db.get_all_trades():
                            db_cnt = str(db_tr.get("contract") or db_tr.get("symbol") or "").replace(" ", "").upper()
                            if db_cnt == cnt_key:
                                ca_time = db_tr.get("candle_a_time") or db_tr.get("CandleATime")
                                if ca_time: break
                except Exception:
                    pass

            opt_tok = t.get("option_token") or t.get("token") or t.get("instrument_token")
            if not opt_tok and contract:
                try:
                    from position_monitor import _get_nfo_cache
                    _df_cache = _get_nfo_cache()
                    if not _df_cache.empty and 'tradingsymbol' in _df_cache.columns:
                        _m = _df_cache[_df_cache['tradingsymbol'] == contract]
                        if not _m.empty:
                            opt_tok = int(_m.iloc[0]['instrument_token'])
                except Exception:
                    pass

            return {
                "symbol": t.get("symbol", ""),
                "contract": contract,
                "option_token": opt_tok,
                "token": opt_tok,
                "side": side_val,
                "entry_spot": entry,
                "current_sl": sl,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "pattern": pattern,
                "entry_time": clean_timestamp(entry_time),
                "exit_time": clean_timestamp(exit_time),
                "result": result,
                "carry_forward": False,
                "rr": round(rr_num, 2),
                "candle_a_time": clean_timestamp(ca_time or ""),
                "timeframe": t.get("timeframe", ""),
                "candle_tf_time": t.get("candle_tf_time", ""),
                "benchmark": t.get("benchmark"),
                "anchor_floor": t.get("anchor_floor"),
                "direction": t.get("direction", "BULL"),
                "swing_waves": t.get("swing_waves", t.get("valid_arch_count", 0)),
                "terminal_base": bool(t.get("terminal_base", t.get("has_terminal_base", False))),
                "tier": t.get("tier", 2),
                "tier_label": t.get("tier_label", "TIER_2_CORE"),
                "tier_badge": t.get("tier_badge", "🥈 T2"),
                "atr_ratio": t.get("atr_ratio", 1.0),
                "is_squeeze": t.get("is_squeeze", False),
                "vcp_tier": t.get("vcp_tier", "NORMAL"),
                "vcp_badge": t.get("vcp_badge", ""),
                "spot_vwap": float(t.get("spot_vwap", 0.0)),
                "vwap": t.get("vwap", 0.0),
                "vwap_stretch": t.get("vwap_stretch", 0.0),
                "vwap_status": t.get("vwap_status", "FAIR"),
                "vwap_zscore": float(t.get("vwap_zscore", 0.0)),
                "vwap_upper_2sigma": float(t.get("vwap_upper_2sigma", 0.0)),
                "spot_confluence": bool(t.get("spot_confluence", False)),
                "spot_confluence_type": str(t.get("spot_confluence_type", "NONE")),
                "twap_c_stable": bool(t.get("twap_c_stable", False)),
                "twap_c_score": float(t.get("twap_c_score", 0.0)),
                "twap_c_std": float(t.get("twap_c_std", 0.0))
            }
        new_staged = [build_trade(t, t.get("pattern", "BE_ABCD"), t.get("entry_time", now_str), None, is_staged=True) for t in (staged or [])]
        carry_fwd = []
        active_live = []
        active_keys = set()
        active_iterable = active.items() if isinstance(active, dict) else [(p.get("symbol", ""), p) for p in (active or [])]
        for s, p in active_iterable:
            t = p.copy()
            t["symbol"] = s
            c_key = str(p.get("contract") or s or "").replace(" ", "").upper()

            # Validation check 1: Status must be ACTIVE or OPEN
            status_val = str(p.get("status") or "ACTIVE").upper()
            if status_val not in ["ACTIVE", "OPEN"]:
                continue

            # Validation check 2: Contract must NOT be expired
            if contract_is_expired(c_key):
                continue

            # Validation check 3: Must have valid SL & T1
            sl_val = float(p.get("current_sl") or p.get("sl") or 0)
            t1_val = float(p.get("t1") or 0)
            if sl_val <= 0 or t1_val <= 0:
                continue
            
            # Lookup original scanned trade from trade_db to get exact candle timestamps
            db_match = None
            try:
                import trade_db
                for db_tr in trade_db.get_all_trades():
                    db_c = str(db_tr.get("contract") or db_tr.get("symbol") or "").replace(" ", "").upper()
                    if db_c == c_key:
                        db_match = db_tr
                        break
            except Exception:
                pass

            if db_match:
                if not t.get("candle_a_time"):
                    t["candle_a_time"] = db_match.get("candle_a_time") or db_match.get("CandleATime")
                curr_et = str(t.get("entry_time") or "").replace("T", " ").split("+")[0].strip()
                curr_parts = curr_et.split(" ")
                curr_hr = 0
                if len(curr_parts) >= 2 and ":" in curr_parts[1]:
                    h_str = curr_parts[1].split(":")[0]
                    if h_str.isdigit():
                        curr_hr = int(h_str)
                if db_match.get("entry_time") and (not t.get("entry_time") or curr_hr >= 16 or curr_hr < 9):
                    t["entry_time"] = db_match.get("entry_time")

            et = t.get("entry_time", now_str)
            entry_date = et[:10] if isinstance(et, str) else today
            cf = entry_date < today
            entry_time_display = et if isinstance(et, str) else now_str
            trade = build_trade(t, "ACTIVE", entry_time_display, None)
            trade["carry_forward"] = cf
            if cf:
                carry_fwd.append(trade)
            else:
                active_live.append(trade)
            c = str(p.get("contract") or "").replace(" ", "").upper()
            if c: active_keys.add(c)

        def _trade_key(t):
            return str(t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()

        # Accumulate all staged trades for today's date from display_file
        existing_staged = []
        cleared_at_ts = None
        if display_file and os.path.exists(display_file):
            try:
                with open(display_file, "r", encoding="utf-8") as fh:
                    old_d = json.load(fh)
                cleared_at_ts = old_d.get("cleared_at")
                if old_d.get("date") == today:
                    raw_old = old_d.get("all_staged_today") or old_d.get("staged_trades") or []
                    if cleared_at_ts:
                        for tr in raw_old:
                            tr_time = str(tr.get("entry_time") or "")
                            if tr_time > cleared_at_ts:
                                existing_staged.append(tr)
                    else:
                        existing_staged = raw_old
            except Exception:
                pass

        combined_staged = existing_staged + (new_staged if new_staged else [])

        # Deduplicate staged trades by unique contract key: keep freshest entry_time & highest RR
        contract_map = {}
        for t in combined_staged:
            key = _trade_key(t)
            if not key or key in active_keys:
                continue
            if key not in contract_map:
                contract_map[key] = t
            else:
                prev = contract_map[key]
                prev_time = str(prev.get("entry_time") or "")
                curr_time = str(t.get("entry_time") or "")
                if curr_time > prev_time or (curr_time == prev_time and float(t.get("rr", 0)) > float(prev.get("rr", 0))):
                    contract_map[key] = t

        deduped_staged = list(contract_map.values())
        
        # For Index Options: Filter out redundant strikes for the same move; retain ONLY the single most profitable winner
        if engine_name == "index":
            sym_side_map = {}
            for t in deduped_staged:
                ss_key = f"{t.get('symbol','')}_{t.get('side','')}".replace(" ", "").upper()
                if ss_key not in sym_side_map:
                    sym_side_map[ss_key] = t
                else:
                    prev = sym_side_map[ss_key]
                    prev_profit = float(prev.get("t1") or 0) - float(prev.get("entry_spot") or 0)
                    curr_profit = float(t.get("t1") or 0) - float(t.get("entry_spot") or 0)
                    prev_rr = float(prev.get("rr") or 0)
                    curr_rr = float(t.get("rr") or 0)
                    if (curr_profit > prev_profit) or (curr_profit == prev_profit and curr_rr > prev_rr):
                        sym_side_map[ss_key] = t
            deduped_staged = list(sym_side_map.values())

        deduped_staged.sort(key=lambda x: float(x.get("rr", 0)), reverse=True)

        data = {
            "date": today,
            "timestamp": now_str,
            "staged_trades": deduped_staged,
            "all_staged_today": deduped_staged,
            "carry_forward": carry_fwd,
            "active_live": active_live
        }
        os.makedirs(os.path.dirname(display_file), exist_ok=True)
        tmp_file = f"{display_file}.tmp.{os.getpid()}"
        written = False
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            for attempt in range(5):
                try:
                    os.replace(tmp_file, display_file)
                    written = True
                    break
                except (PermissionError, OSError):
                    time.sleep(0.05 * (attempt + 1))
            if not written:
                with open(display_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception as write_err:
            logging.warning(f"Display file atomic replace warning: {write_err}, falling back to direct write")
            with open(display_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        finally:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
    except Exception as e:
        logging.error(f"Display data write failed: {e}")

