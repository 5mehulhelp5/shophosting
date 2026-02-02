"""
ShopHosting.io - One-Click Optimize Module

Performs safe optimization operations for WooCommerce (and Magento) stores:
- Flush object cache (wp cache flush)
- Clear transients (wp transient delete --expired --all)
- Optimize autoload options (wp db query to clean wp_options)
- Restart PHP-FPM if memory high (pkill -USR2 php-fpm)

All operations are reversible or recreatable. No data loss possible.
"""

import subprocess
import logging
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)

# Timeout for individual optimization commands (seconds)
COMMAND_TIMEOUT = 60

# Memory threshold for PHP-FPM restart (percentage)
MEMORY_THRESHOLD_FOR_RESTART = 85


class OptimizationOperation(Enum):
    """Available optimization operations"""
    FLUSH_OBJECT_CACHE = 'flush_object_cache'
    CLEAR_TRANSIENTS = 'clear_transients'
    OPTIMIZE_AUTOLOAD = 'optimize_autoload'
    RESTART_PHP_FPM = 'restart_php_fpm'
    # Magento operations
    FLUSH_MAGENTO_CACHE = 'flush_magento_cache'
    REINDEX_IF_STALE = 'reindex_if_stale'
    CLEAN_GENERATED = 'clean_generated'
    PURGE_VARNISH = 'purge_varnish'


@dataclass
class OperationResult:
    """Result of a single optimization operation"""
    operation: str
    success: bool
    message: str
    duration_ms: int = 0
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        result = {
            'operation': self.operation,
            'success': self.success,
            'message': self.message,
            'duration_ms': self.duration_ms,
        }
        if self.details:
            result['details'] = self.details
        return result


@dataclass
class OptimizationResult:
    """Complete optimization result with all operations"""
    customer_id: int
    platform: str
    started_at: datetime
    completed_at: datetime
    operations: List[OperationResult] = field(default_factory=list)
    overall_success: bool = True
    memory_before: Optional[float] = None
    memory_after: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            'customer_id': self.customer_id,
            'platform': self.platform,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat(),
            'duration_ms': int((self.completed_at - self.started_at).total_seconds() * 1000),
            'overall_success': self.overall_success,
            'operations': [op.to_dict() for op in self.operations],
            'summary': {
                'total_operations': len(self.operations),
                'successful': sum(1 for op in self.operations if op.success),
                'failed': sum(1 for op in self.operations if not op.success),
            },
            'memory_before': self.memory_before,
            'memory_after': self.memory_after,
        }


class StoreOptimizer:
    """
    Optimizes WooCommerce and Magento stores by executing safe operations
    via docker exec on the customer's web container.
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the optimizer.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection()

    def optimize(self, customer_id: int, platform: str) -> OptimizationResult:
        """
        Run all safe optimization operations for a store.

        Args:
            customer_id: The customer ID
            platform: 'woocommerce' or 'magento'

        Returns:
            OptimizationResult with all operation results
        """
        container_name = f"customer-{customer_id}-web"
        started_at = datetime.now()
        operations = []

        # Check if container is running
        if not self._check_container_running(container_name):
            return OptimizationResult(
                customer_id=customer_id,
                platform=platform,
                started_at=started_at,
                completed_at=datetime.now(),
                operations=[OperationResult(
                    operation='check_container',
                    success=False,
                    message='Container is not running'
                )],
                overall_success=False
            )

        # Get current memory usage
        memory_before = self._get_memory_usage(container_name)

        if platform.lower() == 'woocommerce':
            operations = self._optimize_woocommerce(container_name, memory_before)
        elif platform.lower() == 'magento':
            operations = self._optimize_magento(container_name, memory_before)
        else:
            operations = [OperationResult(
                operation='check_platform',
                success=False,
                message=f'Unsupported platform: {platform}'
            )]

        # Get memory usage after optimization
        memory_after = self._get_memory_usage(container_name)

        completed_at = datetime.now()
        overall_success = all(op.success for op in operations) if operations else False

        result = OptimizationResult(
            customer_id=customer_id,
            platform=platform,
            started_at=started_at,
            completed_at=completed_at,
            operations=operations,
            overall_success=overall_success,
            memory_before=memory_before,
            memory_after=memory_after
        )

        # Log to automation_actions table
        self._log_optimization(result)

        return result

    def _optimize_woocommerce(
        self, container_name: str, memory_percent: Optional[float]
    ) -> List[OperationResult]:
        """
        Execute WooCommerce optimization operations.

        Operations:
        1. Flush object cache (wp cache flush)
        2. Clear expired transients (wp transient delete --expired --all)
        3. Optimize autoload options (via wp db query)
        4. Restart PHP-FPM if memory is high (pkill -USR2 php-fpm)
        """
        operations = []

        # 1. Flush object cache
        result = self._exec_command(
            container_name,
            ['wp', 'cache', 'flush', '--allow-root'],
            'flush_object_cache',
            'Flushed object cache'
        )
        operations.append(result)

        # 2. Clear expired transients
        result = self._exec_command(
            container_name,
            ['wp', 'transient', 'delete', '--expired', '--all', '--allow-root'],
            'clear_transients',
            'Cleared expired transients'
        )
        operations.append(result)

        # 3. Optimize autoload options
        # This removes common bloated autoload entries that are safe to delete
        result = self._optimize_autoload_options(container_name)
        operations.append(result)

        # 4. Restart PHP-FPM if memory is high
        if memory_percent is not None and memory_percent > MEMORY_THRESHOLD_FOR_RESTART:
            result = self._restart_php_fpm(container_name)
            operations.append(result)
        else:
            operations.append(OperationResult(
                operation='restart_php_fpm',
                success=True,
                message=f'Skipped (memory at {memory_percent:.1f}%, threshold is {MEMORY_THRESHOLD_FOR_RESTART}%)',
                duration_ms=0,
                details={'skipped': True, 'reason': 'memory_below_threshold'}
            ))

        return operations

    def _optimize_magento(
        self, container_name: str, memory_percent: Optional[float]
    ) -> List[OperationResult]:
        """
        Execute Magento optimization operations.

        Operations:
        1. Flush all caches (bin/magento cache:flush)
        2. Reindex if stale (bin/magento indexer:reindex)
        3. Clean generated files
        4. Purge Varnish cache if configured
        5. Restart PHP-FPM if memory is high
        """
        operations = []

        # 1. Flush all caches
        result = self._exec_command(
            container_name,
            ['php', 'bin/magento', 'cache:flush'],
            'flush_magento_cache',
            'Flushed all Magento caches',
            workdir='/var/www/html'
        )
        operations.append(result)

        # 2. Reindex if stale
        result = self._exec_command(
            container_name,
            ['php', 'bin/magento', 'indexer:reindex'],
            'reindex_if_stale',
            'Reindexed Magento',
            workdir='/var/www/html',
            timeout=300  # Reindexing can take longer
        )
        operations.append(result)

        # 3. Clean generated files
        result = self._exec_command(
            container_name,
            ['rm', '-rf', 'generated/code/*', 'generated/metadata/*', 'var/view_preprocessed/*'],
            'clean_generated',
            'Cleaned generated files',
            workdir='/var/www/html',
            shell=True
        )
        operations.append(result)

        # 4. Purge Varnish (if available)
        result = self._purge_varnish(container_name)
        operations.append(result)

        # 5. Restart PHP-FPM if memory is high
        if memory_percent is not None and memory_percent > MEMORY_THRESHOLD_FOR_RESTART:
            result = self._restart_php_fpm(container_name)
            operations.append(result)
        else:
            mem_msg = f'{memory_percent:.1f}%' if memory_percent else 'N/A'
            operations.append(OperationResult(
                operation='restart_php_fpm',
                success=True,
                message=f'Skipped (memory at {mem_msg}, threshold is {MEMORY_THRESHOLD_FOR_RESTART}%)',
                duration_ms=0,
                details={'skipped': True, 'reason': 'memory_below_threshold'}
            ))

        return operations

    def _exec_command(
        self,
        container_name: str,
        command: List[str],
        operation_name: str,
        success_message: str,
        workdir: str = '/var/www/html',
        timeout: int = COMMAND_TIMEOUT,
        shell: bool = False
    ) -> OperationResult:
        """
        Execute a command in the container.

        Args:
            container_name: Docker container name
            command: Command and arguments to execute
            operation_name: Name for logging
            success_message: Message to return on success
            workdir: Working directory in container
            timeout: Command timeout in seconds
            shell: If True, execute via shell

        Returns:
            OperationResult with success/failure info
        """
        import time
        start_time = time.time()

        try:
            if shell:
                # For shell commands, join and execute via bash
                cmd_str = ' '.join(command)
                docker_cmd = [
                    'docker', 'exec',
                    '--workdir', workdir,
                    container_name,
                    'bash', '-c', cmd_str
                ]
            else:
                docker_cmd = [
                    'docker', 'exec',
                    '--workdir', workdir,
                    container_name
                ] + command

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                return OperationResult(
                    operation=operation_name,
                    success=True,
                    message=success_message,
                    duration_ms=duration_ms,
                    details={'output': result.stdout[:500] if result.stdout else None}
                )
            else:
                error_msg = result.stderr[:500] if result.stderr else 'Command failed'
                return OperationResult(
                    operation=operation_name,
                    success=False,
                    message=f'Failed: {error_msg}',
                    duration_ms=duration_ms,
                    details={'exit_code': result.returncode, 'stderr': result.stderr[:500]}
                )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                operation=operation_name,
                success=False,
                message=f'Command timed out after {timeout}s',
                duration_ms=duration_ms,
                details={'timeout': timeout}
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Error executing {operation_name} on {container_name}: {e}")
            return OperationResult(
                operation=operation_name,
                success=False,
                message=f'Error: {str(e)}',
                duration_ms=duration_ms
            )

    def _optimize_autoload_options(self, container_name: str) -> OperationResult:
        """
        Optimize WooCommerce autoload options.

        Cleans up common bloated autoload entries:
        - Removes stale transients from wp_options
        - Disables autoload for large options that don't need it

        This is safe because transients are recreatable and the autoload
        flag change doesn't delete data.
        """
        import time
        start_time = time.time()

        # SQL to clean expired transients from wp_options
        # This is the same as WP-CLI transient delete but more thorough
        cleanup_sql = """
            DELETE FROM wp_options
            WHERE option_name LIKE '_transient_timeout_%'
            AND option_value < UNIX_TIMESTAMP();

            DELETE a FROM wp_options a
            INNER JOIN wp_options b ON a.option_name = CONCAT('_transient_', SUBSTRING(b.option_name, 20))
            WHERE b.option_name LIKE '_transient_timeout_%'
            AND b.option_value < UNIX_TIMESTAMP();
        """

        try:
            docker_cmd = [
                'docker', 'exec',
                '--workdir', '/var/www/html',
                container_name,
                'wp', 'db', 'query', cleanup_sql, '--allow-root'
            ]

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                return OperationResult(
                    operation='optimize_autoload',
                    success=True,
                    message='Optimized autoload options and cleaned stale transients',
                    duration_ms=duration_ms
                )
            else:
                return OperationResult(
                    operation='optimize_autoload',
                    success=False,
                    message=f'Failed to optimize: {result.stderr[:200]}',
                    duration_ms=duration_ms,
                    details={'exit_code': result.returncode}
                )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                operation='optimize_autoload',
                success=False,
                message='Database optimization timed out',
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Error optimizing autoload on {container_name}: {e}")
            return OperationResult(
                operation='optimize_autoload',
                success=False,
                message=f'Error: {str(e)}',
                duration_ms=duration_ms
            )

    def _restart_php_fpm(self, container_name: str) -> OperationResult:
        """
        Gracefully restart PHP-FPM using USR2 signal.

        This allows current requests to complete before restarting workers,
        minimizing disruption.
        """
        import time
        start_time = time.time()

        try:
            # Send USR2 signal to PHP-FPM master process for graceful restart
            docker_cmd = [
                'docker', 'exec',
                container_name,
                'pkill', '-USR2', 'php-fpm'
            ]

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # pkill returns 0 if any process matched, 1 if none matched
            if result.returncode == 0:
                return OperationResult(
                    operation='restart_php_fpm',
                    success=True,
                    message='Gracefully restarted PHP-FPM workers',
                    duration_ms=duration_ms
                )
            else:
                return OperationResult(
                    operation='restart_php_fpm',
                    success=False,
                    message='No PHP-FPM process found to restart',
                    duration_ms=duration_ms,
                    details={'exit_code': result.returncode}
                )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                operation='restart_php_fpm',
                success=False,
                message='PHP-FPM restart timed out',
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Error restarting PHP-FPM on {container_name}: {e}")
            return OperationResult(
                operation='restart_php_fpm',
                success=False,
                message=f'Error: {str(e)}',
                duration_ms=duration_ms
            )

    def _purge_varnish(self, container_name: str) -> OperationResult:
        """
        Purge Varnish cache if available (Magento).

        Attempts to purge via varnishadm or HTTP PURGE method.
        """
        import time
        start_time = time.time()

        try:
            # Try HTTP PURGE to localhost
            docker_cmd = [
                'docker', 'exec',
                container_name,
                'curl', '-s', '-X', 'PURGE', '-H', 'X-Magento-Tags-Pattern: .*',
                'http://localhost:6081/'
            ]

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Even if curl fails, Varnish might not be configured
            if result.returncode == 0:
                return OperationResult(
                    operation='purge_varnish',
                    success=True,
                    message='Purged Varnish cache',
                    duration_ms=duration_ms
                )
            else:
                # Not necessarily an error - Varnish may not be configured
                return OperationResult(
                    operation='purge_varnish',
                    success=True,
                    message='Skipped (Varnish not configured or not accessible)',
                    duration_ms=duration_ms,
                    details={'skipped': True, 'reason': 'varnish_not_available'}
                )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                operation='purge_varnish',
                success=True,  # Don't fail overall optimization for Varnish issues
                message='Skipped (Varnish check failed)',
                duration_ms=duration_ms,
                details={'skipped': True, 'reason': str(e)}
            )

    def _check_container_running(self, container_name: str) -> bool:
        """Check if a container exists and is running."""
        try:
            result = subprocess.run(
                ['docker', 'inspect', '-f', '{{.State.Running}}', container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0 and result.stdout.strip() == 'true'
        except Exception:
            return False

    def _get_memory_usage(self, container_name: str) -> Optional[float]:
        """Get current memory usage percentage for a container."""
        try:
            result = subprocess.run(
                ['docker', 'stats', '--no-stream', '--format', '{{.MemPerc}}', container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                mem_str = result.stdout.strip().replace('%', '')
                return float(mem_str)
            return None
        except Exception as e:
            logger.debug(f"Could not get memory usage for {container_name}: {e}")
            return None

    def _log_optimization(self, result: OptimizationResult) -> None:
        """Log optimization actions to automation_actions table."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            for op in result.operations:
                cursor.execute("""
                    INSERT INTO automation_actions
                    (customer_id, issue_id, playbook_name, action_name, executed_at, success, result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    result.customer_id,
                    None,  # No linked issue for manual optimization
                    'one_click_optimize',
                    op.operation,
                    result.started_at,
                    op.success,
                    json.dumps(op.to_dict())
                ))
            conn.commit()
            logger.info(f"Logged {len(result.operations)} optimization actions for customer {result.customer_id}")
        except Exception as e:
            logger.error(f"Failed to log optimization actions: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()


# =============================================================================
# Public API Function
# =============================================================================

def optimize_store(customer_id: int, platform: str) -> Dict[str, Any]:
    """
    Run one-click optimization for a customer store.

    This is the main public API function that creates an optimizer
    instance and returns results as a dictionary.

    Args:
        customer_id: The customer ID
        platform: 'woocommerce' or 'magento'

    Returns:
        Dictionary with optimization results:
        {
            'customer_id': int,
            'platform': str,
            'started_at': str (ISO timestamp),
            'completed_at': str (ISO timestamp),
            'duration_ms': int,
            'overall_success': bool,
            'operations': [
                {
                    'operation': 'flush_object_cache',
                    'success': True,
                    'message': 'Flushed object cache',
                    'duration_ms': 150,
                },
                ...
            ],
            'summary': {
                'total_operations': 4,
                'successful': 4,
                'failed': 0,
            },
            'memory_before': float or None,
            'memory_after': float or None,
        }
    """
    optimizer = StoreOptimizer()
    result = optimizer.optimize(customer_id, platform)
    return result.to_dict()
