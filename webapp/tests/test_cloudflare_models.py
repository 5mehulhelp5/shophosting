"""
Tests for Cloudflare models (encryption and database operations)
"""

import pytest
import os
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime


class TestEncryptionHelpers:
    """Test token encryption/decryption functions"""

    @pytest.fixture(autouse=True)
    def setup_secret_key(self):
        """Ensure SECRET_KEY is set for encryption tests"""
        os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-encryption'
        yield
        # Cleanup handled by conftest.py

    def test_get_encryption_key_returns_bytes(self):
        """Test encryption key is proper format"""
        from cloudflare.models import get_encryption_key

        key = get_encryption_key()

        assert isinstance(key, bytes)
        # Fernet keys are 44 bytes when base64 encoded
        assert len(key) == 44

    def test_get_encryption_key_consistent(self):
        """Test same secret produces same key"""
        from cloudflare.models import get_encryption_key

        key1 = get_encryption_key()
        key2 = get_encryption_key()

        assert key1 == key2

    def test_get_encryption_key_requires_secret(self):
        """Test missing SECRET_KEY raises error"""
        from cloudflare.models import get_encryption_key

        # Temporarily remove SECRET_KEY
        original = os.environ.pop('SECRET_KEY', None)
        try:
            with pytest.raises(RuntimeError) as exc_info:
                get_encryption_key()
            assert "SECRET_KEY" in str(exc_info.value)
        finally:
            if original:
                os.environ['SECRET_KEY'] = original

    def test_encrypt_token_basic(self):
        """Test basic token encryption"""
        from cloudflare.models import encrypt_token

        encrypted = encrypt_token("my-secret-token")

        assert encrypted is not None
        assert encrypted != "my-secret-token"
        assert isinstance(encrypted, str)

    def test_encrypt_token_none(self):
        """Test encrypting None returns None"""
        from cloudflare.models import encrypt_token

        result = encrypt_token(None)

        assert result is None

    def test_decrypt_token_basic(self):
        """Test basic token decryption"""
        from cloudflare.models import encrypt_token, decrypt_token

        original = "my-secret-api-token-12345"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)

        assert decrypted == original

    def test_decrypt_token_none(self):
        """Test decrypting None returns None"""
        from cloudflare.models import decrypt_token

        result = decrypt_token(None)

        assert result is None

    def test_encrypt_decrypt_roundtrip(self):
        """Test encrypt/decrypt preserves original value"""
        from cloudflare.models import encrypt_token, decrypt_token

        test_tokens = [
            "simple-token",
            "token-with-special-chars-!@#$%^&*()",
            "a" * 1000,  # Long token
            "",  # Empty string
        ]

        for token in test_tokens:
            encrypted = encrypt_token(token)
            decrypted = decrypt_token(encrypted)
            assert decrypted == token, f"Failed for token: {repr(token)}"


class TestCloudflareConnection:
    """Test CloudflareConnection model"""

    @pytest.fixture(autouse=True)
    def setup_secret_key(self):
        """Ensure SECRET_KEY is set"""
        os.environ['SECRET_KEY'] = 'test-secret-key-for-testing'
        yield

    def test_init_defaults(self):
        """Test default values on init"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection()

        assert conn.id is None
        assert conn.customer_id is None
        assert conn.cloudflare_zone_id is None
        assert conn.connected_at is not None  # Has default

    def test_init_with_values(self):
        """Test init with explicit values"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection(
            id=1,
            customer_id=42,
            cloudflare_zone_id='zone123'
        )

        assert conn.id == 1
        assert conn.customer_id == 42
        assert conn.cloudflare_zone_id == 'zone123'

    def test_access_token_encryption(self):
        """Test access token is encrypted when set"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection()
        conn.access_token = "secret-api-token"

        # Internal storage should be encrypted
        assert conn._access_token != "secret-api-token"
        assert conn._access_token is not None

        # Property should return decrypted
        assert conn.access_token == "secret-api-token"

    def test_refresh_token_encryption(self):
        """Test refresh token is encrypted when set"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection()
        conn.refresh_token = "refresh-token-value"

        # Internal storage should be encrypted
        assert conn._refresh_token != "refresh-token-value"

        # Property should return decrypted
        assert conn.refresh_token == "refresh-token-value"

    def test_is_token_expired_no_expiry(self):
        """Test token without expiry is considered expired"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection()
        conn.token_expires_at = None

        assert conn.is_token_expired() is True

    def test_is_token_expired_future(self):
        """Test token with future expiry is not expired"""
        from cloudflare.models import CloudflareConnection
        from datetime import datetime, timedelta

        conn = CloudflareConnection()
        conn.token_expires_at = datetime.now() + timedelta(hours=1)

        assert conn.is_token_expired() is False

    def test_is_token_expired_past(self):
        """Test token with past expiry is expired"""
        from cloudflare.models import CloudflareConnection
        from datetime import datetime, timedelta

        conn = CloudflareConnection()
        conn.token_expires_at = datetime.now() - timedelta(hours=1)

        assert conn.is_token_expired() is True

    @patch('cloudflare.models.get_db_connection')
    def test_save_insert_new(self, mock_get_db):
        """Test saving a new connection inserts"""
        from cloudflare.models import CloudflareConnection

        # Setup mock
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 99
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        conn = CloudflareConnection(customer_id=1)
        conn.access_token = "test-token"
        result = conn.save()

        # Verify insert was called
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert 'INSERT INTO customer_cloudflare_connections' in sql
        assert conn.id == 99
        assert result is conn

    @patch('cloudflare.models.get_db_connection')
    def test_save_update_existing(self, mock_get_db):
        """Test saving existing connection updates"""
        from cloudflare.models import CloudflareConnection

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        conn = CloudflareConnection(id=5, customer_id=1)
        conn.access_token = "updated-token"
        conn.save()

        sql = mock_cursor.execute.call_args[0][0]
        assert 'UPDATE customer_cloudflare_connections' in sql

    @patch('cloudflare.models.get_db_connection')
    def test_delete_removes_record(self, mock_get_db):
        """Test delete removes the connection"""
        from cloudflare.models import CloudflareConnection

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        conn = CloudflareConnection(id=5)
        result = conn.delete()

        assert result is True
        sql = mock_cursor.execute.call_args[0][0]
        assert 'DELETE FROM customer_cloudflare_connections' in sql

    def test_delete_without_id(self):
        """Test delete returns False without ID"""
        from cloudflare.models import CloudflareConnection

        conn = CloudflareConnection()
        result = conn.delete()

        assert result is False

    @patch('cloudflare.models.get_db_connection')
    def test_get_by_customer_id_found(self, mock_get_db):
        """Test finding connection by customer ID"""
        from cloudflare.models import CloudflareConnection, encrypt_token

        # Encrypt token for mock data
        encrypted_token = encrypt_token("stored-token")

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'id': 1,
            'customer_id': 42,
            'cloudflare_zone_id': 'zone123',
            'access_token': encrypted_token,
            'refresh_token': None,
            'token_expires_at': None,
            'connected_at': datetime.now(),
            'last_sync_at': None
        }
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        result = CloudflareConnection.get_by_customer_id(42)

        assert result is not None
        assert result.id == 1
        assert result.customer_id == 42
        assert result.access_token == "stored-token"

    @patch('cloudflare.models.get_db_connection')
    def test_get_by_customer_id_not_found(self, mock_get_db):
        """Test connection not found returns None"""
        from cloudflare.models import CloudflareConnection

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        result = CloudflareConnection.get_by_customer_id(999)

        assert result is None


class TestDNSRecordCache:
    """Test DNSRecordCache model"""

    def test_init_defaults(self):
        """Test default values on init"""
        from cloudflare.models import DNSRecordCache

        record = DNSRecordCache()

        assert record.id is None
        assert record.proxied is False
        assert record.ttl == 1
        assert record.synced_at is not None

    def test_init_with_values(self):
        """Test init with explicit values"""
        from cloudflare.models import DNSRecordCache

        record = DNSRecordCache(
            customer_id=1,
            cloudflare_record_id='rec123',
            record_type='A',
            name='example.com',
            content='1.2.3.4',
            proxied=True,
            ttl=300
        )

        assert record.record_type == 'A'
        assert record.content == '1.2.3.4'
        assert record.proxied is True
        assert record.ttl == 300

    @patch('cloudflare.models.get_db_connection')
    def test_save_uses_upsert(self, mock_get_db):
        """Test save uses INSERT ON DUPLICATE KEY UPDATE"""
        from cloudflare.models import DNSRecordCache

        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 10
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        record = DNSRecordCache(
            customer_id=1,
            cloudflare_record_id='rec123',
            record_type='A',
            name='test.com',
            content='1.2.3.4'
        )
        record.save()

        sql = mock_cursor.execute.call_args[0][0]
        assert 'INSERT INTO dns_records_cache' in sql
        assert 'ON DUPLICATE KEY UPDATE' in sql

    @patch('cloudflare.models.get_db_connection')
    def test_get_by_customer_id(self, mock_get_db):
        """Test getting cached records by customer ID"""
        from cloudflare.models import DNSRecordCache

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'id': 1,
                'customer_id': 42,
                'cloudflare_record_id': 'rec1',
                'record_type': 'A',
                'name': 'example.com',
                'content': '1.2.3.4',
                'priority': None,
                'proxied': False,
                'ttl': 1,
                'synced_at': datetime.now()
            },
            {
                'id': 2,
                'customer_id': 42,
                'cloudflare_record_id': 'rec2',
                'record_type': 'CNAME',
                'name': 'www.example.com',
                'content': 'example.com',
                'priority': None,
                'proxied': True,
                'ttl': 300,
                'synced_at': datetime.now()
            }
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        records = DNSRecordCache.get_by_customer_id(42)

        assert len(records) == 2
        assert records[0].record_type == 'A'
        assert records[1].record_type == 'CNAME'

    @patch('cloudflare.models.get_db_connection')
    def test_delete_by_cloudflare_id(self, mock_get_db):
        """Test deleting by Cloudflare record ID"""
        from cloudflare.models import DNSRecordCache

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        result = DNSRecordCache.delete_by_cloudflare_id('rec123')

        assert result is True
        sql = mock_cursor.execute.call_args[0][0]
        assert 'DELETE FROM dns_records_cache' in sql
        assert 'cloudflare_record_id' in sql

    @patch('cloudflare.models.get_db_connection')
    def test_clear_customer_cache(self, mock_get_db):
        """Test clearing all cached records for a customer"""
        from cloudflare.models import DNSRecordCache

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        count = DNSRecordCache.clear_customer_cache(42)

        assert count == 5
        sql = mock_cursor.execute.call_args[0][0]
        assert 'DELETE FROM dns_records_cache' in sql
        assert 'customer_id' in sql
