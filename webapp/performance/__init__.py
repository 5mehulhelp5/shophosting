"""
ShopHosting.io Performance Module
Health score calculation, performance analysis, issue detection, and auto-remediation tools.
"""

from .health_score import calculate_health_score, HealthScoreCalculator
from .insights import get_performance_insights, InsightsGenerator
from .detection import (
    detect_issues,
    get_detection_rules,
    resolve_issue_by_id,
    IssueDetector,
    DetectedIssue,
    DetectionRule,
    Severity,
    DEFAULT_DETECTION_RULES,
)
from .playbooks import (
    execute_playbook_for_issue,
    get_playbook_for_issue,
    list_available_playbooks,
    PlaybookExecutor,
    PlaybookResult,
)
from .action_logger import ActionLogger
from .notifications import NotificationService

__all__ = [
    # Health score
    'calculate_health_score',
    'HealthScoreCalculator',
    # Insights
    'get_performance_insights',
    'InsightsGenerator',
    # Detection
    'detect_issues',
    'get_detection_rules',
    'resolve_issue_by_id',
    'IssueDetector',
    'DetectedIssue',
    'DetectionRule',
    'Severity',
    'DEFAULT_DETECTION_RULES',
    # Playbooks
    'execute_playbook_for_issue',
    'get_playbook_for_issue',
    'list_available_playbooks',
    'PlaybookExecutor',
    'PlaybookResult',
    # Action Logging
    'ActionLogger',
    # Notifications
    'NotificationService',
]
