import os
import json
import secrets
import threading
from datetime import datetime as dt
from werkzeug.security import generate_password_hash, check_password_hash
import paths

_lock = threading.Lock()


def _load_users():
    try:
        if os.path.exists(paths.DASHBOARD_USERS_FILE):
            with open(paths.DASHBOARD_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_users(users):
    os.makedirs(os.path.dirname(paths.DASHBOARD_USERS_FILE), exist_ok=True)
    with open(paths.DASHBOARD_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def get_secret_key():
    os.makedirs(os.path.dirname(paths.DASHBOARD_SECRET_KEY_FILE), exist_ok=True)
    if os.path.exists(paths.DASHBOARD_SECRET_KEY_FILE):
        try:
            with open(paths.DASHBOARD_SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    key = secrets.token_hex(32)
    try:
        with open(paths.DASHBOARD_SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return key


def register_user(username, password):
    username = (username or "").strip()
    if len(username) < 3:
        return None, "Username must be at least 3 characters"
    if not password or len(password) < 4:
        return None, "Password must be at least 4 characters"
    with _lock:
        users = _load_users()
        if username in users:
            return None, "Username already exists"
        is_first = len(users) == 0
        users[username] = {
            "password_hash": generate_password_hash(password),
            "role": "admin" if is_first else "user",
            "approved": True if is_first else False,
            "created_at": dt.now().isoformat(),
        }
        _save_users(users)
    return username, None


def verify_user(username, password):
    username = (username or "").strip()
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not check_password_hash(user.get("password_hash", ""), password or ""):
        return None
    # Self-healing: if only 1 user exists or no approved admin exists, guarantee admin & approved
    has_admin = any(u.get("role") == "admin" and u.get("approved") for u in users.values())
    if len(users) == 1 or not has_admin:
        if user.get("role") != "admin" or not user.get("approved"):
            with _lock:
                users[username]["role"] = "admin"
                users[username]["approved"] = True
                _save_users(users)
            user["role"] = "admin"
            user["approved"] = True
    return {
        "username": username,
        "role": user.get("role", "user"),
        "approved": bool(user.get("approved"))
    }


def list_users():
    users = _load_users()
    return [{
        "username": name,
        "role": u.get("role", "user"),
        "approved": bool(u.get("approved")),
        "created_at": u.get("created_at", ""),
    } for name, u in users.items()]


def approve_user(username):
    with _lock:
        users = _load_users()
        if username not in users:
            return False
        users[username]["approved"] = True
        _save_users(users)
    return True


def reject_user(username):
    with _lock:
        users = _load_users()
        if username not in users:
            return False
        users[username]["approved"] = False
        _save_users(users)
    return True


def delete_user(username):
    with _lock:
        users = _load_users()
        if username not in users:
            return False
        del users[username]
        _save_users(users)
    return True
