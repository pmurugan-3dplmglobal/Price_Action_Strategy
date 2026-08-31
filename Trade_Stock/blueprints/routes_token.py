from flask import Blueprint, request, jsonify
import os, json

token_bp = Blueprint('token', __name__)

def _app():
    import sys, importlib
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module('app_Stock_Trade')

@token_bp.route('/api/token/check')
def api_token_check():
    app = _app()
    return jsonify(app.check_token_valid())

@token_bp.route('/api/token/url')
def api_token_url():
    app = _app()
    url = app.get_login_url()
    if not url:
        return jsonify({'url': '', 'error': 'Kite API Key is missing.'})
    return jsonify({'url': url})
