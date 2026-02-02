#!/usr/bin/env python3
"""
ShopHosting.io Monitoring Worker
Performs health checks on all active customer sites and collects performance metrics.
"""

import os
import sys
import time
import logging
import requests
import subprocess
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# Add webapp to path for model imports
sys.path.insert(0, '/opt/shophosting/webapp')

from dotenv import load_dotenv
load_dotenv('/opt/shophosting/.env')

from models import (
    Customer, CustomerMonitoringStatus, MonitoringCheck, MonitoringAlert,
    get_db_connection
)

# Configuration - can be overridden via environment variables
CHECK_INTERVAL = int(os.getenv('MONITORING_CHECK_INTERVAL', '60'))  # seconds between cycles
HTTP_TIMEOUT = int(os.getenv('MONITORING_HTTP_TIMEOUT', '10'))  # HTTP request timeout
ALERT_THRESHOLD = int(os.getenv('MONITORING_ALERT_THRESHOLD', '3'))  # failures before alert
ALERT_COOLDOWN = int(os.getenv('MONITORING_ALERT_COOLDOWN', '300'))  # seconds between alerts
RESOURCE_WARNING_CPU = float(os.getenv('MONITORING_CPU_WARNING', '80'))  # % CPU threshold
RESOURCE_WARNING_MEMORY = float(os.getenv('MONITORING_MEMORY_WARNING', '85'))  # % memory threshold
CLEANUP_INTERVAL = int(os.getenv('MONITORING_CLEANUP_INTERVAL', '3600'))  # cleanup every hour
PERFORMANCE_METRICS_ENABLED = os.getenv('PERFORMANCE_METRICS_ENABLED', 'true').lower() == 'true'
SLOW_QUERY_THRESHOLD_MS = int(os.getenv('SLOW_QUERY_THRESHOLD_MS', '1000'))  # 1 second

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('monitoring_worker')


@dataclass
class PerformanceMetrics:
    """Container for collected performance metrics"""
    customer_id: int
    timestamp: datetime = field(default_factory=datetime.now)

    # Page speed (from HTTP probe)
    ttfb_ms: Optional[int] = None

    # Resources (from container check)
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_percent: Optional[float] = None

    # Database metrics
    slow_query_count: Optional[int] = None
    active_connections: Optional[int] = None
    table_size_bytes: Optional[int] = None

    # Cache metrics
    redis_hit_rate: Optional[float] = None
    redis_memory_bytes: Optional[int] = None
    varnish_hit_rate: Optional[float] = None

    def save(self):
        """Store performance snapshot in database"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Calculate a preliminary health score (0-100)
            # Full health score calculation will be done in Task 3
            health_score = self._calculate_preliminary_health_score()

            cursor.execute("""
                INSERT INTO performance_snapshots
                (customer_id, timestamp, health_score, ttfb_ms,
                 cpu_percent, memory_percent, disk_percent,
                 slow_query_count, active_connections, db_size_bytes,
                 redis_hit_rate, varnish_hit_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                self.customer_id, self.timestamp, health_score, self.ttfb_ms,
                self.cpu_percent, self.memory_percent, self.disk_percent,
                self.slow_query_count, self.active_connections, self.table_size_bytes,
                self.redis_hit_rate, self.varnish_hit_rate
            ))
            conn.commit()
            logger.debug(f"Saved performance snapshot for customer {self.customer_id}")
        except Exception as e:
            logger.error(f"Failed to save performance snapshot: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def _calculate_preliminary_health_score(self) -> int:
        """
        Calculate a preliminary health score (0-100).
        This is a simplified version - Task 3 will implement the full algorithm.
        """
        score = 100
        deductions = 0

        # TTFB scoring (target < 500ms)
        if self.ttfb_ms is not None:
            if self.ttfb_ms > 3000:
                deductions += 30
            elif self.ttfb_ms > 1500:
                deductions += 20
            elif self.ttfb_ms > 500:
                deductions += 10

        # CPU scoring
        if self.cpu_percent is not None:
            if self.cpu_percent > 90:
                deductions += 20
            elif self.cpu_percent > 80:
                deductions += 10
            elif self.cpu_percent > 70:
                deductions += 5

        # Memory scoring
        if self.memory_percent is not None:
            if self.memory_percent > 95:
                deductions += 20
            elif self.memory_percent > 85:
                deductions += 10
            elif self.memory_percent > 75:
                deductions += 5

        # Slow query scoring
        if self.slow_query_count is not None:
            if self.slow_query_count > 10:
                deductions += 20
            elif self.slow_query_count > 5:
                deductions += 10
            elif self.slow_query_count > 0:
                deductions += 5

        # Cache hit rate scoring
        if self.redis_hit_rate is not None:
            if self.redis_hit_rate < 50:
                deductions += 15
            elif self.redis_hit_rate < 70:
                deductions += 10
            elif self.redis_hit_rate < 80:
                deductions += 5

        return max(0, score - deductions)

    @staticmethod
    def cleanup_old_snapshots(hours: int = 168) -> int:
        """Delete snapshots older than specified hours (default 7 days)"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM performance_snapshots
                WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s HOUR)
            """, (hours,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        finally:
            cursor.close()
            conn.close()


class MonitoringWorker:
    """Main monitoring worker class"""

    def __init__(self):
        self.last_cleanup = datetime.now()

    def run(self):
        """Main loop - runs continuously"""
        logger.info("Monitoring worker started")
        logger.info(f"Configuration: interval={CHECK_INTERVAL}s, threshold={ALERT_THRESHOLD}, "
                   f"cooldown={ALERT_COOLDOWN}s, cpu_warn={RESOURCE_WARNING_CPU}%, "
                   f"mem_warn={RESOURCE_WARNING_MEMORY}%")

        while True:
            try:
                self.run_check_cycle()

                # Periodic cleanup of old data
                if (datetime.now() - self.last_cleanup).total_seconds() > CLEANUP_INTERVAL:
                    deleted = MonitoringCheck.cleanup_old_checks(hours=48)
                    if deleted > 0:
                        logger.info(f"Cleaned up {deleted} old monitoring checks")

                    # Clean up old performance snapshots (keep 7 days)
                    if PERFORMANCE_METRICS_ENABLED:
                        perf_deleted = PerformanceMetrics.cleanup_old_snapshots(hours=168)
                        if perf_deleted > 0:
                            logger.info(f"Cleaned up {perf_deleted} old performance snapshots")

                    self.last_cleanup = datetime.now()

            except Exception as e:
                logger.error(f"Check cycle error: {e}", exc_info=True)

            time.sleep(CHECK_INTERVAL)

    def run_check_cycle(self):
        """Run checks for all active customers"""
        customers = Customer.get_by_status('active')
        logger.info(f"Running checks for {len(customers)} active customers")

        for customer in customers:
            try:
                self.check_customer(customer)
            except Exception as e:
                logger.error(f"Error checking {customer.domain}: {e}", exc_info=True)

    def check_customer(self, customer):
        """Run all checks for a single customer"""
        status = CustomerMonitoringStatus.get_or_create(customer.id)

        # HTTP check with TTFB measurement
        http_ok, http_time, ttfb_ms = self.check_http_with_ttfb(customer)
        http_status = 'up' if http_ok else 'down'

        status.update_http_status(http_status, http_time)
        MonitoringCheck(
            customer_id=customer.id,
            check_type='http',
            status=http_status,
            response_time_ms=http_time
        ).save()

        # Container + resource check
        container_ok, cpu, mem_mb, disk_mb = self.check_container(customer)
        container_status = 'up' if container_ok else 'down'

        # Calculate memory percentage
        mem_percent = None
        if container_ok:
            if cpu is not None and cpu > RESOURCE_WARNING_CPU:
                container_status = 'degraded'
                logger.warning(f"{customer.domain}: High CPU usage ({cpu}%)")

            # Calculate memory percentage if we have the limit
            plan = customer.plan_id
            if plan and mem_mb:
                # Try to get memory limit from plan
                try:
                    from models import PricingPlan
                    pricing_plan = PricingPlan.get_by_id(plan)
                    if pricing_plan and pricing_plan.memory_limit:
                        # Parse memory limit (e.g., "1g", "512m")
                        limit_str = pricing_plan.memory_limit.lower()
                        if limit_str.endswith('g'):
                            limit_mb = float(limit_str[:-1]) * 1024
                        elif limit_str.endswith('m'):
                            limit_mb = float(limit_str[:-1])
                        else:
                            limit_mb = float(limit_str)

                        mem_percent = (mem_mb / limit_mb) * 100
                        if mem_percent > RESOURCE_WARNING_MEMORY:
                            container_status = 'degraded'
                            logger.warning(f"{customer.domain}: High memory usage ({mem_percent:.1f}%)")
                except Exception as e:
                    logger.debug(f"Could not check memory percentage: {e}")

        status.update_container_status(container_status, cpu, mem_mb, disk_mb)
        MonitoringCheck(
            customer_id=customer.id,
            check_type='container',
            status=container_status,
            details={'cpu': cpu, 'memory_mb': mem_mb, 'disk_mb': disk_mb}
        ).save()

        # Update uptime calculation
        status.calculate_uptime_24h()

        # Handle alerting
        self.process_alerts(customer, status, http_ok, container_ok)

        # Collect and store performance metrics if enabled
        if PERFORMANCE_METRICS_ENABLED and container_ok:
            self.collect_performance_metrics(customer, ttfb_ms, cpu, mem_percent)

    def check_http(self, customer):
        """
        HTTP health check (legacy method for compatibility).
        Returns: (success: bool, response_time_ms: int or None)
        """
        success, response_time, _ = self.check_http_with_ttfb(customer)
        return success, response_time

    def check_http_with_ttfb(self, customer):
        """
        HTTP health check with Time to First Byte measurement.
        Returns: (success: bool, response_time_ms: int or None, ttfb_ms: int or None)
        """
        url = f"https://{customer.domain}/"

        try:
            start = time.time()
            resp = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                allow_redirects=True,
                headers={'User-Agent': 'ShopHosting-Monitor/1.0'},
                stream=True  # Enable streaming to get accurate TTFB
            )

            # TTFB is the time until we receive the first byte of response
            ttfb_ms = int((time.time() - start) * 1000)

            # Read the rest of the response
            _ = resp.content

            elapsed_ms = int((time.time() - start) * 1000)

            # Consider 2xx and 3xx as success, 5xx as failure
            # 4xx might be auth issues, still means server is responding
            is_ok = resp.status_code < 500

            if not is_ok:
                logger.warning(f"{customer.domain}: HTTP {resp.status_code}")

            return is_ok, elapsed_ms, ttfb_ms

        except requests.exceptions.Timeout:
            logger.warning(f"{customer.domain}: HTTP timeout")
            return False, None, None
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"{customer.domain}: Connection error - {e}")
            return False, None, None
        except Exception as e:
            logger.error(f"{customer.domain}: HTTP check error - {e}")
            return False, None, None

    def check_container(self, customer):
        """
        Container health + resource check.
        Returns: (running: bool, cpu_percent: float, memory_mb: int, disk_mb: int)
        """
        container_name = f"customer-{customer.id}-web"

        try:
            # Check if container is running
            result = subprocess.run(
                ['docker', 'inspect', container_name, '--format', '{{.State.Running}}'],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0:
                logger.debug(f"{customer.domain}: Container not found")
                return False, None, None, None

            if 'true' not in result.stdout.lower():
                logger.warning(f"{customer.domain}: Container not running")
                return False, None, None, None

            # Get resource stats
            cpu, mem_mb, disk_mb = None, None, None

            stats_result = subprocess.run(
                ['docker', 'stats', container_name, '--no-stream', '--format',
                 '{{.CPUPerc}},{{.MemUsage}}'],
                capture_output=True, text=True, timeout=10
            )

            if stats_result.returncode == 0 and stats_result.stdout.strip():
                parts = stats_result.stdout.strip().split(',')
                if len(parts) >= 2:
                    # Parse CPU percentage
                    try:
                        cpu_str = parts[0].replace('%', '').strip()
                        cpu = float(cpu_str)
                    except ValueError:
                        pass

                    # Parse memory usage (format: "123MiB / 1GiB")
                    try:
                        mem_str = parts[1].split('/')[0].strip()
                        if 'GiB' in mem_str:
                            mem_mb = int(float(mem_str.replace('GiB', '').strip()) * 1024)
                        elif 'MiB' in mem_str:
                            mem_mb = int(float(mem_str.replace('MiB', '').strip()))
                        elif 'KiB' in mem_str:
                            mem_mb = int(float(mem_str.replace('KiB', '').strip()) / 1024)
                    except (ValueError, IndexError):
                        pass

            return True, cpu, mem_mb, disk_mb

        except subprocess.TimeoutExpired:
            logger.warning(f"{customer.domain}: Docker command timeout")
            return False, None, None, None
        except Exception as e:
            logger.error(f"{customer.domain}: Container check error - {e}")
            return False, None, None, None

    def collect_performance_metrics(self, customer, ttfb_ms, cpu_percent, mem_percent):
        """
        Collect and store comprehensive performance metrics for a customer.
        Called after basic health checks if container is running.
        """
        metrics = PerformanceMetrics(
            customer_id=customer.id,
            ttfb_ms=ttfb_ms,
            cpu_percent=cpu_percent,
            memory_percent=mem_percent
        )

        container_prefix = f"customer-{customer.id}"

        # Collect MySQL metrics
        db_metrics = self.collect_mysql_metrics(customer, container_prefix)
        if db_metrics:
            metrics.slow_query_count = db_metrics.get('slow_query_count')
            metrics.active_connections = db_metrics.get('active_connections')
            metrics.table_size_bytes = db_metrics.get('table_size_bytes')

        # Collect Redis metrics
        redis_metrics = self.collect_redis_metrics(customer, container_prefix)
        if redis_metrics:
            metrics.redis_hit_rate = redis_metrics.get('hit_rate')
            metrics.redis_memory_bytes = redis_metrics.get('memory_bytes')

        # Collect Varnish metrics (Magento only)
        if customer.platform == 'magento':
            varnish_metrics = self.collect_varnish_metrics(customer, container_prefix)
            if varnish_metrics:
                metrics.varnish_hit_rate = varnish_metrics.get('hit_rate')

        # Save the performance snapshot
        metrics.save()

    def collect_mysql_metrics(self, customer, container_prefix) -> Optional[Dict[str, Any]]:
        """
        Collect MySQL performance metrics from the database container.
        Returns dict with slow_query_count, active_connections, table_size_bytes.
        """
        db_container = f"{container_prefix}-db"

        # Check if container exists and is running
        if not self._container_is_running(db_container):
            logger.debug(f"{customer.domain}: MySQL container not available")
            return None

        metrics = {}

        # Escape special characters in password for shell
        escaped_password = customer.db_password.replace("'", "'\"'\"'") if customer.db_password else ''

        try:
            # Get slow query count from performance_schema
            # This counts queries that took > SLOW_QUERY_THRESHOLD_MS in the last interval
            slow_query_cmd = f"""
                docker exec {db_container} mysql -u{customer.db_user} -p'{escaped_password}' \
                -N -e "SELECT COUNT(*) FROM performance_schema.events_statements_summary_by_digest \
                WHERE AVG_TIMER_WAIT/1000000000 > {SLOW_QUERY_THRESHOLD_MS / 1000};" 2>/dev/null
            """
            result = subprocess.run(
                slow_query_cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                try:
                    metrics['slow_query_count'] = int(result.stdout.strip())
                except ValueError:
                    metrics['slow_query_count'] = 0
        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Slow query check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting slow query count: {e}")

        try:
            # Get active connections
            connections_cmd = f"""
                docker exec {db_container} mysql -u{customer.db_user} -p'{escaped_password}' \
                -N -e "SELECT COUNT(*) FROM information_schema.PROCESSLIST;" 2>/dev/null
            """
            result = subprocess.run(
                connections_cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                try:
                    metrics['active_connections'] = int(result.stdout.strip())
                except ValueError:
                    pass
        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Connection count check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting connection count: {e}")

        try:
            # Get total database size
            size_cmd = f"""
                docker exec {db_container} mysql -u{customer.db_user} -p'{escaped_password}' \
                -N -e "SELECT SUM(data_length + index_length) FROM information_schema.TABLES \
                WHERE table_schema = '{customer.db_name}';" 2>/dev/null
            """
            result = subprocess.run(
                size_cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != 'NULL':
                try:
                    metrics['table_size_bytes'] = int(float(result.stdout.strip()))
                except ValueError:
                    pass
        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Database size check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting database size: {e}")

        return metrics if metrics else None

    def collect_redis_metrics(self, customer, container_prefix) -> Optional[Dict[str, Any]]:
        """
        Collect Redis cache metrics from the Redis container.
        Returns dict with hit_rate (percentage) and memory_bytes.
        """
        redis_container = f"{container_prefix}-redis"

        # Check if container exists and is running
        if not self._container_is_running(redis_container):
            logger.debug(f"{customer.domain}: Redis container not available")
            return None

        metrics = {}

        try:
            # Get Redis INFO stats
            info_cmd = f"docker exec {redis_container} redis-cli INFO stats 2>/dev/null"
            result = subprocess.run(
                info_cmd, shell=True, capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0 and result.stdout:
                info = result.stdout
                keyspace_hits = None
                keyspace_misses = None

                for line in info.split('\n'):
                    if line.startswith('keyspace_hits:'):
                        keyspace_hits = int(line.split(':')[1].strip())
                    elif line.startswith('keyspace_misses:'):
                        keyspace_misses = int(line.split(':')[1].strip())

                # Calculate hit rate
                if keyspace_hits is not None and keyspace_misses is not None:
                    total = keyspace_hits + keyspace_misses
                    if total > 0:
                        metrics['hit_rate'] = round((keyspace_hits / total) * 100, 2)
                    else:
                        # No requests yet, consider 100% hit rate
                        metrics['hit_rate'] = 100.0

        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Redis stats check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting Redis stats: {e}")

        try:
            # Get Redis memory usage
            memory_cmd = f"docker exec {redis_container} redis-cli INFO memory 2>/dev/null"
            result = subprocess.run(
                memory_cmd, shell=True, capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0 and result.stdout:
                for line in result.stdout.split('\n'):
                    if line.startswith('used_memory:'):
                        metrics['memory_bytes'] = int(line.split(':')[1].strip())
                        break

        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Redis memory check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting Redis memory: {e}")

        return metrics if metrics else None

    def collect_varnish_metrics(self, customer, container_prefix) -> Optional[Dict[str, Any]]:
        """
        Collect Varnish cache metrics from the Varnish container.
        Only applicable for Magento customers.
        Returns dict with hit_rate (percentage).
        """
        varnish_container = f"{container_prefix}-varnish"

        # Check if container exists and is running
        if not self._container_is_running(varnish_container):
            logger.debug(f"{customer.domain}: Varnish container not available")
            return None

        metrics = {}

        try:
            # Get Varnish stats using varnishstat
            stats_cmd = f"docker exec {varnish_container} varnishstat -1 -f MAIN.cache_hit -f MAIN.cache_miss 2>/dev/null"
            result = subprocess.run(
                stats_cmd, shell=True, capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0 and result.stdout:
                cache_hit = 0
                cache_miss = 0

                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 2:
                        if 'cache_hit' in parts[0]:
                            cache_hit = int(parts[1])
                        elif 'cache_miss' in parts[0]:
                            cache_miss = int(parts[1])

                total = cache_hit + cache_miss
                if total > 0:
                    metrics['hit_rate'] = round((cache_hit / total) * 100, 2)
                else:
                    # No requests yet
                    metrics['hit_rate'] = 100.0

        except subprocess.TimeoutExpired:
            logger.debug(f"{customer.domain}: Varnish stats check timed out")
        except Exception as e:
            logger.debug(f"{customer.domain}: Error getting Varnish stats: {e}")

        return metrics if metrics else None

    def _container_is_running(self, container_name: str) -> bool:
        """Check if a Docker container exists and is running."""
        try:
            result = subprocess.run(
                ['docker', 'inspect', container_name, '--format', '{{.State.Running}}'],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0 and 'true' in result.stdout.lower()
        except (subprocess.TimeoutExpired, Exception):
            return False

    def process_alerts(self, customer, status, http_ok, container_ok):
        """Handle alert logic based on check results"""
        is_down = not http_ok or not container_ok

        if is_down:
            status.increment_failures()

            if status.should_alert(threshold=ALERT_THRESHOLD, cooldown_seconds=ALERT_COOLDOWN):
                # Determine what's down
                issues = []
                if not http_ok:
                    issues.append("HTTP")
                if not container_ok:
                    issues.append("Container")

                alert = MonitoringAlert(
                    customer_id=customer.id,
                    alert_type='down',
                    message=f"{customer.domain} is DOWN ({', '.join(issues)})",
                    details={'http': http_ok, 'container': container_ok}
                )
                alert.save()

                logger.error(f"ALERT: {alert.message}")
                self.send_alert_email(customer, alert)
                status.mark_alert_sent()
        else:
            # Check if recovering from failure
            if status.consecutive_failures >= ALERT_THRESHOLD:
                alert = MonitoringAlert(
                    customer_id=customer.id,
                    alert_type='recovered',
                    message=f"{customer.domain} has RECOVERED",
                    details={'previous_failures': status.consecutive_failures}
                )
                alert.save()

                logger.info(f"RECOVERY: {alert.message}")
                self.send_alert_email(customer, alert)

            status.reset_failures()

    def send_alert_email(self, customer, alert):
        """Send alert email to admins"""
        try:
            from email_utils import send_monitoring_alert
            success, message = send_monitoring_alert(customer, alert)
            if success:
                alert.mark_email_sent()
                logger.info(f"Alert email sent for {customer.domain}")
            else:
                logger.error(f"Failed to send alert email: {message}")
        except ImportError:
            logger.warning("send_monitoring_alert not available in email_utils")
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")


def main():
    """Entry point"""
    worker = MonitoringWorker()
    worker.run()


if __name__ == '__main__':
    main()
