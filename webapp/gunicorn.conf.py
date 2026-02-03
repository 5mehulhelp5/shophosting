"""
Gunicorn configuration file for ShopHosting.io
All settings can be overridden via environment variables

Performance optimizations:
- Uses gevent async workers for better concurrency
- Each worker can handle multiple concurrent requests
- Increased worker count for high-traffic scenarios
"""

import os
import multiprocessing

# Server Socket
bind = os.getenv('GUNICORN_BIND', '127.0.0.1:5000')

# Worker Processes
# For gevent: fewer workers needed since each handles many connections
# Rule of thumb: 2-4 workers per core for I/O bound apps with gevent
cpu_count = multiprocessing.cpu_count()
default_workers = max(4, cpu_count * 2)  # Minimum 4, scale with cores
workers = int(os.getenv('GUNICORN_WORKERS', default_workers))

# Worker class - use gthread for thread-based concurrency (safer than gevent)
# Each worker spawns multiple threads to handle concurrent requests
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gthread')

# Connections per worker (only for gevent/eventlet)
# Higher values allow more concurrent connections per worker
worker_connections = int(os.getenv('GUNICORN_WORKER_CONNECTIONS', '1000'))

# Threads per worker (for gthread worker class)
# More threads = more concurrent requests per worker
threads = int(os.getenv('GUNICORN_THREADS', '4'))

# Timeout for worker processes (seconds)
timeout = int(os.getenv('GUNICORN_TIMEOUT', '30'))

# Graceful timeout (seconds to finish requests during shutdown)
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))

# Keep-alive connections timeout
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', '2'))

# Maximum requests per worker before restart (helps prevent memory leaks)
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '1000'))

# Jitter for max_requests to prevent all workers restarting at once
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '50'))

# Preload application code before forking workers
# Saves memory but prevents code reloading
preload_app = os.getenv('GUNICORN_PRELOAD', 'false').lower() == 'true'

# Access log format
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')  # '-' means stdout
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# Access log format (combined format similar to nginx)
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Security: Don't expose server header
proc_name = 'shophosting-webapp'


def post_fork(server, worker):
    """Called just after a worker has been forked.

    Gevent requires monkey patching to make standard library functions
    cooperative (non-blocking). This must happen early, before other imports.
    """
    if worker_class == 'gevent':
        from gevent import monkey
        monkey.patch_all()


def on_starting(server):
    """Called just before the master process is initialized."""
    pass


def on_reload(server):
    """Called before reloading the worker processes."""
    pass


def worker_int(worker):
    """Called when a worker receives SIGINT."""
    pass


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    pass
