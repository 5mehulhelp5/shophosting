"""
ShopHosting.io - Performance Insights Module

Generates performance insights for customer dashboard:
- Recent detected issues (from performance_issues table)
- Recommendations based on current metrics
- Resolved issues (last 24h)

Insight types:
- warning: Detected issues that need attention
- recommendation: Suggestions based on metric thresholds
- success: Recently resolved issues
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Insight Types and Data Classes
# =============================================================================

class InsightType(Enum):
    """Types of performance insights"""
    WARNING = 'warning'
    RECOMMENDATION = 'recommendation'
    SUCCESS = 'success'


@dataclass
class Insight:
    """A single performance insight"""
    id: str
    type: InsightType
    title: str
    message: str
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None
    issue_id: Optional[int] = None  # Link to performance_issues table

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            'id': self.id,
            'type': self.type.value,
            'title': self.title,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'relative_time': self._relative_time(),
            'details': self.details,
            'issue_id': self.issue_id,
        }

    def _relative_time(self) -> str:
        """Generate human-readable relative time string"""
        now = datetime.now()
        diff = now - self.timestamp

        seconds = diff.total_seconds()
        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f'{minutes} min ago'
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f'{hours} hour{"s" if hours > 1 else ""} ago'
        else:
            days = int(seconds / 86400)
            return f'{days} day{"s" if days > 1 else ""} ago'


# =============================================================================
# Recommendation Rules
# =============================================================================

# Thresholds for generating recommendations
RECOMMENDATION_RULES = {
    'redis_hit_rate': {
        'threshold': 70,
        'operator': '<',
        'title': 'Low cache hit rate',
        'message': 'Consider reviewing your caching strategy',
        'details': 'A low Redis cache hit rate means many requests are not being served from cache. This can slow down your site significantly.',
    },
    'memory_percent': {
        'threshold': 80,
        'operator': '>',
        'title': 'High memory usage',
        'message': 'Memory usage is high - consider optimizing or upgrading',
        'details': 'High memory usage can lead to slowdowns and potential out-of-memory errors. Consider clearing caches or upgrading your plan.',
    },
    'slow_query_count': {
        'threshold': 5,
        'operator': '>',
        'title': 'Slow database queries',
        'message': 'Slow queries detected - review database performance',
        'details': 'Multiple slow database queries can significantly impact page load times. Consider optimizing queries or adding indexes.',
    },
    'cpu_percent': {
        'threshold': 85,
        'operator': '>',
        'title': 'High CPU usage',
        'message': 'CPU usage is elevated - performance may be impacted',
        'details': 'High CPU usage can cause slow response times. Consider optimizing code or scaling resources.',
    },
    'disk_percent': {
        'threshold': 85,
        'operator': '>',
        'title': 'Disk space running low',
        'message': 'Running low on disk space - consider cleanup or upgrade',
        'details': 'Low disk space can prevent logs from being written and backups from being created.',
    },
}

# Issue type to user-friendly message mapping
ISSUE_TYPE_MESSAGES = {
    'high_memory': {
        'title': 'High memory usage detected',
        'message_template': 'Memory usage peaked at {memory_percent:.1f}%',
    },
    'slow_queries': {
        'title': 'Slow database queries detected',
        'message_template': '{slow_query_count} queries averaging >{avg_time:.1f}s',
    },
    'high_cpu': {
        'title': 'High CPU usage detected',
        'message_template': 'CPU usage at {cpu_percent:.1f}%',
    },
    'disk_filling': {
        'title': 'Disk space low',
        'message_template': 'Disk usage at {disk_percent:.1f}%',
    },
    'cache_miss_storm': {
        'title': 'High cache miss rate',
        'message_template': 'Cache hit rate dropped to {hit_rate:.1f}%',
    },
    'connection_exhaustion': {
        'title': 'Database connection limit near',
        'message_template': '{connections} of {max_connections} connections in use',
    },
    'response_time_degradation': {
        'title': 'Response time degraded',
        'message_template': 'Average response time {ttfb_ms}ms (above threshold)',
    },
}


# =============================================================================
# Insights Generator
# =============================================================================

class InsightsGenerator:
    """
    Generates performance insights for a customer by:
    1. Fetching recent issues from performance_issues table
    2. Generating recommendations based on current metrics
    3. Fetching recently resolved issues
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the generator.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from models import get_db_connection
        return get_db_connection(read_only=True)

    def get_insights(self, customer_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get all insights for a customer.

        Args:
            customer_id: The customer ID
            limit: Maximum number of insights to return

        Returns:
            List of insight dictionaries, sorted by timestamp descending
        """
        insights = []

        # 1. Get recent active issues (warnings)
        active_issues = self._get_active_issues(customer_id, limit=5)
        insights.extend(active_issues)

        # 2. Generate recommendations based on current metrics
        recommendations = self._generate_recommendations(customer_id)
        insights.extend(recommendations)

        # 3. Get recently resolved issues (successes)
        resolved_issues = self._get_resolved_issues(customer_id, limit=3)
        insights.extend(resolved_issues)

        # Sort by timestamp descending and apply limit
        insights.sort(key=lambda x: x.timestamp, reverse=True)
        insights = insights[:limit]

        return [insight.to_dict() for insight in insights]

    def _get_active_issues(self, customer_id: int, limit: int = 5) -> List[Insight]:
        """
        Get active (unresolved) issues from performance_issues table.

        Args:
            customer_id: The customer ID
            limit: Maximum number of issues to return

        Returns:
            List of Insight objects for active issues
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        insights = []

        try:
            cursor.execute("""
                SELECT id, issue_type, severity, detected_at, details
                FROM performance_issues
                WHERE customer_id = %s
                  AND resolved_at IS NULL
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'warning' THEN 2
                        ELSE 3
                    END,
                    detected_at DESC
                LIMIT %s
            """, (customer_id, limit))

            rows = cursor.fetchall()

            for row in rows:
                issue_type = row['issue_type']
                details = row['details']

                # Parse details JSON if present
                if details and isinstance(details, str):
                    import json
                    try:
                        details = json.loads(details)
                    except json.JSONDecodeError:
                        details = {}
                elif details is None:
                    details = {}

                # Get title and message from mapping
                type_info = ISSUE_TYPE_MESSAGES.get(issue_type, {
                    'title': issue_type.replace('_', ' ').title(),
                    'message_template': 'Issue detected'
                })

                # Format message with details
                try:
                    message = type_info['message_template'].format(**details)
                except (KeyError, TypeError):
                    message = 'Performance issue detected'

                insight = Insight(
                    id=f"issue-{row['id']}",
                    type=InsightType.WARNING,
                    title=type_info['title'],
                    message=message,
                    timestamp=row['detected_at'],
                    details=details,
                    issue_id=row['id']
                )
                insights.append(insight)

        except Exception as e:
            logger.error(f"Error fetching active issues for customer {customer_id}: {e}")
        finally:
            cursor.close()
            conn.close()

        return insights

    def _get_resolved_issues(self, customer_id: int, limit: int = 3) -> List[Insight]:
        """
        Get issues resolved in the last 24 hours.

        Args:
            customer_id: The customer ID
            limit: Maximum number of resolved issues to return

        Returns:
            List of Insight objects for resolved issues
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        insights = []

        try:
            cursor.execute("""
                SELECT id, issue_type, severity, detected_at, resolved_at,
                       auto_fixed, details
                FROM performance_issues
                WHERE customer_id = %s
                  AND resolved_at IS NOT NULL
                  AND resolved_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                ORDER BY resolved_at DESC
                LIMIT %s
            """, (customer_id, limit))

            rows = cursor.fetchall()

            for row in rows:
                issue_type = row['issue_type']
                details = row['details']

                # Parse details JSON if present
                if details and isinstance(details, str):
                    import json
                    try:
                        details = json.loads(details)
                    except json.JSONDecodeError:
                        details = {}
                elif details is None:
                    details = {}

                # Get type info
                type_info = ISSUE_TYPE_MESSAGES.get(issue_type, {
                    'title': issue_type.replace('_', ' ').title(),
                    'message_template': 'Issue'
                })

                # Build success message
                base_title = type_info['title'].replace('detected', '').strip()
                title = f"{base_title} resolved"

                if row['auto_fixed']:
                    message = 'Automatically resolved'
                else:
                    message = 'Issue resolved'

                # Add resolution context if available
                if details.get('resolution_message'):
                    message = details['resolution_message']

                insight = Insight(
                    id=f"resolved-{row['id']}",
                    type=InsightType.SUCCESS,
                    title=title,
                    message=message,
                    timestamp=row['resolved_at'],
                    details=details,
                    issue_id=row['id']
                )
                insights.append(insight)

        except Exception as e:
            logger.error(f"Error fetching resolved issues for customer {customer_id}: {e}")
        finally:
            cursor.close()
            conn.close()

        return insights

    def _generate_recommendations(self, customer_id: int) -> List[Insight]:
        """
        Generate recommendations based on current metrics.

        Uses simple heuristics based on RECOMMENDATION_RULES to suggest
        improvements when metrics exceed thresholds.

        Args:
            customer_id: The customer ID

        Returns:
            List of Insight objects for recommendations
        """
        insights = []

        # Get latest snapshot
        snapshot = self._get_latest_snapshot(customer_id)
        if not snapshot:
            return insights

        timestamp = snapshot.get('timestamp', datetime.now())

        for metric_name, rule in RECOMMENDATION_RULES.items():
            metric_value = snapshot.get(metric_name)

            if metric_value is None:
                continue

            # Check if threshold is exceeded
            threshold = rule['threshold']
            operator = rule['operator']

            should_recommend = False
            if operator == '<' and metric_value < threshold:
                should_recommend = True
            elif operator == '>' and metric_value > threshold:
                should_recommend = True

            if should_recommend:
                # Check if there's already an active issue for this
                if self._has_active_issue_for_metric(customer_id, metric_name):
                    # Skip recommendation if there's already a warning
                    continue

                insight = Insight(
                    id=f"rec-{metric_name}-{customer_id}",
                    type=InsightType.RECOMMENDATION,
                    title=rule['title'],
                    message=rule['message'],
                    timestamp=timestamp,
                    details={
                        'metric': metric_name,
                        'current_value': float(metric_value) if metric_value else 0,
                        'threshold': threshold,
                        'description': rule.get('details', ''),
                    }
                )
                insights.append(insight)

        return insights

    def _get_latest_snapshot(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get the most recent performance snapshot for a customer"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM performance_snapshots
                WHERE customer_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (customer_id,))
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error fetching snapshot for customer {customer_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _has_active_issue_for_metric(self, customer_id: int, metric_name: str) -> bool:
        """
        Check if there's already an active issue related to this metric.

        Helps avoid duplicate recommendations when there's already a warning.
        """
        # Map metric names to issue types
        metric_to_issue_type = {
            'redis_hit_rate': 'cache_miss_storm',
            'memory_percent': 'high_memory',
            'slow_query_count': 'slow_queries',
            'cpu_percent': 'high_cpu',
            'disk_percent': 'disk_filling',
        }

        issue_type = metric_to_issue_type.get(metric_name)
        if not issue_type:
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*) FROM performance_issues
                WHERE customer_id = %s
                  AND issue_type = %s
                  AND resolved_at IS NULL
            """, (customer_id, issue_type))
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as e:
            logger.error(f"Error checking active issues: {e}")
            return False
        finally:
            cursor.close()
            conn.close()


# =============================================================================
# Public API Function
# =============================================================================

def get_performance_insights(customer_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get performance insights for a customer.

    This is the main public API function that creates a generator
    instance and returns insights as a list of dictionaries.

    Args:
        customer_id: The customer ID to get insights for
        limit: Maximum number of insights to return (default 10)

    Returns:
        List of insight dictionaries:
        [
            {
                'id': 'issue-123',
                'type': 'warning',
                'title': 'Slow database queries detected',
                'message': '3 queries averaging >2s',
                'timestamp': '2026-02-01T12:00:00',
                'relative_time': '2 min ago',
                'details': {...},
                'issue_id': 123
            },
            ...
        ]
    """
    generator = InsightsGenerator()
    return generator.get_insights(customer_id, limit=limit)
