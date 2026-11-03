"""
KAZHUDHAI CLUB — wsgi.py
Production WSGI and SocketIO server entrypoint.
Compatible with Gunicorn (gthread, eventlet, gevent) and Waitress.
Usage:
  gunicorn --worker-class gthread --workers 1 --threads 100 --bind 0.0.0.0:$PORT wsgi:app
  waitress-serve --port=5000 wsgi:app
"""
import os
import sys

# Monkey patch ONLY if eventlet is explicitly requested
if os.environ.get('SOCKETIO_ASYNC_MODE') == 'eventlet':
    try:
        import eventlet
        eventlet.monkey_patch()
    except (ImportError, Exception):
        pass

# Ensure backend directory is in python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config import Config
from app import app, socketio

# Application callable for Gunicorn: `app`
application = app

if __name__ == '__main__':
    port = Config.PORT
    run_kwargs = {'host': '0.0.0.0', 'port': port, 'debug': Config.DEBUG}
    if Config.DEBUG:
        run_kwargs['allow_unsafe_werkzeug'] = True
    socketio.run(app, **run_kwargs)
