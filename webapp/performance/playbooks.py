"""
ShopHosting.io - Auto-Fix Playbooks Module

Defines automated remediation playbooks that execute when issues are detected.
Each playbook maps to an issue type and contains a series of actions to resolve it.

Playbooks:
- high_memory: Clear caches, transients, restart PHP-FPM
- slow_queries: Log queries, kill long-running, generate recommendations
- disk_filling: Clear old logs, cache directories, old backups

Safety levels:
- Level 2 (Safe Auto-Fix): Only reversible/safe actions
- Level 3 (Full Auto): All actions including aggressive ones
"""

import subprocess
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)

# Command timeout
COMMAND_TIMEOUT = 60


class ActionSafety(Enum):
    """Safety classification for playbook actions"""
    SAFE = 'safe'           # Reversible, no data loss
    MODERATE = 'moderate'   # Not reversible but no data loss
    AGGRESSIVE = 'aggressive'  # May cause brief downtime or data cleanup


@dataclass
class PlaybookAction:
    """A single action within a playbook"""
    name: str
    description: str
    command: Optional[List[str]] = None  # Docker exec command
    function: Optional[str] = None  # Python function to call
    safety: ActionSafety = ActionSafety.SAFE
    condition: Optional[str] = None  # Condition to check before running
    platform: Optional[str] = None  # 'woocommerce', 'magento', or None for both


@dataclass
class ActionResult:
    """Result of executing a playbook action"""
    action_name: str
    success: bool
    message: str
    duration_ms: int = 0
    skipped: bool = False
    skip_reason: Optional[str] = None
    output: Optional[str] = None


@dataclass
class PlaybookResult:
    """Result of executing a complete playbook"""
    playbook_name: str
    issue_type: str
    customer_id: int
    success: bool
    actions: List[ActionResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    total_duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'playbook_name': self.playbook_name,
            'issue_type': self.issue_type,
            'customer_id': self.customer_id,
            'success': self.success,
            'actions': [
                {
                    'name': a.action_name,
                    'success': a.success,
                    'message': a.message,
                    'duration_ms': a.duration_ms,
                    'skipped': a.skipped,
                    'skip_reason': a.skip_reason
                }
                for a in self.actions
            ],
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_duration_ms': self.total_duration_ms
        }


# =============================================================================
# Playbook Definitions
# =============================================================================

HIGH_MEMORY_PLAYBOOK = {
    'name': 'High Memory Usage',
    'issue_types': ['high_memory', 'critical_memory'],
    'description': 'Clears caches and restarts services to reduce memory usage',
    'actions': [
        PlaybookAction(
            name='flush_object_cache',
            description='Flush WordPress object cache',
            command=['wp', 'cache', 'flush'],
            safety=ActionSafety.SAFE,
            platform='woocommerce'
        ),
        PlaybookAction(
            name='flush_magento_cache',
            description='Flush all Magento caches',
            command=['php', 'bin/magento', 'cache:flush'],
            safety=ActionSafety.SAFE,
            platform='magento'
        ),
        PlaybookAction(
            name='clear_transients',
            description='Clear expired WordPress transients',
            command=['wp', 'transient', 'delete', '--expired', '--all'],
            safety=ActionSafety.SAFE,
            platform='woocommerce'
        ),
        PlaybookAction(
            name='restart_php_fpm',
            description='Gracefully restart PHP-FPM',
            command=['pkill', '-USR2', 'php-fpm'],
            safety=ActionSafety.MODERATE,
            condition='memory_still_high'  # Only if still high after cache clear
        ),
    ]
}

SLOW_QUERIES_PLAYBOOK = {
    'name': 'Slow Query Remediation',
    'issue_types': ['slow_queries', 'query_explosion'],
    'description': 'Handles slow database queries by logging and killing long-running ones',
    'actions': [
        PlaybookAction(
            name='capture_slow_queries',
            description='Log current slow queries for analysis',
            function='capture_slow_queries',
            safety=ActionSafety.SAFE
        ),
        PlaybookAction(
            name='kill_long_queries',
            description='Kill queries running longer than 30 seconds',
            function='kill_long_running_queries',
            safety=ActionSafety.MODERATE,
            condition='has_long_queries'
        ),
    ]
}

DISK_FILLING_PLAYBOOK = {
    'name': 'Disk Space Recovery',
    'issue_types': ['disk_filling', 'disk_critical'],
    'description': 'Recovers disk space by clearing logs and caches',
    'actions': [
        PlaybookAction(
            name='clear_old_logs',
            description='Remove log files older than 7 days',
            command=['find', '/var/log', '-name', '*.log.*', '-mtime', '+7', '-delete'],
            safety=ActionSafety.MODERATE
        ),
        PlaybookAction(
            name='clear_cache_dirs',
            description='Clear application cache directories',
            function='clear_cache_directories',
            safety=ActionSafety.SAFE
        ),
        PlaybookAction(
            name='clear_old_backups',
            description='Remove old local backup files',
            function='clear_old_local_backups',
            safety=ActionSafety.AGGRESSIVE,
            condition='disk_critical'  # Only if >95%
        ),
    ]
}

# Map issue types to playbooks
PLAYBOOKS = {
    'high_memory': HIGH_MEMORY_PLAYBOOK,
    'critical_memory': HIGH_MEMORY_PLAYBOOK,
    'slow_queries': SLOW_QUERIES_PLAYBOOK,
    'query_explosion': SLOW_QUERIES_PLAYBOOK,
    'disk_filling': DISK_FILLING_PLAYBOOK,
    'disk_critical': DISK_FILLING_PLAYBOOK,
}


class PlaybookExecutor:
    """
    Executes playbooks to remediate detected issues.

    Respects customer automation_level:
    - Level 1: No execution (notify only)
    - Level 2: Execute SAFE and MODERATE actions
    - Level 3: Execute all actions including AGGRESSIVE
    """

    def __init__(self, customer_id: int, container_name: str, platform: str,
                 automation_level: int = 2):
        self.customer_id = customer_id
        self.container_name = container_name
        self.platform = platform.lower()
        self.automation_level = automation_level
        self.context: Dict[str, Any] = {}  # Runtime context for conditions

    def execute_playbook(self, issue_type: str, issue_details: Dict[str, Any] = None) -> PlaybookResult:
        """
        Execute the playbook for a given issue type.

        Args:
            issue_type: The type of issue detected (e.g., 'high_memory')
            issue_details: Additional details about the issue

        Returns:
            PlaybookResult with execution details
        """
        playbook = PLAYBOOKS.get(issue_type)
        if not playbook:
            return PlaybookResult(
                playbook_name='unknown',
                issue_type=issue_type,
                customer_id=self.customer_id,
                success=False,
                actions=[ActionResult(
                    action_name='lookup',
                    success=False,
                    message=f'No playbook defined for issue type: {issue_type}'
                )]
            )

        # Store issue details in context for condition evaluation
        self.context = issue_details or {}
        self.context['issue_type'] = issue_type

        result = PlaybookResult(
            playbook_name=playbook['name'],
            issue_type=issue_type,
            customer_id=self.customer_id,
            success=True
        )

        start_time = time.time()

        for action in playbook['actions']:
            # Skip if platform doesn't match
            if action.platform and action.platform != self.platform:
                continue

            # Check if action safety level is allowed
            if not self._is_action_allowed(action):
                result.actions.append(ActionResult(
                    action_name=action.name,
                    success=True,
                    message=f'Skipped: {action.safety.value} action not allowed at automation level {self.automation_level}',
                    skipped=True,
                    skip_reason='automation_level'
                ))
                continue

            # Check condition if specified
            if action.condition and not self._check_condition(action.condition):
                result.actions.append(ActionResult(
                    action_name=action.name,
                    success=True,
                    message=f'Skipped: condition "{action.condition}" not met',
                    skipped=True,
                    skip_reason='condition_not_met'
                ))
                continue

            # Execute the action
            action_result = self._execute_action(action)
            result.actions.append(action_result)

            # If a critical action fails, stop the playbook
            if not action_result.success and action.safety != ActionSafety.AGGRESSIVE:
                result.success = False
                logger.warning(f"Playbook {playbook['name']} stopped due to action failure: {action.name}")
                break

        result.completed_at = datetime.now()
        result.total_duration_ms = int((time.time() - start_time) * 1000)

        # Update overall success based on actions
        if not any(a.success and not a.skipped for a in result.actions):
            result.success = False

        return result

    def _is_action_allowed(self, action: PlaybookAction) -> bool:
        """Check if action is allowed based on automation level"""
        if self.automation_level >= 3:
            return True  # Full auto - all actions allowed
        if self.automation_level >= 2:
            return action.safety in (ActionSafety.SAFE, ActionSafety.MODERATE)
        return False  # Level 1 - no actions

    def _check_condition(self, condition: str) -> bool:
        """Evaluate a condition string against current context"""
        if condition == 'memory_still_high':
            # Check if memory is still above threshold after cache clear
            return self.context.get('memory_percent', 0) > 85
        if condition == 'has_long_queries':
            # Check if there are queries running > 30s
            return self.context.get('long_query_count', 0) > 0
        if condition == 'disk_critical':
            # Check if disk is critically full (>95%)
            return self.context.get('disk_percent', 0) > 95
        # Default: condition met
        return True

    def _execute_action(self, action: PlaybookAction) -> ActionResult:
        """Execute a single playbook action"""
        start_time = time.time()

        try:
            if action.command:
                return self._execute_command(action, start_time)
            elif action.function:
                return self._execute_function(action, start_time)
            else:
                return ActionResult(
                    action_name=action.name,
                    success=False,
                    message='No command or function specified',
                    duration_ms=0
                )
        except Exception as e:
            logger.error(f"Error executing action {action.name}: {e}")
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Error: {str(e)}',
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def _execute_command(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Execute a docker exec command"""
        docker_cmd = [
            'docker', 'exec',
            '-w', '/var/www/html',
            self.container_name
        ] + action.command

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                return ActionResult(
                    action_name=action.name,
                    success=True,
                    message=action.description,
                    duration_ms=duration_ms,
                    output=result.stdout[:500] if result.stdout else None
                )
            else:
                return ActionResult(
                    action_name=action.name,
                    success=False,
                    message=f'Command failed: {result.stderr[:200] if result.stderr else "Unknown error"}',
                    duration_ms=duration_ms,
                    output=result.stderr[:500] if result.stderr else None
                )

        except subprocess.TimeoutExpired:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Command timed out after {COMMAND_TIMEOUT}s',
                duration_ms=COMMAND_TIMEOUT * 1000
            )

    def _execute_function(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Execute a Python function action"""
        func_name = action.function

        if func_name == 'capture_slow_queries':
            return self._capture_slow_queries(action, start_time)
        elif func_name == 'kill_long_running_queries':
            return self._kill_long_running_queries(action, start_time)
        elif func_name == 'clear_cache_directories':
            return self._clear_cache_directories(action, start_time)
        elif func_name == 'clear_old_local_backups':
            return self._clear_old_local_backups(action, start_time)
        else:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Unknown function: {func_name}',
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def _capture_slow_queries(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Capture current slow queries to the slow_queries table"""
        # This integrates with the slow_queries module
        try:
            from .slow_queries import SlowQueryViewer
            viewer = SlowQueryViewer(self.customer_id)
            # The viewer already logs queries when fetching
            queries = viewer.get_slow_queries(limit=50)

            duration_ms = int((time.time() - start_time) * 1000)
            return ActionResult(
                action_name=action.name,
                success=True,
                message=f'Captured {len(queries)} slow queries for analysis',
                duration_ms=duration_ms
            )
        except Exception as e:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Failed to capture slow queries: {e}',
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def _kill_long_running_queries(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Kill queries running longer than 30 seconds"""
        # Query for long-running processes and kill them
        kill_query = """
            SELECT CONCAT('KILL ', id, ';')
            FROM information_schema.processlist
            WHERE command = 'Query'
            AND time > 30
            AND user NOT IN ('root', 'system user')
        """

        try:
            db_container = f"customer-{self.customer_id}-db"
            result = subprocess.run(
                ['docker', 'exec', db_container, 'mysql', '-N', '-B', '-e', kill_query],
                capture_output=True,
                text=True,
                timeout=10
            )

            killed_count = 0
            if result.returncode == 0 and result.stdout.strip():
                kill_commands = result.stdout.strip().split('\n')
                for kill_cmd in kill_commands:
                    subprocess.run(
                        ['docker', 'exec', db_container, 'mysql', '-e', kill_cmd],
                        capture_output=True,
                        timeout=5
                    )
                    killed_count += 1

            duration_ms = int((time.time() - start_time) * 1000)
            return ActionResult(
                action_name=action.name,
                success=True,
                message=f'Killed {killed_count} long-running queries',
                duration_ms=duration_ms
            )
        except Exception as e:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Failed to kill queries: {e}',
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def _clear_cache_directories(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Clear application cache directories based on platform"""
        if self.platform == 'woocommerce':
            dirs = ['wp-content/cache/*']
        else:  # magento
            dirs = ['var/cache/*', 'var/page_cache/*', 'var/view_preprocessed/*']

        try:
            for cache_dir in dirs:
                subprocess.run(
                    ['docker', 'exec', '-w', '/var/www/html', self.container_name,
                     'rm', '-rf', cache_dir],
                    capture_output=True,
                    timeout=30
                )

            duration_ms = int((time.time() - start_time) * 1000)
            return ActionResult(
                action_name=action.name,
                success=True,
                message=f'Cleared cache directories',
                duration_ms=duration_ms
            )
        except Exception as e:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Failed to clear caches: {e}',
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def _clear_old_local_backups(self, action: PlaybookAction, start_time: float) -> ActionResult:
        """Clear old local backup files, keeping only the most recent"""
        backup_dir = f"/var/customers/customer-{self.customer_id}/backups"

        try:
            # Find and delete old backups, keeping newest
            result = subprocess.run(
                ['find', backup_dir, '-name', '*.tar.gz', '-mtime', '+7', '-delete'],
                capture_output=True,
                text=True,
                timeout=60
            )

            duration_ms = int((time.time() - start_time) * 1000)
            return ActionResult(
                action_name=action.name,
                success=True,
                message='Cleared old backup files (>7 days)',
                duration_ms=duration_ms
            )
        except Exception as e:
            return ActionResult(
                action_name=action.name,
                success=False,
                message=f'Failed to clear backups: {e}',
                duration_ms=int((time.time() - start_time) * 1000)
            )


# =============================================================================
# Public API
# =============================================================================

def get_playbook_for_issue(issue_type: str) -> Optional[Dict[str, Any]]:
    """Get the playbook definition for an issue type"""
    return PLAYBOOKS.get(issue_type)


def execute_playbook_for_issue(
    customer_id: int,
    container_name: str,
    platform: str,
    automation_level: int,
    issue_type: str,
    issue_details: Dict[str, Any] = None
) -> PlaybookResult:
    """
    Execute the appropriate playbook for a detected issue.

    Args:
        customer_id: Customer ID
        container_name: Docker container name (e.g., customer-1-web)
        platform: 'woocommerce' or 'magento'
        automation_level: Customer's automation preference (1-3)
        issue_type: Type of issue detected
        issue_details: Additional context about the issue

    Returns:
        PlaybookResult with execution details
    """
    if automation_level < 2:
        return PlaybookResult(
            playbook_name='none',
            issue_type=issue_type,
            customer_id=customer_id,
            success=True,
            actions=[ActionResult(
                action_name='check_level',
                success=True,
                message='Automation level 1: Notify only, no actions taken',
                skipped=True,
                skip_reason='automation_level'
            )]
        )

    executor = PlaybookExecutor(
        customer_id=customer_id,
        container_name=container_name,
        platform=platform,
        automation_level=automation_level
    )

    return executor.execute_playbook(issue_type, issue_details)


def list_available_playbooks() -> List[Dict[str, Any]]:
    """List all available playbooks with their descriptions"""
    seen = set()
    playbooks = []

    for issue_type, playbook in PLAYBOOKS.items():
        if playbook['name'] not in seen:
            seen.add(playbook['name'])
            playbooks.append({
                'name': playbook['name'],
                'description': playbook['description'],
                'issue_types': playbook['issue_types'],
                'action_count': len(playbook['actions'])
            })

    return playbooks
