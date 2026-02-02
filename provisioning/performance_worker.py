#!/usr/bin/env python3
"""
ShopHosting.io - Performance Worker

Background worker process that monitors customer stores and automatically
remediates performance issues based on customer automation preferences.

Runs every 60 seconds and for each active customer:
1. Detects issues using IssueDetector
2. Based on automation_level:
   - Level 1: Create alert only (notify)
   - Level 2+: Execute safe playbooks, notify after
   - Level 3: Execute all playbooks including aggressive ones
3. Logs all actions to automation_actions table
4. Sends notifications to customers

Usage:
    python3 performance_worker.py

Configuration (environment variables):
    PERFORMANCE_WORKER_ENABLED: Set to 'true' to enable (default: true)
    CHECK_INTERVAL_SECONDS: Interval between checks (default: 60)
    LOG_LEVEL: Logging level (default: INFO)
"""

import os
import sys
import time
import logging
import signal
from datetime import datetime
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv('/opt/shophosting/.env')

from webapp.performance.detection import IssueDetector, DetectedIssue
from webapp.performance.playbooks import execute_playbook_for_issue, PlaybookResult
from webapp.performance.action_logger import ActionLogger
from webapp.performance.notifications import NotificationService

# Configuration
PERFORMANCE_WORKER_ENABLED = os.getenv('PERFORMANCE_WORKER_ENABLED', 'true').lower() == 'true'
CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_SECONDS', '60'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Set up logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/shophosting/logs/performance_worker.log')
    ]
)
logger = logging.getLogger('performance_worker')


class PerformanceWorker:
    """
    Background worker for automated performance monitoring and remediation.
    """

    def __init__(self):
        self.running = True
        self.detector = IssueDetector()
        self.action_logger = ActionLogger()
        self.notification_service = NotificationService()
        self.check_count = 0
        self.issues_detected = 0
        self.playbooks_executed = 0

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def run(self):
        """Main worker loop"""
        logger.info("Performance worker started")
        logger.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")

        while self.running:
            try:
                self._check_all_customers()
                self.check_count += 1

                if self.check_count % 10 == 0:
                    logger.info(f"Stats: {self.check_count} checks, "
                               f"{self.issues_detected} issues detected, "
                               f"{self.playbooks_executed} playbooks executed")

            except Exception as e:
                logger.error(f"Error in check cycle: {e}", exc_info=True)

            # Sleep in small increments to allow for graceful shutdown
            for _ in range(CHECK_INTERVAL_SECONDS):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("Performance worker stopped")

    def _check_all_customers(self):
        """Check all active customers for performance issues"""
        customers = self._get_active_customers()

        for customer in customers:
            if not self.running:
                break

            try:
                self._check_customer(customer)
            except Exception as e:
                logger.error(f"Error checking customer {customer['id']}: {e}")

    def _get_active_customers(self) -> List[dict]:
        """Get list of active customers with their settings"""
        try:
            from webapp.models import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    c.id,
                    c.domain,
                    c.platform,
                    c.status,
                    c.automation_level,
                    c.automation_exceptions
                FROM customers c
                WHERE c.status = 'active'
                ORDER BY c.id
            """)

            customers = cursor.fetchall()
            cursor.close()
            conn.close()

            return customers

        except Exception as e:
            logger.error(f"Error fetching active customers: {e}")
            return []

    def _check_customer(self, customer: dict):
        """Check a single customer for issues and remediate if needed"""
        customer_id = customer['id']
        automation_level = customer.get('automation_level', 2)
        platform = customer.get('platform', 'woocommerce')
        container_name = f"customer-{customer_id}-web"

        # Detect issues
        issues = self.detector.detect_issues(customer_id)

        if not issues:
            return

        self.issues_detected += len(issues)
        logger.info(f"Customer {customer_id}: Detected {len(issues)} issue(s)")

        for issue in issues:
            self._handle_issue(customer_id, container_name, platform, automation_level, issue)

    def _handle_issue(
        self,
        customer_id: int,
        container_name: str,
        platform: str,
        automation_level: int,
        issue: DetectedIssue
    ):
        """Handle a detected issue based on automation level"""
        logger.info(f"Customer {customer_id}: Handling issue {issue.issue_type} "
                   f"(severity: {issue.severity})")

        # Store the issue in the database
        issue_id = self._store_issue(customer_id, issue)

        if automation_level == 1:
            # Level 1: Notify only
            self._notify_customer(customer_id, issue, None)
            logger.info(f"Customer {customer_id}: Notification sent (level 1)")
            return

        # Level 2+: Execute playbook
        result = execute_playbook_for_issue(
            customer_id=customer_id,
            container_name=container_name,
            platform=platform,
            automation_level=automation_level,
            issue_type=issue.issue_type,
            issue_details=issue.details
        )

        self.playbooks_executed += 1

        # Log the playbook execution
        self._log_playbook_result(customer_id, issue_id, result)

        # Send notification with results
        self._notify_customer(customer_id, issue, result)

        # If playbook succeeded, mark issue as auto-fixed
        if result.success:
            self._mark_issue_auto_fixed(issue_id)

        logger.info(f"Customer {customer_id}: Playbook '{result.playbook_name}' "
                   f"{'succeeded' if result.success else 'failed'}")

    def _store_issue(self, customer_id: int, issue: DetectedIssue) -> Optional[int]:
        """Store detected issue in the database"""
        try:
            from webapp.models import get_db_connection
            import json

            conn = get_db_connection()
            cursor = conn.cursor()

            # Check if same issue type is already open for this customer
            cursor.execute("""
                SELECT id FROM performance_issues
                WHERE customer_id = %s
                  AND issue_type = %s
                  AND resolved_at IS NULL
                LIMIT 1
            """, (customer_id, issue.issue_type))

            existing = cursor.fetchone()
            if existing:
                cursor.close()
                conn.close()
                return existing[0]  # Return existing issue ID

            # Insert new issue
            cursor.execute("""
                INSERT INTO performance_issues
                (customer_id, issue_type, severity, detected_at, details)
                VALUES (%s, %s, %s, NOW(), %s)
            """, (
                customer_id,
                issue.issue_type,
                issue.severity,
                json.dumps(issue.details) if issue.details else None
            ))

            issue_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            conn.close()

            return issue_id

        except Exception as e:
            logger.error(f"Error storing issue: {e}")
            return None

    def _mark_issue_auto_fixed(self, issue_id: Optional[int]):
        """Mark an issue as auto-fixed"""
        if not issue_id:
            return

        try:
            from webapp.models import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE performance_issues
                SET resolved_at = NOW(), auto_fixed = TRUE
                WHERE id = %s
            """, (issue_id,))

            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"Error marking issue as fixed: {e}")

    def _log_playbook_result(self, customer_id: int, issue_id: Optional[int], result: PlaybookResult):
        """Log playbook execution results"""
        for action in result.actions:
            if action.skipped:
                continue

            self.action_logger.log_action(
                customer_id=customer_id,
                playbook_name=result.playbook_name,
                action_name=action.action_name,
                success=action.success,
                result={
                    'message': action.message,
                    'duration_ms': action.duration_ms,
                    'output': action.output
                },
                issue_id=issue_id
            )

    def _notify_customer(self, customer_id: int, issue: DetectedIssue, result: Optional[PlaybookResult]):
        """Send notification to customer about issue and actions taken"""
        if result and result.success:
            # Auto-fix applied
            title = f"Performance issue auto-fixed: {issue.issue_type.replace('_', ' ').title()}"
            message = f"Detected {issue.issue_type.replace('_', ' ')} and automatically applied fixes. "
            actions_taken = [a.action_name for a in result.actions if a.success and not a.skipped]
            if actions_taken:
                message += f"Actions: {', '.join(actions_taken)}"
            severity = 'info'
            event_type = 'auto_fix_applied'
        elif result and not result.success:
            # Auto-fix attempted but failed
            title = f"Performance issue detected: {issue.issue_type.replace('_', ' ').title()}"
            message = f"Attempted to fix {issue.issue_type.replace('_', ' ')} but some actions failed. Please review."
            severity = 'warning'
            event_type = 'auto_fix_failed'
        else:
            # No auto-fix (level 1)
            title = f"Performance alert: {issue.issue_type.replace('_', ' ').title()}"
            message = issue.message
            severity = issue.severity
            event_type = 'issue_detected'

        self.notification_service.notify_customer(
            customer_id=customer_id,
            event_type=event_type,
            title=title,
            message=message,
            severity=severity
        )


def main():
    """Main entry point"""
    if not PERFORMANCE_WORKER_ENABLED:
        logger.info("Performance worker is disabled (PERFORMANCE_WORKER_ENABLED != 'true')")
        return

    worker = PerformanceWorker()
    worker.run()


if __name__ == '__main__':
    main()
