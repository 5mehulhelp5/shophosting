# Admin Permissions Audit

**Date:** 2026-01-30
**Status:** Complete

## Overview

Comprehensive audit of all admin routes to ensure proper role-based access control following the implementation of the billing system with its new `finance_admin` role.

## Role Definitions

| Role | Description |
|------|-------------|
| `support` | Customer support - limited access, can view but limited modifications |
| `admin` | Full operational access to customer and system management |
| `finance_admin` | Revenue reports and billing data access only |
| `super_admin` | Everything including configuration, user management, destructive operations |

## Audit Findings

### Routes Requiring `super_admin_required`

These routes perform destructive or configuration-level operations:

| Route | Current | Required | Reason |
|-------|---------|----------|--------|
| `/system/backup/create` | admin_required | super_admin_required | Creates system backups |
| `/system/backup/restore/<id>` | admin_required | super_admin_required | **CRITICAL:** Restores from backup |
| `/servers/create` | admin_required | super_admin_required | Adds infrastructure |
| `/servers/<id>/edit` | admin_required | super_admin_required | Modifies infrastructure |
| `/servers/<id>/delete` | admin_required | super_admin_required | **CRITICAL:** Removes servers |
| `/servers/<id>/maintenance` | admin_required | super_admin_required | Server maintenance mode |
| `/restart/<service>` | admin_required | super_admin_required | **CRITICAL:** Restarts services |
| `/backup/run` | admin_required | super_admin_required | Triggers backup jobs |
| `/jobs/clear-failed` | admin_required | super_admin_required | Clears job queue |
| `/manage-customers/<id>/delete` | admin_required | super_admin_required | **CRITICAL:** Deletes customer data |

### Routes Requiring `admin_or_super_required` (Not Support)

These routes modify data but are not destructive enough for super_admin only:

| Route | Current | Required | Reason |
|-------|---------|----------|--------|
| `/manage-customers/create` | admin_required | admin_or_super | Creates customer accounts |
| `/manage-customers/<id>/edit` | admin_required | admin_or_super | Edits customer data |
| `/staging/<id>/delete` | admin_required | admin_or_super | Deletes staging environments |
| `/status/incident/create` | admin_required | admin_or_super | Creates public incidents |
| `/status/maintenance/create` | admin_required | admin_or_super | Schedules maintenance |
| `/status/override` | admin_required | admin_or_super | Overrides status display |
| `/mail/mailboxes/create` | admin_required | admin_or_super | Creates email accounts |
| `/mail/mailboxes/<id>/edit` | admin_required | admin_or_super | Edits email accounts |
| `/mail/mailboxes/<id>/delete` | admin_required | admin_or_super | Deletes email accounts |
| `/mail/aliases/*` | admin_required | admin_or_super | Manages email aliases |
| `/mail/catch-all` | admin_required | admin_or_super | Manages catch-all |

### Routes That Are Correctly Configured

| Route Category | Decorator | Notes |
|----------------|-----------|-------|
| `/admins/*` | super_admin_required | Correct - admin user management |
| `/pages/*` | super_admin_required | Correct - CMS management |
| `/pricing/*` | super_admin_required | Correct - pricing configuration |
| `/customers/*` (view) | admin_required | Correct - all roles can view |
| `/tickets/*` | admin_required | Correct - all roles handle tickets |
| `/monitoring/*` | admin_required | Correct - all roles can monitor |
| `/billing/*` | Various billing decorators | Correct - uses new permission system |

## Implementation

### New Decorator Added

```python
def admin_or_super_required(f):
    """Require admin or super_admin role (not support or finance_admin)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = session.get('admin_user_role')
        if role not in ['admin', 'super_admin']:
            flash('This action requires admin privileges.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated
```

### Changes Applied

1. Added `admin_or_super_required` decorator to routes.py
2. Updated 10 routes to use `super_admin_required`
3. Updated 11 routes to use `admin_or_super_required`
4. Updated mail_routes.py with proper decorators

## Post-Audit Status

All admin routes now have appropriate role-based access control:

- **Support role**: Can view customers, tickets, monitoring; limited billing actions
- **Admin role**: Full customer/system operations; no config changes
- **Finance admin**: Billing read + revenue reports only
- **Super admin**: Full access including destructive operations
