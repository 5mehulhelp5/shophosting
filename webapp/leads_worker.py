#!/usr/bin/env python3
"""
Leads Worker - RQ Worker for processing site scans and sending lead emails.
Processes jobs from 'scans' and 'emails' queues.
"""

import os
import sys
import logging

# Add the webapp directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redis import Redis
from rq import Worker, Queue, Connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('leads_worker')


def main():
    """Start the RQ worker for leads processing"""
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))

    logger.info(f"Connecting to Redis at {redis_host}:{redis_port}")
    redis_conn = Redis(host=redis_host, port=redis_port)

    # Test connection
    try:
        redis_conn.ping()
        logger.info("Redis connection successful")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        sys.exit(1)

    # Define queues to process (battles and scans first, then emails)
    queues = ['battles', 'scans', 'emails']

    with Connection(redis_conn):
        worker = Worker(
            queues=queues,
            name=f"leads-worker-{os.getpid()}",
            default_worker_ttl=600,  # Worker heartbeat TTL
            job_monitoring_interval=5,  # Check for jobs every 5 seconds
        )

        logger.info(f"Starting worker for queues: {queues}")
        worker.work(with_scheduler=False)


if __name__ == '__main__':
    main()
