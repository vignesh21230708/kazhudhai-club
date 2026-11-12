"""
KAZHUDHAI CLUB — app.py
Flask application entry point.
Serves the frontend and provides REST + SocketIO API.
Supports offline AI gameplay and real-time online multiplayer.
"""
import os
import sys

# Make sure backend/ is on the path
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
from config import Config
from game_engine.room_manager import room_manager

# ── Create Flask app ──
app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'),
    static_url_path='',
)
app.config.from_object(Config)
CORS(app)

# ── SocketIO Setup ──
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=Config.ASYNC_MODE,
    ping_timeout=25,
    ping_interval=10,
)

# ── Register Blueprints ──
from api.offline_routes import offline_bp
app.register_blueprint(offline_bp)

# ── Register SocketIO Events ──
from sockets.game_events import register_socket_events
register_socket_events(socketio)

# ── Database Health Check ──
from database import get_db_status

# ── Serve Frontend ──
@app.route('/')
def index():
    """Serve the main HTML file."""
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    return send_from_directory(frontend_dir, 'index.html')

@app.route('/.well-known/assetlinks.json')
def asset_links():
    """Serve Android TWA Digital Asset Links verification JSON."""
    well_known_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', '.well-known')
    return send_from_directory(well_known_dir, 'assetlinks.json', mimetype='application/json')

@app.route('/<path:filename>')
def static_files(filename):
    """Serve static frontend files."""
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    return send_from_directory(frontend_dir, filename)

# ── Health check ──
@app.route('/api/health')
def health():
    db_info = get_db_status()
    return {
        'status': 'ok',
        'game': 'KAZHUDHAI CLUB',
        'environment': 'development' if Config.DEBUG else 'production',
        'async_mode': Config.ASYNC_MODE,
        'database': db_info,
    }

# ── Public Rooms listing ──
@app.route('/api/rooms/public')
def public_rooms():
    return jsonify(room_manager.get_public_rooms())


if __name__ == '__main__':
    port = Config.PORT
    print(f"\n{'='*50}")
    print(f"  KAZHUDHAI CLUB Server (REST + SocketIO)")
    print(f"  Mode: {'Development' if Config.DEBUG else 'Production'} | Async: {Config.ASYNC_MODE}")
    print(f"  http://localhost:{port}")
    print(f"{'='*50}\n")
    # When executed directly via python, allow_unsafe_werkzeug enables local development server
    # On cloud platforms (Render, Railway, Heroku), Gunicorn/Waitress runs wsgi:app directly
    socketio.run(app, host='0.0.0.0', port=port, debug=Config.DEBUG, allow_unsafe_werkzeug=True)
