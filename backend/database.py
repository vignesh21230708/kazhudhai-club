"""
KAZHUDHAI CLUB — backend/database.py
Database connection management and connectivity health checking.
Supports PostgreSQL for cloud deployments and SQLite for local fallback.
Securely shields database credentials and connection strings from exposure.
"""
from __future__ import annotations
import os
import sqlite3
from config import Config


def get_db_status() -> dict:
    """
    Check database connectivity without exposing connection secrets or passwords.
    Returns:
      {
        'configured': bool,
        'engine': 'postgresql' | 'sqlite',
        'connected': bool,
        'message': str
      }
    """
    db_url = Config.DATABASE_URL
    if db_url and Config.IS_POSTGRES:
        try:
            import psycopg2
            # Connect with a short timeout to prevent blocking on network lags
            conn = psycopg2.connect(db_url, connect_timeout=3)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            conn.close()
            return {
                'configured': True,
                'engine':     'postgresql',
                'connected':  True,
                'message':    'PostgreSQL connection verified successfully.',
            }
        except ImportError:
            return {
                'configured': True,
                'engine':     'postgresql',
                'connected':  False,
                'message':    'psycopg2 driver not installed in environment.',
            }
        except Exception as e:
            # Mask credentials from error output
            return {
                'configured': True,
                'engine':     'postgresql',
                'connected':  False,
                'message':    f'PostgreSQL connection error: {e.__class__.__name__}',
            }

    # SQLite fallback
    try:
        conn = sqlite3.connect(Config.DB_PATH, timeout=2)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        conn.close()
        return {
            'configured': False,
            'engine':     'sqlite',
            'connected':  True,
            'message':    f'Local SQLite database operational ({Config.DB_PATH}).',
        }
    except Exception as e:
        return {
            'configured': False,
            'engine':     'sqlite',
            'connected':  False,
            'message':    f'SQLite connection error: {e.__class__.__name__}',
        }
