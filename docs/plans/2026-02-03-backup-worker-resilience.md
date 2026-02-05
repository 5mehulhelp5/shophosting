# Backup Worker Resilience Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent stuck backup jobs by adding RQ failure callbacks, automatic stale job cleanup, and worker restart on model changes.

**Architecture:**
1. Add RQ `on_failure` callback to mark jobs as failed in MySQL when RQ exceptions occur
2. Add periodic cleanup loop to mark stale pending jobs (>1 hour) as failed
3. Add post-deploy hook script that restarts backup worker when models.py changes

**Tech Stack:** Python, RQ, Redis, systemd, bash

---

## Task 1: Add RQ Failure Callback

**Files:**
- Modify: `/opt/shophosting/provisioning/backup_worker.py`

**Step 1: Add failure callback function**

Add after line 179 (after `_determine_backup_source` method, before RQ Job Functions section):

```python
def _on_job_failure(job, connection, type, value, traceback):
    """
    RQ failure callback - ensures MySQL job status is updated when RQ job fails.
    This catches exceptions that happen before job.update_status() is called,
    such as model loading errors or database connection issues.
    """
    try:
        # Extract job_id from the RQ job args
        if job.args:
            job_id = job.args[0]
            backup_job = CustomerBackupJob.get_by_id(job_id)
            if backup_job and backup_job.status in ('pending', 'running'):
                error_msg = f"Worker error: {type.__name__}: {str(value)[:200]}"
                backup_job.update_status('failed', error_msg)
                logger.error(f"Marked backup job {job_id} as failed via RQ callback: {error_msg}")
    except Exception as e:
        logger.error(f"Failed to update job status in RQ failure callback: {e}")
```

**Step 2: Update create_backup_job to use failure callback**

Modify `create_backup_job` function (around line 186) to register the callback:

```python
def create_backup_job(job_id):
    """RQ job wrapper for creating backup"""
    worker = BackupWorker()
    return worker.create_backup(job_id)

# Register failure callback for this function
create_backup_job.on_failure = _on_job_failure
```

**Step 3: Update restore_backup_job to use failure callback**

Modify `restore_backup_job` function (around line 192):

```python
def restore_backup_job(job_id):
    """RQ job wrapper for restoring backup"""
    worker = BackupWorker()
    return worker.restore_backup(job_id)

# Register failure callback for this function
restore_backup_job.on_failure = _on_job_failure
```

**Step 4: Test failure callback manually**

Run:
```bash
# Restart worker to pick up changes
sudo systemctl restart shophosting-backup-worker

# Check logs to verify worker started
journalctl -u shophosting-backup-worker -n 5 --no-pager
```

Expected: Worker starts successfully with "Starting backup worker..."

**Step 5: Commit**

```bash
git add provisioning/backup_worker.py
git commit -m "fix(backup-worker): add RQ failure callback to mark jobs as failed

When RQ jobs fail with uncaught exceptions (like model loading errors),
the MySQL job status wasn't being updated, causing 'Creating backup...'
spinner to persist indefinitely.

Added on_failure callback that catches these cases and properly marks
the job as failed in the database."
```

---

## Task 2: Add Stale Job Cleanup

**Files:**
- Modify: `/opt/shophosting/webapp/models.py`
- Modify: `/opt/shophosting/provisioning/backup_worker.py`

**Step 1: Add cleanup_stale_jobs method to CustomerBackupJob model**

Add after the `get_recent_jobs` method in `/opt/shophosting/webapp/models.py` (around line 2295):

```python
    @staticmethod
    def cleanup_stale_jobs(max_age_hours=1):
        """
        Mark stale pending/running jobs as failed.
        Jobs stuck in pending/running for more than max_age_hours are marked failed.
        Returns count of jobs cleaned up.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE customer_backup_jobs
                SET status = 'failed',
                    error_message = 'Job timed out (no response from worker)',
                    completed_at = NOW()
                WHERE status IN ('pending', 'running')
                AND created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
            """, (max_age_hours,))

            count = cursor.rowcount
            conn.commit()
            return count
        finally:
            cursor.close()
            conn.close()
```

**Step 2: Add cleanup loop to backup worker**

Modify the `if __name__ == '__main__':` section in `/opt/shophosting/provisioning/backup_worker.py`:

```python
if __name__ == '__main__':
    # Run as RQ worker with periodic cleanup
    from redis import Redis
    from rq import Worker, Queue
    import threading
    import time

    # Enable file logging when running as worker
    _configure_file_logging()

    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_conn = Redis(host=redis_host, port=6379)

    queues = [Queue('backups', connection=redis_conn)]

    # Stale job cleanup interval (1 hour)
    CLEANUP_INTERVAL_SECONDS = 3600

    def cleanup_loop():
        """Periodically clean up stale backup jobs"""
        while True:
            try:
                time.sleep(CLEANUP_INTERVAL_SECONDS)
                count = CustomerBackupJob.cleanup_stale_jobs(max_age_hours=1)
                if count > 0:
                    logger.info(f"Cleaned up {count} stale backup jobs")
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("Started stale job cleanup thread (interval: 1 hour)")

    logger.info("Starting backup worker...")
    worker = Worker(queues, connection=redis_conn)
    worker.work()
```

**Step 3: Restart worker and verify**

Run:
```bash
sudo systemctl restart shophosting-backup-worker
journalctl -u shophosting-backup-worker -n 10 --no-pager
```

Expected: Logs show "Started stale job cleanup thread" and "Starting backup worker..."

**Step 4: Commit**

```bash
git add webapp/models.py provisioning/backup_worker.py
git commit -m "feat(backup-worker): add automatic stale job cleanup

Jobs stuck in pending/running for more than 1 hour are now automatically
marked as failed. This prevents infinite spinner states when workers
crash or jobs are never picked up from the queue.

- Added CustomerBackupJob.cleanup_stale_jobs() method
- Added background cleanup thread to backup worker"
```

---

## Task 3: Add Worker Restart on Model Changes

**Files:**
- Create: `/opt/shophosting/scripts/restart-workers-if-models-changed.sh`
- Modify: `/opt/shophosting/scripts/rolling-restart.sh` (optional hook point)

**Step 1: Create the restart script**

Create `/opt/shophosting/scripts/restart-workers-if-models-changed.sh`:

```bash
#!/bin/bash
#
# Restart Python workers if models.py has changed since last deploy.
# Called after git pull or deploy operations.
#
# Usage: ./restart-workers-if-models-changed.sh [commit_before] [commit_after]
#        If no args provided, compares HEAD~1 to HEAD
#

set -e

MODELS_FILE="webapp/models.py"
WORKERS=(
    "shophosting-backup-worker"
    "shophosting-provisioning-worker"
    "shophosting-staging-worker"
)

# Get commit range
BEFORE="${1:-HEAD~1}"
AFTER="${2:-HEAD}"

# Check if models.py changed
if git diff --name-only "$BEFORE" "$AFTER" | grep -q "^${MODELS_FILE}$"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - models.py changed, restarting workers..."

    for worker in "${WORKERS[@]}"; do
        if systemctl is-active --quiet "$worker" 2>/dev/null; then
            echo "  Restarting $worker..."
            sudo systemctl restart "$worker"
            sleep 2

            if systemctl is-active --quiet "$worker"; then
                echo "  ✓ $worker restarted successfully"
            else
                echo "  ✗ $worker failed to restart!"
                journalctl -u "$worker" -n 5 --no-pager
            fi
        else
            echo "  - $worker not running, skipping"
        fi
    done

    echo "$(date '+%Y-%m-%d %H:%M:%S') - Worker restart complete"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - models.py unchanged, no worker restart needed"
fi
```

**Step 2: Make script executable**

Run:
```bash
chmod +x /opt/shophosting/scripts/restart-workers-if-models-changed.sh
```

**Step 3: Test the script**

Run:
```bash
# Test with current changes (should detect models.py didn't change recently)
/opt/shophosting/scripts/restart-workers-if-models-changed.sh

# Verify it works by simulating a models.py change
git diff --name-only HEAD~5 HEAD | grep models.py || echo "No models.py in last 5 commits"
```

**Step 4: Add hook to rolling-restart.sh**

Add at the end of `/opt/shophosting/scripts/rolling-restart.sh` (before the final echo):

```bash
# Restart workers if models changed
if [[ -x "/opt/shophosting/scripts/restart-workers-if-models-changed.sh" ]]; then
    echo "Checking if workers need restart..."
    /opt/shophosting/scripts/restart-workers-if-models-changed.sh "${GIT_PREV_HEAD:-HEAD~1}" "${GIT_HEAD:-HEAD}" || true
fi
```

**Step 5: Commit**

```bash
git add scripts/restart-workers-if-models-changed.sh scripts/rolling-restart.sh
git commit -m "feat(deploy): auto-restart workers when models.py changes

Python workers cache model definitions in memory. When models.py changes
(new columns, modified __init__), workers must restart to avoid TypeError
exceptions like 'got an unexpected keyword argument'.

Added script that checks git diff for models.py changes and restarts
relevant workers. Integrated into rolling-restart.sh deploy process."
```

---

## Task 4: Add Unit Tests

**Files:**
- Create: `/opt/shophosting/provisioning/tests/test_backup_worker.py`

**Step 1: Create test file**

```python
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
```

**Step 2: Create tests directory if needed**

Run:
```bash
mkdir -p /opt/shophosting/provisioning/tests
touch /opt/shophosting/provisioning/tests/__init__.py
```

**Step 3: Run tests**

Run:
```bash
cd /opt/shophosting/provisioning
python -m pytest tests/test_backup_worker.py -v
```

Expected: All tests pass

**Step 4: Commit**

```bash
git add provisioning/tests/
git commit -m "test(backup-worker): add unit tests for failure handling

Tests cover:
- RQ failure callback marks pending jobs as failed
- Failure callback skips already-completed jobs
- Stale job cleanup updates correct number of jobs"
```

---

## Task 5: Final Verification

**Step 1: Restart all services**

Run:
```bash
sudo systemctl restart shophosting-backup-worker
sleep 3
systemctl status shophosting-backup-worker --no-pager
```

**Step 2: Verify logs show cleanup thread**

Run:
```bash
journalctl -u shophosting-backup-worker -n 15 --no-pager | grep -E "(cleanup|Starting)"
```

Expected: See "Started stale job cleanup thread" message

**Step 3: Verify failure callback is registered**

Run:
```bash
cd /opt/shophosting/provisioning
python3 -c "from backup_worker import create_backup_job; print('on_failure:', hasattr(create_backup_job, 'on_failure'))"
```

Expected: `on_failure: True`

**Step 4: Final commit (if any cleanup needed)**

```bash
git status
# If clean, no commit needed
```

---

## Summary

After completing all tasks:

1. **RQ failure callback** ensures MySQL job status is updated even when exceptions occur before `job.update_status()` is called
2. **Stale job cleanup** runs every hour and marks jobs stuck >1 hour as failed
3. **Worker restart script** automatically restarts workers when `models.py` changes during deploys
4. **Unit tests** verify the failure handling logic works correctly

The customer-facing "Creating backup..." infinite spinner issue is now prevented at multiple levels.
