"""
Tests for backup_worker.py failure handling and cleanup
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys

sys.path.insert(0, '/opt/shophosting/webapp')
sys.path.insert(0, '/opt/shophosting/provisioning')


class TestOnJobFailure(unittest.TestCase):
    """Test the RQ failure callback"""

    @patch('backup_worker.CustomerBackupJob')
    @patch('backup_worker.logger')
    def test_failure_callback_marks_job_failed(self, mock_logger, mock_job_class):
        """Test that failure callback updates job status to failed"""
        from backup_worker import _on_job_failure

        # Setup mock job
        mock_backup_job = Mock()
        mock_backup_job.status = 'pending'
        mock_job_class.get_by_id.return_value = mock_backup_job

        # Create mock RQ job
        rq_job = Mock()
        rq_job.args = (42,)  # job_id = 42

        # Call failure callback
        _on_job_failure(
            job=rq_job,
            connection=Mock(),
            type=TypeError,
            value=TypeError("got an unexpected keyword argument 'foo'"),
            traceback=None
        )

        # Verify job was marked as failed
        mock_job_class.get_by_id.assert_called_once_with(42)
        mock_backup_job.update_status.assert_called_once()
        call_args = mock_backup_job.update_status.call_args
        self.assertEqual(call_args[0][0], 'failed')
        self.assertIn('TypeError', call_args[0][1])

    @patch('backup_worker.CustomerBackupJob')
    @patch('backup_worker.logger')
    def test_failure_callback_ignores_completed_jobs(self, mock_logger, mock_job_class):
        """Test that failure callback doesn't update already completed jobs"""
        from backup_worker import _on_job_failure

        mock_backup_job = Mock()
        mock_backup_job.status = 'completed'  # Already done
        mock_job_class.get_by_id.return_value = mock_backup_job

        rq_job = Mock()
        rq_job.args = (42,)

        _on_job_failure(rq_job, Mock(), Exception, Exception("test"), None)

        # Should NOT update status since job is already completed
        mock_backup_job.update_status.assert_not_called()


class TestStaleJobCleanup(unittest.TestCase):
    """Test stale job cleanup functionality"""

    @patch('models.get_db_connection')
    def test_cleanup_stale_jobs_updates_old_pending(self, mock_get_conn):
        """Test that cleanup marks old pending jobs as failed"""
        from models import CustomerBackupJob

        mock_cursor = Mock()
        mock_cursor.rowcount = 3
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = CustomerBackupJob.cleanup_stale_jobs(max_age_hours=1)

        self.assertEqual(result, 3)
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch('models.get_db_connection')
    def test_cleanup_stale_jobs_returns_zero_when_none(self, mock_get_conn):
        """Test cleanup returns 0 when no stale jobs"""
        from models import CustomerBackupJob

        mock_cursor = Mock()
        mock_cursor.rowcount = 0
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = CustomerBackupJob.cleanup_stale_jobs(max_age_hours=1)

        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
