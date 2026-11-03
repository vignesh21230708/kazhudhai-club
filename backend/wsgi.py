"""
KAZHUDHAI CLUB — wsgi.py
Production WSGI and SocketIO server entrypoint.
Compatible with Gunicorn (Eventlet/Gevent) and Waitress.
Usage:
  gunicorn --worker-class eventlet -w 1 wsgi:app
  waitress-serve --port=5000 wsgi:app
"""
import os
import sys

# Monkey patch for eventlet in production environments prior to socket/network imports
if os.environ.get('SOCKETIO_ASYNC_MODE', 'eventlet') == 'eventlet':
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

# Application callable for Gunicorn: `app` or `socketio.wsgi_app`
# Gunicorn with eventlet uses `wsgi:app`
application = app

if __name__ == '__main__':
    port = Config.PORT
    run_kwargs = {'host': '0.0.0.0', 'port': port, 'debug': Config.DEBUG}
    if Config.DEBUG:
        run_kwargs['allow_unsafe_werkzeug'] = True
    socketio.run(app, **run_kwargs)
