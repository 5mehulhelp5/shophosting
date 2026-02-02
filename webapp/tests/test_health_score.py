"""
Tests for the Health Score Calculation Module

Tests the health score algorithm as specified in Section 1.1 of the
Performance Optimization Suite design document.

Weighted factors:
- Page Speed (30%): Based on TTFB, LCP, FCP thresholds
- Resource Usage (25%): CPU %, Memory %, Disk % vs plan limits
- Database Health (20%): Slow query count, connection usage ratio
- Cache Efficiency (15%): Redis hit rate, Varnish hit rate (Magento)
- Uptime (10%): Last 24h availability percentage
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance.health_score import (
    HealthScoreCalculator,
    calculate_health_score,
    FactorScore,
    HealthScoreResult,
    FACTOR_WEIGHTS,
    TTFB_THRESHOLDS,
    RESOURCE_THRESHOLDS,
    CACHE_HIT_THRESHOLDS,
    UPTIME_THRESHOLDS,
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
def excellent_snapshot():
    """Snapshot data representing excellent performance"""
    return {
        'customer_id': 1,
        'timestamp': datetime.now(),
        'health_score': 95,
        'ttfb_ms': 150,      # Excellent (< 200)
        'fcp_ms': 400,       # Excellent (< 500)
        'lcp_ms': 800,       # Excellent (< 1000)
        'cpu_percent': 30.0,  # Excellent (< 50)
        'memory_percent': 40.0,  # Excellent (< 50)
        'disk_percent': 35.0,    # Excellent (< 50)
        'slow_query_count': 0,   # Excellent (0)
        'active_connections': 10,  # Excellent (< 30% of 100)
        'db_size_bytes': 1024 * 1024 * 100,  # 100 MB
        'redis_hit_rate': 98.0,   # Excellent (>= 95)
        'varnish_hit_rate': 96.0,  # Excellent (>= 95)
    }


@pytest.fixture
def warning_snapshot():
    """Snapshot data representing warning-level performance"""
    return {
        'customer_id': 2,
        'timestamp': datetime.now(),
        'health_score': 65,
        'ttfb_ms': 1200,     # Warning (500-1500)
        'fcp_ms': 2500,      # Warning (1800-3000)
        'lcp_ms': 3500,      # Warning (2500-4000)
        'cpu_percent': 78.0,  # Warning (70-85)
        'memory_percent': 80.0,  # Warning (70-85)
        'disk_percent': 75.0,    # Warning (70-85)
        'slow_query_count': 4,   # Warning (3-5)
        'active_connections': 60,  # Warning (50-70% of 100)
        'db_size_bytes': 1024 * 1024 * 500,  # 500 MB
        'redis_hit_rate': 75.0,   # Warning (70-85)
        'varnish_hit_rate': 72.0,  # Warning (70-85)
    }


@pytest.fixture
def critical_snapshot():
    """Snapshot data representing critical performance"""
    return {
        'customer_id': 3,
        'timestamp': datetime.now(),
        'health_score': 25,
        'ttfb_ms': 3500,     # Critical (>= 3000)
        'fcp_ms': 5500,      # Critical (>= 5000)
        'lcp_ms': 7000,      # Critical (>= 6000)
        'cpu_percent': 96.0,  # Critical (>= 95)
        'memory_percent': 97.0,  # Critical (>= 95)
        'disk_percent': 98.0,    # Critical (>= 95)
        'slow_query_count': 15,  # Critical (> 10)
        'active_connections': 95,  # Critical (>= 90% of 100)
        'db_size_bytes': 1024 * 1024 * 1000,  # 1 GB
        'redis_hit_rate': 40.0,   # Critical (< 50)
        'varnish_hit_rate': 35.0,  # Critical (< 50)
    }


@pytest.fixture
def excellent_monitoring_status():
    """Monitoring status with excellent uptime"""
    return {
        'customer_id': 1,
        'http_status': 'up',
        'container_status': 'up',
        'uptime_24h': 100.0,
        'cpu_percent': 30.0,
        'memory_percent': 40.0,
        'consecutive_failures': 0,
    }


@pytest.fixture
def warning_monitoring_status():
    """Monitoring status with warning-level uptime"""
    return {
        'customer_id': 2,
        'http_status': 'up',
        'container_status': 'up',
        'uptime_24h': 97.0,  # Warning (95-99)
        'cpu_percent': 75.0,
        'memory_percent': 78.0,
        'consecutive_failures': 1,
    }


@pytest.fixture
def mock_plan_limits():
    """Standard plan limits"""
    return {
        'memory_limit': '1g',
        'cpu_limit': '1.0',
        'disk_limit_gb': 25,
    }


# =============================================================================
# Test Factor Weights
# =============================================================================

class TestFactorWeights:
    """Test that factor weights are correctly configured"""

    def test_weights_sum_to_one(self):
        """Verify all weights sum to 1.0 (100%)"""
        total = sum(FACTOR_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"

    def test_page_speed_weight_is_30_percent(self):
        """Page Speed should be 30% weight"""
        assert FACTOR_WEIGHTS['page_speed'] == 0.30

    def test_resource_usage_weight_is_25_percent(self):
        """Resource Usage should be 25% weight"""
        assert FACTOR_WEIGHTS['resource_usage'] == 0.25

    def test_database_health_weight_is_20_percent(self):
        """Database Health should be 20% weight"""
        assert FACTOR_WEIGHTS['database_health'] == 0.20

    def test_cache_efficiency_weight_is_15_percent(self):
        """Cache Efficiency should be 15% weight"""
        assert FACTOR_WEIGHTS['cache_efficiency'] == 0.15

    def test_uptime_weight_is_10_percent(self):
        """Uptime should be 10% weight"""
        assert FACTOR_WEIGHTS['uptime'] == 0.10


# =============================================================================
# Test Score Status Mapping
# =============================================================================

class TestScoreToStatus:
    """Test score to status mapping"""

    def test_score_100_is_excellent(self):
        """Score of 100 should be excellent"""
        assert HealthScoreCalculator._score_to_status(100) == 'excellent'

    def test_score_90_is_good(self):
        """Score of 90 should be good"""
        assert HealthScoreCalculator._score_to_status(90) == 'good'

    def test_score_80_is_good(self):
        """Score of 80 should be good (boundary)"""
        assert HealthScoreCalculator._score_to_status(80) == 'good'

    def test_score_79_is_warning(self):
        """Score of 79 should be warning"""
        assert HealthScoreCalculator._score_to_status(79) == 'warning'

    def test_score_50_is_warning(self):
        """Score of 50 should be warning (boundary)"""
        assert HealthScoreCalculator._score_to_status(50) == 'warning'

    def test_score_49_is_critical(self):
        """Score of 49 should be critical"""
        assert HealthScoreCalculator._score_to_status(49) == 'critical'

    def test_score_0_is_critical(self):
        """Score of 0 should be critical"""
        assert HealthScoreCalculator._score_to_status(0) == 'critical'


# =============================================================================
# Test Page Speed Factor
# =============================================================================

class TestPageSpeedFactor:
    """Test Page Speed factor calculation"""

    def test_excellent_ttfb_scores_100(self):
        """TTFB < 200ms should score 100"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(150, TTFB_THRESHOLDS, lower_is_better=True)
        assert score == 100

    def test_good_ttfb_scores_80_to_99(self):
        """TTFB 200-500ms should score 80-99"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(350, TTFB_THRESHOLDS, lower_is_better=True)
        assert 80 <= score < 100

    def test_warning_ttfb_scores_50_to_79(self):
        """TTFB 500-1500ms should score 50-79"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(1000, TTFB_THRESHOLDS, lower_is_better=True)
        assert 50 <= score < 80

    def test_critical_ttfb_scores_below_50(self):
        """TTFB 1500-3000ms should score below 50"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(2500, TTFB_THRESHOLDS, lower_is_better=True)
        assert score < 50

    def test_very_slow_ttfb_scores_zero(self):
        """TTFB >= 3000ms should score 0"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(4000, TTFB_THRESHOLDS, lower_is_better=True)
        assert score == 0

    def test_page_speed_with_no_data(self, mock_db_connection):
        """Page speed with no data should be marked unavailable"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_page_speed_score(None)
        assert result.data_available is False
        assert result.status == 'unknown'

    def test_page_speed_with_partial_data(self, mock_db_connection):
        """Page speed with only TTFB should still calculate"""
        calc = HealthScoreCalculator(mock_db_connection)
        snapshot = {'ttfb_ms': 200}  # Only TTFB available
        result = calc._calculate_page_speed_score(snapshot)
        assert result.data_available is True
        assert result.score >= 80  # Good TTFB

    def test_page_speed_excellent(self, mock_db_connection, excellent_snapshot):
        """Excellent page speed metrics should score high"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_page_speed_score(excellent_snapshot)
        assert result.score >= 80
        assert result.status in ('excellent', 'good')

    def test_page_speed_critical(self, mock_db_connection, critical_snapshot):
        """Critical page speed metrics should score low"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_page_speed_score(critical_snapshot)
        assert result.score < 50
        assert result.status == 'critical'


# =============================================================================
# Test Resource Usage Factor
# =============================================================================

class TestResourceUsageFactor:
    """Test Resource Usage factor calculation"""

    def test_low_cpu_scores_excellent(self):
        """CPU < 50% should score excellent"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(30, RESOURCE_THRESHOLDS, lower_is_better=True)
        assert score == 100

    def test_moderate_cpu_scores_good(self):
        """CPU 50-70% should score good"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(60, RESOURCE_THRESHOLDS, lower_is_better=True)
        assert 80 <= score < 100

    def test_high_cpu_scores_warning(self):
        """CPU 70-85% should score warning"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(78, RESOURCE_THRESHOLDS, lower_is_better=True)
        assert 50 <= score < 80

    def test_critical_cpu_scores_low(self):
        """CPU >= 95% should score critical"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(96, RESOURCE_THRESHOLDS, lower_is_better=True)
        assert score < 50

    def test_resource_with_no_data(self, mock_db_connection):
        """Resource usage with no data should be marked unavailable"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_resource_score(None, None, None)
        assert result.data_available is False

    def test_resource_prefers_snapshot_over_monitoring(self, mock_db_connection):
        """Should prefer snapshot data over monitoring status"""
        calc = HealthScoreCalculator(mock_db_connection)
        snapshot = {'cpu_percent': 30.0, 'memory_percent': 40.0}
        monitoring = {'cpu_percent': 80.0, 'memory_percent': 85.0}
        result = calc._calculate_resource_score(snapshot, monitoring, None)
        # Should use snapshot values (30%, 40%) not monitoring (80%, 85%)
        assert result.details['cpu_percent'] == 30.0
        assert result.details['memory_percent'] == 40.0

    def test_resource_falls_back_to_monitoring(self, mock_db_connection):
        """Should fall back to monitoring status if snapshot lacks data"""
        calc = HealthScoreCalculator(mock_db_connection)
        snapshot = {}  # No resource data
        monitoring = {'cpu_percent': 50.0, 'memory_percent': 60.0}
        result = calc._calculate_resource_score(snapshot, monitoring, None)
        assert result.details['cpu_percent'] == 50.0


# =============================================================================
# Test Database Health Factor
# =============================================================================

class TestDatabaseHealthFactor:
    """Test Database Health factor calculation"""

    def test_zero_slow_queries_scores_100(self):
        """0 slow queries should score 100"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._slow_query_to_score(0)
        assert score == 100

    def test_few_slow_queries_scores_good(self):
        """1-2 slow queries should score good"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._slow_query_to_score(2)
        assert score == 90

    def test_some_slow_queries_scores_warning(self):
        """3-5 slow queries should score warning"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._slow_query_to_score(4)
        assert 50 <= score < 90

    def test_many_slow_queries_scores_critical(self):
        """> 10 slow queries should score critical"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._slow_query_to_score(15)
        assert score == 0

    def test_database_with_no_data(self, mock_db_connection):
        """Database health with no data should be marked unavailable"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_database_score(None, None)
        assert result.data_available is False

    def test_database_excellent(self, mock_db_connection, excellent_snapshot):
        """Excellent database metrics should score high"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_database_score(excellent_snapshot, None)
        assert result.score >= 80
        assert result.status in ('excellent', 'good')


# =============================================================================
# Test Cache Efficiency Factor
# =============================================================================

class TestCacheEfficiencyFactor:
    """Test Cache Efficiency factor calculation"""

    def test_high_hit_rate_scores_excellent(self):
        """Hit rate >= 95% should score excellent"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._cache_hit_to_score(98.0)
        assert score == 100

    def test_good_hit_rate_scores_good(self):
        """Hit rate 85-95% should score good"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._cache_hit_to_score(90.0)
        assert 80 <= score < 100

    def test_moderate_hit_rate_scores_warning(self):
        """Hit rate 70-85% should score warning"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._cache_hit_to_score(75.0)
        assert 50 <= score < 80

    def test_low_hit_rate_scores_critical(self):
        """Hit rate 50-70% should score critical"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._cache_hit_to_score(55.0)
        assert score < 50

    def test_very_low_hit_rate_scores_zero(self):
        """Hit rate < 50% should score 0"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._cache_hit_to_score(40.0)
        assert score == 0

    def test_cache_with_no_data(self, mock_db_connection):
        """Cache efficiency with no data should be marked unavailable"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_cache_score(None, 'woocommerce')
        assert result.data_available is False

    def test_magento_includes_varnish(self, mock_db_connection):
        """Magento should include Varnish in cache score"""
        calc = HealthScoreCalculator(mock_db_connection)
        snapshot = {'redis_hit_rate': 90.0, 'varnish_hit_rate': 85.0}
        result = calc._calculate_cache_score(snapshot, 'magento')
        assert 'varnish_hit_rate' in result.details
        assert result.details['is_magento'] is True

    def test_woocommerce_excludes_varnish(self, mock_db_connection):
        """WooCommerce should not include Varnish in cache score"""
        calc = HealthScoreCalculator(mock_db_connection)
        snapshot = {'redis_hit_rate': 90.0, 'varnish_hit_rate': 85.0}
        result = calc._calculate_cache_score(snapshot, 'woocommerce')
        assert 'varnish_hit_rate' not in result.details
        assert result.details['is_magento'] is False


# =============================================================================
# Test Uptime Factor
# =============================================================================

class TestUptimeFactor:
    """Test Uptime factor calculation"""

    def test_100_percent_uptime_scores_excellent(self):
        """100% uptime should score excellent"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(100.0)
        assert score == 100

    def test_99_9_percent_uptime_scores_excellent(self):
        """99.9% uptime should score excellent"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(99.9)
        assert score == 100

    def test_99_percent_uptime_scores_good(self):
        """99% uptime should score good"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(99.0)
        assert 80 <= score < 100

    def test_97_percent_uptime_scores_warning(self):
        """97% uptime should score warning"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(97.0)
        assert 50 <= score < 80

    def test_low_uptime_scores_critical(self):
        """< 90% uptime should score critical"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(85.0)
        assert score < 50

    def test_uptime_with_no_data(self, mock_db_connection):
        """Uptime with no data should be marked unavailable"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_uptime_score(None)
        assert result.data_available is False

    def test_uptime_excellent(self, mock_db_connection, excellent_monitoring_status):
        """Excellent uptime should score high"""
        calc = HealthScoreCalculator(mock_db_connection)
        result = calc._calculate_uptime_score(excellent_monitoring_status)
        assert result.score == 100
        assert result.status == 'excellent'


# =============================================================================
# Test Overall Score Calculation
# =============================================================================

class TestOverallScore:
    """Test overall score calculation with weight adjustment"""

    def test_all_factors_excellent(self, mock_db_connection):
        """All excellent factors should produce excellent overall score"""
        calc = HealthScoreCalculator(mock_db_connection)
        factors = {
            'page_speed': FactorScore('Page Speed', 100, 'excellent'),
            'resource_usage': FactorScore('Resource Usage', 100, 'excellent'),
            'database_health': FactorScore('Database Health', 100, 'excellent'),
            'cache_efficiency': FactorScore('Cache Efficiency', 100, 'excellent'),
            'uptime': FactorScore('Uptime', 100, 'excellent'),
        }
        score, weights = calc._calculate_overall_score(factors)
        assert score == 100

    def test_all_factors_critical(self, mock_db_connection):
        """All critical factors should produce critical overall score"""
        calc = HealthScoreCalculator(mock_db_connection)
        factors = {
            'page_speed': FactorScore('Page Speed', 20, 'critical'),
            'resource_usage': FactorScore('Resource Usage', 20, 'critical'),
            'database_health': FactorScore('Database Health', 20, 'critical'),
            'cache_efficiency': FactorScore('Cache Efficiency', 20, 'critical'),
            'uptime': FactorScore('Uptime', 20, 'critical'),
        }
        score, weights = calc._calculate_overall_score(factors)
        assert score == 20

    def test_mixed_factors(self, mock_db_connection):
        """Mixed factor scores should produce weighted average"""
        calc = HealthScoreCalculator(mock_db_connection)
        factors = {
            'page_speed': FactorScore('Page Speed', 100, 'excellent'),
            'resource_usage': FactorScore('Resource Usage', 80, 'good'),
            'database_health': FactorScore('Database Health', 60, 'warning'),
            'cache_efficiency': FactorScore('Cache Efficiency', 90, 'good'),
            'uptime': FactorScore('Uptime', 100, 'excellent'),
        }
        score, weights = calc._calculate_overall_score(factors)
        # Expected: 100*0.30 + 80*0.25 + 60*0.20 + 90*0.15 + 100*0.10
        #         = 30 + 20 + 12 + 13.5 + 10 = 85.5 -> 86
        assert 80 <= score <= 90

    def test_weight_redistribution_with_missing_data(self, mock_db_connection):
        """Missing data should redistribute weights"""
        calc = HealthScoreCalculator(mock_db_connection)
        factors = {
            'page_speed': FactorScore('Page Speed', 100, 'excellent'),
            'resource_usage': FactorScore('Resource Usage', 100, 'excellent'),
            'database_health': FactorScore('Database Health', 0, 'unknown', data_available=False),
            'cache_efficiency': FactorScore('Cache Efficiency', 100, 'excellent'),
            'uptime': FactorScore('Uptime', 100, 'excellent'),
        }
        score, weights = calc._calculate_overall_score(factors)
        # Only 4 factors available (80% of original weight)
        # All score 100, so overall should still be 100
        assert score == 100
        # Database health weight should be 0
        assert weights['database_health'] == 0.0
        # Other weights should be redistributed (scaled up)
        assert weights['page_speed'] > FACTOR_WEIGHTS['page_speed']

    def test_no_data_returns_zero(self, mock_db_connection):
        """No available data should return score of 0"""
        calc = HealthScoreCalculator(mock_db_connection)
        factors = {
            'page_speed': FactorScore('Page Speed', 0, 'unknown', data_available=False),
            'resource_usage': FactorScore('Resource Usage', 0, 'unknown', data_available=False),
            'database_health': FactorScore('Database Health', 0, 'unknown', data_available=False),
            'cache_efficiency': FactorScore('Cache Efficiency', 0, 'unknown', data_available=False),
            'uptime': FactorScore('Uptime', 0, 'unknown', data_available=False),
        }
        score, weights = calc._calculate_overall_score(factors)
        assert score == 0


# =============================================================================
# Test HealthScoreResult
# =============================================================================

class TestHealthScoreResult:
    """Test HealthScoreResult data class"""

    def test_to_dict_includes_all_fields(self):
        """to_dict should include all required fields"""
        factors = {
            'page_speed': FactorScore('Page Speed', 90, 'good', weight=0.30),
        }
        result = HealthScoreResult(
            customer_id=1,
            overall_score=90,
            overall_status='good',
            factors=factors,
        )
        d = result.to_dict()

        assert 'customer_id' in d
        assert 'overall_score' in d
        assert 'overall_status' in d
        assert 'overall_color' in d
        assert 'calculated_at' in d
        assert 'factors' in d

    def test_to_dict_color_mapping(self):
        """to_dict should map status to correct color"""
        factors = {}

        # Test excellent/good -> green
        result = HealthScoreResult(1, 90, 'good', factors)
        assert result.to_dict()['overall_color'] == 'green'

        result = HealthScoreResult(1, 100, 'excellent', factors)
        assert result.to_dict()['overall_color'] == 'green'

        # Test warning -> yellow
        result = HealthScoreResult(1, 60, 'warning', factors)
        assert result.to_dict()['overall_color'] == 'yellow'

        # Test critical -> red
        result = HealthScoreResult(1, 30, 'critical', factors)
        assert result.to_dict()['overall_color'] == 'red'


# =============================================================================
# Test FactorScore
# =============================================================================

class TestFactorScore:
    """Test FactorScore data class"""

    def test_color_property_green_for_excellent(self):
        """Excellent status should return green color"""
        score = FactorScore('Test', 100, 'excellent')
        assert score.color == 'green'

    def test_color_property_green_for_good(self):
        """Good status should return green color"""
        score = FactorScore('Test', 85, 'good')
        assert score.color == 'green'

    def test_color_property_yellow_for_warning(self):
        """Warning status should return yellow color"""
        score = FactorScore('Test', 65, 'warning')
        assert score.color == 'yellow'

    def test_color_property_red_for_critical(self):
        """Critical status should return red color"""
        score = FactorScore('Test', 30, 'critical')
        assert score.color == 'red'

    def test_color_property_gray_for_unknown(self):
        """Unknown status should return gray color"""
        score = FactorScore('Test', 0, 'unknown')
        assert score.color == 'gray'


# =============================================================================
# Test Public API Function
# =============================================================================

class TestCalculateHealthScoreAPI:
    """Test the public calculate_health_score function"""

    def test_returns_dict(self):
        """calculate_health_score should return a dictionary"""
        with patch.object(HealthScoreCalculator, 'calculate') as mock_calc:
            mock_calc.return_value = HealthScoreResult(
                customer_id=1,
                overall_score=80,
                overall_status='good',
                factors={}
            )
            result = calculate_health_score(1)
            assert isinstance(result, dict)

    def test_dict_has_required_keys(self):
        """Result dict should have all required keys"""
        with patch.object(HealthScoreCalculator, 'calculate') as mock_calc:
            mock_calc.return_value = HealthScoreResult(
                customer_id=1,
                overall_score=80,
                overall_status='good',
                factors={
                    'page_speed': FactorScore('Page Speed', 80, 'good'),
                }
            )
            result = calculate_health_score(1)

            assert 'customer_id' in result
            assert 'overall_score' in result
            assert 'overall_status' in result
            assert 'overall_color' in result
            assert 'factors' in result


# =============================================================================
# Integration Tests (with mocked DB)
# =============================================================================

class TestFullCalculation:
    """Integration tests for full health score calculation"""

    def test_excellent_customer(self, excellent_snapshot, excellent_monitoring_status, mock_plan_limits):
        """Test full calculation for excellent performance"""
        def mock_connection():
            conn = MagicMock()
            cursor = MagicMock()

            # Set up mock responses for different queries
            def mock_execute(query, params=None):
                pass

            def mock_fetchone():
                # Return appropriate data based on call order
                return None

            cursor.execute = mock_execute
            cursor.fetchone = mock_fetchone
            conn.cursor.return_value = cursor
            return conn

        calc = HealthScoreCalculator(mock_connection)

        # Test individual factors with excellent data
        ps_score = calc._calculate_page_speed_score(excellent_snapshot)
        assert ps_score.score >= 80

        rs_score = calc._calculate_resource_score(
            excellent_snapshot, excellent_monitoring_status, mock_plan_limits
        )
        assert rs_score.score >= 80

        db_score = calc._calculate_database_score(excellent_snapshot, mock_plan_limits)
        assert db_score.score >= 80

        cache_score = calc._calculate_cache_score(excellent_snapshot, 'woocommerce')
        assert cache_score.score >= 80

        uptime_score = calc._calculate_uptime_score(excellent_monitoring_status)
        assert uptime_score.score == 100

    def test_critical_customer(self, critical_snapshot, mock_plan_limits):
        """Test full calculation for critical performance"""
        def mock_connection():
            conn = MagicMock()
            cursor = MagicMock()
            conn.cursor.return_value = cursor
            return conn

        calc = HealthScoreCalculator(mock_connection)

        critical_monitoring = {
            'customer_id': 3,
            'http_status': 'down',
            'container_status': 'down',
            'uptime_24h': 75.0,
            'cpu_percent': 96.0,
            'memory_percent': 97.0,
        }

        ps_score = calc._calculate_page_speed_score(critical_snapshot)
        assert ps_score.score < 50

        db_score = calc._calculate_database_score(critical_snapshot, mock_plan_limits)
        assert db_score.score < 50

        cache_score = calc._calculate_cache_score(critical_snapshot, 'magento')
        assert cache_score.score < 50

        uptime_score = calc._calculate_uptime_score(critical_monitoring)
        assert uptime_score.score < 50


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_boundary_ttfb_200(self):
        """TTFB exactly at 200ms boundary"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(200, TTFB_THRESHOLDS, lower_is_better=True)
        assert score == 100  # Should still be excellent

    def test_boundary_cpu_50(self):
        """CPU exactly at 50% boundary"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._metric_to_score(50, RESOURCE_THRESHOLDS, lower_is_better=True)
        assert score == 100  # Should still be excellent

    def test_boundary_uptime_99_9(self):
        """Uptime exactly at 99.9% boundary"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        score = calc._uptime_to_score(99.9)
        assert score == 100  # Should be excellent

    def test_negative_values_handled(self):
        """Negative metric values should not crash"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        # Negative shouldn't happen but should be handled gracefully
        score = calc._metric_to_score(-10, TTFB_THRESHOLDS, lower_is_better=True)
        assert score == 100  # Better than excellent

    def test_zero_connections_handled(self):
        """Zero active connections should score excellent"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        snapshot = {'active_connections': 0, 'slow_query_count': 0}
        result = calc._calculate_database_score(snapshot, None)
        assert result.score >= 80

    def test_none_values_in_snapshot(self):
        """None values in snapshot should be skipped gracefully"""
        calc = HealthScoreCalculator(lambda: MagicMock())
        snapshot = {
            'ttfb_ms': None,
            'lcp_ms': None,
            'fcp_ms': None,
            'cpu_percent': None,
        }
        ps_result = calc._calculate_page_speed_score(snapshot)
        assert ps_result.data_available is False

    def test_decimal_type_handling(self):
        """Decimal types from database should be handled"""
        from decimal import Decimal
        calc = HealthScoreCalculator(lambda: MagicMock())
        snapshot = {
            'cpu_percent': Decimal('45.50'),
            'memory_percent': Decimal('55.25'),
            'redis_hit_rate': Decimal('92.33'),
        }
        rs_result = calc._calculate_resource_score(snapshot, None, None)
        assert rs_result.data_available is True
        assert rs_result.score >= 80
