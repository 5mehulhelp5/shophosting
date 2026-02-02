"""
Docker command executor for terminal

Executes validated commands inside customer Docker containers.
"""

import subprocess
import os
import time
import logging
import hashlib
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Command execution limits
COMMAND_TIMEOUT = 30  # seconds
MAX_OUTPUT_SIZE = 512 * 1024  # 512KB

# Base directory that all commands are restricted to
BASE_DIRECTORY = '/var/www/html'


def execute_in_container(
    container_name: str,
    command: str,
    args: list,
    workdir: str = BASE_DIRECTORY,
    customer_id: Optional[int] = None,
    session_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> Dict:
    """
    Execute a command inside a Docker container.

    Args:
        container_name: The Docker container name (e.g., customer-123-web)
        command: The base command (e.g., 'ls', 'wp')
        args: List of arguments
        workdir: Working directory inside container
        customer_id: For audit logging
        session_id: For audit logging
        ip_address: For audit logging
        user_agent: For audit logging

    Returns:
        dict with 'exit_code', 'output', 'new_cwd' (for cd), 'execution_time_ms'
    """
    start_time = time.time()
    full_command = [command] + args
    full_command_str = ' '.join(full_command)

    # Special handling for 'cd' command
    if command == 'cd':
        return handle_cd_command(container_name, args, workdir)

    # Build docker exec command
    docker_cmd = [
        'docker', 'exec',
        '--workdir', workdir,
        '--user', 'www-data',  # Run as web user, not root
        container_name
    ] + full_command

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT
        )

        execution_time_ms = int((time.time() - start_time) * 1000)
        output = result.stdout
        if result.stderr:
            output = output + result.stderr if output else result.stderr

        # Truncate if too large
        output_truncated = False
        if len(output) > MAX_OUTPUT_SIZE:
            output = output[:MAX_OUTPUT_SIZE] + '\n\n... (output truncated, showing first 512KB)'
            output_truncated = True

        # Log to audit table
        if customer_id:
            log_command_execution(
                customer_id=customer_id,
                session_id=session_id,
                command=full_command_str,
                working_directory=workdir,
                exit_code=result.returncode,
                execution_time_ms=execution_time_ms,
                output_size_bytes=len(output),
                ip_address=ip_address,
                user_agent=user_agent
            )

        return {
            'exit_code': result.returncode,
            'output': output,
            'new_cwd': workdir,
            'execution_time_ms': execution_time_ms,
            'truncated': output_truncated
        }

    except subprocess.TimeoutExpired:
        execution_time_ms = int((time.time() - start_time) * 1000)

        if customer_id:
            log_command_execution(
                customer_id=customer_id,
                session_id=session_id,
                command=full_command_str,
                working_directory=workdir,
                exit_code=124,  # Standard timeout exit code
                execution_time_ms=execution_time_ms,
                ip_address=ip_address,
                user_agent=user_agent
            )

        return {
            'exit_code': 124,
            'output': f'Command timed out after {COMMAND_TIMEOUT} seconds',
            'new_cwd': workdir,
            'execution_time_ms': execution_time_ms
        }

    except FileNotFoundError:
        logger.error(f"Docker not found when executing command in {container_name}")
        return {
            'exit_code': 127,
            'output': 'Internal error: Docker not available',
            'new_cwd': workdir,
            'execution_time_ms': 0
        }

    except Exception as e:
        logger.error(f"Container exec error for {container_name}: {e}")
        return {
            'exit_code': 1,
            'output': f'Execution error: {str(e)}',
            'new_cwd': workdir,
            'execution_time_ms': int((time.time() - start_time) * 1000)
        }


def handle_cd_command(container_name: str, args: list, current_dir: str) -> Dict:
    """
    Handle 'cd' command by verifying target directory exists.

    Since we can't actually change directory in a stateless exec,
    we verify the path exists and return the new working directory
    for the session to track.
    """
    if not args:
        # cd with no args goes to base directory
        return {
            'exit_code': 0,
            'output': '',
            'new_cwd': BASE_DIRECTORY,
            'execution_time_ms': 0
        }

    target = args[0]

    # Handle relative paths
    if not target.startswith('/'):
        if target == '~' or target.startswith('~/'):
            # Treat ~ as base directory
            target = target.replace('~', BASE_DIRECTORY, 1)
        else:
            target = os.path.normpath(os.path.join(current_dir, target))

    # Normalize the path
    target = os.path.normpath(target)

    # Security check: must be within base directory
    if not target.startswith(BASE_DIRECTORY):
        return {
            'exit_code': 1,
            'output': f"cd: Permission denied: cannot navigate outside {BASE_DIRECTORY}",
            'new_cwd': current_dir,
            'execution_time_ms': 0
        }

    # Verify directory exists in container
    check_cmd = ['docker', 'exec', container_name, 'test', '-d', target]

    try:
        result = subprocess.run(check_cmd, capture_output=True, timeout=5)

        if result.returncode == 0:
            return {
                'exit_code': 0,
                'output': '',
                'new_cwd': target,
                'execution_time_ms': 0
            }
        else:
            return {
                'exit_code': 1,
                'output': f"cd: {args[0]}: No such directory",
                'new_cwd': current_dir,
                'execution_time_ms': 0
            }
    except subprocess.TimeoutExpired:
        return {
            'exit_code': 1,
            'output': "cd: Operation timed out",
            'new_cwd': current_dir,
            'execution_time_ms': 0
        }
    except Exception as e:
        logger.error(f"Error checking directory in container: {e}")
        return {
            'exit_code': 1,
            'output': f"cd: Error verifying directory",
            'new_cwd': current_dir,
            'execution_time_ms': 0
        }


def check_container_exists(container_name: str) -> bool:
    """Check if a container exists and is running."""
    try:
        result = subprocess.run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', container_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and result.stdout.strip() == 'true'
    except Exception:
        return False


def log_command_execution(
    customer_id: int,
    session_id: Optional[str],
    command: str,
    working_directory: str,
    exit_code: int,
    execution_time_ms: int,
    output_size_bytes: int = 0,
    blocked: bool = False,
    block_reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> None:
    """Log command execution to audit table."""
    from models import get_db_connection

    # Generate command hash for deduplication analysis
    command_hash = hashlib.sha256(command.encode()).hexdigest()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO terminal_audit_log
            (customer_id, session_id, command, command_hash, working_directory,
             exit_code, execution_time_ms, output_size_bytes, blocked, block_reason,
             ip_address, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            customer_id,
            session_id or '',
            command[:2000],  # Limit stored command length
            command_hash,
            working_directory,
            exit_code,
            execution_time_ms,
            output_size_bytes,
            blocked,
            block_reason,
            ip_address,
            user_agent[:512] if user_agent else None,
            datetime.utcnow()
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log terminal command: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def log_blocked_command(
    customer_id: int,
    session_id: Optional[str],
    command: str,
    working_directory: str,
    block_reason: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> None:
    """Log a blocked command attempt."""
    log_command_execution(
        customer_id=customer_id,
        session_id=session_id,
        command=command,
        working_directory=working_directory,
        exit_code=-1,
        execution_time_ms=0,
        blocked=True,
        block_reason=block_reason,
        ip_address=ip_address,
        user_agent=user_agent
    )
