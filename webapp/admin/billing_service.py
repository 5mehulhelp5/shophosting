"""
Admin Billing Service
Centralized business logic for all billing operations with audit logging
"""

import json
import logging
from datetime import datetime
from decimal import Decimal

import stripe

from models import get_db_connection, Customer, Subscription, Invoice
from stripe_integration.config import is_stripe_configured, get_stripe_config

logger = logging.getLogger(__name__)


class BillingServiceError(Exception):
    """Custom exception for billing service errors"""
    pass


class BillingAuditLog:
    """Model for billing audit log entries"""

    ACTION_TYPES = [
        'refund', 'credit', 'plan_change', 'subscription_cancel',
        'subscription_pause', 'subscription_resume', 'invoice_create',
        'payment_retry', 'payment_method_update', 'coupon_apply', 'settings_change'
    ]

    def __init__(self, id=None, admin_user_id=None, action_type=None,
                 target_customer_id=None, target_invoice_id=None,
                 target_subscription_id=None, amount_cents=0, currency='usd',
                 before_state=None, after_state=None, reason=None,
                 stripe_request_id=None, ip_address=None, created_at=None):
        self.id = id
        self.admin_user_id = admin_user_id
        self.action_type = action_type
        self.target_customer_id = target_customer_id
        self.target_invoice_id = target_invoice_id
        self.target_subscription_id = target_subscription_id
        self.amount_cents = amount_cents
        self.currency = currency
        self.before_state = before_state
        self.after_state = after_state
        self.reason = reason
        self.stripe_request_id = stripe_request_id
        self.ip_address = ip_address
        self.created_at = created_at

    def save(self):
        """Save audit log entry (insert only - immutable)"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO billing_audit_log (
                    admin_user_id, action_type, target_customer_id,
                    target_invoice_id, target_subscription_id, amount_cents,
                    currency, before_state, after_state, reason,
                    stripe_request_id, ip_address
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                self.admin_user_id, self.action_type, self.target_customer_id,
                self.target_invoice_id, self.target_subscription_id,
                self.amount_cents, self.currency,
                json.dumps(self.before_state) if self.before_state else None,
                json.dumps(self.after_state) if self.after_state else None,
                self.reason, self.stripe_request_id, self.ip_address
            ))
            conn.commit()
            self.id = cursor.lastrowid
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_by_customer(customer_id, limit=50, offset=0):
        """Get audit logs for a customer"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT bal.*, au.full_name as admin_name, au.email as admin_email
                FROM billing_audit_log bal
                LEFT JOIN admin_users au ON bal.admin_user_id = au.id
                WHERE bal.target_customer_id = %s
                ORDER BY bal.created_at DESC
                LIMIT %s OFFSET %s
            """, (customer_id, limit, offset))
            rows = cursor.fetchall()

            logs = []
            for row in rows:
                row['before_state'] = json.loads(row['before_state']) if row['before_state'] else None
                row['after_state'] = json.loads(row['after_state']) if row['after_state'] else None
                logs.append(row)
            return logs
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def search(filters=None, limit=100, offset=0):
        """Search audit logs with filters"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        filters = filters or {}
        where_clauses = []
        params = []

        if filters.get('admin_user_id'):
            where_clauses.append("bal.admin_user_id = %s")
            params.append(filters['admin_user_id'])

        if filters.get('action_type'):
            where_clauses.append("bal.action_type = %s")
            params.append(filters['action_type'])

        if filters.get('customer_id'):
            where_clauses.append("bal.target_customer_id = %s")
            params.append(filters['customer_id'])

        if filters.get('date_from'):
            where_clauses.append("bal.created_at >= %s")
            params.append(filters['date_from'])

        if filters.get('date_to'):
            where_clauses.append("bal.created_at <= %s")
            params.append(filters['date_to'])

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        try:
            cursor.execute(f"""
                SELECT bal.*, au.full_name as admin_name, au.email as admin_email,
                       c.email as customer_email
                FROM billing_audit_log bal
                LEFT JOIN admin_users au ON bal.admin_user_id = au.id
                LEFT JOIN customers c ON bal.target_customer_id = c.id
                WHERE {where_sql}
                ORDER BY bal.created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()


class CustomerCredit:
    """Model for customer credits"""

    def __init__(self, id=None, customer_id=None, amount_cents=0, currency='usd',
                 reason=None, created_by_admin_id=None, applied_to_invoice_id=None,
                 expires_at=None, created_at=None):
        self.id = id
        self.customer_id = customer_id
        self.amount_cents = amount_cents
        self.currency = currency
        self.reason = reason
        self.created_by_admin_id = created_by_admin_id
        self.applied_to_invoice_id = applied_to_invoice_id
        self.expires_at = expires_at
        self.created_at = created_at

    def save(self):
        """Save credit to database"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO customer_credits (
                    customer_id, amount_cents, currency, reason,
                    created_by_admin_id, applied_to_invoice_id, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                self.customer_id, self.amount_cents, self.currency,
                self.reason, self.created_by_admin_id,
                self.applied_to_invoice_id, self.expires_at
            ))
            conn.commit()
            self.id = cursor.lastrowid
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_balance(customer_id):
        """Get total available credit balance for a customer"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COALESCE(SUM(amount_cents), 0) as balance
                FROM customer_credits
                WHERE customer_id = %s
                  AND applied_to_invoice_id IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
            """, (customer_id,))
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_by_customer(customer_id, limit=50):
        """Get credit history for a customer"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT cc.*, au.full_name as admin_name
                FROM customer_credits cc
                LEFT JOIN admin_users au ON cc.created_by_admin_id = au.id
                WHERE cc.customer_id = %s
                ORDER BY cc.created_at DESC
                LIMIT %s
            """, (customer_id, limit))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()


class BillingService:
    """
    Centralized service for all billing operations

    All methods:
    1. Validate permissions (caller responsibility via decorators)
    2. Perform Stripe API call (if applicable)
    3. Update local database
    4. Write audit log entry
    5. Return result
    """

    @staticmethod
    def _log_action(admin_id, action_type, customer_id=None, invoice_id=None,
                    subscription_id=None, amount_cents=0, before_state=None,
                    after_state=None, reason=None, stripe_request_id=None,
                    ip_address=None):
        """Create an audit log entry"""
        log = BillingAuditLog(
            admin_user_id=admin_id,
            action_type=action_type,
            target_customer_id=customer_id,
            target_invoice_id=invoice_id,
            target_subscription_id=subscription_id,
            amount_cents=amount_cents,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            stripe_request_id=stripe_request_id,
            ip_address=ip_address
        )
        log.save()
        return log

    @staticmethod
    def get_customer_billing_summary(customer_id):
        """
        Get comprehensive billing summary for a customer

        Returns dict with:
        - subscription info
        - recent invoices
        - credit balance
        - payment methods (from Stripe)
        """
        customer = Customer.get_by_id(customer_id)
        if not customer:
            raise BillingServiceError(f"Customer {customer_id} not found")

        subscription = Subscription.get_by_customer_id(customer_id)
        invoices = Invoice.get_by_customer_id(customer_id, limit=10)
        credit_balance = CustomerCredit.get_balance(customer_id)
        billing_history = BillingAuditLog.get_by_customer(customer_id, limit=10)

        # Get payment methods from Stripe if customer has Stripe ID
        payment_methods = []
        if customer.stripe_customer_id and is_stripe_configured():
            try:
                pm_list = stripe.PaymentMethod.list(
                    customer=customer.stripe_customer_id,
                    type='card'
                )
                payment_methods = [
                    {
                        'id': pm.id,
                        'brand': pm.card.brand,
                        'last4': pm.card.last4,
                        'exp_month': pm.card.exp_month,
                        'exp_year': pm.card.exp_year,
                        'is_default': pm.id == customer.default_payment_method_id if hasattr(customer, 'default_payment_method_id') else False
                    }
                    for pm in pm_list.data
                ]
            except stripe.error.StripeError as e:
                logger.warning(f"Failed to fetch payment methods for customer {customer_id}: {e}")

        return {
            'customer': customer,
            'subscription': subscription,
            'invoices': invoices,
            'credit_balance_cents': credit_balance,
            'payment_methods': payment_methods,
            'billing_history': billing_history,
        }

    @staticmethod
    def process_refund(admin_id, invoice_id, amount_cents, reason, ip_address=None):
        """
        Process a refund for an invoice

        Args:
            admin_id: ID of admin processing refund
            invoice_id: Local invoice ID
            amount_cents: Amount to refund in cents
            reason: Reason for refund (required)
            ip_address: Admin's IP address

        Returns:
            dict with refund details

        Raises:
            BillingServiceError on failure
        """
        if not is_stripe_configured():
            raise BillingServiceError("Stripe is not configured")

        if not reason:
            raise BillingServiceError("Refund reason is required")

        # Get invoice from local DB
        invoice = Invoice.get_by_id(invoice_id)
        if not invoice:
            raise BillingServiceError(f"Invoice {invoice_id} not found")

        if invoice.status != 'paid':
            raise BillingServiceError("Can only refund paid invoices")

        # Capture before state
        before_state = {
            'invoice_id': invoice.id,
            'stripe_invoice_id': invoice.stripe_invoice_id,
            'amount_paid': invoice.amount_paid,
            'status': invoice.status
        }

        try:
            # Get Stripe invoice to find payment intent
            stripe_invoice = stripe.Invoice.retrieve(invoice.stripe_invoice_id)
            payment_intent_id = stripe_invoice.payment_intent

            if not payment_intent_id:
                raise BillingServiceError("No payment found for this invoice")

            # Process refund via Stripe
            refund = stripe.Refund.create(
                payment_intent=payment_intent_id,
                amount=amount_cents,
                reason='requested_by_customer',
                metadata={
                    'admin_id': str(admin_id),
                    'reason': reason[:500]  # Stripe metadata limit
                }
            )

            # Capture after state
            after_state = {
                'refund_id': refund.id,
                'refund_amount': refund.amount,
                'refund_status': refund.status
            }

            # Log the action
            BillingService._log_action(
                admin_id=admin_id,
                action_type='refund',
                customer_id=invoice.customer_id,
                invoice_id=invoice.id,
                amount_cents=amount_cents,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
                stripe_request_id=refund.id,
                ip_address=ip_address
            )

            logger.info(f"Refund processed: ${amount_cents/100:.2f} for invoice {invoice_id} by admin {admin_id}")

            return {
                'success': True,
                'refund_id': refund.id,
                'amount': amount_cents,
                'status': refund.status
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe refund error: {e}")
            raise BillingServiceError(f"Stripe error: {str(e)}")

    @staticmethod
    def apply_credit(admin_id, customer_id, amount_cents, reason, expires_at=None, ip_address=None):
        """
        Apply a credit to a customer's account

        Args:
            admin_id: ID of admin applying credit
            customer_id: Customer ID
            amount_cents: Credit amount in cents
            reason: Reason for credit (required)
            expires_at: Optional expiration datetime
            ip_address: Admin's IP address

        Returns:
            dict with credit details
        """
        if not reason:
            raise BillingServiceError("Credit reason is required")

        customer = Customer.get_by_id(customer_id)
        if not customer:
            raise BillingServiceError(f"Customer {customer_id} not found")

        # Get current balance
        before_balance = CustomerCredit.get_balance(customer_id)

        # Create credit record
        credit = CustomerCredit(
            customer_id=customer_id,
            amount_cents=amount_cents,
            reason=reason,
            created_by_admin_id=admin_id,
            expires_at=expires_at
        )
        credit.save()

        # Get new balance
        after_balance = CustomerCredit.get_balance(customer_id)

        # Log the action
        BillingService._log_action(
            admin_id=admin_id,
            action_type='credit',
            customer_id=customer_id,
            amount_cents=amount_cents,
            before_state={'credit_balance': before_balance},
            after_state={'credit_balance': after_balance, 'credit_id': credit.id},
            reason=reason,
            ip_address=ip_address
        )

        logger.info(f"Credit applied: ${amount_cents/100:.2f} to customer {customer_id} by admin {admin_id}")

        return {
            'success': True,
            'credit_id': credit.id,
            'amount': amount_cents,
            'new_balance': after_balance
        }

    @staticmethod
    def change_subscription_plan(admin_id, subscription_id, new_price_id, reason=None, ip_address=None):
        """
        Change a customer's subscription plan

        Args:
            admin_id: ID of admin making change
            subscription_id: Local subscription ID
            new_price_id: Stripe price ID for new plan
            reason: Optional reason for change
            ip_address: Admin's IP address

        Returns:
            dict with subscription details
        """
        if not is_stripe_configured():
            raise BillingServiceError("Stripe is not configured")

        subscription = Subscription.get_by_id(subscription_id)
        if not subscription:
            raise BillingServiceError(f"Subscription {subscription_id} not found")

        before_state = {
            'plan_name': subscription.plan_name,
            'stripe_price_id': subscription.stripe_price_id,
            'status': subscription.status
        }

        try:
            # Get current Stripe subscription
            stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)

            # Update to new plan
            updated_sub = stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                items=[{
                    'id': stripe_sub['items']['data'][0].id,
                    'price': new_price_id,
                }],
                proration_behavior='create_prorations',
                metadata={
                    'changed_by_admin': str(admin_id)
                }
            )

            # Update local database
            subscription.stripe_price_id = new_price_id
            subscription.save()

            after_state = {
                'plan_name': subscription.plan_name,
                'stripe_price_id': new_price_id,
                'status': updated_sub.status
            }

            # Log the action
            BillingService._log_action(
                admin_id=admin_id,
                action_type='plan_change',
                customer_id=subscription.customer_id,
                subscription_id=subscription.id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
                stripe_request_id=updated_sub.id,
                ip_address=ip_address
            )

            logger.info(f"Plan changed for subscription {subscription_id} by admin {admin_id}")

            return {
                'success': True,
                'subscription_id': subscription.id,
                'new_price_id': new_price_id,
                'status': updated_sub.status
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe plan change error: {e}")
            raise BillingServiceError(f"Stripe error: {str(e)}")

    @staticmethod
    def cancel_subscription(admin_id, subscription_id, reason, cancel_immediately=False, ip_address=None):
        """
        Cancel a customer's subscription

        Args:
            admin_id: ID of admin canceling
            subscription_id: Local subscription ID
            reason: Reason for cancellation (required)
            cancel_immediately: If True, cancel now; if False, cancel at period end
            ip_address: Admin's IP address

        Returns:
            dict with cancellation details
        """
        if not is_stripe_configured():
            raise BillingServiceError("Stripe is not configured")

        if not reason:
            raise BillingServiceError("Cancellation reason is required")

        subscription = Subscription.get_by_id(subscription_id)
        if not subscription:
            raise BillingServiceError(f"Subscription {subscription_id} not found")

        before_state = {
            'status': subscription.status,
            'cancel_at_period_end': False
        }

        try:
            if cancel_immediately:
                # Cancel immediately
                canceled_sub = stripe.Subscription.cancel(
                    subscription.stripe_subscription_id,
                    metadata={'canceled_by_admin': str(admin_id)}
                )
            else:
                # Cancel at period end
                canceled_sub = stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True,
                    metadata={'canceled_by_admin': str(admin_id)}
                )

            # Update local database
            subscription.status = canceled_sub.status
            subscription.save()

            after_state = {
                'status': canceled_sub.status,
                'cancel_at_period_end': canceled_sub.cancel_at_period_end,
                'canceled_at': canceled_sub.canceled_at
            }

            # Log the action
            BillingService._log_action(
                admin_id=admin_id,
                action_type='subscription_cancel',
                customer_id=subscription.customer_id,
                subscription_id=subscription.id,
                before_state=before_state,
                after_state=after_state,
                reason=reason,
                stripe_request_id=canceled_sub.id,
                ip_address=ip_address
            )

            logger.info(f"Subscription {subscription_id} canceled by admin {admin_id}")

            return {
                'success': True,
                'subscription_id': subscription.id,
                'status': canceled_sub.status,
                'cancel_at_period_end': canceled_sub.cancel_at_period_end
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe cancellation error: {e}")
            raise BillingServiceError(f"Stripe error: {str(e)}")

    @staticmethod
    def retry_payment(admin_id, invoice_id, ip_address=None):
        """
        Retry a failed payment for an invoice

        Args:
            admin_id: ID of admin retrying payment
            invoice_id: Local invoice ID
            ip_address: Admin's IP address

        Returns:
            dict with payment result
        """
        if not is_stripe_configured():
            raise BillingServiceError("Stripe is not configured")

        invoice = Invoice.get_by_id(invoice_id)
        if not invoice:
            raise BillingServiceError(f"Invoice {invoice_id} not found")

        if invoice.status == 'paid':
            raise BillingServiceError("Invoice is already paid")

        before_state = {
            'invoice_id': invoice.id,
            'status': invoice.status
        }

        try:
            # Pay the invoice via Stripe
            paid_invoice = stripe.Invoice.pay(invoice.stripe_invoice_id)

            # Update local database
            invoice.status = paid_invoice.status
            invoice.save()

            after_state = {
                'status': paid_invoice.status,
                'paid': paid_invoice.paid
            }

            # Log the action
            BillingService._log_action(
                admin_id=admin_id,
                action_type='payment_retry',
                customer_id=invoice.customer_id,
                invoice_id=invoice.id,
                before_state=before_state,
                after_state=after_state,
                stripe_request_id=paid_invoice.id,
                ip_address=ip_address
            )

            logger.info(f"Payment retry for invoice {invoice_id} by admin {admin_id}")

            return {
                'success': True,
                'invoice_id': invoice.id,
                'status': paid_invoice.status,
                'paid': paid_invoice.paid
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe payment retry error: {e}")
            raise BillingServiceError(f"Payment failed: {str(e)}")

    @staticmethod
    def get_revenue_summary(start_date=None, end_date=None):
        """
        Get revenue summary for reporting

        Args:
            start_date: Start of period (default: 30 days ago)
            end_date: End of period (default: now)

        Returns:
            dict with revenue metrics
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        try:
            # Total revenue in period
            cursor.execute("""
                SELECT
                    COUNT(*) as invoice_count,
                    COALESCE(SUM(amount_paid), 0) as total_revenue,
                    COALESCE(AVG(amount_paid), 0) as avg_invoice
                FROM invoices
                WHERE status = 'paid'
                  AND paid_at BETWEEN %s AND %s
            """, (start_date, end_date))
            revenue = cursor.fetchone()

            # MRR calculation (active subscriptions)
            cursor.execute("""
                SELECT COUNT(*) as active_subscriptions
                FROM subscriptions
                WHERE status = 'active'
            """)
            subscriptions = cursor.fetchone()

            # Refunds in period
            cursor.execute("""
                SELECT
                    COUNT(*) as refund_count,
                    COALESCE(SUM(amount_cents), 0) as total_refunds
                FROM billing_audit_log
                WHERE action_type = 'refund'
                  AND created_at BETWEEN %s AND %s
            """, (start_date, end_date))
            refunds = cursor.fetchone()

            return {
                'period_start': start_date,
                'period_end': end_date,
                'total_revenue_cents': revenue['total_revenue'] or 0,
                'invoice_count': revenue['invoice_count'] or 0,
                'avg_invoice_cents': int(revenue['avg_invoice'] or 0),
                'active_subscriptions': subscriptions['active_subscriptions'] or 0,
                'refund_count': refunds['refund_count'] or 0,
                'total_refunds_cents': refunds['total_refunds'] or 0,
            }

        finally:
            cursor.close()
            conn.close()


# Import timedelta for revenue summary
from datetime import timedelta
