"""
Container metrics exporter for customer containers.
Exposes CPU, memory, and network metrics with customer_id labels.

Uses background caching to avoid slow Docker API calls during scrape requests.
"""
import docker
import threading
import time
import logging
from flask import Blueprint, Response

logger = logging.getLogger(__name__)
container_metrics_bp = Blueprint('container_metrics', __name__)

# Cache for container metrics
_metrics_cache = {
    'metrics': [],
    'last_update': 0,
    'lock': threading.Lock(),
    'collector_started': False
}

# Update interval in seconds
CACHE_UPDATE_INTERVAL = 15


def collect_container_stats():
    """Collect stats for all customer containers. Called by background thread."""
    try:
        client = docker.from_env()
        containers = client.containers.list()

        metrics = []

        for container in containers:
            name = container.name
            # Only process customer containers
            if not name.startswith('customer-'):
                continue

            # Extract customer ID from name (customer-X-...)
            parts = name.split('-')
            if len(parts) < 2:
                continue
            customer_id = parts[1]

            # Get container type (web, db, redis, etc.)
            container_type = parts[2] if len(parts) > 2 else 'unknown'

            try:
                stats = container.stats(stream=False)

                # CPU calculation
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']
                cpu_count = stats['cpu_stats'].get('online_cpus', 1)

                if system_delta > 0:
                    cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
                else:
                    cpu_percent = 0.0

                # Memory calculation
                memory_usage = stats['memory_stats'].get('usage', 0)
                memory_limit = stats['memory_stats'].get('limit', 1)
                memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0

                # Network I/O
                networks = stats.get('networks', {})
                rx_bytes = sum(n.get('rx_bytes', 0) for n in networks.values())
                tx_bytes = sum(n.get('tx_bytes', 0) for n in networks.values())

                labels = f'customer_id="{customer_id}",container_name="{name}",container_type="{container_type}"'

                metrics.append(f'container_cpu_usage_percent{{{labels}}} {cpu_percent:.2f}')
                metrics.append(f'container_memory_usage_bytes{{{labels}}} {memory_usage}')
                metrics.append(f'container_memory_limit_bytes{{{labels}}} {memory_limit}')
                metrics.append(f'container_memory_usage_percent{{{labels}}} {memory_percent:.2f}')
                metrics.append(f'container_network_rx_bytes{{{labels}}} {rx_bytes}')
                metrics.append(f'container_network_tx_bytes{{{labels}}} {tx_bytes}')

            except Exception as e:
                # Container might have stopped
                logger.debug(f"Failed to get stats for {name}: {e}")
                continue

        # Update cache
        with _metrics_cache['lock']:
            _metrics_cache['metrics'] = metrics
            _metrics_cache['last_update'] = time.time()

        logger.debug(f"Updated container metrics cache: {len(metrics)} metrics")
        return metrics

    except Exception as e:
        logger.error(f"Error collecting container stats: {e}")
        return []


def _background_collector():
    """Background thread that periodically updates the metrics cache."""
    logger.info("Starting container metrics background collector")
    while True:
        try:
            collect_container_stats()
        except Exception as e:
            logger.error(f"Background collector error: {e}")
        time.sleep(CACHE_UPDATE_INTERVAL)


def start_background_collector():
    """Start the background metrics collector thread (if not already started)."""
    with _metrics_cache['lock']:
        if _metrics_cache['collector_started']:
            return
        _metrics_cache['collector_started'] = True

    # Start background thread - do NOT block on initial collection
    # The first scrape may return empty data, but subsequent ones will have data
    thread = threading.Thread(target=_background_collector, daemon=True)
    thread.start()
    logger.info("Container metrics background collector started")


def get_cached_metrics():
    """Get metrics from cache."""
    with _metrics_cache['lock']:
        return list(_metrics_cache['metrics']), _metrics_cache['last_update']


@container_metrics_bp.route('/metrics/containers')
def container_metrics():
    """Prometheus metrics endpoint for container stats. Returns cached data."""
    # Lazy-start the background collector on first request
    start_background_collector()

    metrics_lines = [
        '# HELP container_cpu_usage_percent CPU usage percentage',
        '# TYPE container_cpu_usage_percent gauge',
        '# HELP container_memory_usage_bytes Memory usage in bytes',
        '# TYPE container_memory_usage_bytes gauge',
        '# HELP container_memory_limit_bytes Memory limit in bytes',
        '# TYPE container_memory_limit_bytes gauge',
        '# HELP container_memory_usage_percent Memory usage percentage',
        '# TYPE container_memory_usage_percent gauge',
        '# HELP container_network_rx_bytes Network received bytes',
        '# TYPE container_network_rx_bytes counter',
        '# HELP container_network_tx_bytes Network transmitted bytes',
        '# TYPE container_network_tx_bytes counter',
        '# HELP container_metrics_cache_age_seconds Age of cached metrics',
        '# TYPE container_metrics_cache_age_seconds gauge',
    ]

    cached_metrics, last_update = get_cached_metrics()
    cache_age = time.time() - last_update if last_update > 0 else -1

    metrics_lines.extend(cached_metrics)
    metrics_lines.append(f'container_metrics_cache_age_seconds {cache_age:.2f}')

    return Response('\n'.join(metrics_lines) + '\n', mimetype='text/plain')
