"""
ShopHosting.io Performance Module
Health score calculation, performance analysis, and issue detection tools.
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
]
