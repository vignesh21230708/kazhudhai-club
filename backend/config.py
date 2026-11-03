"""
KAZHUDHAI CLUB — config.py
Application configuration for production and local development.
"""
import os
import secrets
import sys

class Config:
    # ── Security & Secret Key ──
    # Reads SECRET_KEY from environment. If unset, generates a cryptographically
    # secure random key per instance to prevent predictable secret vulnerabilities.
    _env_secret = os.environ.get('SECRET_KEY')
    SECRET_KEY = _env_secret if _env_secret else secrets.token_hex(32)

    # ── Environment & Debug Mode ──
    # Defaults to False in production for safety unless explicitly enabled.
    DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')

    # ── Hosting Platform Port Binding ──
    PORT = int(os.environ.get('PORT', 5000))

    # ── Database: SQLite for development, PostgreSQL for cloud deployment ──
    _raw_db_url = os.environ.get('DATABASE_URL')
    if _raw_db_url and _raw_db_url.startswith('postgres://'):
        # Fix legacy Heroku/Render dialect scheme
        _raw_db_url = _raw_db_url.replace('postgres://', 'postgresql://', 1)

    DB_PATH = os.environ.get('DB_PATH', 'kazhudhai.db')
    DATABASE_URL = _raw_db_url
    SQLALCHEMY_DATABASE_URI = _raw_db_url or f'sqlite:///{DB_PATH}'
    IS_POSTGRES = bool(_raw_db_url and _raw_db_url.startswith('postgresql://'))

    # ── SocketIO Async Worker Mode ──
    # Allows environment override (e.g. eventlet, gevent, threading).
    # On Linux/Cloud, eventlet powers production WebSockets. On Windows dev, threading is used.
    _env_async = os.environ.get('SOCKETIO_ASYNC_MODE')
    if _env_async:
        ASYNC_MODE = _env_async
    else:
        try:
            import eventlet
            # Avoid eventlet issues on Python 3.12+ Windows if platform is win32
            ASYNC_MODE = 'threading' if sys.platform == 'win32' else 'eventlet'
        except ImportError:
            ASYNC_MODE = 'threading'

    # ── Game Engine Constraints ──
    MIN_PLAYERS = 2
    MAX_PLAYERS = 7
    MIN_DECKS   = 1
    MAX_DECKS   = 5
