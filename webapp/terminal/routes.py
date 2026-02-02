"""
Terminal Routes - Restricted shell for all customers

Provides API endpoints for the CLI terminal feature.
Supports WP-CLI for WordPress/WooCommerce and bin/magento for Magento.
"""

import uuid
import logging
from functools import wraps

from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from . import terminal_bp
from .command_validator import validate_command, get_help_text
from .session_manager import TerminalSession
from .executor import execute_in_container, check_container_exists, log_blocked_command

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')


def get_real_ip():
    """Get the real client IP address."""
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr


def terminal_access_required(f):
    """Decorator to restrict terminal access to active customers."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # Import here to avoid circular imports
        from models import Customer

        customer = Customer.get_by_id(current_user.id)

        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        if customer.status != 'active':
            return jsonify({'error': 'Store must be active to use terminal'}), 403

        # Add customer to request context
        request.terminal_customer = customer

        return f(*args, **kwargs)
    return decorated


@terminal_bp.route('/')
@login_required
def terminal_page():
    """Render the terminal UI page."""
    from models import Customer

    customer = Customer.get_by_id(current_user.id)

    if not customer:
        return render_template('errors/404.html'), 404

    if customer.status != 'active':
        return render_template('errors/403.html',
                             message='Store must be active to use terminal'), 403

    return render_template('dashboard/terminal.html',
                          customer=customer,
                          active_page='terminal')


@terminal_bp.route('/api/session', methods=['POST'])
@terminal_access_required
def create_session():
    """Create a new terminal session."""
    customer = request.terminal_customer

    # Check container is running
    container_name = f"customer-{customer.id}-web"
    if not check_container_exists(container_name):
        return jsonify({
            'error': 'Container not running. Please start your store first.'
        }), 503

    # Create session
    try:
        session = TerminalSession.create(customer.id)

        security_logger.info(
            f"TERMINAL_SESSION_START: customer={customer.id} "
            f"session={session.id} ip={get_real_ip()}"
        )

        return jsonify({
            'session_id': session.id,
            'cwd': session.current_directory,
            'platform': customer.platform
        })
    except Exception as e:
        logger.error(f"Failed to create terminal session: {e}")
        return jsonify({'error': 'Failed to create session'}), 500


@terminal_bp.route('/api/execute', methods=['POST'])
@terminal_access_required
def execute_command():
    """Execute a command in the customer's container."""
    customer = request.terminal_customer

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    session_id = data.get('session_id')
    command = data.get('command', '').strip()

    if not session_id:
        return jsonify({'error': 'Missing session_id'}), 400

    if not command:
        return jsonify({'error': 'Empty command'}), 400

    # Validate session
    session = TerminalSession.get(session_id)
    if not session:
        return jsonify({'error': 'Session expired. Please refresh the page.'}), 401

    if session.customer_id != customer.id:
        security_logger.warning(
            f"TERMINAL_SESSION_MISMATCH: customer={customer.id} "
            f"session_owner={session.customer_id} session={session_id}"
        )
        return jsonify({'error': 'Invalid session'}), 401

    # Touch session to extend timeout
    session.touch()

    # Handle local commands
    if command.lower() == 'help':
        return jsonify({
            'execution_id': str(uuid.uuid4()),
            'status': 'complete',
            'exit_code': 0,
            'output': get_help_text(customer.platform),
            'cwd': session.current_directory
        })

    if command.lower() == 'clear':
        return jsonify({
            'execution_id': str(uuid.uuid4()),
            'status': 'complete',
            'exit_code': 0,
            'output': '',
            'cwd': session.current_directory,
            'action': 'clear'
        })

    # Validate command with platform context
    is_valid, error_msg, parsed = validate_command(
        command,
        session.current_directory,
        platform=customer.platform
    )

    if not is_valid:
        # Log blocked command
        log_blocked_command(
            customer_id=customer.id,
            session_id=session_id,
            command=command,
            working_directory=session.current_directory,
            block_reason=error_msg,
            ip_address=get_real_ip(),
            user_agent=request.user_agent.string
        )

        security_logger.warning(
            f"TERMINAL_BLOCKED: customer={customer.id} "
            f"cmd={command[:100]} reason={error_msg} ip={get_real_ip()}"
        )

        return jsonify({'error': error_msg}), 400

    # Check container is running
    container_name = f"customer-{customer.id}-web"
    if not check_container_exists(container_name):
        return jsonify({
            'error': 'Container not running. Please start your store first.'
        }), 503

    # Execute command
    result = execute_in_container(
        container_name=container_name,
        command=parsed['command'],
        args=parsed.get('args', []),
        workdir=session.current_directory,
        customer_id=customer.id,
        session_id=session_id,
        ip_address=get_real_ip(),
        user_agent=request.user_agent.string
    )

    # Update session working directory if cd command succeeded
    if parsed['command'] == 'cd' and result['exit_code'] == 0:
        session.current_directory = result['new_cwd']
        session.save()

    # Include any warnings from validation
    warning = parsed.get('warning')

    response = {
        'execution_id': str(uuid.uuid4()),
        'status': 'complete',
        'exit_code': result['exit_code'],
        'output': result['output'],
        'cwd': result['new_cwd'],
        'execution_time_ms': result.get('execution_time_ms', 0)
    }

    if warning:
        response['warning'] = warning

    return jsonify(response)


@terminal_bp.route('/api/output/<execution_id>')
@terminal_access_required
def get_output(execution_id):
    """
    Get output for an execution.

    For the current synchronous implementation, commands complete
    immediately so this endpoint always returns 'complete'.
    This is kept for future async command support.
    """
    return jsonify({
        'status': 'complete',
        'output': '',
        'cwd': '/var/www/html'
    })


@terminal_bp.route('/api/session/<session_id>', methods=['DELETE'])
@terminal_access_required
def delete_session(session_id):
    """End a terminal session."""
    customer = request.terminal_customer

    session = TerminalSession.get(session_id)
    if session and session.customer_id == customer.id:
        TerminalSession.delete(session_id)
        security_logger.info(
            f"TERMINAL_SESSION_END: customer={customer.id} "
            f"session={session_id} ip={get_real_ip()}"
        )

    return jsonify({'success': True})
