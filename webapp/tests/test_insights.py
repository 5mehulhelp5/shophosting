"""
Tests for the Performance Insights Module

Tests the insights generation as specified in Section 1.2 of the
Performance Optimization Suite design document.

Insight types:
- warning: Detected issues that need attention
- recommendation: Suggestions based on metric thresholds
- success: Recently resolved issues
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance.insights import (
    InsightsGenerator,
    get_performance_insights,
    Insight,
    InsightType,
    RECOMMENDATION_RULES,
    ISSUE_TYPE_MESSAGES,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db_connection():
    """Create a mock database connection function"""
    def get_connection():
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        conn.cursor.return_value = cursor
        return conn
    return get_connection


@pytest.fixture
def mock_active_issues():
    """Mock active performance issues"""
    return [
        {
            'id': 1,
            'issue_type': 'slow_queries',
            'severity': 'warning',
            'detected_at': datetime.now() - timedelta(minutes=5),
            'details': json.dumps({
                'slow_query_count': 7,
                'avg_time': 2.5
            })
        },
        {
            'id': 2,
            'issue_type': 'high_memory',
            'severity': 'critical',
            'detected_at': datetime.now() - timedelta(minutes=2),
            'details': json.dumps({
                'memory_percent': 92.5
            })
        },
    ]


@pytest.fixture
def mock_resolved_issues():
    """Mock resolved performance issues"""
    return [
        {
            'id': 3,
            'issue_type': 'high_memory',
            'severity': 'warning',
            'detected_at': datetime.now() - timedelta(hours=2),
            'resolved_at': datetime.now() - timedelta(hours=1),
            'auto_fixed': True,
            'details': json.dumps({
                'memory_percent': 88.0,
                'resolution_message': 'Peak of 88% resolved after cache cleanup'
            })
        },
    ]


@pytest.fixture
def mock_snapshot_low_cache():
    """Snapshot with low cache hit rate (should trigger recommendation)"""
    return {
        'customer_id': 1,
        'timestamp': datetime.now(),
        'redis_hit_rate': 65.0,  # Below 70% threshold
        'memory_percent': 60.0,
        'slow_query_count': 2,
        'cpu_percent': 50.0,
        'disk_percent': 45.0,
    }


@pytest.fixture
def mock_snapshot_high_memory():
    """Snapshot with high memory (should trigger recommendation)"""
    return {
        'customer_id': 1,
        'timestamp': datetime.now(),
        'redis_hit_rate': 85.0,
        'memory_percent': 85.0,  # Above 80% threshold
        'slow_query_count': 2,
        'cpu_percent': 50.0,
        'disk_percent': 45.0,
    }


@pytest.fixture
def mock_snapshot_healthy():
    """Healthy snapshot (should not trigger recommendations)"""
    return {
        'customer_id': 1,
        'timestamp': datetime.now(),
        'redis_hit_rate': 92.0,
        'memory_percent': 55.0,
        'slow_query_count': 2,
        'cpu_percent': 40.0,
        'disk_percent': 35.0,
    }


# =============================================================================
# Insight Class Tests
# =============================================================================

class TestInsight:
    """Tests for the Insight dataclass"""

    def test_insight_creation(self):
        """Test creating an Insight object"""
        insight = Insight(
            id='test-1',
            type=InsightType.WARNING,
            title='Test Warning',
            message='This is a test warning',
            timestamp=datetime.now(),
            details={'key': 'value'},
            issue_id=123
        )

        assert insight.id == 'test-1'
        assert insight.type == InsightType.WARNING
        assert insight.title == 'Test Warning'
        assert insight.message == 'This is a test warning'
        assert insight.details == {'key': 'value'}
        assert insight.issue_id == 123

    def test_insight_to_dict(self):
        """Test converting Insight to dictionary"""
        now = datetime.now()
        insight = Insight(
            id='test-2',
            type=InsightType.RECOMMENDATION,
            title='Test Recommendation',
            message='Consider doing this',
            timestamp=now,
            details={'metric': 'redis_hit_rate'},
            issue_id=None
        )

        result = insight.to_dict()

        assert result['id'] == 'test-2'
        assert result['type'] == 'recommendation'
        assert result['title'] == 'Test Recommendation'
        assert result['message'] == 'Consider doing this'
        assert result['timestamp'] == now.isoformat()
        assert 'relative_time' in result
        assert result['details'] == {'metric': 'redis_hit_rate'}
        assert result['issue_id'] is None

    def test_relative_time_just_now(self):
        """Test relative time for recent events"""
        insight = Insight(
            id='test-3',
            type=InsightType.SUCCESS,
            title='Test',
            message='Test',
            timestamp=datetime.now() - timedelta(seconds=30)
        )

        assert insight._relative_time() == 'just now'

    def test_relative_time_minutes(self):
        """Test relative time for minutes ago"""
        insight = Insight(
            id='test-4',
            type=InsightType.WARNING,
            title='Test',
            message='Test',
            timestamp=datetime.now() - timedelta(minutes=15)
        )

        assert insight._relative_time() == '15 min ago'

    def test_relative_time_hours(self):
        """Test relative time for hours ago"""
        insight = Insight(
            id='test-5',
            type=InsightType.WARNING,
            title='Test',
            message='Test',
            timestamp=datetime.now() - timedelta(hours=3)
        )

        assert insight._relative_time() == '3 hours ago'

    def test_relative_time_single_hour(self):
        """Test relative time for single hour ago"""
        insight = Insight(
            id='test-6',
            type=InsightType.WARNING,
            title='Test',
            message='Test',
            timestamp=datetime.now() - timedelta(hours=1)
        )

        assert insight._relative_time() == '1 hour ago'

    def test_relative_time_days(self):
        """Test relative time for days ago"""
        insight = Insight(
            id='test-7',
            type=InsightType.SUCCESS,
            title='Test',
            message='Test',
            timestamp=datetime.now() - timedelta(days=2)
        )

        assert insight._relative_time() == '2 days ago'


# =============================================================================
# InsightsGenerator Tests
# =============================================================================

class TestInsightsGenerator:
    """Tests for the InsightsGenerator class"""

    def test_generator_initialization(self, mock_db_connection):
        """Test initializing the generator with db connection"""
        generator = InsightsGenerator(db_connection_func=mock_db_connection)
        assert generator._get_db_connection is not None

    def test_get_active_issues(self, mock_db_connection, mock_active_issues):
        """Test fetching active issues"""
        # Setup mock to return active issues
        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchall.return_value = mock_active_issues
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        insights = generator._get_active_issues(customer_id=1, limit=5)

        assert len(insights) == 2
        # Critical issues should come first (sorted by severity)
        assert insights[0].type == InsightType.WARNING
        assert 'memory' in insights[1].title.lower() or 'queries' in insights[0].title.lower()

    def test_get_resolved_issues(self, mock_db_connection, mock_resolved_issues):
        """Test fetching resolved issues"""
        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchall.return_value = mock_resolved_issues
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        insights = generator._get_resolved_issues(customer_id=1, limit=3)

        assert len(insights) == 1
        assert insights[0].type == InsightType.SUCCESS
        assert 'resolved' in insights[0].title.lower()

    def test_generate_recommendations_low_cache(self, mock_db_connection, mock_snapshot_low_cache):
        """Test generating recommendations for low cache hit rate"""
        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            # Return snapshot for latest metrics
            cursor.fetchone.side_effect = [
                mock_snapshot_low_cache,  # _get_latest_snapshot
                (0,)  # _has_active_issue_for_metric count
            ]
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        recommendations = generator._generate_recommendations(customer_id=1)

        # Should have at least one recommendation for low cache hit rate
        assert len(recommendations) >= 1
        cache_rec = [r for r in recommendations if 'cache' in r.title.lower()]
        assert len(cache_rec) == 1
        assert cache_rec[0].type == InsightType.RECOMMENDATION

    def test_generate_recommendations_high_memory(self, mock_db_connection, mock_snapshot_high_memory):
        """Test generating recommendations for high memory usage"""
        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.side_effect = [
                mock_snapshot_high_memory,
                (0,)  # No active issues
            ]
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        recommendations = generator._generate_recommendations(customer_id=1)

        memory_rec = [r for r in recommendations if 'memory' in r.title.lower()]
        assert len(memory_rec) == 1
        assert 'high' in memory_rec[0].title.lower()

    def test_generate_recommendations_healthy(self, mock_db_connection, mock_snapshot_healthy):
        """Test that healthy snapshots don't generate recommendations"""
        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = mock_snapshot_healthy
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        recommendations = generator._generate_recommendations(customer_id=1)

        # Should have no recommendations when all metrics are healthy
        assert len(recommendations) == 0

    def test_skip_recommendation_when_active_issue_exists(self, mock_db_connection, mock_snapshot_high_memory):
        """Test that recommendations are skipped when there's an active issue for the same metric"""
        # Track which call we're on
        call_count = [0]

        def get_connection():
            conn = MagicMock()
            cursor = MagicMock()

            # First call is for getting snapshot, second for checking active issue
            def fetchone_side_effect():
                call_count[0] += 1
                if call_count[0] == 1:
                    return mock_snapshot_high_memory
                else:
                    return (1,)  # Has active issue for this metric

            cursor.fetchone.side_effect = fetchone_side_effect
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        recommendations = generator._generate_recommendations(customer_id=1)

        # Should skip memory recommendation since there's already an active issue
        memory_rec = [r for r in recommendations if 'memory' in r.title.lower()]
        assert len(memory_rec) == 0

    def test_get_insights_combined(self, mock_db_connection):
        """Test getting combined insights from all sources"""
        active_issues = [
            {
                'id': 1,
                'issue_type': 'slow_queries',
                'severity': 'warning',
                'detected_at': datetime.now() - timedelta(minutes=5),
                'details': json.dumps({'slow_query_count': 7, 'avg_time': 2.5})
            }
        ]

        resolved_issues = [
            {
                'id': 2,
                'issue_type': 'high_memory',
                'severity': 'warning',
                'detected_at': datetime.now() - timedelta(hours=2),
                'resolved_at': datetime.now() - timedelta(hours=1),
                'auto_fixed': True,
                'details': json.dumps({'resolution_message': 'Resolved after cleanup'})
            }
        ]

        healthy_snapshot = {
            'customer_id': 1,
            'timestamp': datetime.now(),
            'redis_hit_rate': 92.0,
            'memory_percent': 55.0,
            'slow_query_count': 2,
            'cpu_percent': 40.0,
            'disk_percent': 35.0,
        }

        call_count = 0

        def get_connection():
            nonlocal call_count
            conn = MagicMock()
            cursor = MagicMock()

            if call_count == 0:  # Active issues query
                cursor.fetchall.return_value = active_issues
            elif call_count == 1:  # Snapshot query
                cursor.fetchone.return_value = healthy_snapshot
            elif call_count == 2:  # Resolved issues query
                cursor.fetchall.return_value = resolved_issues

            call_count += 1
            conn.cursor.return_value = cursor
            return conn

        generator = InsightsGenerator(db_connection_func=get_connection)
        insights = generator.get_insights(customer_id=1, limit=10)

        # Should have warning from active issue and success from resolved issue
        assert len(insights) >= 2

        types = [i['type'] for i in insights]
        assert 'warning' in types
        assert 'success' in types


# =============================================================================
# Public API Tests
# =============================================================================

class TestGetPerformanceInsights:
    """Tests for the get_performance_insights public API function"""

    def test_get_performance_insights_returns_list(self, mock_db_connection):
        """Test that get_performance_insights returns a list"""
        with patch('performance.insights.InsightsGenerator') as MockGenerator:
            mock_instance = MockGenerator.return_value
            mock_instance.get_insights.return_value = []

            result = get_performance_insights(customer_id=1)

            assert isinstance(result, list)
            mock_instance.get_insights.assert_called_once_with(1, limit=10)

    def test_get_performance_insights_respects_limit(self, mock_db_connection):
        """Test that limit parameter is passed through"""
        with patch('performance.insights.InsightsGenerator') as MockGenerator:
            mock_instance = MockGenerator.return_value
            mock_instance.get_insights.return_value = []

            get_performance_insights(customer_id=1, limit=5)

            mock_instance.get_insights.assert_called_once_with(1, limit=5)


# =============================================================================
# Recommendation Rules Tests
# =============================================================================

class TestRecommendationRules:
    """Tests for recommendation rule configuration"""

    def test_redis_hit_rate_rule_exists(self):
        """Test that redis_hit_rate rule is configured"""
        assert 'redis_hit_rate' in RECOMMENDATION_RULES
        rule = RECOMMENDATION_RULES['redis_hit_rate']
        assert rule['threshold'] == 70
        assert rule['operator'] == '<'

    def test_memory_percent_rule_exists(self):
        """Test that memory_percent rule is configured"""
        assert 'memory_percent' in RECOMMENDATION_RULES
        rule = RECOMMENDATION_RULES['memory_percent']
        assert rule['threshold'] == 80
        assert rule['operator'] == '>'

    def test_slow_query_count_rule_exists(self):
        """Test that slow_query_count rule is configured"""
        assert 'slow_query_count' in RECOMMENDATION_RULES
        rule = RECOMMENDATION_RULES['slow_query_count']
        assert rule['threshold'] == 5
        assert rule['operator'] == '>'

    def test_all_rules_have_required_fields(self):
        """Test that all rules have required fields"""
        required_fields = ['threshold', 'operator', 'title', 'message']

        for metric, rule in RECOMMENDATION_RULES.items():
            for field in required_fields:
                assert field in rule, f"Rule '{metric}' missing field '{field}'"


# =============================================================================
# Issue Type Messages Tests
# =============================================================================

class TestIssueTypeMessages:
    """Tests for issue type message configuration"""

    def test_high_memory_message_exists(self):
        """Test that high_memory message is configured"""
        assert 'high_memory' in ISSUE_TYPE_MESSAGES
        assert 'title' in ISSUE_TYPE_MESSAGES['high_memory']
        assert 'message_template' in ISSUE_TYPE_MESSAGES['high_memory']

    def test_slow_queries_message_exists(self):
        """Test that slow_queries message is configured"""
        assert 'slow_queries' in ISSUE_TYPE_MESSAGES
        assert 'title' in ISSUE_TYPE_MESSAGES['slow_queries']

    def test_message_template_formatting(self):
        """Test that message templates can be formatted"""
        template = ISSUE_TYPE_MESSAGES['high_memory']['message_template']
        result = template.format(memory_percent=92.5)
        assert '92.5' in result
