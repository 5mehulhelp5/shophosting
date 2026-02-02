"""
Resource Hotspot Detection for ShopHosting.io Admin Console

Identifies customers using excessive resources relative to their plan or peers.

Hotspot detection helps platform administrators identify:
- CPU hotspots: Sustained high CPU usage (default >80% for 30+ minutes)
- Memory hotspots: Consistently high memory utilization (default >90%)
- Disk hotspots: High disk usage relative to plan limits (default >85%)

Data sources:
- performance_snapshots: Real-time metrics collected by monitoring_worker
- customers: Customer information including domain and plan
- pricing_plans: Plan limits for resource comparison
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


class HotspotDetector:
    """Detects resource hotspots across the customer fleet.

    Provides methods to identify customers consuming disproportionate
    resources compared to their plan limits or peer averages.
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the hotspot detector.

        Args:
            db_connection_func: Function that returns a database connection.
                               If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection."""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection(read_only=True)

    def _convert_decimal(self, value: Any) -> Any:
        """Convert Decimal values to float for JSON serialization."""
        if isinstance(value, Decimal):
            return float(value)
        return value

    def _row_to_dict(self, row: Dict) -> Dict:
        """Convert a database row, handling Decimal conversions."""
        if row is None:
            return {}
        return {k: self._convert_decimal(v) for k, v in row.items()}

    def get_cpu_hotspots(
        self,
        threshold_percent: float = 80,
        duration_minutes: int = 30
    ) -> List[Dict]:
        """Find customers with sustained high CPU usage.

        Identifies customers whose average CPU usage has exceeded the threshold
        for the specified duration window.

        Args:
            threshold_percent: CPU usage threshold (0-100). Default 80%.
            duration_minutes: Time window to check for sustained usage. Default 30 min.

        Returns:
            List of dicts with: customer_id, domain, avg_cpu, max_cpu,
            duration_minutes, snapshot_count
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # Calculate the time window
            start_time = datetime.now() - timedelta(minutes=duration_minutes)

            # Query for customers with high average CPU in the window
            # Only include customers with sufficient data points (at least 50% of expected)
            # Assuming ~1 snapshot per minute, we expect at least half that many
            min_snapshots = max(1, duration_minutes // 2)

            query = """
                SELECT
                    ps.customer_id,
                    c.domain,
                    ROUND(AVG(ps.cpu_percent), 2) as avg_cpu,
                    ROUND(MAX(ps.cpu_percent), 2) as max_cpu,
                    COUNT(*) as snapshot_count,
                    %s as duration_minutes
                FROM performance_snapshots ps
                JOIN customers c ON ps.customer_id = c.id
                WHERE ps.timestamp >= %s
                  AND ps.cpu_percent IS NOT NULL
                GROUP BY ps.customer_id, c.domain
                HAVING AVG(ps.cpu_percent) >= %s
                   AND COUNT(*) >= %s
                ORDER BY avg_cpu DESC
                LIMIT 100
            """

            cursor.execute(query, (duration_minutes, start_time, threshold_percent, min_snapshots))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error detecting CPU hotspots: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_memory_hotspots(self, threshold_percent: float = 90) -> List[Dict]:
        """Find customers consistently using >threshold% memory.

        Identifies customers whose current or recent average memory usage
        exceeds the threshold.

        Args:
            threshold_percent: Memory usage threshold (0-100). Default 90%.

        Returns:
            List of dicts with: customer_id, domain, current_memory, avg_memory,
            limit_mb (from plan)
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # Get customers with recent high memory usage
            # Join with pricing_plans to get memory limits
            # Look at last 10 minutes of data for "current" state
            recent_window = datetime.now() - timedelta(minutes=10)

            query = """
                SELECT
                    ps.customer_id,
                    c.domain,
                    ROUND(
                        (SELECT memory_percent
                         FROM performance_snapshots ps2
                         WHERE ps2.customer_id = ps.customer_id
                         ORDER BY ps2.timestamp DESC
                         LIMIT 1), 2
                    ) as current_memory,
                    ROUND(AVG(ps.memory_percent), 2) as avg_memory,
                    CASE
                        WHEN pp.memory_limit IS NOT NULL THEN
                            CAST(REPLACE(REPLACE(pp.memory_limit, 'g', ''), 'm', '') AS DECIMAL) *
                            CASE
                                WHEN pp.memory_limit LIKE '%%g' THEN 1024
                                ELSE 1
                            END
                        ELSE 1024
                    END as limit_mb
                FROM performance_snapshots ps
                JOIN customers c ON ps.customer_id = c.id
                LEFT JOIN pricing_plans pp ON c.plan_id = pp.id
                WHERE ps.timestamp >= %s
                  AND ps.memory_percent IS NOT NULL
                GROUP BY ps.customer_id, c.domain, pp.memory_limit
                HAVING AVG(ps.memory_percent) >= %s
                ORDER BY avg_memory DESC
                LIMIT 100
            """

            cursor.execute(query, (recent_window, threshold_percent))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error detecting memory hotspots: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_disk_hotspots(self, threshold_percent: float = 85) -> List[Dict]:
        """Find customers with high disk usage.

        Identifies customers whose disk usage percentage exceeds the threshold.
        Uses the most recent snapshot for each customer.

        Args:
            threshold_percent: Disk usage threshold (0-100). Default 85%.

        Returns:
            List of dicts with: customer_id, domain, disk_percent,
            disk_used_gb, disk_total_gb
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # Get the latest disk usage for each customer
            # Join with pricing_plans to estimate disk limits
            query = """
                SELECT
                    ps.customer_id,
                    c.domain,
                    ROUND(ps.disk_percent, 2) as disk_percent,
                    ROUND(
                        COALESCE(pp.disk_limit_gb, 25) * ps.disk_percent / 100,
                        2
                    ) as disk_used_gb,
                    COALESCE(pp.disk_limit_gb, 25) as disk_total_gb
                FROM performance_snapshots ps
                JOIN customers c ON ps.customer_id = c.id
                LEFT JOIN pricing_plans pp ON c.plan_id = pp.id
                WHERE ps.id = (
                    SELECT ps2.id
                    FROM performance_snapshots ps2
                    WHERE ps2.customer_id = ps.customer_id
                    ORDER BY ps2.timestamp DESC
                    LIMIT 1
                )
                AND ps.disk_percent IS NOT NULL
                AND ps.disk_percent >= %s
                ORDER BY ps.disk_percent DESC
                LIMIT 100
            """

            cursor.execute(query, (threshold_percent,))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error detecting disk hotspots: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_all_hotspots(
        self,
        cpu_threshold: float = 80,
        cpu_duration: int = 30,
        memory_threshold: float = 90,
        disk_threshold: float = 85
    ) -> Dict[str, Any]:
        """Get all hotspots grouped by type.

        Retrieves CPU, memory, and disk hotspots in a single call,
        with summary statistics.

        Args:
            cpu_threshold: CPU usage threshold percentage. Default 80%.
            cpu_duration: Duration in minutes for sustained CPU usage. Default 30.
            memory_threshold: Memory usage threshold percentage. Default 90%.
            disk_threshold: Disk usage threshold percentage. Default 85%.

        Returns:
            Dict containing:
            - 'cpu': List of CPU hotspot dicts
            - 'memory': List of memory hotspot dicts
            - 'disk': List of disk hotspot dicts
            - 'summary': Dict with total_hotspots and affected_customers counts
            - 'thresholds': Dict of threshold values used
            - 'generated_at': ISO timestamp
        """
        cpu_hotspots = self.get_cpu_hotspots(
            threshold_percent=cpu_threshold,
            duration_minutes=cpu_duration
        )
        memory_hotspots = self.get_memory_hotspots(
            threshold_percent=memory_threshold
        )
        disk_hotspots = self.get_disk_hotspots(
            threshold_percent=disk_threshold
        )

        # Calculate summary statistics
        # Count unique affected customers across all hotspot types
        affected_customer_ids = set()
        for hotspot in cpu_hotspots:
            affected_customer_ids.add(hotspot.get('customer_id'))
        for hotspot in memory_hotspots:
            affected_customer_ids.add(hotspot.get('customer_id'))
        for hotspot in disk_hotspots:
            affected_customer_ids.add(hotspot.get('customer_id'))

        total_hotspots = len(cpu_hotspots) + len(memory_hotspots) + len(disk_hotspots)

        return {
            'cpu': cpu_hotspots,
            'memory': memory_hotspots,
            'disk': disk_hotspots,
            'summary': {
                'total_hotspots': total_hotspots,
                'affected_customers': len(affected_customer_ids),
                'cpu_count': len(cpu_hotspots),
                'memory_count': len(memory_hotspots),
                'disk_count': len(disk_hotspots),
            },
            'thresholds': {
                'cpu_percent': cpu_threshold,
                'cpu_duration_minutes': cpu_duration,
                'memory_percent': memory_threshold,
                'disk_percent': disk_threshold,
            },
            'generated_at': datetime.now().isoformat(),
        }

    def get_hotspots_for_customer(self, customer_id: int) -> Dict[str, Any]:
        """Get hotspot status for a specific customer.

        Checks if a customer is currently a hotspot for any resource type.

        Args:
            customer_id: The customer ID to check.

        Returns:
            Dict with 'is_hotspot' boolean and details for each resource type.
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # Get recent metrics for this customer
            recent_window = datetime.now() - timedelta(minutes=30)

            query = """
                SELECT
                    AVG(cpu_percent) as avg_cpu,
                    MAX(cpu_percent) as max_cpu,
                    AVG(memory_percent) as avg_memory,
                    (SELECT disk_percent
                     FROM performance_snapshots ps2
                     WHERE ps2.customer_id = %s
                     ORDER BY ps2.timestamp DESC
                     LIMIT 1) as current_disk,
                    COUNT(*) as snapshot_count
                FROM performance_snapshots
                WHERE customer_id = %s
                  AND timestamp >= %s
            """

            cursor.execute(query, (customer_id, customer_id, recent_window))
            row = cursor.fetchone()

            if not row or row['snapshot_count'] == 0:
                return {
                    'is_hotspot': False,
                    'customer_id': customer_id,
                    'cpu': {'is_hotspot': False, 'avg': None, 'max': None},
                    'memory': {'is_hotspot': False, 'avg': None},
                    'disk': {'is_hotspot': False, 'current': None},
                    'message': 'No recent performance data available',
                }

            avg_cpu = self._convert_decimal(row['avg_cpu'])
            max_cpu = self._convert_decimal(row['max_cpu'])
            avg_memory = self._convert_decimal(row['avg_memory'])
            current_disk = self._convert_decimal(row['current_disk'])

            # Check against default thresholds
            cpu_hotspot = avg_cpu is not None and avg_cpu >= 80
            memory_hotspot = avg_memory is not None and avg_memory >= 90
            disk_hotspot = current_disk is not None and current_disk >= 85

            is_hotspot = cpu_hotspot or memory_hotspot or disk_hotspot

            return {
                'is_hotspot': is_hotspot,
                'customer_id': customer_id,
                'cpu': {
                    'is_hotspot': cpu_hotspot,
                    'avg': round(avg_cpu, 2) if avg_cpu else None,
                    'max': round(max_cpu, 2) if max_cpu else None,
                    'threshold': 80,
                },
                'memory': {
                    'is_hotspot': memory_hotspot,
                    'avg': round(avg_memory, 2) if avg_memory else None,
                    'threshold': 90,
                },
                'disk': {
                    'is_hotspot': disk_hotspot,
                    'current': round(current_disk, 2) if current_disk else None,
                    'threshold': 85,
                },
                'checked_at': datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error checking hotspot status for customer {customer_id}: {e}")
            return {
                'is_hotspot': False,
                'customer_id': customer_id,
                'error': str(e),
            }
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_top_resource_consumers(
        self,
        resource_type: str = 'cpu',
        limit: int = 10
    ) -> List[Dict]:
        """Get top resource consumers regardless of threshold.

        Useful for identifying relative resource usage across the fleet.

        Args:
            resource_type: One of 'cpu', 'memory', or 'disk'.
            limit: Number of top consumers to return. Default 10.

        Returns:
            List of dicts with customer_id, domain, and resource usage metrics.
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # Map resource type to column name
            column_map = {
                'cpu': 'cpu_percent',
                'memory': 'memory_percent',
                'disk': 'disk_percent',
            }

            if resource_type not in column_map:
                logger.warning(f"Invalid resource type: {resource_type}")
                return []

            column = column_map[resource_type]
            recent_window = datetime.now() - timedelta(minutes=30)

            query = f"""
                SELECT
                    ps.customer_id,
                    c.domain,
                    ROUND(AVG(ps.{column}), 2) as avg_usage,
                    ROUND(MAX(ps.{column}), 2) as max_usage,
                    COUNT(*) as snapshot_count
                FROM performance_snapshots ps
                JOIN customers c ON ps.customer_id = c.id
                WHERE ps.timestamp >= %s
                  AND ps.{column} IS NOT NULL
                GROUP BY ps.customer_id, c.domain
                ORDER BY avg_usage DESC
                LIMIT %s
            """

            cursor.execute(query, (recent_window, limit))
            rows = cursor.fetchall()

            result = []
            for row in rows:
                item = self._row_to_dict(row)
                item['resource_type'] = resource_type
                result.append(item)

            return result

        except Exception as e:
            logger.error(f"Error getting top {resource_type} consumers: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


def get_hotspots(
    cpu_threshold: float = 80,
    cpu_duration: int = 30,
    memory_threshold: float = 90,
    disk_threshold: float = 85
) -> Dict[str, Any]:
    """Convenience function to get all hotspots.

    Args:
        cpu_threshold: CPU usage threshold percentage. Default 80%.
        cpu_duration: Duration in minutes for sustained CPU usage. Default 30.
        memory_threshold: Memory usage threshold percentage. Default 90%.
        disk_threshold: Disk usage threshold percentage. Default 85%.

    Returns:
        Dict with 'cpu', 'memory', 'disk' hotspot lists and 'summary'.
    """
    detector = HotspotDetector()
    return detector.get_all_hotspots(
        cpu_threshold=cpu_threshold,
        cpu_duration=cpu_duration,
        memory_threshold=memory_threshold,
        disk_threshold=disk_threshold
    )


def get_cpu_hotspots(threshold_percent: float = 80, duration_minutes: int = 30) -> List[Dict]:
    """Convenience function to get CPU hotspots only."""
    detector = HotspotDetector()
    return detector.get_cpu_hotspots(threshold_percent, duration_minutes)


def get_memory_hotspots(threshold_percent: float = 90) -> List[Dict]:
    """Convenience function to get memory hotspots only."""
    detector = HotspotDetector()
    return detector.get_memory_hotspots(threshold_percent)


def get_disk_hotspots(threshold_percent: float = 85) -> List[Dict]:
    """Convenience function to get disk hotspots only."""
    detector = HotspotDetector()
    return detector.get_disk_hotspots(threshold_percent)
