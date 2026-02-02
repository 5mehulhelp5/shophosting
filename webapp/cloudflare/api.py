"""
Cloudflare API Wrapper for ShopHosting.io

Provides a client for interacting with Cloudflare's v4 API using API tokens.
"""

import requests
from urllib.parse import urlencode


# API Configuration
CLOUDFLARE_API_BASE_URL = 'https://api.cloudflare.com/client/v4'


class CloudflareAPIError(Exception):
    """Exception raised when a Cloudflare API request fails."""

    def __init__(self, message, status_code=None, errors=None):
        """
        Initialize the CloudflareAPIError.

        Args:
            message: Human-readable error message
            status_code: HTTP status code from the response (optional)
            errors: List of error details from Cloudflare API (optional)
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or []

    def __str__(self):
        if self.status_code:
            return f"CloudflareAPIError ({self.status_code}): {self.message}"
        return f"CloudflareAPIError: {self.message}"


class CloudflareAPI:
    """Client for interacting with the Cloudflare v4 API."""

    def __init__(self, api_token):
        """
        Initialize the Cloudflare API client.

        Args:
            api_token: Cloudflare API token for authentication
        """
        self.api_token = api_token
        self.base_url = CLOUDFLARE_API_BASE_URL

    def _request(self, method, endpoint, data=None):
        """
        Make an authenticated request to the Cloudflare API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint path (e.g., '/zones')
            data: Request body data for POST/PUT/PATCH requests (optional)

        Returns:
            dict: The 'result' field from the Cloudflare API response

        Raises:
            CloudflareAPIError: If the request fails or returns an error
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                timeout=30
            )
        except requests.exceptions.Timeout:
            raise CloudflareAPIError("Request to Cloudflare API timed out")
        except requests.exceptions.RequestException as e:
            raise CloudflareAPIError(f"Request to Cloudflare API failed: {str(e)}")

        try:
            response_data = response.json()
        except ValueError:
            raise CloudflareAPIError(
                f"Invalid JSON response from Cloudflare API",
                status_code=response.status_code
            )

        # Check for API errors
        if not response_data.get('success', False):
            errors = response_data.get('errors', [])
            error_messages = [e.get('message', 'Unknown error') for e in errors]
            message = '; '.join(error_messages) if error_messages else 'Unknown API error'
            raise CloudflareAPIError(
                message,
                status_code=response.status_code,
                errors=errors
            )

        return response_data.get('result')

    def get_zones(self):
        """
        List all zones accessible with the current token.

        Returns:
            list: List of zone objects

        Raises:
            CloudflareAPIError: If the request fails
        """
        return self._request('GET', '/zones')

    def get_zone_by_name(self, domain):
        """
        Find a zone by domain name.

        Args:
            domain: The domain name to search for (e.g., 'example.com')

        Returns:
            dict: Zone object if found, None if not found

        Raises:
            CloudflareAPIError: If the request fails
        """
        params = urlencode({'name': domain})
        result = self._request('GET', f'/zones?{params}')

        if result and len(result) > 0:
            return result[0]
        return None

    def get_dns_records(self, zone_id, record_types=None):
        """
        List DNS records for a zone.

        Args:
            zone_id: The zone identifier
            record_types: Optional list of record types to filter by
                         (e.g., ['A', 'AAAA', 'CNAME'])

        Returns:
            list: List of DNS record objects

        Raises:
            CloudflareAPIError: If the request fails
        """
        endpoint = f'/zones/{zone_id}/dns_records'

        if record_types:
            # Cloudflare API accepts multiple type parameters
            params = '&'.join([f'type={t}' for t in record_types])
            endpoint = f'{endpoint}?{params}'

        return self._request('GET', endpoint)

    def create_dns_record(self, zone_id, record_type, name, content, ttl=1,
                          priority=None, proxied=False):
        """
        Create a new DNS record.

        Args:
            zone_id: The zone identifier
            record_type: DNS record type (A, AAAA, CNAME, MX, TXT, etc.)
            name: DNS record name (e.g., 'subdomain.example.com')
            content: DNS record content (e.g., IP address, target hostname)
            ttl: Time to live for DNS record (1 = automatic, otherwise seconds)
            priority: Priority for MX/SRV records (optional)
            proxied: Whether the record receives Cloudflare's protection (default False)

        Returns:
            dict: The created DNS record object

        Raises:
            CloudflareAPIError: If the request fails
        """
        data = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': ttl,
            'proxied': proxied
        }

        # Priority is only valid for MX and SRV records
        if priority is not None and record_type in ('MX', 'SRV'):
            data['priority'] = priority

        return self._request('POST', f'/zones/{zone_id}/dns_records', data)

    def update_dns_record(self, zone_id, record_id, record_type, name, content,
                          ttl=1, priority=None, proxied=False):
        """
        Update an existing DNS record.

        Args:
            zone_id: The zone identifier
            record_id: The DNS record identifier
            record_type: DNS record type (A, AAAA, CNAME, MX, TXT, etc.)
            name: DNS record name (e.g., 'subdomain.example.com')
            content: DNS record content (e.g., IP address, target hostname)
            ttl: Time to live for DNS record (1 = automatic, otherwise seconds)
            priority: Priority for MX/SRV records (optional)
            proxied: Whether the record receives Cloudflare's protection (default False)

        Returns:
            dict: The updated DNS record object

        Raises:
            CloudflareAPIError: If the request fails
        """
        data = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': ttl,
            'proxied': proxied
        }

        # Priority is only valid for MX and SRV records
        if priority is not None and record_type in ('MX', 'SRV'):
            data['priority'] = priority

        return self._request('PUT', f'/zones/{zone_id}/dns_records/{record_id}', data)

    def delete_dns_record(self, zone_id, record_id):
        """
        Delete a DNS record.

        Args:
            zone_id: The zone identifier
            record_id: The DNS record identifier

        Returns:
            dict: Deletion confirmation (contains 'id' of deleted record)

        Raises:
            CloudflareAPIError: If the request fails
        """
        return self._request('DELETE', f'/zones/{zone_id}/dns_records/{record_id}')

    # =========================================================================
    # Security Settings
    # =========================================================================

    def get_security_level(self, zone_id):
        """
        Get the current security level for a zone.

        Args:
            zone_id: The zone identifier

        Returns:
            str: Current security level (essentially_off, low, medium, high, under_attack)

        Raises:
            CloudflareAPIError: If the request fails
        """
        result = self._request('GET', f'/zones/{zone_id}/settings/security_level')
        return result.get('value')

    def set_security_level(self, zone_id, level):
        """
        Set the security level for a zone.

        Args:
            zone_id: The zone identifier
            level: Security level - one of:
                   'essentially_off', 'low', 'medium', 'high', 'under_attack'

        Returns:
            dict: Updated setting

        Raises:
            CloudflareAPIError: If the request fails
        """
        valid_levels = ['essentially_off', 'low', 'medium', 'high', 'under_attack']
        if level not in valid_levels:
            raise CloudflareAPIError(f'Invalid security level. Must be one of: {", ".join(valid_levels)}')

        return self._request('PATCH', f'/zones/{zone_id}/settings/security_level', {'value': level})

    def get_bot_fight_mode(self, zone_id):
        """
        Get Bot Fight Mode status for a zone.

        Args:
            zone_id: The zone identifier

        Returns:
            str: 'on' or 'off'

        Raises:
            CloudflareAPIError: If the request fails
        """
        result = self._request('GET', f'/zones/{zone_id}/settings/bot_fight_mode')
        return result.get('value')

    def set_bot_fight_mode(self, zone_id, enabled):
        """
        Enable or disable Bot Fight Mode for a zone.

        Args:
            zone_id: The zone identifier
            enabled: True to enable, False to disable

        Returns:
            dict: Updated setting

        Raises:
            CloudflareAPIError: If the request fails
        """
        value = 'on' if enabled else 'off'
        return self._request('PATCH', f'/zones/{zone_id}/settings/bot_fight_mode', {'value': value})
