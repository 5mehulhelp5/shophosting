# Admin Billing System Design

**Date:** 2026-01-30
**Status:** Approved

## Overview

Comprehensive billing management system for super admins with tiered role-based access. Provides revenue visibility, customer billing support tools, and manual billing operations.

## Role & Permission System

### Admin Roles (4 total)

| Role | Description |
|------|-------------|
| `support` | Customer support agents - limited billing access |
| `admin` | Full customer billing operations |
| `finance_admin` | Revenue reports and exports (NEW) |
| `super_admin` | Everything including configuration |

### Billing Permissions Matrix

| Capability | support | admin | finance_admin | super_admin |
|------------|---------|-------|---------------|-------------|
| View customer billing | ✓ | ✓ | ✓ | ✓ |
| Process refunds ≤$50 | ✓ | ✓ | ✗ | ✓ |
| Process refunds >$50 | ✗ | ✓ | ✗ | ✓ |
| Change plans | ✗ | ✓ | ✗ | ✓ |
| Apply credits | ✗ | ✓ | ✗ | ✓ |
| Cancel/pause subscriptions | ✗ | ✓ | ✗ | ✓ |
| Create manual invoices | ✗ | ✓ | ✗ | ✓ |
| Manage payment methods | ✗ | ✓ | ✗ | ✓ |
| Retry failed payments | ✓ | ✓ | ✗ | ✓ |
| View revenue reports | ✗ | ✗ | ✓ | ✓ |
| Export billing data | ✗ | ✗ | ✓ | ✓ |
| Billing settings/config | ✗ | ✗ | ✗ | ✓ |

### Permission Decorators

New module: `admin/permissions.py`

```python
@require_billing_read          # Any admin role
@require_billing_write         # admin, super_admin only
@require_billing_refund(max_amount=None)  # Checks role + amount limit
@require_revenue_access        # finance_admin, super_admin only
@require_billing_admin         # super_admin only
```

## Database Schema

### New Tables

#### `billing_audit_log`
Immutable audit trail for all billing actions.

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment |
| admin_user_id | INT FK | Admin who performed action |
| action_type | ENUM | refund, credit, plan_change, subscription_cancel, invoice_create, payment_retry, payment_method_update, coupon_apply, settings_change |
| target_customer_id | INT FK NULL | Affected customer |
| target_invoice_id | INT FK NULL | Affected invoice |
| target_subscription_id | INT FK NULL | Affected subscription |
| amount_cents | INT | For monetary actions |
| currency | VARCHAR(3) | Default 'usd' |
| before_state | JSON | Snapshot before change |
| after_state | JSON | Snapshot after change |
| reason | TEXT | Required for refunds/credits |
| stripe_request_id | VARCHAR | For traceability |
| ip_address | VARCHAR | Admin IP |
| created_at | DATETIME | Immutable timestamp |

#### `customer_credits`
Track account credits applied to customers.

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK | Auto-increment |
| customer_id | INT FK | Customer receiving credit |
| amount_cents | INT | Credit amount |
| currency | VARCHAR(3) | Default 'usd' |
| reason | TEXT | Why credit was applied |
| created_by_admin_id | INT FK | Admin who applied |
| applied_to_invoice_id | INT FK NULL | If used on invoice |
| expires_at | DATETIME NULL | Optional expiration |
| created_at | DATETIME | When created |

#### `billing_settings`
Key-value store for billing configuration.

| Column | Type | Description |
|--------|------|-------------|
| key | VARCHAR PK | Setting name |
| value | JSON | Setting value |
| updated_by_admin_id | INT FK | Last updater |
| updated_at | DATETIME | Last update time |

### Schema Updates to Existing Tables

- `admin_users.role`: Add `'finance_admin'` to allowed values
- `invoices`: Add `manual` BOOLEAN, `notes` TEXT, `created_by_admin_id` INT FK

## Route Structure

### New Blueprint: `admin/billing_routes.py`

```
/admin/billing/
├── GET  /                          → Dashboard (MRR, quick stats)
├── GET  /invoices                  → Invoice list with filters
├── GET  /invoices/<id>             → Invoice detail
├── POST /invoices/create           → Create manual invoice
│
├── GET  /subscriptions             → Subscription list
├── GET  /subscriptions/<id>        → Subscription detail
├── POST /subscriptions/<id>/change-plan  → Upgrade/downgrade
├── POST /subscriptions/<id>/cancel       → Cancel subscription
├── POST /subscriptions/<id>/pause        → Pause subscription
├── POST /subscriptions/<id>/resume       → Resume paused
│
├── POST /refunds/create            → Process refund
├── GET  /credits                   → Credits list
├── POST /credits/create            → Apply customer credit
│
├── POST /payments/<id>/retry       → Retry failed payment
├── GET  /payment-methods/<customer_id>   → List payment methods
├── DELETE /payment-methods/<id>          → Remove payment method
│
├── GET  /revenue                   → Revenue reports page
├── GET  /revenue/export            → CSV export
├── GET  /revenue/api/mrr           → MRR chart data (JSON)
├── GET  /revenue/api/churn         → Churn data (JSON)
│
├── GET  /coupons                   → Coupon management
├── POST /coupons/apply             → Apply coupon to customer
│
├── GET  /audit-log                 → Audit log viewer
├── GET  /audit-log/export          → Audit log export
│
├── GET  /settings                  → Billing settings (super_admin)
├── POST /settings                  → Update settings
```

### Customer Detail Integration

Add "Billing" tab to `/admin/customers/<id>`:
- Current plan & subscription status
- Payment method on file
- Recent invoices (last 5)
- Credit balance
- Quick action buttons (refund, change plan, apply credit)

## Stripe Integration (Hybrid Approach)

### Local Database Usage
- Invoice lists and filtering
- Subscription lists
- Revenue calculations (MRR, churn, trends)
- Audit log
- Credits and manual invoices

Data synced via existing webhook handlers.

### Real-time Stripe API Usage
- Processing refunds → `stripe.Refund.create()`
- Changing plans → `stripe.Subscription.modify()`
- Canceling subscriptions → `stripe.Subscription.cancel()`
- Retrying payments → `stripe.PaymentIntent.confirm()`
- Fetching payment methods → `stripe.PaymentMethod.list()`
- Creating invoices → `stripe.Invoice.create()` + `stripe.InvoiceItem.create()`
- Applying coupons → `stripe.Subscription.modify()`

### Service Layer: `billing_service.py`

Centralized business logic that:
1. Performs Stripe API call
2. Updates local database
3. Writes audit log entry
4. Returns result

Example refund flow:
```
Admin clicks Refund → Route validates permissions →
billing_service.process_refund() →
  1. stripe.Refund.create()
  2. Update local invoice record
  3. Write audit_log entry
  4. Return success/failure
→ Flash message + redirect
```

## UI Templates

### New Template Structure

```
templates/admin/billing/
├── dashboard.html          → Overview with MRR card, quick stats
├── invoices/
│   ├── list.html          → Filterable invoice table
│   ├── detail.html        → Invoice view with refund button
│   └── create.html        → Manual invoice form
├── subscriptions/
│   ├── list.html          → Subscription table
│   └── detail.html        → Subscription management
├── revenue/
│   ├── reports.html       → Charts (MRR, churn, revenue by plan)
│   └── export.html        → Export options
├── credits/
│   └── list.html          → Credit history
├── coupons/
│   └── list.html          → Coupon management
├── audit_log.html          → Searchable audit trail
└── settings.html           → Billing configuration
```

### Reusable Components
- `_invoice_status_badge.html` - Color-coded status
- `_subscription_status_badge.html` - Active/paused/canceled
- `_billing_action_modal.html` - Confirmation with reason field

## Audit Logging

### Logged Actions

| Action | Before State | After State | Reason Required |
|--------|-------------|-------------|-----------------|
| Refund | Invoice snapshot | Refund details | ✓ Yes |
| Credit applied | Credit balance | New balance | ✓ Yes |
| Plan change | Old plan, price | New plan, price | Optional |
| Subscription cancel | Status | Canceled + cancel_at | ✓ Yes |
| Subscription pause | Status: active | Status: paused | Optional |
| Payment retry | Payment status | New status | No |
| Manual invoice | null | Invoice details | Optional |
| Coupon applied | null | Coupon, discount | No |
| Settings change | Old value | New value | No |

### Compliance Features
- Append-only (no UPDATE/DELETE)
- Searchable by admin, customer, action, date range
- Export to CSV/JSON
- Default retention: 7 years

## Implementation Phases

### Phase 1: Foundation
- Add `finance_admin` role
- Create permission decorators
- Database migrations
- Build `billing_service.py` with audit logging
- Billing tab on customer detail (view-only)

### Phase 2: Customer Billing Operations
- Refund processing (with $50 limit for support)
- Plan changes
- Apply credits
- Cancel/pause subscriptions
- Retry failed payments
- Invoice list and detail views

### Phase 3: Revenue & Advanced Features
- Revenue dashboard with charts
- Manual invoice creation
- Coupon management
- Payment method management
- CSV/JSON exports
- Billing settings page
- Full admin permissions audit

## Post-Implementation

After billing system is complete:
- Full permissions audit of all existing admin routes
- Ensure all routes have appropriate role-based access
