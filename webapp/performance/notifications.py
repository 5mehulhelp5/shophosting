"""
ShopHosting.io - Customer Notification Service

Provides notification functionality for performance events:
- Issue detected (warning/critical)
- Auto-fix executed
- Issue resolved

Notification channels:
- Dashboard notifications (always)
- Email notifications (future - structure prepared)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class EventType(Enum):
    """Types of notification events"""
    ISSUE_DETECTED = 'issue_detected'
    AUTO_FIX_EXECUTED = 'auto_fix_executed'
    ISSUE_RESOLVED = 'issue_resolved'


class Severity(Enum):
    """Notification severity levels"""
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'
    SUCCESS = 'success'


# Map event types to default severities
EVENT_SEVERITY_MAP = {
    EventType.ISSUE_DETECTED: Severity.WARNING,
    EventType.AUTO_FIX_EXECUTED: Severity.INFO,
    EventType.ISSUE_RESOLVED: Severity.SUCCESS,
}

# Map severities to icon SVGs for dashboard display
SEVERITY_ICONS = {
    'info': '''<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="16" x2="12" y2="12"></line>
        <line x1="12" y1="8" x2="12.01" y2="8"></line>
    </svg>''',
    'warning': '''<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
        <line x1="12" y1="9" x2="12" y2="13"></line>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
    </svg>''',
    'critical': '''<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="15" y1="9" x2="9" y2="15"></line>
        <line x1="9" y1="9" x2="15" y2="15"></line>
    </svg>''',
    'success': '''<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
    </svg>''',
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Notification:
    """A single customer notification"""
    id: int
    customer_id: int
    event_type: str
    title: str
    message: str
    severity: str
    is_read: bool
    read_at: Optional[datetime]
    link_url: Optional[str]
    link_text: Optional[str]
    related_issue_id: Optional[int]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'event_type': self.event_type,
            'title': self.title,
            'message': self.message,
            'severity': self.severity,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'link_url': self.link_url,
            'link_text': self.link_text,
            'related_issue_id': self.related_issue_id,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'relative_time': self._relative_time(),
            'icon_svg': SEVERITY_ICONS.get(self.severity, SEVERITY_ICONS['info']),
        }

    def _relative_time(self) -> str:
        """Generate human-readable relative time string"""
        now = datetime.now()
        diff = now - self.created_at

        seconds = diff.total_seconds()
        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f'{minutes} min ago'
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f'{hours} hour{"s" if hours > 1 else ""} ago'
        elif seconds < 604800:  # 7 days
            days = int(seconds / 86400)
            return f'{days} day{"s" if days > 1 else ""} ago'
        else:
            return self.created_at.strftime('%b %d')


# =============================================================================
# Notification Service
# =============================================================================

class NotificationService:
    """
    Service for managing customer notifications.

    Handles:
    - Creating notifications for performance events
    - Retrieving notifications (with unread filtering)
    - Marking notifications as read
    - Getting unread count for badge display
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the service.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection()

    def notify_customer(
        self,
        customer_id: int,
        event_type: str,
        title: str,
        message: str,
        severity: Optional[str] = None,
        link_url: Optional[str] = None,
        link_text: Optional[str] = None,
        related_issue_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Create a notification for a customer.

        Args:
            customer_id: The customer to notify
            event_type: Type of event (issue_detected, auto_fix_executed, issue_resolved)
            title: Short notification title
            message: Detailed notification message
            severity: Notification severity (info, warning, critical, success)
                     Defaults based on event_type if not provided
            link_url: Optional URL to link to (e.g., /dashboard/health)
            link_text: Optional text for the link (e.g., "View Details")
            related_issue_id: Optional ID of related performance_issues record
            metadata: Optional additional data (for email templates, etc.)

        Returns:
            The ID of the created notification, or None on error
        """
        # Determine severity from event type if not provided
        if severity is None:
            try:
                event_enum = EventType(event_type)
                severity = EVENT_SEVERITY_MAP.get(event_enum, Severity.INFO).value
            except ValueError:
                severity = Severity.INFO.value

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Serialize metadata to JSON string if provided
            import json
            metadata_json = json.dumps(metadata) if metadata else None

            cursor.execute("""
                INSERT INTO customer_notifications
                (customer_id, event_type, title, message, severity,
                 link_url, link_text, related_issue_id, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                customer_id, event_type, title, message, severity,
                link_url, link_text, related_issue_id, metadata_json
            ))
            conn.commit()
            notification_id = cursor.lastrowid

            logger.info(
                f"Created notification {notification_id} for customer {customer_id}: "
                f"{event_type} - {title}"
            )

            # Future: Trigger email notification if enabled for customer
            # self._send_email_notification(customer_id, notification_id)

            return notification_id

        except Exception as e:
            logger.error(f"Error creating notification for customer {customer_id}: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()
            conn.close()

    def get_notifications(
        self,
        customer_id: int,
        unread_only: bool = False,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get notifications for a customer.

        Args:
            customer_id: The customer ID
            unread_only: If True, return only unread notifications
            limit: Maximum number of notifications to return (max 100)

        Returns:
            List of notification dictionaries
        """
        limit = min(limit, 100)  # Cap at 100
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        notifications = []

        try:
            query = """
                SELECT id, customer_id, event_type, title, message, severity,
                       is_read, read_at, link_url, link_text, related_issue_id,
                       metadata, created_at
                FROM customer_notifications
                WHERE customer_id = %s
            """
            params = [customer_id]

            if unread_only:
                query += " AND is_read = FALSE"

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            for row in rows:
                # Parse metadata JSON
                metadata = row.get('metadata')
                if metadata and isinstance(metadata, str):
                    import json
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = None

                notification = Notification(
                    id=row['id'],
                    customer_id=row['customer_id'],
                    event_type=row['event_type'],
                    title=row['title'],
                    message=row['message'],
                    severity=row['severity'],
                    is_read=bool(row['is_read']),
                    read_at=row['read_at'],
                    link_url=row['link_url'],
                    link_text=row['link_text'],
                    related_issue_id=row['related_issue_id'],
                    metadata=metadata,
                    created_at=row['created_at']
                )
                notifications.append(notification.to_dict())

        except Exception as e:
            logger.error(f"Error fetching notifications for customer {customer_id}: {e}")
        finally:
            cursor.close()
            conn.close()

        return notifications

    def get_unread_count(self, customer_id: int) -> int:
        """
        Get count of unread notifications for a customer.

        Args:
            customer_id: The customer ID

        Returns:
            Number of unread notifications
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*) FROM customer_notifications
                WHERE customer_id = %s AND is_read = FALSE
            """, (customer_id,))
            count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Error getting unread count for customer {customer_id}: {e}")
            return 0
        finally:
            cursor.close()
            conn.close()

    def mark_as_read(self, notification_id: int, customer_id: int = None) -> bool:
        """
        Mark a notification as read.

        Args:
            notification_id: The notification ID to mark as read
            customer_id: Optional customer ID for security validation

        Returns:
            True if successful, False otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                UPDATE customer_notifications
                SET is_read = TRUE, read_at = NOW()
                WHERE id = %s AND is_read = FALSE
            """
            params = [notification_id]

            # Add customer_id check for security if provided
            if customer_id is not None:
                query += " AND customer_id = %s"
                params.append(customer_id)

            cursor.execute(query, params)
            conn.commit()

            success = cursor.rowcount > 0
            if success:
                logger.debug(f"Marked notification {notification_id} as read")
            return success

        except Exception as e:
            logger.error(f"Error marking notification {notification_id} as read: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def mark_all_as_read(self, customer_id: int) -> int:
        """
        Mark all notifications for a customer as read.

        Args:
            customer_id: The customer ID

        Returns:
            Number of notifications marked as read
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE customer_notifications
                SET is_read = TRUE, read_at = NOW()
                WHERE customer_id = %s AND is_read = FALSE
            """, (customer_id,))
            conn.commit()

            count = cursor.rowcount
            if count > 0:
                logger.info(f"Marked {count} notifications as read for customer {customer_id}")
            return count

        except Exception as e:
            logger.error(f"Error marking all notifications as read for customer {customer_id}: {e}")
            conn.rollback()
            return 0
        finally:
            cursor.close()
            conn.close()

    def delete_old_notifications(self, days: int = 30) -> int:
        """
        Delete read notifications older than specified days.
        Called by a maintenance job.

        Args:
            days: Delete read notifications older than this many days

        Returns:
            Number of notifications deleted
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM customer_notifications
                WHERE is_read = TRUE
                  AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            conn.commit()

            count = cursor.rowcount
            if count > 0:
                logger.info(f"Deleted {count} old read notifications")
            return count

        except Exception as e:
            logger.error(f"Error deleting old notifications: {e}")
            conn.rollback()
            return 0
        finally:
            cursor.close()
            conn.close()


# =============================================================================
# Helper Functions for Common Notifications
# =============================================================================

def notify_issue_detected(
    customer_id: int,
    issue_type: str,
    severity: str,
    details: Dict[str, Any],
    issue_id: Optional[int] = None
) -> Optional[int]:
    """
    Helper to create notification for detected performance issue.

    Args:
        customer_id: The customer ID
        issue_type: Type of issue (high_memory, slow_queries, etc.)
        severity: Issue severity (warning, critical)
        details: Issue details dictionary
        issue_id: Optional performance_issues table ID

    Returns:
        Notification ID or None
    """
    service = NotificationService()

    # Build title and message based on issue type
    issue_titles = {
        'high_memory': 'High Memory Usage',
        'slow_queries': 'Slow Database Queries',
        'high_cpu': 'High CPU Usage',
        'disk_filling': 'Disk Space Low',
        'cache_miss_storm': 'Cache Performance Degraded',
        'connection_exhaustion': 'Database Connection Limit',
        'response_time_degradation': 'Response Time Degraded',
    }

    title = issue_titles.get(issue_type, f'Performance Issue: {issue_type.replace("_", " ").title()}')

    # Build message based on details
    message = _build_issue_message(issue_type, details)

    return service.notify_customer(
        customer_id=customer_id,
        event_type=EventType.ISSUE_DETECTED.value,
        title=title,
        message=message,
        severity=severity,
        link_url='/dashboard/health',
        link_text='View Site Health',
        related_issue_id=issue_id,
        metadata={'issue_type': issue_type, 'details': details}
    )


def notify_auto_fix_executed(
    customer_id: int,
    playbook_name: str,
    action_name: str,
    success: bool,
    result: Optional[Dict[str, Any]] = None,
    issue_id: Optional[int] = None
) -> Optional[int]:
    """
    Helper to create notification for auto-fix execution.

    Args:
        customer_id: The customer ID
        playbook_name: Name of the playbook executed
        action_name: Name of the specific action
        success: Whether the action succeeded
        result: Optional result data
        issue_id: Optional performance_issues table ID

    Returns:
        Notification ID or None
    """
    service = NotificationService()

    if success:
        title = f'Auto-Fix Applied: {action_name.replace("_", " ").title()}'
        message = f'Automatic remediation was applied to address a performance issue. Playbook: {playbook_name}'
        severity = 'success'
    else:
        title = f'Auto-Fix Attempted: {action_name.replace("_", " ").title()}'
        message = f'Automatic remediation was attempted but may require attention. Playbook: {playbook_name}'
        severity = 'warning'

    return service.notify_customer(
        customer_id=customer_id,
        event_type=EventType.AUTO_FIX_EXECUTED.value,
        title=title,
        message=message,
        severity=severity,
        link_url='/dashboard/health',
        link_text='View Status',
        related_issue_id=issue_id,
        metadata={
            'playbook_name': playbook_name,
            'action_name': action_name,
            'success': success,
            'result': result
        }
    )


def notify_issue_resolved(
    customer_id: int,
    issue_type: str,
    auto_fixed: bool = False,
    issue_id: Optional[int] = None
) -> Optional[int]:
    """
    Helper to create notification for resolved issue.

    Args:
        customer_id: The customer ID
        issue_type: Type of issue that was resolved
        auto_fixed: Whether it was auto-fixed
        issue_id: Optional performance_issues table ID

    Returns:
        Notification ID or None
    """
    service = NotificationService()

    issue_titles = {
        'high_memory': 'Memory Usage',
        'slow_queries': 'Database Performance',
        'high_cpu': 'CPU Usage',
        'disk_filling': 'Disk Space',
        'cache_miss_storm': 'Cache Performance',
        'connection_exhaustion': 'Database Connections',
        'response_time_degradation': 'Response Time',
    }

    issue_name = issue_titles.get(issue_type, issue_type.replace('_', ' ').title())
    title = f'{issue_name} Issue Resolved'

    if auto_fixed:
        message = 'This issue was automatically resolved by our optimization system.'
    else:
        message = 'This performance issue has been resolved.'

    return service.notify_customer(
        customer_id=customer_id,
        event_type=EventType.ISSUE_RESOLVED.value,
        title=title,
        message=message,
        severity='success',
        link_url='/dashboard/health',
        link_text='View Site Health',
        related_issue_id=issue_id,
        metadata={'issue_type': issue_type, 'auto_fixed': auto_fixed}
    )


def _build_issue_message(issue_type: str, details: Dict[str, Any]) -> str:
    """Build a human-readable message for an issue based on its type and details."""
    templates = {
        'high_memory': 'Memory usage has reached {memory_percent:.1f}%, which may impact site performance.',
        'slow_queries': '{slow_query_count} slow database queries detected, averaging {avg_time:.1f}s execution time.',
        'high_cpu': 'CPU usage is at {cpu_percent:.1f}%, which may cause slow response times.',
        'disk_filling': 'Disk usage has reached {disk_percent:.1f}%. Consider cleaning up old files.',
        'cache_miss_storm': 'Cache hit rate has dropped to {hit_rate:.1f}%, causing increased database load.',
        'connection_exhaustion': '{connections} of {max_connections} database connections are in use.',
        'response_time_degradation': 'Average response time has increased to {ttfb_ms}ms.',
    }

    template = templates.get(issue_type)
    if template:
        try:
            return template.format(**details)
        except (KeyError, TypeError):
            pass

    return f'A performance issue has been detected: {issue_type.replace("_", " ")}'


# =============================================================================
# Public API
# =============================================================================

def get_notification_service(db_connection_func=None) -> NotificationService:
    """
    Get a NotificationService instance.

    Args:
        db_connection_func: Optional database connection function

    Returns:
        NotificationService instance
    """
    return NotificationService(db_connection_func)
