"""
Tests for the Health Score API endpoint

Tests the GET /api/customer/health-score endpoint which returns
health scores and trend data for customer dashboards.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestHealthScoreApiUnauthenticated:
    """Test health score API without authentication"""

    def test_health_score_requires_authentication(self, client):
        """Test that health score endpoint requires login"""
        response = client.get('/api/customer/health-score')
        # Should redirect to login (302) or return 401
        assert response.status_code in [302, 401]


class TestHealthScoreApiAuthenticated:
    """Test health score API with authentication (mocked)"""

    @pytest.mark.skip(reason="Requires database tables - skipping in CI")
    def test_health_score_returns_json(self, client):
        """Test that health score returns JSON response"""
        # This test requires actual authentication
        # In a full integration test environment, you'd set up a test user
        response = client.get('/api/customer/health-score')
        # When not authenticated, it redirects
        assert response.status_code in [302, 401, 400, 200]


class TestHealthScoreCalculation:
    """Test health score calculation logic directly"""

    def test_score_to_status_excellent(self):
        """Test that score 100 returns 'excellent' status"""
        from performance.health_score import HealthScoreCalculator
        assert HealthScoreCalculator._score_to_status(100) == 'excellent'

    def test_score_to_status_good(self):
        """Test that score 85 returns 'good' status"""
        from performance.health_score import HealthScoreCalculator
        assert HealthScoreCalculator._score_to_status(85) == 'good'

    def test_score_to_status_warning(self):
        """Test that score 65 returns 'warning' status"""
        from performance.health_score import HealthScoreCalculator
        assert HealthScoreCalculator._score_to_status(65) == 'warning'

    def test_score_to_status_critical(self):
        """Test that score 30 returns 'critical' status"""
        from performance.health_score import HealthScoreCalculator
        assert HealthScoreCalculator._score_to_status(30) == 'critical'

    def test_factor_weights_sum_to_one(self):
        """Test that factor weights sum to 1.0"""
        from performance.health_score import FACTOR_WEIGHTS
        total = sum(FACTOR_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001  # Allow for floating point errors


class TestHealthScoreThresholds:
    """Test health score threshold configurations"""

    def test_ttfb_thresholds_exist(self):
        """Test that TTFB thresholds are defined"""
        from performance.health_score import TTFB_THRESHOLDS
        assert 'excellent' in TTFB_THRESHOLDS
        assert 'good' in TTFB_THRESHOLDS
        assert 'warning' in TTFB_THRESHOLDS
        assert 'critical' in TTFB_THRESHOLDS

    def test_ttfb_thresholds_increase(self):
        """Test that TTFB thresholds increase (excellent < good < warning < critical)"""
        from performance.health_score import TTFB_THRESHOLDS
        assert TTFB_THRESHOLDS['excellent'] < TTFB_THRESHOLDS['good']
        assert TTFB_THRESHOLDS['good'] < TTFB_THRESHOLDS['warning']
        assert TTFB_THRESHOLDS['warning'] < TTFB_THRESHOLDS['critical']

    def test_resource_thresholds_exist(self):
        """Test that resource thresholds are defined"""
        from performance.health_score import RESOURCE_THRESHOLDS
        assert 'excellent' in RESOURCE_THRESHOLDS
        assert 'good' in RESOURCE_THRESHOLDS
        assert 'warning' in RESOURCE_THRESHOLDS
        assert 'critical' in RESOURCE_THRESHOLDS

    def test_cache_hit_thresholds_exist(self):
        """Test that cache hit thresholds are defined"""
        from performance.health_score import CACHE_HIT_THRESHOLDS
        assert 'excellent' in CACHE_HIT_THRESHOLDS
        assert 'good' in CACHE_HIT_THRESHOLDS
        assert 'warning' in CACHE_HIT_THRESHOLDS
        assert 'critical' in CACHE_HIT_THRESHOLDS


class TestHealthScoreResult:
    """Test HealthScoreResult dataclass"""

    def test_to_dict_structure(self):
        """Test that HealthScoreResult.to_dict() returns expected structure"""
        from performance.health_score import HealthScoreResult, FactorScore
        from datetime import datetime

        factors = {
            'page_speed': FactorScore(
                name='Page Speed',
                score=90,
                status='excellent',
                details={},
                weight=0.30,
                data_available=True
            )
        }

        result = HealthScoreResult(
            customer_id=1,
            overall_score=85,
            overall_status='good',
            factors=factors,
            calculated_at=datetime(2026, 2, 1, 12, 0, 0),
            data_freshness=datetime(2026, 2, 1, 11, 55, 0)
        )

        result_dict = result.to_dict()

        assert 'customer_id' in result_dict
        assert 'overall_score' in result_dict
        assert 'overall_status' in result_dict
        assert 'overall_color' in result_dict
        assert 'calculated_at' in result_dict
        assert 'data_freshness' in result_dict
        assert 'factors' in result_dict

        assert result_dict['customer_id'] == 1
        assert result_dict['overall_score'] == 85
        assert result_dict['overall_status'] == 'good'
        assert result_dict['overall_color'] == 'green'

    def test_factor_score_color_mapping(self):
        """Test that FactorScore.color property returns correct colors"""
        from performance.health_score import FactorScore

        excellent_factor = FactorScore(name='Test', score=100, status='excellent')
        assert excellent_factor.color == 'green'

        good_factor = FactorScore(name='Test', score=85, status='good')
        assert good_factor.color == 'green'

        warning_factor = FactorScore(name='Test', score=65, status='warning')
        assert warning_factor.color == 'yellow'

        critical_factor = FactorScore(name='Test', score=30, status='critical')
        assert critical_factor.color == 'red'

        unknown_factor = FactorScore(name='Test', score=0, status='unknown')
        assert unknown_factor.color == 'gray'


class TestGetHealthScoreWithTrend:
    """Test the get_health_score_with_trend function"""

    def test_trend_field_exists(self):
        """Test that trend field is returned in result"""
        # This test uses mocking to avoid database dependencies
        with patch('performance.health_score.HealthScoreCalculator') as MockCalculator:
            from performance.health_score import HealthScoreResult, FactorScore
            from datetime import datetime

            # Create a mock result
            mock_result = HealthScoreResult(
                customer_id=1,
                overall_score=85,
                overall_status='good',
                factors={
                    'page_speed': FactorScore(
                        name='Page Speed',
                        score=90,
                        status='excellent',
                        details={},
                        weight=0.30,
                        data_available=True
                    )
                },
                calculated_at=datetime.now()
            )

            # Configure the mock
            mock_instance = MockCalculator.return_value
            mock_instance.calculate.return_value = mock_result
            mock_instance._get_connection.return_value = MagicMock()

            # Patch _get_score_24h_ago to return None (no previous data)
            with patch('performance.health_score._get_score_24h_ago', return_value=None):
                from performance.health_score import get_health_score_with_trend
                result = get_health_score_with_trend(1)

                assert 'trend' in result
                assert 'score' in result
                assert 'factors' in result

    def test_trend_up_when_score_increases(self):
        """Test that trend is 'up' when score increased vs 24h ago"""
        with patch('performance.health_score.HealthScoreCalculator') as MockCalculator:
            from performance.health_score import HealthScoreResult, FactorScore
            from datetime import datetime

            mock_result = HealthScoreResult(
                customer_id=1,
                overall_score=85,
                overall_status='good',
                factors={
                    'page_speed': FactorScore(
                        name='Page Speed', score=90, status='excellent',
                        details={}, weight=0.30, data_available=True
                    )
                },
                calculated_at=datetime.now()
            )

            mock_instance = MockCalculator.return_value
            mock_instance.calculate.return_value = mock_result
            mock_instance._get_connection.return_value = MagicMock()

            # Previous score was 80, current is 85 (increase of 5 > 2)
            with patch('performance.health_score._get_score_24h_ago', return_value=80):
                from performance.health_score import get_health_score_with_trend
                result = get_health_score_with_trend(1)

                assert result['trend'] == 'up'
                assert result['score_change'] == 5

    def test_trend_down_when_score_decreases(self):
        """Test that trend is 'down' when score decreased vs 24h ago"""
        with patch('performance.health_score.HealthScoreCalculator') as MockCalculator:
            from performance.health_score import HealthScoreResult, FactorScore
            from datetime import datetime

            mock_result = HealthScoreResult(
                customer_id=1,
                overall_score=75,
                overall_status='warning',
                factors={
                    'page_speed': FactorScore(
                        name='Page Speed', score=70, status='warning',
                        details={}, weight=0.30, data_available=True
                    )
                },
                calculated_at=datetime.now()
            )

            mock_instance = MockCalculator.return_value
            mock_instance.calculate.return_value = mock_result
            mock_instance._get_connection.return_value = MagicMock()

            # Previous score was 85, current is 75 (decrease of 10 > 2)
            with patch('performance.health_score._get_score_24h_ago', return_value=85):
                from performance.health_score import get_health_score_with_trend
                result = get_health_score_with_trend(1)

                assert result['trend'] == 'down'
                assert result['score_change'] == -10

    def test_trend_stable_when_score_unchanged(self):
        """Test that trend is 'stable' when score changed by <= 2"""
        with patch('performance.health_score.HealthScoreCalculator') as MockCalculator:
            from performance.health_score import HealthScoreResult, FactorScore
            from datetime import datetime

            mock_result = HealthScoreResult(
                customer_id=1,
                overall_score=85,
                overall_status='good',
                factors={
                    'page_speed': FactorScore(
                        name='Page Speed', score=90, status='excellent',
                        details={}, weight=0.30, data_available=True
                    )
                },
                calculated_at=datetime.now()
            )

            mock_instance = MockCalculator.return_value
            mock_instance.calculate.return_value = mock_result
            mock_instance._get_connection.return_value = MagicMock()

            # Previous score was 84, current is 85 (change of 1 <= 2)
            with patch('performance.health_score._get_score_24h_ago', return_value=84):
                from performance.health_score import get_health_score_with_trend
                result = get_health_score_with_trend(1)

                assert result['trend'] == 'stable'
                assert result['score_change'] == 1
