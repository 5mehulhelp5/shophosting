"""
ShopHosting.io - Automation Action Logger Module

Comprehensive logging for automation actions per Section 2.3 of the
Performance Optimization Suite design document.

Logs automation actions to the automation_actions table:
- customer_id: Customer the action was performed for
- issue_id: FK to performance_issues (nullable, if action is in response to issue)
- playbook_name: Name of the playbook that triggered the action
- action_name: Specific action performed (e.g., 'restart_php', 'clear_cache')
- executed_at: Timestamp when action was executed
- success: Boolean indicating if action succeeded
- result: JSON with command output, duration, errors

Captures:
- Command executed
- stdout/stderr output
- Duration (milliseconds)
- Error messages (if any)
"""

import logging
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ActionResult:
    """Result data for an automation action"""
    command: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {}
        if self.command is not None:
            result['command'] = self.command
        if self.stdout is not None:
            result['stdout'] = self.stdout
        if self.stderr is not None:
            result['stderr'] = self.stderr
        if self.duration_ms is not None:
            result['duration_ms'] = self.duration_ms
        if self.error_message is not None:
            result['error_message'] = self.error_message
        if self.details:
            result['details'] = self.details
        return result


@dataclass
class ActionLogEntry:
    """A logged automation action"""
    id: int
    customer_id: int
    playbook_name: str
    action_name: str
    executed_at: datetime
    success: bool
    result: Dict[str, Any]
    issue_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'issue_id': self.issue_id,
            'playbook_name': self.playbook_name,
            'action_name': self.action_name,
            'executed_at': self.executed_at.isoformat(),
            'relative_time': self._relative_time(),
            'success': self.success,
            'result': self.result,
        }

    def _relative_time(self) -> str:
        """Generate human-readable relative time string"""
        now = datetime.now()
        diff = now - self.executed_at

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
# Action Logger Class
# =============================================================================

class ActionLogger:
    """
    Logs automation actions to the database for audit trail and history display.

    Used by:
    - Playbooks when executing automated remediation actions
    - Performance worker when taking corrective actions
    - Admin tools when manually triggering actions

    Actions are stored in the automation_actions table with full result details
    including command output, duration, and any errors encountered.
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the action logger.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self, read_only: bool = False):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection(read_only=read_only)

    def log_action(
        self,
        customer_id: int,
        playbook_name: str,
        action_name: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        issue_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Log an automation action to the database.

        Args:
            customer_id: The customer ID the action was performed for
            playbook_name: Name of the playbook (e.g., 'memory_relief', 'cache_warmup')
            action_name: Specific action performed (e.g., 'restart_php', 'clear_redis')
            success: Whether the action succeeded
            result: Dictionary containing:
                - command: The command that was executed (optional)
                - stdout: Standard output from command (optional)
                - stderr: Standard error from command (optional)
                - duration_ms: Execution duration in milliseconds (optional)
                - error_message: Error message if action failed (optional)
                - details: Any additional details (optional)
            issue_id: FK to performance_issues if action was in response to an issue

        Returns:
            The ID of the logged action, or None if logging failed
        """
        if result is None:
            result = {}

        # If result is an ActionResult object, convert to dict
        if isinstance(result, ActionResult):
            result = result.to_dict()

        conn = self._get_connection(read_only=False)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO automation_actions
                    (customer_id, issue_id, playbook_name, action_name,
                     executed_at, success, result)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                customer_id,
                issue_id,
                playbook_name,
                action_name,
                datetime.now(),
                success,
                json.dumps(result)
            ))
            conn.commit()
            action_id = cursor.lastrowid

            # Log to application log as well for monitoring
            log_level = logging.INFO if success else logging.WARNING
            logger.log(
                log_level,
                f"Automation action logged: customer={customer_id} "
                f"playbook={playbook_name} action={action_name} "
                f"success={success} issue_id={issue_id}"
            )

            return action_id

        except Exception as e:
            logger.error(
                f"Failed to log automation action for customer {customer_id}: {e}"
            )
            conn.rollback()
            return None
        finally:
            cursor.close()
            conn.close()

    def get_customer_actions(
        self,
        customer_id: int,
        limit: int = 20,
        playbook_name: Optional[str] = None,
        success_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent automation actions for a customer.

        Args:
            customer_id: The customer ID to get actions for
            limit: Maximum number of actions to return (default 20)
            playbook_name: Optional filter by playbook name
            success_only: Optional filter by success status (True/False/None for all)

        Returns:
            List of action dictionaries sorted by executed_at descending:
            [
                {
                    'id': 1,
                    'customer_id': 123,
                    'issue_id': 456,  # or None
                    'playbook_name': 'memory_relief',
                    'action_name': 'restart_php',
                    'executed_at': '2026-02-01T12:00:00',
                    'relative_time': '5 min ago',
                    'success': True,
                    'result': {
                        'command': 'docker restart ...',
                        'duration_ms': 1500,
                        'stdout': '...'
                    }
                },
                ...
            ]
        """
        conn = self._get_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            # Build query with optional filters
            query = """
                SELECT id, customer_id, issue_id, playbook_name, action_name,
                       executed_at, success, result
                FROM automation_actions
                WHERE customer_id = %s
            """
            params = [customer_id]

            if playbook_name is not None:
                query += " AND playbook_name = %s"
                params.append(playbook_name)

            if success_only is not None:
                query += " AND success = %s"
                params.append(success_only)

            query += " ORDER BY executed_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

            actions = []
            for row in rows:
                # Parse result JSON
                result_data = row.get('result')
                if result_data:
                    if isinstance(result_data, str):
                        try:
                            result_data = json.loads(result_data)
                        except json.JSONDecodeError:
                            result_data = {}
                else:
                    result_data = {}

                entry = ActionLogEntry(
                    id=row['id'],
                    customer_id=row['customer_id'],
                    issue_id=row.get('issue_id'),
                    playbook_name=row['playbook_name'],
                    action_name=row['action_name'],
                    executed_at=row['executed_at'],
                    success=bool(row['success']),
                    result=result_data
                )
                actions.append(entry.to_dict())

            return actions

        except Exception as e:
            logger.error(
                f"Failed to get automation actions for customer {customer_id}: {e}"
            )
            return []
        finally:
            cursor.close()
            conn.close()

    def get_action_by_id(self, action_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific automation action by ID.

        Args:
            action_id: The action ID to retrieve

        Returns:
            Action dictionary or None if not found
        """
        conn = self._get_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT id, customer_id, issue_id, playbook_name, action_name,
                       executed_at, success, result
                FROM automation_actions
                WHERE id = %s
            """, (action_id,))

            row = cursor.fetchone()
            if not row:
                return None

            # Parse result JSON
            result_data = row.get('result')
            if result_data:
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except json.JSONDecodeError:
                        result_data = {}
            else:
                result_data = {}

            entry = ActionLogEntry(
                id=row['id'],
                customer_id=row['customer_id'],
                issue_id=row.get('issue_id'),
                playbook_name=row['playbook_name'],
                action_name=row['action_name'],
                executed_at=row['executed_at'],
                success=bool(row['success']),
                result=result_data
            )
            return entry.to_dict()

        except Exception as e:
            logger.error(f"Failed to get automation action {action_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_actions_for_issue(self, issue_id: int) -> List[Dict[str, Any]]:
        """
        Get all automation actions taken for a specific performance issue.

        Args:
            issue_id: The performance issue ID

        Returns:
            List of action dictionaries sorted by executed_at ascending (chronological)
        """
        conn = self._get_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT id, customer_id, issue_id, playbook_name, action_name,
                       executed_at, success, result
                FROM automation_actions
                WHERE issue_id = %s
                ORDER BY executed_at ASC
            """, (issue_id,))

            rows = cursor.fetchall()

            actions = []
            for row in rows:
                # Parse result JSON
                result_data = row.get('result')
                if result_data:
                    if isinstance(result_data, str):
                        try:
                            result_data = json.loads(result_data)
                        except json.JSONDecodeError:
                            result_data = {}
                else:
                    result_data = {}

                entry = ActionLogEntry(
                    id=row['id'],
                    customer_id=row['customer_id'],
                    issue_id=row.get('issue_id'),
                    playbook_name=row['playbook_name'],
                    action_name=row['action_name'],
                    executed_at=row['executed_at'],
                    success=bool(row['success']),
                    result=result_data
                )
                actions.append(entry.to_dict())

            return actions

        except Exception as e:
            logger.error(f"Failed to get actions for issue {issue_id}: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_action_stats(
        self,
        customer_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get automation action statistics for a customer.

        Args:
            customer_id: The customer ID
            days: Number of days to look back (default 7)

        Returns:
            Dictionary with action statistics:
            {
                'total_actions': 15,
                'successful_actions': 14,
                'failed_actions': 1,
                'success_rate': 93.33,
                'by_playbook': {
                    'memory_relief': {'total': 5, 'success': 5},
                    'cache_warmup': {'total': 10, 'success': 9}
                }
            }
        """
        conn = self._get_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    playbook_name
                FROM automation_actions
                WHERE customer_id = %s
                  AND executed_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY playbook_name
            """, (customer_id, days))

            rows = cursor.fetchall()

            total = 0
            successful = 0
            by_playbook = {}

            for row in rows:
                playbook = row['playbook_name']
                playbook_total = row['total']
                playbook_success = row['successful'] or 0

                total += playbook_total
                successful += playbook_success

                by_playbook[playbook] = {
                    'total': playbook_total,
                    'success': playbook_success
                }

            failed = total - successful
            success_rate = round((successful / total * 100), 2) if total > 0 else 100.0

            return {
                'total_actions': total,
                'successful_actions': successful,
                'failed_actions': failed,
                'success_rate': success_rate,
                'by_playbook': by_playbook,
                'period_days': days
            }

        except Exception as e:
            logger.error(
                f"Failed to get action stats for customer {customer_id}: {e}"
            )
            return {
                'total_actions': 0,
                'successful_actions': 0,
                'failed_actions': 0,
                'success_rate': 100.0,
                'by_playbook': {},
                'period_days': days
            }
        finally:
            cursor.close()
            conn.close()


# =============================================================================
# Public API Functions
# =============================================================================

def log_action(
    customer_id: int,
    playbook_name: str,
    action_name: str,
    success: bool,
    result: Optional[Dict[str, Any]] = None,
    issue_id: Optional[int] = None,
) -> Optional[int]:
    """
    Log an automation action.

    This is the main public API function for logging actions.
    Creates an ActionLogger instance and logs the action.

    Args:
        customer_id: The customer ID the action was performed for
        playbook_name: Name of the playbook (e.g., 'memory_relief', 'cache_warmup')
        action_name: Specific action performed (e.g., 'restart_php', 'clear_redis')
        success: Whether the action succeeded
        result: Dictionary with command output, duration, errors (see ActionLogger.log_action)
        issue_id: FK to performance_issues if action was in response to an issue

    Returns:
        The ID of the logged action, or None if logging failed
    """
    logger_instance = ActionLogger()
    return logger_instance.log_action(
        customer_id=customer_id,
        playbook_name=playbook_name,
        action_name=action_name,
        success=success,
        result=result,
        issue_id=issue_id
    )


def get_customer_actions(
    customer_id: int,
    limit: int = 20,
    playbook_name: Optional[str] = None,
    success_only: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """
    Get recent automation actions for a customer.

    This is the main public API function for retrieving action history.

    Args:
        customer_id: The customer ID to get actions for
        limit: Maximum number of actions to return (default 20)
        playbook_name: Optional filter by playbook name
        success_only: Optional filter by success status

    Returns:
        List of action dictionaries (see ActionLogger.get_customer_actions)
    """
    logger_instance = ActionLogger()
    return logger_instance.get_customer_actions(
        customer_id=customer_id,
        limit=limit,
        playbook_name=playbook_name,
        success_only=success_only
    )
