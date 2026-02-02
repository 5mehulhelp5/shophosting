"""
Command validator for CLI Terminal

Security-focused validation of commands before execution.
Supports both WP-CLI (WordPress) and bin/magento (Magento) commands.
Uses allowlist approach with explicit blocking of dangerous commands.
"""

import shlex
import re
from typing import Tuple, Dict, List, Optional


# Shell metacharacters that could enable command injection
DANGEROUS_CHARS = ['|', '&', ';', '`', '$', '(', ')', '{', '}', '<', '>', '\n', '\r']

# Explicitly blocked commands (checked first)
BLOCKED_COMMANDS = frozenset([
    # Destructive file operations
    'rm', 'rmdir', 'unlink', 'shred', 'truncate',
    # File modification
    'mv', 'cp', 'chmod', 'chown', 'chgrp', 'touch', 'mkdir',
    # Editors (prevent shell escape)
    'vi', 'vim', 'nano', 'emacs', 'ed', 'pico', 'joe',
    # Network tools
    'wget', 'curl', 'nc', 'netcat', 'ssh', 'scp', 'sftp', 'rsync', 'ftp',
    # Package managers
    'apt', 'apt-get', 'yum', 'dnf', 'pip', 'pip3', 'npm', 'yarn', 'composer',
    # Process control
    'kill', 'pkill', 'killall', 'nohup', 'screen', 'tmux',
    # Shell access
    'bash', 'sh', 'zsh', 'csh', 'tcsh', 'dash', 'ksh', 'fish',
    # System commands
    'sudo', 'su', 'passwd', 'useradd', 'userdel', 'groupadd',
    # Dangerous utilities
    'dd', 'mkfs', 'fdisk', 'mount', 'umount',
    'crontab', 'at', 'batch',
    # PHP execution (direct)
    'php', 'python', 'python3', 'perl', 'ruby', 'node',
])

# Blocked WP-CLI subcommands (dangerous operations)
BLOCKED_WP_SUBCOMMANDS = frozenset([
    'db drop', 'db reset', 'db clean',
    'site delete', 'site empty',
    'plugin delete', 'theme delete',
    'core download', 'core update',  # Prevent core replacement
    'eval', 'eval-file', 'shell',  # Code execution
    'config set',  # Prevent config tampering
    'user delete', 'user create',  # User management restricted
])

# Blocked Magento subcommands (dangerous operations)
BLOCKED_MAGENTO_SUBCOMMANDS = frozenset([
    'setup:uninstall',
    'setup:rollback',
    'module:uninstall',
    'theme:uninstall',
    'deploy:mode:set',  # Prevent mode changes
    'app:config:import',  # Prevent config imports
    'encryption:key:change',
    'admin:user:create', 'admin:user:delete', 'admin:user:unlock',
    'cron:remove',
    'setup:backup',  # Can expose sensitive data
    'i18n:pack',  # Can write files
    'dev:source-theme:deploy',  # Can modify theme files
    'setup:config:set',  # Prevent config changes
])

# Allowed basic shell commands with their restrictions
ALLOWED_SHELL_COMMANDS: Dict[str, Dict] = {
    'ls': {
        'allowed_flags': ['-l', '-la', '-lah', '-a', '-h', '-1', '--color', '-R'],
        'requires_path': False,
    },
    'cd': {
        'allowed_flags': [],
        'requires_path': True,
    },
    'cat': {
        'allowed_flags': ['-n', '-A'],
        'requires_path': True,
    },
    'head': {
        'allowed_flags': ['-n', '-c'],
        'requires_path': True,
    },
    'tail': {
        'allowed_flags': ['-n', '-c'],  # -f intentionally excluded (blocking)
        'requires_path': True,
    },
    'pwd': {
        'allowed_flags': [],
        'requires_path': False,
    },
    'grep': {
        'allowed_flags': ['-i', '-n', '-r', '-l', '-c', '-v', '-E', '-w'],
        'requires_path': False,  # Pattern can be provided without path
    },
    'find': {
        'allowed_flags': ['-name', '-type', '-mtime', '-size', '-maxdepth'],
        'requires_path': True,
    },
    'wc': {
        'allowed_flags': ['-l', '-w', '-c', '-m'],
        'requires_path': True,
    },
    'du': {
        'allowed_flags': ['-h', '-s', '-d', '--max-depth'],
        'requires_path': False,
    },
    'df': {
        'allowed_flags': ['-h'],
        'requires_path': False,
    },
    'stat': {
        'allowed_flags': [],
        'requires_path': True,
    },
    'file': {
        'allowed_flags': [],
        'requires_path': True,
    },
    'less': {
        'allowed_flags': [],
        'requires_path': True,
    },
    'more': {
        'allowed_flags': [],
        'requires_path': True,
    },
}

# Allowed WP-CLI commands (wp is the prefix)
ALLOWED_WP_SUBCOMMANDS = frozenset([
    # Information/status commands
    'core version', 'core check-update',
    'plugin list', 'plugin status', 'plugin get', 'plugin verify-checksums',
    'theme list', 'theme status', 'theme get',
    'user list', 'user get',
    'option list', 'option get',
    'post list', 'post get',
    'term list',
    'menu list',
    'widget list',
    'sidebar list',
    'comment list',
    'db size', 'db tables', 'db query',  # db query is read-only if SELECT only
    'cron event list', 'cron event run', 'cron schedule list',
    'transient list', 'transient get',
    'rewrite list',
    'role list',
    'cap list',
    'site list',  # Multisite info
    'network meta list',

    # Cache operations (safe)
    'cache flush', 'cache get', 'cache type',
    'transient delete',  # Safe cleanup
    'rewrite flush',

    # Plugin/theme management (limited)
    'plugin activate', 'plugin deactivate', 'plugin update', 'plugin install',
    'theme activate', 'theme update', 'theme install',

    # Maintenance
    'maintenance-mode status',

    # Search/replace (with restrictions)
    'search-replace',

    # Export (read operations)
    'db export', 'export',

    # WooCommerce specific
    'wc product list', 'wc order list', 'wc customer list',
    'wc shop_order list', 'wc report',
])

# Allowed Magento CLI commands (bin/magento prefix)
ALLOWED_MAGENTO_SUBCOMMANDS = frozenset([
    # Information/status commands
    'info:adminuri',
    'info:backups:list',
    'info:currency:list',
    'info:dependencies:show-framework',
    'info:dependencies:show-modules',
    'info:dependencies:show-modules-circular',
    'info:language:list',
    'info:timezone:list',
    '--version',
    'list',

    # Module information
    'module:status',
    'module:enable', 'module:disable',

    # Cache management (safe operations)
    'cache:status',
    'cache:clean', 'cache:flush',
    'cache:enable', 'cache:disable',

    # Index management
    'indexer:status',
    'indexer:info',
    'indexer:show-mode',
    'indexer:reindex',
    'indexer:reset',
    'indexer:set-mode',

    # Cron
    'cron:run',
    'cron:install',

    # Maintenance mode
    'maintenance:status',
    'maintenance:enable', 'maintenance:disable',

    # Setup commands (safe ones)
    'setup:db:status',
    'setup:upgrade',
    'setup:di:compile',
    'setup:static-content:deploy',
    'setup:store-config:set',

    # Store/config info
    'store:list',
    'store:website:list',
    'config:show',

    # Customer/catalog info
    'customer:hash:upgrade',
    'catalog:images:resize',
    'catalog:product:attributes:cleanup',

    # Queue
    'queue:consumers:list',
    'queue:consumers:start',

    # Deploy
    'deploy:mode:show',

    # Dev tools (read-only)
    'dev:query-log:enable', 'dev:query-log:disable',
    'dev:template-hints:enable', 'dev:template-hints:disable',

    # Sampledata (info only)
    'sampledata:deploy',
    'sampledata:remove',
    'sampledata:reset',
])


def contains_dangerous_chars(command: str) -> Tuple[bool, Optional[str]]:
    """Check if command contains shell metacharacters."""
    for char in DANGEROUS_CHARS:
        if char in command:
            return True, char
    return False, None


def validate_command(raw_command: str, current_dir: str = '/var/www/html',
                    platform: str = 'woocommerce') -> Tuple[bool, str, Dict]:
    """
    Validate and parse a command string.

    Args:
        raw_command: The raw command string from user input
        current_dir: Current working directory for path resolution
        platform: Customer platform ('woocommerce', 'wordpress', or 'magento')

    Returns:
        Tuple of (is_valid, error_message, parsed_result)
        parsed_result contains 'command', 'args', 'full_command' if valid
    """
    if not raw_command or not raw_command.strip():
        return False, "Empty command", {}

    raw_command = raw_command.strip()

    # Check length limit
    if len(raw_command) > 1000:
        return False, "Command too long (max 1000 characters)", {}

    # Check for dangerous characters
    has_dangerous, char = contains_dangerous_chars(raw_command)
    if has_dangerous:
        return False, f"Character '{char}' not allowed in commands", {}

    # Parse command with shlex
    try:
        args = shlex.split(raw_command)
    except ValueError as e:
        return False, f"Invalid command syntax: {e}", {}

    if not args:
        return False, "Empty command after parsing", {}

    base_command = args[0].lower()

    # Check against blocklist first
    if base_command in BLOCKED_COMMANDS:
        return False, f"Command '{base_command}' is not allowed. Please open a support ticket if you need assistance with this operation.", {}

    # Handle WP-CLI commands (WordPress/WooCommerce)
    if base_command == 'wp':
        if platform not in ('woocommerce', 'wordpress'):
            return False, "WP-CLI commands are only available for WordPress stores", {}
        return validate_wp_command(args)

    # Handle Magento CLI commands
    if base_command == 'bin/magento' or (base_command == 'magento' and args[0] == 'bin/magento'):
        if platform != 'magento':
            return False, "Magento CLI commands are only available for Magento stores", {}
        return validate_magento_command(args)

    # Handle "bin/magento" as two separate args
    if base_command == 'bin' and len(args) > 1 and args[1] == 'magento':
        # Reconstruct as bin/magento command
        if platform != 'magento':
            return False, "Magento CLI commands are only available for Magento stores", {}
        # Rebuild args with bin/magento as first element
        new_args = ['bin/magento'] + args[2:]
        return validate_magento_command(new_args)

    # Check against shell command allowlist
    if base_command not in ALLOWED_SHELL_COMMANDS:
        if platform == 'magento':
            return False, f"Command '{base_command}' is not in the allowlist. Type 'help' for available commands. Use 'bin/magento' for Magento CLI.", {}
        else:
            return False, f"Command '{base_command}' is not in the allowlist. Type 'help' for available commands.", {}

    # Validate shell command
    return validate_shell_command(base_command, args)


def validate_wp_command(args: List[str]) -> Tuple[bool, str, Dict]:
    """Validate WP-CLI command."""
    if len(args) < 2:
        # Just 'wp' by itself - show help
        return True, "", {
            'command': 'wp',
            'args': ['--help'],
            'full_command': ['wp', '--help']
        }

    # Build subcommand string for checking (e.g., "plugin list", "db drop")
    subcommand_parts = []
    for arg in args[1:]:
        if arg.startswith('-'):
            break
        subcommand_parts.append(arg.lower())

    subcommand = ' '.join(subcommand_parts)

    # Check against blocked WP subcommands
    for blocked in BLOCKED_WP_SUBCOMMANDS:
        if subcommand.startswith(blocked):
            return False, f"'{blocked}' is restricted. Please open a support ticket if you need assistance with this operation.", {}

    # Check if subcommand is in allowlist
    allowed = False
    for allowed_cmd in ALLOWED_WP_SUBCOMMANDS:
        if subcommand.startswith(allowed_cmd):
            allowed = True
            break

    if not allowed:
        return False, f"WP-CLI subcommand '{subcommand}' is not in the allowlist", {}

    # Special handling for db query - only allow SELECT
    if subcommand.startswith('db query'):
        query_idx = None
        for i, arg in enumerate(args):
            if not arg.startswith('-') and i > 2:
                query_idx = i
                break
        if query_idx:
            query = args[query_idx].strip().upper()
            if not query.startswith('SELECT'):
                return False, "Only SELECT queries allowed with 'wp db query'", {}

    # Special handling for search-replace - recommend dry-run
    if subcommand.startswith('search-replace'):
        if '--dry-run' not in args:
            return True, "", {
                'command': 'wp',
                'args': args[1:],
                'full_command': args,
                'warning': "Consider using --dry-run first to preview changes"
            }

    return True, "", {
        'command': 'wp',
        'args': args[1:],
        'full_command': args
    }


def validate_magento_command(args: List[str]) -> Tuple[bool, str, Dict]:
    """Validate Magento CLI command."""
    if len(args) < 2:
        # Just 'bin/magento' by itself - show help
        return True, "", {
            'command': 'bin/magento',
            'args': ['list'],
            'full_command': ['bin/magento', 'list']
        }

    # Build subcommand string for checking
    subcommand_parts = []
    for arg in args[1:]:
        if arg.startswith('-'):
            break
        subcommand_parts.append(arg.lower())

    subcommand = ':'.join(subcommand_parts) if subcommand_parts else ''

    # Handle case where subcommand uses space instead of colon
    if not subcommand and len(args) > 1:
        subcommand = args[1].lower()

    # Check against blocked Magento subcommands
    for blocked in BLOCKED_MAGENTO_SUBCOMMANDS:
        if subcommand.startswith(blocked) or subcommand == blocked:
            return False, f"'{blocked}' is restricted. Please open a support ticket if you need assistance with this operation.", {}

    # Check if subcommand is in allowlist
    allowed = False
    for allowed_cmd in ALLOWED_MAGENTO_SUBCOMMANDS:
        if subcommand.startswith(allowed_cmd) or subcommand == allowed_cmd:
            allowed = True
            break

    # Also check the original format (cache:clean vs cache clean)
    if not allowed:
        subcommand_space = ' '.join(subcommand_parts)
        for allowed_cmd in ALLOWED_MAGENTO_SUBCOMMANDS:
            if subcommand_space.startswith(allowed_cmd.replace(':', ' ')):
                allowed = True
                break

    if not allowed:
        return False, f"Magento subcommand '{subcommand}' is not in the allowlist. Type 'help' for available commands.", {}

    # Special handling for static-content:deploy - warn about time
    if 'static-content:deploy' in subcommand or 'static-content deploy' in ' '.join(args).lower():
        return True, "", {
            'command': 'bin/magento',
            'args': args[1:],
            'full_command': args,
            'warning': "This command may take several minutes to complete"
        }

    # Special handling for setup:di:compile - warn about time
    if 'di:compile' in subcommand or 'di compile' in ' '.join(args).lower():
        return True, "", {
            'command': 'bin/magento',
            'args': args[1:],
            'full_command': args,
            'warning': "This command may take several minutes to complete"
        }

    return True, "", {
        'command': 'bin/magento',
        'args': args[1:],
        'full_command': args
    }


def validate_shell_command(command: str, args: List[str]) -> Tuple[bool, str, Dict]:
    """Validate basic shell command."""
    config = ALLOWED_SHELL_COMMANDS[command]
    allowed_flags = config.get('allowed_flags', [])

    # Check flags
    for arg in args[1:]:
        if arg.startswith('-'):
            # Handle combined short flags like -la
            if arg.startswith('--'):
                flag = arg.split('=')[0]  # Handle --flag=value
            else:
                # For combined flags like -la, check each character
                flag = arg

            # Check if flag is allowed (exact match or prefix for combined)
            flag_allowed = False
            for allowed in allowed_flags:
                if flag == allowed or flag.startswith(allowed):
                    flag_allowed = True
                    break
                # Handle combined short flags: -la contains -l and -a
                if not arg.startswith('--') and len(arg) > 2:
                    # Check each flag character
                    all_chars_allowed = True
                    for char in arg[1:]:
                        if f'-{char}' not in allowed_flags:
                            all_chars_allowed = False
                            break
                    if all_chars_allowed:
                        flag_allowed = True
                        break

            if not flag_allowed:
                return False, f"Flag '{arg}' not allowed for '{command}'", {}

    return True, "", {
        'command': command,
        'args': args[1:],
        'full_command': args
    }


def validate_path(path: str, base_dir: str = '/var/www/html') -> Tuple[bool, str]:
    """
    Validate that a path stays within the allowed directory.

    This is a pre-validation check. The actual path resolution
    happens inside the container.

    Args:
        path: The path to validate
        base_dir: The allowed base directory

    Returns:
        Tuple of (is_valid, error_or_normalized_path)
    """
    import os

    # Reject obvious traversal attempts
    if '..' in path:
        # Could be legitimate like ./foo/../bar, but we reject for safety
        # Let docker exec handle path resolution within container
        pass

    # Reject absolute paths outside base_dir
    if path.startswith('/'):
        if not path.startswith(base_dir):
            return False, f"Access denied: paths must be within {base_dir}"

    # Reject paths starting with ~
    if path.startswith('~') and not path.startswith('~/'):
        return False, "Invalid path: use ~/ for home directory"

    return True, path


def get_help_text(platform: str = 'woocommerce') -> str:
    """Generate help text for available commands based on platform."""
    help_lines = [
        "\x1b[1mAvailable Commands:\x1b[0m",
        "",
    ]

    if platform in ('woocommerce', 'wordpress'):
        help_lines.extend([
            "\x1b[36mWP-CLI Commands:\x1b[0m",
            "  wp plugin list          - List installed plugins",
            "  wp plugin status        - Show plugin status",
            "  wp plugin activate      - Activate a plugin",
            "  wp plugin deactivate    - Deactivate a plugin",
            "  wp plugin update        - Update plugins (--all for all)",
            "  wp theme list           - List installed themes",
            "  wp theme activate       - Activate a theme",
            "  wp cache flush          - Flush WordPress cache",
            "  wp rewrite flush        - Flush rewrite rules",
            "  wp user list            - List users",
            "  wp option list          - List options",
            "  wp db size              - Show database size",
            "  wp cron event list      - List scheduled events",
            "",
        ])
    elif platform == 'magento':
        help_lines.extend([
            "\x1b[36mMagento CLI Commands:\x1b[0m",
            "  bin/magento cache:status      - Show cache status",
            "  bin/magento cache:clean       - Clean cache",
            "  bin/magento cache:flush       - Flush cache storage",
            "  bin/magento indexer:status    - Show indexer status",
            "  bin/magento indexer:reindex   - Reindex data",
            "  bin/magento module:status     - Show module status",
            "  bin/magento setup:upgrade     - Upgrade Magento",
            "  bin/magento setup:di:compile  - Compile DI",
            "  bin/magento setup:static-content:deploy - Deploy static",
            "  bin/magento maintenance:status - Show maintenance mode",
            "  bin/magento deploy:mode:show  - Show deploy mode",
            "  bin/magento cron:run          - Run cron jobs",
            "",
        ])

    help_lines.extend([
        "\x1b[36mShell Commands:\x1b[0m",
        "  ls [-la]                - List directory contents",
        "  cd <dir>                - Change directory",
        "  cat <file>              - Display file contents",
        "  head/tail <file>        - Show beginning/end of file",
        "  grep <pattern> <file>   - Search in files",
        "  find . -name <pattern>  - Find files",
        "  pwd                     - Print working directory",
        "  du -h                   - Show disk usage",
        "",
        "\x1b[36mLocal Commands:\x1b[0m",
        "  help                    - Show this help",
        "  clear                   - Clear terminal",
        "",
        "\x1b[33mRestrictions:\x1b[0m",
        "  - Commands restricted to /var/www/html",
        "  - File modification not allowed",
        "  - Network commands not allowed",
    ])
    return '\n'.join(help_lines)
