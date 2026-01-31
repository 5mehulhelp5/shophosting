"""
Admin Billing Permission Decorators
Role-based access control for billing operations
"""

import json
from functools import wraps
from flask import session, redirect, url_for, flash, request, abort

from models import get_db_connection


# Role hierarchy for billing permissions
BILLING_ROLES = {
    'super_admin': {
        'billing_read': True,
        'billing_write': True,
        'billing_refund': True,
        'refund_limit': None,  # Unlimited
        'revenue_access': True,
        'billing_admin': True,
    },
    'admin': {
        'billing_read': True,
        'billing_write': True,
        'billing_refund': True,
        'refund_limit': None,  # Unlimited
        'revenue_access': False,
        'billing_admin': False,
    },
    'finance_admin': {
        'billing_read': True,
        'billing_write': False,
        'billing_refund': False,
        'refund_limit': 0,
        'revenue_access': True,
        'billing_admin': False,
    },
    'support': {
        'billing_read': True,
        'billing_write': False,
        'billing_refund': True,
        'refund_limit': 5000,  # $50.00 in cents
        'revenue_access': False,
        'billing_admin': False,
    },
}


def get_billing_setting(key, default=None):
    """Get a billing setting value from the database"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT setting_value FROM billing_settings WHERE setting_key = %s",
            (key,)
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row['setting_value'])
            except (json.JSONDecodeError, TypeError):
                return row['setting_value']
        return default
    finally:
        cursor.close()
        conn.close()


def get_role_permissions(role):
    """Get permission settings for a role"""
    return BILLING_ROLES.get(role, {
        'billing_read': False,
        'billing_write': False,
        'billing_refund': False,
        'refund_limit': 0,
        'revenue_access': False,
        'billing_admin': False,
    })


def has_billing_permission(permission_name):
    """Check if current admin has a specific billing permission"""
    role = session.get('admin_user_role')
    if not role:
        return False

    permissions = get_role_permissions(role)
    return permissions.get(permission_name, False)


def get_refund_limit():
    """Get the refund limit for the current admin's role"""
    role = session.get('admin_user_role')
    if not role:
        return 0

    permissions = get_role_permissions(role)
    limit = permissions.get('refund_limit')

    # If role is support, check for configurable limit
    if role == 'support':
        configured_limit = get_billing_setting('support_refund_limit_cents', 5000)
        if configured_limit is not None:
            return int(configured_limit)

    return limit


def require_billing_read(f):
    """
    Require billing read permission (any admin role can view billing info)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        if not has_billing_permission('billing_read'):
            flash('You do not have permission to view billing information.', 'error')
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def require_billing_write(f):
    """
    Require billing write permission (admin, super_admin only)
    For operations like: plan changes, apply credits, cancel subscriptions
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        if not has_billing_permission('billing_write'):
            flash('You do not have permission to modify billing settings.', 'error')
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def require_billing_refund(max_amount=None):
    """
    Require refund permission with optional amount limit check

    Usage:
        @require_billing_refund()  # Check permission only
        @require_billing_refund(max_amount=5000)  # Check permission + amount

    For dynamic amount checking, pass max_amount=None and check manually:
        refund_amount = request.form.get('amount')
        if not can_process_refund(refund_amount):
            abort(403)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('admin_user_id'):
                flash('Please log in to access the admin panel.', 'error')
                return redirect(url_for('admin.login'))

            if not has_billing_permission('billing_refund'):
                flash('You do not have permission to process refunds.', 'error')
                return redirect(url_for('admin.dashboard'))

            # If max_amount is specified, check against role limit
            if max_amount is not None:
                limit = get_refund_limit()
                if limit is not None and max_amount > limit:
                    flash(f'Refund amount exceeds your limit of ${limit/100:.2f}.', 'error')
                    return redirect(url_for('admin.dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def can_process_refund(amount_cents):
    """
    Check if current admin can process a refund of the given amount

    Args:
        amount_cents: Refund amount in cents

    Returns:
        bool: True if admin can process this refund
    """
    if not has_billing_permission('billing_refund'):
        return False

    limit = get_refund_limit()

    # None means unlimited
    if limit is None:
        return True

    return amount_cents <= limit


def require_revenue_access(f):
    """
    Require revenue access permission (finance_admin, super_admin only)
    For operations like: view revenue reports, export billing data
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        if not has_billing_permission('revenue_access'):
            flash('You do not have permission to access revenue reports.', 'error')
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def require_billing_admin(f):
    """
    Require billing admin permission (super_admin only)
    For operations like: billing settings, configuration changes
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        if not has_billing_permission('billing_admin'):
            flash('This action requires super admin privileges.', 'error')
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def require_payment_retry(f):
    """
    Require permission to retry failed payments (support, admin, super_admin)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        role = session.get('admin_user_role')
        if role not in ['support', 'admin', 'super_admin']:
            flash('You do not have permission to retry payments.', 'error')
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function
