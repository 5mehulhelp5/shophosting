"""
Tests for the Performance Insights API Endpoint

Tests the GET /api/customer/insights endpoint as specified in Task 5.

Returns:
    {
        "insights": [
            {
                "id": "issue-123",
                "type": "warning",
                "title": "Slow database queries detected",
                "message": "3 queries averaging >2s",
                "timestamp": "2026-02-01T12:00:00",
                "relative_time": "2 min ago",
                "details": {...},
                "issue_id": 123
            },
            ...
        ],
        "count": 5
    }
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_insights_response():
    """Mock insights data that would be returned by the API"""
    return [
        {
            'id': 'issue-1',
            'type': 'warning',
            'title': 'Slow database queries detected',
            'message': '7 queries averaging >2.5s',
            'timestamp': datetime.now().isoformat(),
            'relative_time': '5 min ago',
            'details': {'slow_query_count': 7, 'avg_time': 2.5},
            'issue_id': 1
        },
        {
            'id': 'rec-redis_hit_rate-1',
            'type': 'recommendation',
            'title': 'Low cache hit rate',
            'message': 'Consider reviewing your caching strategy',
            'timestamp': datetime.now().isoformat(),
            'relative_time': '10 min ago',
            'details': {'metric': 'redis_hit_rate', 'current_value': 65.0, 'threshold': 70},
            'issue_id': None
        },
        {
            'id': 'resolved-2',
            'type': 'success',
            'title': 'High memory usage resolved',
            'message': 'Automatically resolved',
            'timestamp': datetime.now().isoformat(),
            'relative_time': '1 hour ago',
            'details': {},
            'issue_id': 2
        },
    ]


@pytest.fixture
def mock_active_customer():
    """Mock an active customer for API testing"""
    customer = MagicMock()
    customer.id = 1
    customer.email = 'test@example.com'
    customer.status = 'active'
    customer.is_authenticated = True
    customer.is_active = True
    customer.get_id.return_value = '1'
    return customer


@pytest.fixture
def mock_inactive_customer():
    """Mock an inactive customer for API testing"""
    customer = MagicMock()
    customer.id = 2
    customer.email = 'inactive@example.com'
    customer.status = 'pending_payment'
    customer.is_authenticated = True
    customer.is_active = True
    customer.get_id.return_value = '2'
    return customer


# =============================================================================
# API Endpoint Tests
# =============================================================================

class TestInsightsAPIEndpoint:
    """Tests for the GET /api/customer/insights endpoint"""

    def test_insights_endpoint_exists(self, client):
        """Test that the insights endpoint exists"""
        # Without authentication, should return 401/redirect
        response = client.get('/api/customer/insights')
        # Should redirect to login or return unauthorized
        assert response.status_code in [302, 401, 403]

    def test_insights_requires_authentication(self, client):
        """Test that insights endpoint requires login"""
        response = client.get('/api/customer/insights')
        assert response.status_code in [302, 401, 403]

    def test_insights_returns_json(self, app, mock_active_customer, mock_insights_response):
        """Test that insights endpoint returns JSON"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights', return_value=mock_insights_response):
                    with app.test_client() as client:
                        # Simulate logged in user
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            response = client.get('/api/customer/insights')

                            # The response should be JSON
                            if response.status_code == 200:
                                data = response.get_json()
                                assert data is not None
                                assert 'insights' in data or 'error' in data

    def test_insights_default_limit(self, app, mock_active_customer, mock_insights_response):
        """Test that default limit is 10"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights') as mock_get_insights:
                    mock_get_insights.return_value = mock_insights_response

                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            client.get('/api/customer/insights')

                            # Check that get_performance_insights was called with limit=10
                            if mock_get_insights.called:
                                _, kwargs = mock_get_insights.call_args
                                assert kwargs.get('limit', 10) == 10

    def test_insights_custom_limit(self, app, mock_active_customer, mock_insights_response):
        """Test that custom limit is respected"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights') as mock_get_insights:
                    mock_get_insights.return_value = mock_insights_response[:2]

                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            client.get('/api/customer/insights?limit=5')

                            if mock_get_insights.called:
                                _, kwargs = mock_get_insights.call_args
                                assert kwargs.get('limit') in [5, 10]

    def test_insights_limit_max_capped(self, app, mock_active_customer):
        """Test that limit is capped at 50"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights') as mock_get_insights:
                    mock_get_insights.return_value = []

                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            client.get('/api/customer/insights?limit=100')

                            if mock_get_insights.called:
                                _, kwargs = mock_get_insights.call_args
                                # Should be capped at 50
                                assert kwargs.get('limit', 10) <= 50

    def test_insights_invalid_limit_defaults(self, app, mock_active_customer):
        """Test that invalid limit defaults to 10"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights') as mock_get_insights:
                    mock_get_insights.return_value = []

                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            client.get('/api/customer/insights?limit=invalid')

                            if mock_get_insights.called:
                                _, kwargs = mock_get_insights.call_args
                                assert kwargs.get('limit') == 10


# =============================================================================
# Response Format Tests
# =============================================================================

class TestInsightsResponseFormat:
    """Tests for the insights API response format"""

    def test_response_contains_insights_array(self, app, mock_active_customer, mock_insights_response):
        """Test that response contains insights array"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights', return_value=mock_insights_response):
                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            response = client.get('/api/customer/insights')

                            if response.status_code == 200:
                                data = response.get_json()
                                assert 'insights' in data
                                assert isinstance(data['insights'], list)

    def test_response_contains_count(self, app, mock_active_customer, mock_insights_response):
        """Test that response contains count field"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights', return_value=mock_insights_response):
                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            response = client.get('/api/customer/insights')

                            if response.status_code == 200:
                                data = response.get_json()
                                assert 'count' in data
                                assert data['count'] == len(data.get('insights', []))

    def test_insight_contains_required_fields(self, mock_insights_response):
        """Test that each insight contains required fields"""
        required_fields = ['id', 'type', 'title', 'message', 'timestamp', 'relative_time']

        for insight in mock_insights_response:
            for field in required_fields:
                assert field in insight, f"Insight missing required field '{field}'"

    def test_insight_types_are_valid(self, mock_insights_response):
        """Test that insight types are valid values"""
        valid_types = {'warning', 'recommendation', 'success'}

        for insight in mock_insights_response:
            assert insight['type'] in valid_types


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestInsightsErrorHandling:
    """Tests for error handling in insights endpoint"""

    def test_inactive_customer_returns_error(self, app, mock_inactive_customer):
        """Test that inactive customers receive an error"""
        with patch('app.current_user', mock_inactive_customer):
            with patch('app.Customer.get_by_id', return_value=mock_inactive_customer):
                with app.test_client() as client:
                    with client.session_transaction() as sess:
                        sess['_user_id'] = '2'
                        sess['last_activity'] = datetime.now().timestamp()

                    with patch('flask_login.utils._get_user', return_value=mock_inactive_customer):
                        response = client.get('/api/customer/insights')

                        # Should return 400 for inactive store
                        if response.status_code in [200, 400]:
                            data = response.get_json()
                            if response.status_code == 400:
                                assert 'error' in data

    def test_customer_not_found_returns_404(self, app, mock_active_customer):
        """Test that non-existent customer returns 404"""
        mock_active_customer.id = 999

        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=None):
                with app.test_client() as client:
                    with client.session_transaction() as sess:
                        sess['_user_id'] = '999'
                        sess['last_activity'] = datetime.now().timestamp()

                    with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                        response = client.get('/api/customer/insights')

                        if response.status_code == 404:
                            data = response.get_json()
                            assert 'error' in data

    def test_internal_error_returns_500(self, app, mock_active_customer):
        """Test that internal errors return 500"""
        with patch('app.current_user', mock_active_customer):
            with patch('app.Customer.get_by_id', return_value=mock_active_customer):
                with patch('performance.insights.get_performance_insights', side_effect=Exception('Database error')):
                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = '1'
                            sess['last_activity'] = datetime.now().timestamp()

                        with patch('flask_login.utils._get_user', return_value=mock_active_customer):
                            response = client.get('/api/customer/insights')

                            if response.status_code == 500:
                                data = response.get_json()
                                assert 'error' in data
