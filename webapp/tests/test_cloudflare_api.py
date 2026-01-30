"""
Tests for Cloudflare API wrapper
"""

import pytest
from unittest.mock import patch, Mock
import requests


class TestCloudflareAPIError:
    """Test CloudflareAPIError exception"""

    def test_error_with_message_only(self):
        """Test error with just a message"""
        from cloudflare.api import CloudflareAPIError

        error = CloudflareAPIError("Something went wrong")
        assert str(error) == "CloudflareAPIError: Something went wrong"
        assert error.message == "Something went wrong"
        assert error.status_code is None
        assert error.errors == []

    def test_error_with_status_code(self):
        """Test error with status code"""
        from cloudflare.api import CloudflareAPIError

        error = CloudflareAPIError("Unauthorized", status_code=401)
        assert str(error) == "CloudflareAPIError (401): Unauthorized"
        assert error.status_code == 401

    def test_error_with_errors_list(self):
        """Test error with Cloudflare error details"""
        from cloudflare.api import CloudflareAPIError

        errors = [{'code': 1001, 'message': 'Invalid token'}]
        error = CloudflareAPIError("API Error", status_code=400, errors=errors)
        assert error.errors == errors


class TestCloudflareAPI:
    """Test CloudflareAPI client"""

    @pytest.fixture
    def api(self):
        """Create a CloudflareAPI instance for testing"""
        from cloudflare.api import CloudflareAPI
        return CloudflareAPI("test-api-token")

    def test_init_sets_token(self, api):
        """Test that API token is stored"""
        assert api.api_token == "test-api-token"
        assert api.base_url == "https://api.cloudflare.com/client/v4"

    @patch('cloudflare.api.requests.request')
    def test_request_sets_headers(self, mock_request, api):
        """Test that requests include authorization header"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': []}
        mock_request.return_value = mock_response

        api.get_zones()

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['headers']['Authorization'] == 'Bearer test-api-token'
        assert call_kwargs['headers']['Content-Type'] == 'application/json'

    @patch('cloudflare.api.requests.request')
    def test_request_timeout(self, mock_request, api):
        """Test that requests have timeout set"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': []}
        mock_request.return_value = mock_response

        api.get_zones()

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['timeout'] == 30

    @patch('cloudflare.api.requests.request')
    def test_request_handles_timeout_exception(self, mock_request, api):
        """Test timeout exceptions are wrapped"""
        from cloudflare.api import CloudflareAPIError

        mock_request.side_effect = requests.exceptions.Timeout()

        with pytest.raises(CloudflareAPIError) as exc_info:
            api.get_zones()

        assert "timed out" in str(exc_info.value).lower()

    @patch('cloudflare.api.requests.request')
    def test_request_handles_connection_error(self, mock_request, api):
        """Test connection errors are wrapped"""
        from cloudflare.api import CloudflareAPIError

        mock_request.side_effect = requests.exceptions.ConnectionError("Network unreachable")

        with pytest.raises(CloudflareAPIError) as exc_info:
            api.get_zones()

        assert "failed" in str(exc_info.value).lower()

    @patch('cloudflare.api.requests.request')
    def test_request_handles_invalid_json(self, mock_request, api):
        """Test invalid JSON responses are handled"""
        from cloudflare.api import CloudflareAPIError

        mock_response = Mock()
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.status_code = 500
        mock_request.return_value = mock_response

        with pytest.raises(CloudflareAPIError) as exc_info:
            api.get_zones()

        assert "Invalid JSON" in str(exc_info.value)

    @patch('cloudflare.api.requests.request')
    def test_request_handles_api_error_response(self, mock_request, api):
        """Test API error responses are parsed correctly"""
        from cloudflare.api import CloudflareAPIError

        mock_response = Mock()
        mock_response.json.return_value = {
            'success': False,
            'errors': [
                {'code': 9103, 'message': 'Unknown X-Auth-Key or X-Auth-Email'}
            ]
        }
        mock_response.status_code = 403
        mock_request.return_value = mock_response

        with pytest.raises(CloudflareAPIError) as exc_info:
            api.get_zones()

        assert exc_info.value.status_code == 403
        assert "Unknown X-Auth-Key" in exc_info.value.message


class TestCloudflareAPIZones:
    """Test zone-related API methods"""

    @pytest.fixture
    def api(self):
        from cloudflare.api import CloudflareAPI
        return CloudflareAPI("test-token")

    @patch('cloudflare.api.requests.request')
    def test_get_zones(self, mock_request, api):
        """Test listing zones"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': [
                {'id': 'zone123', 'name': 'example.com'},
                {'id': 'zone456', 'name': 'test.com'}
            ]
        }
        mock_request.return_value = mock_response

        zones = api.get_zones()

        assert len(zones) == 2
        assert zones[0]['name'] == 'example.com'

    @patch('cloudflare.api.requests.request')
    def test_get_zone_by_name_found(self, mock_request, api):
        """Test finding zone by domain name"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': [{'id': 'zone123', 'name': 'example.com'}]
        }
        mock_request.return_value = mock_response

        zone = api.get_zone_by_name('example.com')

        assert zone['id'] == 'zone123'
        # Verify query parameter was passed
        call_url = mock_request.call_args[1]['url']
        assert 'name=example.com' in call_url

    @patch('cloudflare.api.requests.request')
    def test_get_zone_by_name_not_found(self, mock_request, api):
        """Test zone not found returns None"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': []}
        mock_request.return_value = mock_response

        zone = api.get_zone_by_name('notfound.com')

        assert zone is None


class TestCloudflareAPIDNS:
    """Test DNS record API methods"""

    @pytest.fixture
    def api(self):
        from cloudflare.api import CloudflareAPI
        return CloudflareAPI("test-token")

    @patch('cloudflare.api.requests.request')
    def test_get_dns_records(self, mock_request, api):
        """Test listing DNS records"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': [
                {'id': 'rec1', 'type': 'A', 'name': 'example.com', 'content': '1.2.3.4'},
                {'id': 'rec2', 'type': 'CNAME', 'name': 'www.example.com', 'content': 'example.com'}
            ]
        }
        mock_request.return_value = mock_response

        records = api.get_dns_records('zone123')

        assert len(records) == 2
        assert records[0]['type'] == 'A'

    @patch('cloudflare.api.requests.request')
    def test_get_dns_records_with_type_filter(self, mock_request, api):
        """Test filtering DNS records by type"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': []}
        mock_request.return_value = mock_response

        api.get_dns_records('zone123', record_types=['A', 'CNAME'])

        call_url = mock_request.call_args[1]['url']
        assert 'type=A' in call_url
        assert 'type=CNAME' in call_url

    @patch('cloudflare.api.requests.request')
    def test_create_dns_record(self, mock_request, api):
        """Test creating a DNS record"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': {
                'id': 'newrec1',
                'type': 'A',
                'name': 'test.example.com',
                'content': '5.6.7.8'
            }
        }
        mock_request.return_value = mock_response

        result = api.create_dns_record(
            zone_id='zone123',
            record_type='A',
            name='test.example.com',
            content='5.6.7.8'
        )

        assert result['id'] == 'newrec1'
        # Verify POST data
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['method'] == 'POST'
        assert call_kwargs['json']['type'] == 'A'
        assert call_kwargs['json']['name'] == 'test.example.com'

    @patch('cloudflare.api.requests.request')
    def test_create_mx_record_with_priority(self, mock_request, api):
        """Test creating MX record includes priority"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'id': 'mxrec'}}
        mock_request.return_value = mock_response

        api.create_dns_record(
            zone_id='zone123',
            record_type='MX',
            name='example.com',
            content='mail.example.com',
            priority=10
        )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['json']['priority'] == 10

    @patch('cloudflare.api.requests.request')
    def test_create_a_record_ignores_priority(self, mock_request, api):
        """Test A record ignores priority parameter"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'id': 'arec'}}
        mock_request.return_value = mock_response

        api.create_dns_record(
            zone_id='zone123',
            record_type='A',
            name='example.com',
            content='1.2.3.4',
            priority=10  # Should be ignored for A records
        )

        call_kwargs = mock_request.call_args[1]
        assert 'priority' not in call_kwargs['json']

    @patch('cloudflare.api.requests.request')
    def test_update_dns_record(self, mock_request, api):
        """Test updating a DNS record"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': {'id': 'rec1', 'content': '9.9.9.9'}
        }
        mock_request.return_value = mock_response

        result = api.update_dns_record(
            zone_id='zone123',
            record_id='rec1',
            record_type='A',
            name='example.com',
            content='9.9.9.9'
        )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['method'] == 'PUT'
        assert '/dns_records/rec1' in call_kwargs['url']

    @patch('cloudflare.api.requests.request')
    def test_delete_dns_record(self, mock_request, api):
        """Test deleting a DNS record"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'id': 'rec1'}}
        mock_request.return_value = mock_response

        api.delete_dns_record(zone_id='zone123', record_id='rec1')

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['method'] == 'DELETE'
        assert '/dns_records/rec1' in call_kwargs['url']


class TestCloudflareAPISecurity:
    """Test security settings API methods"""

    @pytest.fixture
    def api(self):
        from cloudflare.api import CloudflareAPI
        return CloudflareAPI("test-token")

    @patch('cloudflare.api.requests.request')
    def test_get_security_level(self, mock_request, api):
        """Test getting security level"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'success': True,
            'result': {'value': 'medium'}
        }
        mock_request.return_value = mock_response

        level = api.get_security_level('zone123')

        assert level == 'medium'

    @patch('cloudflare.api.requests.request')
    def test_set_security_level_valid(self, mock_request, api):
        """Test setting valid security level"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'value': 'high'}}
        mock_request.return_value = mock_response

        api.set_security_level('zone123', 'high')

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['json']['value'] == 'high'

    def test_set_security_level_invalid(self, api):
        """Test setting invalid security level raises error"""
        from cloudflare.api import CloudflareAPIError

        with pytest.raises(CloudflareAPIError) as exc_info:
            api.set_security_level('zone123', 'invalid_level')

        assert "Invalid security level" in str(exc_info.value)

    @patch('cloudflare.api.requests.request')
    def test_get_bot_fight_mode(self, mock_request, api):
        """Test getting bot fight mode status"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'value': 'on'}}
        mock_request.return_value = mock_response

        status = api.get_bot_fight_mode('zone123')

        assert status == 'on'

    @patch('cloudflare.api.requests.request')
    def test_set_bot_fight_mode_enabled(self, mock_request, api):
        """Test enabling bot fight mode"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'value': 'on'}}
        mock_request.return_value = mock_response

        api.set_bot_fight_mode('zone123', enabled=True)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['json']['value'] == 'on'

    @patch('cloudflare.api.requests.request')
    def test_set_bot_fight_mode_disabled(self, mock_request, api):
        """Test disabling bot fight mode"""
        mock_response = Mock()
        mock_response.json.return_value = {'success': True, 'result': {'value': 'off'}}
        mock_request.return_value = mock_response

        api.set_bot_fight_mode('zone123', enabled=False)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs['json']['value'] == 'off'
