"""Tests for mail management module."""
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
import importlib.util

# Import the mail module directly to avoid triggering admin/__init__.py
# which would cause import issues with the local secrets.py module
_mail_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'admin', 'mail.py')
_spec = importlib.util.spec_from_file_location('admin_mail', _mail_path)
mail_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mail_module)


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        with patch.object(mail_module, 'subprocess') as mock_subprocess:
            mock_subprocess.run.return_value = MagicMock(
                stdout='{SHA512-CRYPT}$6$rounds=5000$saltsalt$hashhash\n',
                returncode=0
            )
            result = mail_module.hash_password('testpass')
            assert result.startswith('{SHA512-CRYPT}')
            assert '\n' not in result

    def test_hash_password_calls_doveadm(self):
        with patch.object(mail_module, 'subprocess') as mock_subprocess:
            mock_subprocess.run.return_value = MagicMock(stdout='hash\n', returncode=0)
            mail_module.hash_password('testpass')
            mock_subprocess.run.assert_called_once()
            args = mock_subprocess.run.call_args[0][0]
            assert 'doveadm' in args
            assert 'pw' in args


class TestMailboxModel:
    def test_validate_username_valid(self):
        Mailbox = mail_module.Mailbox
        assert Mailbox.validate_username('john') == True
        assert Mailbox.validate_username('john.doe') == True
        assert Mailbox.validate_username('john_doe123') == True

    def test_validate_username_invalid(self):
        Mailbox = mail_module.Mailbox
        assert Mailbox.validate_username('') == False
        assert Mailbox.validate_username('john@domain') == False
        assert Mailbox.validate_username('john doe') == False
        assert Mailbox.validate_username('../etc') == False


class TestMaildirSize:
    def test_get_maildir_size_returns_int(self):
        with patch.object(mail_module, 'subprocess') as mock_subprocess:
            mock_subprocess.run.return_value = MagicMock(
                stdout='12345\t/var/mail/vhosts/shophosting.io/test\n',
                returncode=0
            )
            result = mail_module.get_maildir_size('test')
            assert result == 12345

    def test_get_maildir_size_nonexistent_returns_zero(self):
        with patch.object(mail_module, 'subprocess') as mock_subprocess:
            mock_subprocess.run.return_value = MagicMock(stdout='', returncode=1)
            result = mail_module.get_maildir_size('nonexistent')
            assert result == 0
