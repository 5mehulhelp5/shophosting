"""
Admin Intervention Playbooks for ShopHosting.io

Pre-built playbooks for admin actions on customer stores.
These are manual admin interventions (not automated) that can be
executed from the admin dashboard.

Playbooks:
- optimize_store: Full optimization pass
- emergency_stabilize: Emergency stabilization for critical issues
- clear_caches: Clear all caches (application, Redis, OPcache)
- restart_services: Restart PHP-FPM and related services
"""

import subprocess
import logging
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Command timeouts
COMMAND_TIMEOUT = 60
EMERGENCY_TIMEOUT = 30


class PlaybookType(Enum):
    OPTIMIZE_STORE = "optimize_store"
    EMERGENCY_STABILIZE = "emergency_stabilize"
    CLEAR_CACHES = "clear_caches"
    RESTART_SERVICES = "restart_services"


@dataclass
class PlaybookAction:
    """Result of a single action within a playbook."""
    name: str
    description: str
    success: bool = False
    message: str = ""
    duration_ms: int = 0
    output: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'description': self.description,
            'success': self.success,
            'message': self.message,
            'duration_ms': self.duration_ms,
            'output': self.output
        }


@dataclass
class PlaybookResult:
    """Result of executing a complete playbook."""
    playbook_name: str
    customer_id: int
    executed_by: int  # admin user id
    started_at: datetime
    completed_at: datetime = None
    success: bool = False
    actions: List[PlaybookAction] = field(default_factory=list)
    error: str = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'playbook_name': self.playbook_name,
            'customer_id': self.customer_id,
            'executed_by': self.executed_by,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'success': self.success,
            'actions': [a.to_dict() for a in self.actions],
            'error': self.error
        }


class AdminPlaybookExecutor:
    """
    Executes admin intervention playbooks on customer stores.

    These are manual interventions triggered by admin users, not automated
    responses to detected issues.
    """

    def __init__(self, customer_id: int, admin_user_id: int):
        """
        Initialize the executor.

        Args:
            customer_id: The customer store to operate on
            admin_user_id: The admin user executing the playbook
        """
        self.customer_id = customer_id
        self.admin_user_id = admin_user_id
        self.container_name = f"customer-{customer_id}-web"
        self.db_container_name = f"customer-{customer_id}-db"
        self.platform = None  # 'woocommerce' or 'magento'
        self.customer = None

    def _load_customer(self):
        """Load customer details including platform."""
        from webapp.models import Customer
        self.customer = Customer.get_by_id(self.customer_id)
        if self.customer:
            self.platform = self.customer.platform.lower() if self.customer.platform else 'woocommerce'
        else:
            raise ValueError(f"Customer {self.customer_id} not found")

    def _run_container_command(
        self,
        command: List[str],
        timeout: int = COMMAND_TIMEOUT,
        workdir: str = '/var/www/html'
    ) -> tuple:
        """
        Run a command in the customer's web container.

        Args:
            command: Command and arguments to run
            timeout: Timeout in seconds
            workdir: Working directory for the command

        Returns:
            tuple: (success: bool, output: str)
        """
        docker_cmd = [
            'docker', 'exec',
            '-w', workdir,
            self.container_name
        ] + command

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                return (True, result.stdout.strip() if result.stdout else "")
            else:
                error_msg = result.stderr.strip() if result.stderr else f"Exit code: {result.returncode}"
                return (False, error_msg)

        except subprocess.TimeoutExpired:
            return (False, f"Command timed out after {timeout}s")
        except Exception as e:
            return (False, str(e))

    def _run_db_command(self, query: str, timeout: int = 30) -> tuple:
        """
        Run a SQL query in the customer's database container.

        Args:
            query: SQL query to execute
            timeout: Timeout in seconds

        Returns:
            tuple: (success: bool, output: str)
        """
        docker_cmd = [
            'docker', 'exec',
            self.db_container_name,
            'mysql', '-N', '-B', '-e', query
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                return (True, result.stdout.strip() if result.stdout else "")
            else:
                error_msg = result.stderr.strip() if result.stderr else f"Exit code: {result.returncode}"
                return (False, error_msg)

        except subprocess.TimeoutExpired:
            return (False, f"Query timed out after {timeout}s")
        except Exception as e:
            return (False, str(e))

    def _log_intervention(self, result: PlaybookResult):
        """Log the intervention to admin_interventions table."""
        from webapp.models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            result_json = json.dumps({
                'success': result.success,
                'actions': [a.to_dict() for a in result.actions],
                'error': result.error,
                'duration_ms': int((result.completed_at - result.started_at).total_seconds() * 1000) if result.completed_at else 0
            })

            cursor.execute("""
                INSERT INTO admin_interventions
                    (customer_id, admin_user_id, playbook_name, executed_at, reason, result)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                self.customer_id,
                self.admin_user_id,
                result.playbook_name,
                result.started_at,
                None,  # reason is passed separately
                result_json
            ))
            conn.commit()

            logger.info(
                f"Admin intervention logged: admin={self.admin_user_id} "
                f"customer={self.customer_id} playbook={result.playbook_name} "
                f"success={result.success}"
            )

        except Exception as e:
            logger.error(f"Failed to log admin intervention: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def _execute_action(
        self,
        name: str,
        description: str,
        func
    ) -> PlaybookAction:
        """
        Execute a single action and return the result.

        Args:
            name: Action name
            description: Human-readable description
            func: Function to execute, should return (success, message, output)

        Returns:
            PlaybookAction with results
        """
        start_time = time.time()
        action = PlaybookAction(name=name, description=description)

        try:
            success, message, output = func()
            action.success = success
            action.message = message
            action.output = output
        except Exception as e:
            action.success = False
            action.message = f"Exception: {str(e)}"
            logger.error(f"Action {name} failed with exception: {e}")

        action.duration_ms = int((time.time() - start_time) * 1000)
        return action

    def execute_optimize_store(self, reason: str = None) -> PlaybookResult:
        """
        Full optimization pass:
        - Clear all caches
        - Optimize database tables
        - Restart PHP-FPM

        Args:
            reason: Optional reason for the intervention

        Returns:
            PlaybookResult with execution details
        """
        result = PlaybookResult(
            playbook_name='optimize_store',
            customer_id=self.customer_id,
            executed_by=self.admin_user_id,
            started_at=datetime.now()
        )

        try:
            # Action 1: Clear application cache
            if self.platform == 'woocommerce':
                action = self._execute_action(
                    'clear_wp_cache',
                    'Clear WordPress object cache',
                    lambda: self._clear_wp_cache()
                )
            else:
                action = self._execute_action(
                    'clear_magento_cache',
                    'Clear Magento cache',
                    lambda: self._clear_magento_cache()
                )
            result.actions.append(action)

            # Action 2: Clear transients/sessions
            if self.platform == 'woocommerce':
                action = self._execute_action(
                    'clear_transients',
                    'Clear WordPress expired transients',
                    lambda: self._clear_wp_transients()
                )
            else:
                action = self._execute_action(
                    'clear_sessions',
                    'Clear Magento sessions',
                    lambda: self._clear_magento_sessions()
                )
            result.actions.append(action)

            # Action 3: Clear OPcache
            action = self._execute_action(
                'clear_opcache',
                'Reset PHP OPcache',
                lambda: self._clear_opcache()
            )
            result.actions.append(action)

            # Action 4: Optimize database tables
            action = self._execute_action(
                'optimize_tables',
                'Optimize database tables',
                lambda: self._optimize_database_tables()
            )
            result.actions.append(action)

            # Action 5: Restart PHP-FPM
            action = self._execute_action(
                'restart_php_fpm',
                'Gracefully restart PHP-FPM',
                lambda: self._restart_php_fpm()
            )
            result.actions.append(action)

            # Determine overall success
            result.success = all(a.success for a in result.actions)

        except Exception as e:
            result.error = str(e)
            result.success = False
            logger.error(f"optimize_store playbook failed: {e}")

        result.completed_at = datetime.now()
        self._log_intervention(result)
        return result

    def execute_emergency_stabilize(self, reason: str = None) -> PlaybookResult:
        """
        Emergency stabilization:
        - Kill long-running queries (>30s)
        - Clear caches
        - Restart container if needed

        Args:
            reason: Optional reason for the intervention

        Returns:
            PlaybookResult with execution details
        """
        result = PlaybookResult(
            playbook_name='emergency_stabilize',
            customer_id=self.customer_id,
            executed_by=self.admin_user_id,
            started_at=datetime.now()
        )

        try:
            # Action 1: Kill long-running queries
            action = self._execute_action(
                'kill_long_queries',
                'Kill queries running longer than 30 seconds',
                lambda: self._kill_long_running_queries()
            )
            result.actions.append(action)

            # Action 2: Clear application cache (fast path)
            if self.platform == 'woocommerce':
                action = self._execute_action(
                    'flush_cache',
                    'Flush WordPress cache',
                    lambda: self._clear_wp_cache()
                )
            else:
                action = self._execute_action(
                    'flush_cache',
                    'Flush Magento cache',
                    lambda: self._clear_magento_cache()
                )
            result.actions.append(action)

            # Action 3: Clear Redis if available
            action = self._execute_action(
                'flush_redis',
                'Flush Redis cache',
                lambda: self._flush_redis()
            )
            result.actions.append(action)

            # Action 4: Restart PHP-FPM gracefully
            action = self._execute_action(
                'restart_php_fpm',
                'Gracefully restart PHP-FPM',
                lambda: self._restart_php_fpm()
            )
            result.actions.append(action)

            # Action 5: Check if container needs full restart
            # Only restart if PHP-FPM restart failed
            if not result.actions[-1].success:
                action = self._execute_action(
                    'restart_container',
                    'Restart web container',
                    lambda: self._restart_container()
                )
                result.actions.append(action)

            # Success if critical actions worked (kill queries + at least cache or restart)
            critical_success = result.actions[0].success  # kill queries
            stabilized = any(a.success for a in result.actions[1:])  # any of the other actions
            result.success = critical_success or stabilized

        except Exception as e:
            result.error = str(e)
            result.success = False
            logger.error(f"emergency_stabilize playbook failed: {e}")

        result.completed_at = datetime.now()
        self._log_intervention(result)
        return result

    def execute_clear_caches(self, reason: str = None) -> PlaybookResult:
        """
        Clear all caches:
        - Application cache (WP/Magento)
        - Redis cache
        - OPcache

        Args:
            reason: Optional reason for the intervention

        Returns:
            PlaybookResult with execution details
        """
        result = PlaybookResult(
            playbook_name='clear_caches',
            customer_id=self.customer_id,
            executed_by=self.admin_user_id,
            started_at=datetime.now()
        )

        try:
            # Action 1: Clear application cache
            if self.platform == 'woocommerce':
                action = self._execute_action(
                    'clear_wp_cache',
                    'Clear WordPress object cache',
                    lambda: self._clear_wp_cache()
                )
            else:
                action = self._execute_action(
                    'clear_magento_cache',
                    'Clear all Magento caches',
                    lambda: self._clear_magento_cache()
                )
            result.actions.append(action)

            # Action 2: Clear transients/temporary data
            if self.platform == 'woocommerce':
                action = self._execute_action(
                    'clear_transients',
                    'Clear WordPress expired transients',
                    lambda: self._clear_wp_transients()
                )
            else:
                action = self._execute_action(
                    'clear_sessions',
                    'Clear Magento sessions',
                    lambda: self._clear_magento_sessions()
                )
            result.actions.append(action)

            # Action 3: Flush Redis
            action = self._execute_action(
                'flush_redis',
                'Flush Redis cache',
                lambda: self._flush_redis()
            )
            result.actions.append(action)

            # Action 4: Clear OPcache
            action = self._execute_action(
                'clear_opcache',
                'Reset PHP OPcache',
                lambda: self._clear_opcache()
            )
            result.actions.append(action)

            # Action 5: Clear static file cache directories
            action = self._execute_action(
                'clear_static_cache',
                'Clear static file cache directories',
                lambda: self._clear_static_cache()
            )
            result.actions.append(action)

            # Success if at least the main cache clear worked
            result.success = result.actions[0].success

        except Exception as e:
            result.error = str(e)
            result.success = False
            logger.error(f"clear_caches playbook failed: {e}")

        result.completed_at = datetime.now()
        self._log_intervention(result)
        return result

    def execute_restart_services(self, reason: str = None) -> PlaybookResult:
        """
        Restart services:
        - PHP-FPM
        - Redis (if dedicated)

        Args:
            reason: Optional reason for the intervention

        Returns:
            PlaybookResult with execution details
        """
        result = PlaybookResult(
            playbook_name='restart_services',
            customer_id=self.customer_id,
            executed_by=self.admin_user_id,
            started_at=datetime.now()
        )

        try:
            # Action 1: Restart PHP-FPM gracefully
            action = self._execute_action(
                'restart_php_fpm',
                'Gracefully restart PHP-FPM',
                lambda: self._restart_php_fpm()
            )
            result.actions.append(action)

            # Action 2: Restart Redis if customer has dedicated Redis
            action = self._execute_action(
                'restart_redis',
                'Restart Redis service',
                lambda: self._restart_redis()
            )
            result.actions.append(action)

            # Action 3: Restart cron service
            action = self._execute_action(
                'restart_cron',
                'Restart cron service',
                lambda: self._restart_cron()
            )
            result.actions.append(action)

            # Success if PHP-FPM restart worked (primary service)
            result.success = result.actions[0].success

        except Exception as e:
            result.error = str(e)
            result.success = False
            logger.error(f"restart_services playbook failed: {e}")

        result.completed_at = datetime.now()
        self._log_intervention(result)
        return result

    def execute(self, playbook_type: PlaybookType, reason: str = None) -> PlaybookResult:
        """
        Execute a playbook by type.

        Args:
            playbook_type: The type of playbook to execute
            reason: Optional reason for the intervention

        Returns:
            PlaybookResult with execution details
        """
        self._load_customer()

        if playbook_type == PlaybookType.OPTIMIZE_STORE:
            return self.execute_optimize_store(reason)
        elif playbook_type == PlaybookType.EMERGENCY_STABILIZE:
            return self.execute_emergency_stabilize(reason)
        elif playbook_type == PlaybookType.CLEAR_CACHES:
            return self.execute_clear_caches(reason)
        elif playbook_type == PlaybookType.RESTART_SERVICES:
            return self.execute_restart_services(reason)
        else:
            raise ValueError(f"Unknown playbook type: {playbook_type}")

    # =========================================================================
    # Private action implementations
    # =========================================================================

    def _clear_wp_cache(self) -> tuple:
        """Clear WordPress object cache."""
        success, output = self._run_container_command(['wp', 'cache', 'flush'])
        if success:
            return (True, "WordPress cache flushed successfully", output)
        return (False, f"Failed to flush WordPress cache: {output}", output)

    def _clear_wp_transients(self) -> tuple:
        """Clear WordPress expired transients."""
        success, output = self._run_container_command(
            ['wp', 'transient', 'delete', '--expired', '--all']
        )
        if success:
            return (True, "Expired transients cleared", output)
        return (False, f"Failed to clear transients: {output}", output)

    def _clear_magento_cache(self) -> tuple:
        """Clear Magento cache."""
        success, output = self._run_container_command(
            ['php', 'bin/magento', 'cache:flush']
        )
        if success:
            return (True, "Magento cache flushed successfully", output)
        return (False, f"Failed to flush Magento cache: {output}", output)

    def _clear_magento_sessions(self) -> tuple:
        """Clear Magento session files."""
        success, output = self._run_container_command(
            ['rm', '-rf', 'var/session/*']
        )
        if success:
            return (True, "Magento sessions cleared", output)
        return (False, f"Failed to clear sessions: {output}", output)

    def _flush_redis(self) -> tuple:
        """Flush Redis cache."""
        # Try using redis-cli inside the container first
        success, output = self._run_container_command(
            ['redis-cli', 'FLUSHALL'],
            timeout=10
        )
        if success:
            return (True, "Redis cache flushed", output)

        # If redis-cli not in web container, try dedicated redis container
        redis_container = f"customer-{self.customer_id}-redis"
        try:
            result = subprocess.run(
                ['docker', 'exec', redis_container, 'redis-cli', 'FLUSHALL'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return (True, "Redis cache flushed", result.stdout.strip())
            # Redis might not be configured, that's okay
            return (True, "Redis not available (may not be configured)", "")
        except Exception:
            return (True, "Redis not available (may not be configured)", "")

    def _clear_opcache(self) -> tuple:
        """Clear PHP OPcache."""
        # Create a temporary PHP script to reset opcache
        php_code = "<?php if(function_exists('opcache_reset')) { opcache_reset(); echo 'OPcache reset'; } else { echo 'OPcache not available'; } ?>"

        success, output = self._run_container_command(
            ['php', '-r', "if(function_exists('opcache_reset')) { opcache_reset(); echo 'OPcache reset'; } else { echo 'OPcache not available'; }"],
            timeout=10
        )
        if success or 'not available' in output:
            return (True, output if output else "OPcache reset attempted", output)
        return (False, f"Failed to reset OPcache: {output}", output)

    def _clear_static_cache(self) -> tuple:
        """Clear static file cache directories."""
        if self.platform == 'woocommerce':
            dirs = ['wp-content/cache']
        else:
            dirs = ['var/cache', 'var/page_cache', 'var/view_preprocessed', 'generated']

        errors = []
        cleared = []
        for cache_dir in dirs:
            success, output = self._run_container_command(
                ['rm', '-rf', f'{cache_dir}/*'],
                timeout=30
            )
            if success:
                cleared.append(cache_dir)
            else:
                errors.append(f"{cache_dir}: {output}")

        if cleared:
            return (True, f"Cleared: {', '.join(cleared)}", "\n".join(errors) if errors else None)
        return (False, f"Failed to clear cache directories: {'; '.join(errors)}", "\n".join(errors))

    def _optimize_database_tables(self) -> tuple:
        """Optimize database tables."""
        # Get list of tables
        success, tables_output = self._run_db_command(
            "SHOW TABLES"
        )
        if not success:
            return (False, f"Failed to list tables: {tables_output}", tables_output)

        tables = [t.strip() for t in tables_output.split('\n') if t.strip()]
        if not tables:
            return (True, "No tables to optimize", "")

        # Optimize tables (limit to first 20 to prevent timeout)
        tables_to_optimize = tables[:20]
        table_list = ', '.join(f'`{t}`' for t in tables_to_optimize)

        success, output = self._run_db_command(
            f"OPTIMIZE TABLE {table_list}",
            timeout=120  # Allow more time for optimization
        )
        if success:
            return (True, f"Optimized {len(tables_to_optimize)} tables", output)
        return (False, f"Table optimization had issues: {output}", output)

    def _restart_php_fpm(self) -> tuple:
        """Gracefully restart PHP-FPM."""
        # Send USR2 signal for graceful restart
        success, output = self._run_container_command(
            ['pkill', '-USR2', 'php-fpm'],
            timeout=15
        )
        # pkill returns 0 if processes matched, 1 if not
        # We consider it success if we sent the signal
        if success or 'no process' not in output.lower():
            # Give it a moment to restart
            time.sleep(1)
            # Verify PHP-FPM is running
            check_success, check_output = self._run_container_command(
                ['pgrep', '-f', 'php-fpm'],
                timeout=5
            )
            if check_success:
                return (True, "PHP-FPM restarted gracefully", output)
            return (False, "PHP-FPM may not have restarted properly", output)
        return (False, f"Failed to restart PHP-FPM: {output}", output)

    def _restart_redis(self) -> tuple:
        """Restart Redis service."""
        redis_container = f"customer-{self.customer_id}-redis"
        try:
            result = subprocess.run(
                ['docker', 'restart', redis_container],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return (True, "Redis container restarted", result.stdout.strip())
            # Container might not exist
            if 'no such container' in result.stderr.lower():
                return (True, "No dedicated Redis container (shared Redis)", "")
            return (False, f"Failed to restart Redis: {result.stderr}", result.stderr)
        except subprocess.TimeoutExpired:
            return (False, "Redis restart timed out", "")
        except Exception as e:
            return (True, f"Redis not available: {str(e)}", "")

    def _restart_cron(self) -> tuple:
        """Restart cron service in container."""
        success, output = self._run_container_command(
            ['service', 'cron', 'restart'],
            timeout=10
        )
        if success:
            return (True, "Cron service restarted", output)
        # Try alternative method
        success, output = self._run_container_command(
            ['/etc/init.d/cron', 'restart'],
            timeout=10
        )
        if success:
            return (True, "Cron service restarted", output)
        return (True, "Cron service may not be running as a service", output)

    def _restart_container(self) -> tuple:
        """Restart the web container entirely."""
        try:
            result = subprocess.run(
                ['docker', 'restart', self.container_name],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                return (True, "Web container restarted", result.stdout.strip())
            return (False, f"Failed to restart container: {result.stderr}", result.stderr)
        except subprocess.TimeoutExpired:
            return (False, "Container restart timed out", "")
        except Exception as e:
            return (False, f"Container restart failed: {str(e)}", "")

    def _kill_long_running_queries(self) -> tuple:
        """Kill queries running longer than 30 seconds."""
        # Find long-running queries
        find_query = """
            SELECT id, time, info
            FROM information_schema.processlist
            WHERE command = 'Query'
            AND time > 30
            AND user NOT IN ('root', 'system user', 'event_scheduler')
            AND info NOT LIKE '%KILL%'
        """

        success, output = self._run_db_command(find_query)
        if not success:
            return (False, f"Failed to find long queries: {output}", output)

        if not output.strip():
            return (True, "No long-running queries found", "")

        # Parse and kill queries
        killed_count = 0
        errors = []
        for line in output.strip().split('\n'):
            if line.strip():
                parts = line.split('\t')
                if len(parts) >= 1:
                    try:
                        process_id = int(parts[0])
                        kill_success, kill_output = self._run_db_command(f"KILL {process_id}")
                        if kill_success:
                            killed_count += 1
                        else:
                            errors.append(f"PID {process_id}: {kill_output}")
                    except (ValueError, IndexError):
                        pass

        if killed_count > 0:
            return (True, f"Killed {killed_count} long-running queries", "\n".join(errors) if errors else None)
        elif errors:
            return (False, f"Failed to kill queries: {'; '.join(errors)}", "\n".join(errors))
        return (True, "No queries needed to be killed", "")


# =============================================================================
# Public API Functions
# =============================================================================

def execute_admin_playbook(
    customer_id: int,
    admin_user_id: int,
    playbook_name: str,
    reason: str = None
) -> Dict[str, Any]:
    """
    Convenience function to execute a playbook.

    Args:
        customer_id: The customer store to operate on
        admin_user_id: The admin user executing the playbook
        playbook_name: Name of the playbook (from PlaybookType values)
        reason: Optional reason for the intervention

    Returns:
        dict with playbook result details:
        {
            'success': bool,
            'playbook_name': str,
            'actions': [{'name': str, 'success': bool, 'message': str}, ...],
            'error': str or None,
            'duration_ms': int
        }
    """
    try:
        executor = AdminPlaybookExecutor(customer_id, admin_user_id)
        playbook_type = PlaybookType(playbook_name)
        result = executor.execute(playbook_type, reason)

        duration_ms = 0
        if result.completed_at and result.started_at:
            duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)

        return {
            'success': result.success,
            'playbook_name': result.playbook_name,
            'customer_id': result.customer_id,
            'executed_by': result.executed_by,
            'actions': [
                {
                    'name': a.name,
                    'success': a.success,
                    'message': a.message,
                    'duration_ms': a.duration_ms
                }
                for a in result.actions
            ],
            'error': result.error,
            'duration_ms': duration_ms
        }
    except ValueError as e:
        return {
            'success': False,
            'playbook_name': playbook_name,
            'customer_id': customer_id,
            'executed_by': admin_user_id,
            'actions': [],
            'error': str(e),
            'duration_ms': 0
        }
    except Exception as e:
        logger.error(f"Error executing admin playbook {playbook_name}: {e}")
        return {
            'success': False,
            'playbook_name': playbook_name,
            'customer_id': customer_id,
            'executed_by': admin_user_id,
            'actions': [],
            'error': f"Playbook execution failed: {str(e)}",
            'duration_ms': 0
        }


def get_available_playbooks() -> List[Dict[str, str]]:
    """
    Return list of available playbooks with descriptions.

    Returns:
        List of playbook dictionaries:
        [
            {'name': 'optimize_store', 'description': '...'},
            ...
        ]
    """
    return [
        {
            'name': 'optimize_store',
            'description': 'Full optimization pass - clear caches, optimize tables, restart services'
        },
        {
            'name': 'emergency_stabilize',
            'description': 'Emergency stabilization - kill runaway queries, clear caches, restart containers'
        },
        {
            'name': 'clear_caches',
            'description': 'Clear all caches - application, Redis, OPcache, static files'
        },
        {
            'name': 'restart_services',
            'description': 'Restart PHP-FPM, Redis, and cron services'
        },
    ]


def get_intervention_history(
    customer_id: int = None,
    admin_user_id: int = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get admin intervention history.

    Args:
        customer_id: Filter by customer (optional)
        admin_user_id: Filter by admin user (optional)
        limit: Maximum number of records to return

    Returns:
        List of intervention records
    """
    from webapp.models import get_db_connection

    conn = get_db_connection(read_only=True)
    cursor = conn.cursor(dictionary=True)

    try:
        query = """
            SELECT ai.*,
                   c.domain as customer_domain,
                   c.company_name as customer_company,
                   au.email as admin_email
            FROM admin_interventions ai
            JOIN customers c ON ai.customer_id = c.id
            JOIN admin_users au ON ai.admin_user_id = au.id
            WHERE 1=1
        """
        params = []

        if customer_id:
            query += " AND ai.customer_id = %s"
            params.append(customer_id)

        if admin_user_id:
            query += " AND ai.admin_user_id = %s"
            params.append(admin_user_id)

        query += " ORDER BY ai.executed_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        interventions = []
        for row in rows:
            result_data = row.get('result')
            if result_data and isinstance(result_data, str):
                try:
                    result_data = json.loads(result_data)
                except json.JSONDecodeError:
                    result_data = {}

            interventions.append({
                'id': row['id'],
                'customer_id': row['customer_id'],
                'customer_domain': row.get('customer_domain'),
                'customer_company': row.get('customer_company'),
                'admin_user_id': row['admin_user_id'],
                'admin_email': row.get('admin_email'),
                'playbook_name': row['playbook_name'],
                'executed_at': row['executed_at'].isoformat() if row.get('executed_at') else None,
                'reason': row.get('reason'),
                'result': result_data or {}
            })

        return interventions

    except Exception as e:
        logger.error(f"Failed to get intervention history: {e}")
        return []
    finally:
        cursor.close()
        conn.close()
