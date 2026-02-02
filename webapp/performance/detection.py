"""
ShopHosting.io - Issue Detection Rules Engine

Detects performance issues based on configurable rules and time windows.
Implements rolling window detection for time-based rules using performance_snapshots.

Detection Rules:
| Issue                 | Detection Rule                 | Severity |
|-----------------------|--------------------------------|----------|
| high_memory           | >85% for 5 min                 | warning  |
| critical_memory       | >95% for 2 min                 | critical |
| high_cpu              | >90% for 10 min                | warning  |
| slow_queries          | >5 queries >3s in 5 min        | warning  |
| cache_miss_storm      | hit rate <50% for 10 min       | warning  |
| disk_filling          | >90% used                      | warning  |
| disk_critical         | >95% used                      | critical |
| response_degradation  | TTFB >3s for 5 min             | warning  |
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Data Classes
# =============================================================================

class Severity(Enum):
    """Issue severity levels"""
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'


@dataclass
class DetectionRule:
    """
    Configuration for a single detection rule.

    Attributes:
        issue_type: Unique identifier for the issue (e.g., 'high_memory')
        metric_name: Name of the metric to check in performance_snapshots
        threshold: Threshold value to compare against
        operator: Comparison operator ('>' or '<')
        duration_minutes: How long condition must persist (0 for instant)
        severity: Issue severity level
        description: Human-readable description of the rule
        custom_detector: Optional custom detection function
    """
    issue_type: str
    metric_name: str
    threshold: float
    operator: str  # '>' or '<'
    duration_minutes: int
    severity: Severity
    description: str = ''
    custom_detector: Optional[Callable] = None


@dataclass
class DetectedIssue:
    """
    Represents a detected performance issue.

    Attributes:
        issue_type: The type of issue detected
        severity: Severity level
        detected_at: When the issue was first detected
        details: Additional context about the issue
        customer_id: The affected customer
        existing_issue_id: If this matches an existing open issue, its ID
    """
    issue_type: str
    severity: Severity
    detected_at: datetime
    details: Dict[str, Any] = field(default_factory=dict)
    customer_id: Optional[int] = None
    existing_issue_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'issue_type': self.issue_type,
            'severity': self.severity.value,
            'detected_at': self.detected_at.isoformat(),
            'details': self.details,
            'customer_id': self.customer_id,
        }


# =============================================================================
# Default Detection Rules
# =============================================================================

DEFAULT_DETECTION_RULES = [
    DetectionRule(
        issue_type='high_memory',
        metric_name='memory_percent',
        threshold=85.0,
        operator='>',
        duration_minutes=5,
        severity=Severity.WARNING,
        description='Memory usage exceeds 85% for 5 minutes'
    ),
    DetectionRule(
        issue_type='critical_memory',
        metric_name='memory_percent',
        threshold=95.0,
        operator='>',
        duration_minutes=2,
        severity=Severity.CRITICAL,
        description='Memory usage exceeds 95% for 2 minutes'
    ),
    DetectionRule(
        issue_type='high_cpu',
        metric_name='cpu_percent',
        threshold=90.0,
        operator='>',
        duration_minutes=10,
        severity=Severity.WARNING,
        description='CPU usage exceeds 90% for 10 minutes'
    ),
    DetectionRule(
        issue_type='slow_queries',
        metric_name='slow_query_count',
        threshold=5,
        operator='>',
        duration_minutes=5,
        severity=Severity.WARNING,
        description='More than 5 slow queries (>3s) in 5 minutes'
    ),
    DetectionRule(
        issue_type='cache_miss_storm',
        metric_name='redis_hit_rate',
        threshold=50.0,
        operator='<',
        duration_minutes=10,
        severity=Severity.WARNING,
        description='Cache hit rate below 50% for 10 minutes'
    ),
    DetectionRule(
        issue_type='disk_filling',
        metric_name='disk_percent',
        threshold=90.0,
        operator='>',
        duration_minutes=0,  # Instant detection
        severity=Severity.WARNING,
        description='Disk usage exceeds 90%'
    ),
    DetectionRule(
        issue_type='disk_critical',
        metric_name='disk_percent',
        threshold=95.0,
        operator='>',
        duration_minutes=0,  # Instant detection
        severity=Severity.CRITICAL,
        description='Disk usage exceeds 95%'
    ),
    DetectionRule(
        issue_type='response_degradation',
        metric_name='ttfb_ms',
        threshold=3000,  # 3 seconds in ms
        operator='>',
        duration_minutes=5,
        severity=Severity.WARNING,
        description='Time to First Byte exceeds 3 seconds for 5 minutes'
    ),
]


# =============================================================================
# Issue Detector Class
# =============================================================================

class IssueDetector:
    """
    Detects performance issues based on configurable rules.

    Uses rolling windows from performance_snapshots for time-based rules.
    Stores NEW issues in performance_issues table (no duplicates of open issues).
    Marks issues as resolved when conditions clear.
    """

    def __init__(
        self,
        db_connection_func=None,
        rules: Optional[List[DetectionRule]] = None,
        snapshot_interval_seconds: int = 60
    ):
        """
        Initialize the issue detector.

        Args:
            db_connection_func: Function that returns a database connection.
                               If None, will import from models.
            rules: Custom detection rules. If None, uses DEFAULT_DETECTION_RULES.
            snapshot_interval_seconds: Expected interval between snapshots (default 60s).
                                       Used to calculate required snapshot count.
        """
        self._get_db_connection = db_connection_func
        self.rules = rules if rules is not None else DEFAULT_DETECTION_RULES
        self.snapshot_interval_seconds = snapshot_interval_seconds

        # Build rule lookup by issue_type for quick access
        self._rules_by_type = {rule.issue_type: rule for rule in self.rules}

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection()

    def detect_issues(self, customer_id: int) -> List[DetectedIssue]:
        """
        Detect all performance issues for a customer.

        Args:
            customer_id: The customer ID to check

        Returns:
            List of DetectedIssue objects for newly detected issues
        """
        detected = []
        now = datetime.now()

        # Get open issues to avoid duplicates
        open_issues = self._get_open_issues(customer_id)
        open_issue_types = {issue['issue_type'] for issue in open_issues}

        # Check each rule
        for rule in self.rules:
            try:
                is_triggered, details = self._check_rule(customer_id, rule, now)

                if is_triggered:
                    if rule.issue_type in open_issue_types:
                        # Issue already exists, skip
                        logger.debug(
                            f"Issue {rule.issue_type} already open for customer {customer_id}"
                        )
                        continue

                    # Create new detected issue
                    issue = DetectedIssue(
                        issue_type=rule.issue_type,
                        severity=rule.severity,
                        detected_at=now,
                        details=details,
                        customer_id=customer_id
                    )
                    detected.append(issue)

                    # Store in database
                    self._store_issue(issue)

                    logger.info(
                        f"Detected {rule.severity.value} issue '{rule.issue_type}' "
                        f"for customer {customer_id}: {details}"
                    )
            except Exception as e:
                logger.error(
                    f"Error checking rule {rule.issue_type} for customer {customer_id}: {e}"
                )

        # Check for issues that should be resolved
        self._check_resolutions(customer_id, open_issues, now)

        return detected

    def _check_rule(
        self,
        customer_id: int,
        rule: DetectionRule,
        now: datetime
    ) -> tuple:
        """
        Check if a detection rule is triggered.

        Args:
            customer_id: The customer ID
            rule: The detection rule to check
            now: Current timestamp

        Returns:
            Tuple of (is_triggered: bool, details: dict)
        """
        # Handle custom detector if provided
        if rule.custom_detector:
            return rule.custom_detector(customer_id, rule, self)

        # Get snapshots for the time window
        if rule.duration_minutes > 0:
            snapshots = self._get_snapshots_in_window(
                customer_id,
                now - timedelta(minutes=rule.duration_minutes),
                now
            )
        else:
            # Instant detection - just get the latest snapshot
            snapshots = self._get_snapshots_in_window(
                customer_id,
                now - timedelta(minutes=5),  # Look back 5 min for latest
                now,
                limit=1
            )

        if not snapshots:
            return False, {}

        # Check if condition is met across the window
        return self._evaluate_condition(snapshots, rule)

    def _evaluate_condition(
        self,
        snapshots: List[Dict[str, Any]],
        rule: DetectionRule
    ) -> tuple:
        """
        Evaluate whether a condition is met across snapshots.

        For time-based rules, the condition must be met in ALL snapshots
        in the window (sustained condition).

        Args:
            snapshots: List of snapshot dictionaries
            rule: The detection rule

        Returns:
            Tuple of (is_triggered: bool, details: dict)
        """
        if not snapshots:
            return False, {}

        metric_values = []

        for snapshot in snapshots:
            value = snapshot.get(rule.metric_name)
            if value is not None:
                metric_values.append(float(value))

        if not metric_values:
            return False, {}

        # For instant detection (duration_minutes=0), check latest value
        if rule.duration_minutes == 0:
            latest_value = metric_values[0] if snapshots else None
            if latest_value is None:
                return False, {}

            is_triggered = self._compare(latest_value, rule.operator, rule.threshold)

            return is_triggered, {
                'current_value': latest_value,
                'threshold': rule.threshold,
                'metric': rule.metric_name,
            }

        # For time-based rules, check if condition is sustained
        # Require at least 2 data points for time-based detection
        min_snapshots = max(2, rule.duration_minutes // (self.snapshot_interval_seconds // 60))

        if len(metric_values) < min_snapshots:
            # Not enough data points to determine sustained condition
            return False, {}

        # Check if ALL values in the window exceed threshold
        all_exceed = all(
            self._compare(v, rule.operator, rule.threshold)
            for v in metric_values
        )

        if all_exceed:
            # Calculate statistics for details
            avg_value = sum(metric_values) / len(metric_values)
            max_value = max(metric_values)
            min_value = min(metric_values)

            return True, {
                'current_value': metric_values[0],  # Most recent
                'average_value': round(avg_value, 2),
                'max_value': max_value,
                'min_value': min_value,
                'threshold': rule.threshold,
                'metric': rule.metric_name,
                'duration_minutes': rule.duration_minutes,
                'sample_count': len(metric_values),
            }

        return False, {}

    @staticmethod
    def _compare(value: float, operator: str, threshold: float) -> bool:
        """Compare a value against a threshold using the given operator"""
        if operator == '>':
            return value > threshold
        elif operator == '<':
            return value < threshold
        elif operator == '>=':
            return value >= threshold
        elif operator == '<=':
            return value <= threshold
        elif operator == '==':
            return value == threshold
        else:
            raise ValueError(f"Unknown operator: {operator}")

    def _get_snapshots_in_window(
        self,
        customer_id: int,
        start_time: datetime,
        end_time: datetime,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get performance snapshots within a time window.

        Args:
            customer_id: The customer ID
            start_time: Start of the window
            end_time: End of the window
            limit: Optional limit on number of snapshots

        Returns:
            List of snapshot dictionaries, ordered by timestamp descending
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT * FROM performance_snapshots
                WHERE customer_id = %s
                  AND timestamp >= %s
                  AND timestamp <= %s
                ORDER BY timestamp DESC
            """
            params = [customer_id, start_time, end_time]

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            cursor.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(
                f"Error fetching snapshots for customer {customer_id}: {e}"
            )
            return []
        finally:
            cursor.close()
            conn.close()

    def _get_open_issues(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Get all open (unresolved) issues for a customer.

        Args:
            customer_id: The customer ID

        Returns:
            List of issue dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT id, issue_type, severity, detected_at, details
                FROM performance_issues
                WHERE customer_id = %s
                  AND resolved_at IS NULL
            """, (customer_id,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(
                f"Error fetching open issues for customer {customer_id}: {e}"
            )
            return []
        finally:
            cursor.close()
            conn.close()

    def _store_issue(self, issue: DetectedIssue) -> Optional[int]:
        """
        Store a detected issue in the database.

        Args:
            issue: The detected issue to store

        Returns:
            The ID of the inserted row, or None if failed
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO performance_issues
                (customer_id, issue_type, severity, detected_at, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                issue.customer_id,
                issue.issue_type,
                issue.severity.value,
                issue.detected_at,
                json.dumps(issue.details) if issue.details else None
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error storing issue: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()
            conn.close()

    def _check_resolutions(
        self,
        customer_id: int,
        open_issues: List[Dict[str, Any]],
        now: datetime
    ):
        """
        Check if any open issues should be resolved.

        An issue is resolved when the triggering condition is no longer met.

        Args:
            customer_id: The customer ID
            open_issues: List of currently open issues
            now: Current timestamp
        """
        for issue in open_issues:
            issue_type = issue['issue_type']
            rule = self._rules_by_type.get(issue_type)

            if not rule:
                # Unknown issue type, skip
                continue

            try:
                is_still_triggered, _ = self._check_rule(customer_id, rule, now)

                if not is_still_triggered:
                    # Resolve the issue
                    self._resolve_issue(issue['id'], now)
                    logger.info(
                        f"Resolved issue '{issue_type}' (ID: {issue['id']}) "
                        f"for customer {customer_id}"
                    )
            except Exception as e:
                logger.error(
                    f"Error checking resolution for issue {issue['id']}: {e}"
                )

    def _resolve_issue(self, issue_id: int, resolved_at: datetime):
        """
        Mark an issue as resolved.

        Args:
            issue_id: The issue ID to resolve
            resolved_at: When the issue was resolved
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE performance_issues
                SET resolved_at = %s
                WHERE id = %s
            """, (resolved_at, issue_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Error resolving issue {issue_id}: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def get_rule(self, issue_type: str) -> Optional[DetectionRule]:
        """
        Get a detection rule by issue type.

        Args:
            issue_type: The issue type to look up

        Returns:
            The DetectionRule, or None if not found
        """
        return self._rules_by_type.get(issue_type)

    def add_rule(self, rule: DetectionRule):
        """
        Add a new detection rule.

        Args:
            rule: The rule to add
        """
        self.rules.append(rule)
        self._rules_by_type[rule.issue_type] = rule

    def remove_rule(self, issue_type: str) -> bool:
        """
        Remove a detection rule by issue type.

        Args:
            issue_type: The issue type to remove

        Returns:
            True if removed, False if not found
        """
        if issue_type in self._rules_by_type:
            del self._rules_by_type[issue_type]
            self.rules = [r for r in self.rules if r.issue_type != issue_type]
            return True
        return False


# =============================================================================
# Public API Functions
# =============================================================================

def detect_issues(customer_id: int) -> List[Dict[str, Any]]:
    """
    Detect performance issues for a customer.

    This is the main public API function that creates a detector
    instance and returns detected issues as a list of dictionaries.

    Args:
        customer_id: The customer ID to check

    Returns:
        List of detected issue dictionaries:
        [
            {
                'issue_type': 'high_memory',
                'severity': 'warning',
                'detected_at': '2026-02-01T12:00:00',
                'details': {
                    'current_value': 87.5,
                    'threshold': 85.0,
                    ...
                },
                'customer_id': 123
            },
            ...
        ]
    """
    detector = IssueDetector()
    issues = detector.detect_issues(customer_id)
    return [issue.to_dict() for issue in issues]


def get_detection_rules() -> List[Dict[str, Any]]:
    """
    Get all configured detection rules.

    Returns:
        List of rule dictionaries with configuration details
    """
    return [
        {
            'issue_type': rule.issue_type,
            'metric_name': rule.metric_name,
            'threshold': rule.threshold,
            'operator': rule.operator,
            'duration_minutes': rule.duration_minutes,
            'severity': rule.severity.value,
            'description': rule.description,
        }
        for rule in DEFAULT_DETECTION_RULES
    ]


def resolve_issue_by_id(issue_id: int) -> bool:
    """
    Manually resolve an issue by ID.

    Args:
        issue_id: The issue ID to resolve

    Returns:
        True if resolved successfully, False otherwise
    """
    detector = IssueDetector()
    try:
        detector._resolve_issue(issue_id, datetime.now())
        return True
    except Exception as e:
        logger.error(f"Failed to resolve issue {issue_id}: {e}")
        return False
