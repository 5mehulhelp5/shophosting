"""
ShopHosting.io Performance Module
Health score calculation and performance analysis tools.
"""

from .health_score import calculate_health_score, HealthScoreCalculator
from .insights import get_performance_insights, InsightsGenerator

__all__ = [
    'calculate_health_score',
    'HealthScoreCalculator',
    'get_performance_insights',
    'InsightsGenerator',
]
