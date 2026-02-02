"""
Admin Panel API Endpoints
JSON endpoints for AJAX dashboard updates
"""

import os
from flask import jsonify, request, session

from . import admin_bp
from .routes import (
    admin_required, get_customer_stats, get_queue_stats,
    get_service_status, get_disk_usage, get_backup_status,
    get_billing_stats, get_customers_filtered, get_all_provisioning_jobs
)

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import PortManager, Ticket, TicketCategory, get_db_connection


@admin_bp.route('/api/stats')
@admin_required
def api_stats():
    """Dashboard statistics"""
    stats = get_customer_stats()
    port_usage = PortManager.get_port_usage()
    queue_stats = get_queue_stats()

    return jsonify({
        'customers': stats,
        'ports': port_usage,
        'queue': queue_stats
    })


@admin_bp.route('/api/customers')
@admin_required
def api_customers():
    """Paginated customer list"""
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')
    platform = request.args.get('platform', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    customers, total = get_customers_filtered(
        search=search,
        status=status,
        platform=platform,
        page=page,
        per_page=per_page
    )

    # Convert datetime objects to strings
    for c in customers:
        if c.get('created_at'):
            c['created_at'] = c['created_at'].isoformat()

    return jsonify({
        'customers': customers,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@admin_bp.route('/api/queue')
@admin_required
def api_queue():
    """Queue status and recent jobs"""
    queue_stats = get_queue_stats()
    jobs = get_all_provisioning_jobs(limit=20)

    # Convert datetime objects to strings
    for job in jobs:
        for key in ['started_at', 'finished_at', 'created_at']:
            if job.get(key):
                job[key] = job[key].isoformat()

    return jsonify({
        'stats': queue_stats,
        'jobs': jobs
    })


@admin_bp.route('/api/system')
@admin_required
def api_system():
    """System health metrics"""
    services = get_service_status()
    port_usage = PortManager.get_port_usage()
    disk_usage = get_disk_usage()
    backup_status = get_backup_status()

    return jsonify({
        'services': services,
        'ports': port_usage,
        'disk': disk_usage,
        'backup': backup_status
    })


@admin_bp.route('/api/billing')
@admin_required
def api_billing():
    """Billing metrics"""
    billing_stats = get_billing_stats()

    return jsonify({
        'stats': billing_stats
    })


@admin_bp.route('/api/tickets')
@admin_required
def api_tickets():
    """Paginated ticket list with filters"""
    status = request.args.get('status', '')
    priority = request.args.get('priority', '')
    category_id = request.args.get('category', '')
    assigned = request.args.get('assigned', '')
    search = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    tickets, total = Ticket.get_all_filtered(
        status=status or None,
        priority=priority or None,
        category_id=int(category_id) if category_id else None,
        assigned_admin_id=assigned or None,
        search=search or None,
        page=page,
        per_page=per_page
    )

    # Convert datetime objects to strings
    for t in tickets:
        for key in ['created_at', 'updated_at', 'resolved_at', 'closed_at']:
            if t.get(key):
                t[key] = t[key].isoformat()

    return jsonify({
        'tickets': tickets,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@admin_bp.route('/api/tickets/stats')
@admin_required
def api_ticket_stats():
    """Ticket statistics for dashboard"""
    stats = Ticket.get_stats()

    return jsonify({
        'total': stats['total'] or 0,
        'open': stats['open_count'] or 0,
        'in_progress': stats['in_progress_count'] or 0,
        'waiting_customer': stats['waiting_count'] or 0,
        'urgent': stats['urgent_count'] or 0,
        'unassigned': stats['unassigned_count'] or 0
    })


@admin_bp.route('/api/provisioning-logs/<int:customer_id>')
@admin_required
def api_provisioning_logs(customer_id):
    """Get provisioning logs for a customer (for live updates)"""
    from .routes import get_provisioning_logs_by_customer, get_provisioning_jobs

    jobs = get_provisioning_jobs(customer_id)
    in_progress_job = None
    for job in jobs:
        if job['status'] == 'started':
            in_progress_job = job
            break

    if not in_progress_job:
        return jsonify({'logs': [], 'in_progress': False})

    logs = get_provisioning_logs_by_customer(customer_id, limit=100)

    for log in logs:
        for key in ['created_at']:
            if log.get(key):
                log[key] = log[key].isoformat()

    return jsonify({
        'logs': logs,
        'in_progress': True,
        'job_id': in_progress_job['job_id']
    })


# =============================================================================
# Fleet Health Dashboard API Endpoints
# =============================================================================

@admin_bp.route('/api/fleet/overview')
@admin_required
def api_fleet_overview():
    """
    Fleet health overview - summary statistics.

    Returns:
        JSON with total_customers, active_customers, customers_with_issues, critical_issues
    """
    conn = get_db_connection(read_only=True)
    cursor = conn.cursor(dictionary=True)

    try:
        # Get customer counts
        cursor.execute("""
            SELECT
                COUNT(*) as total_customers,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_customers
            FROM customers
        """)
        customer_counts = cursor.fetchone()

        # Get customers with open performance issues
        cursor.execute("""
            SELECT COUNT(DISTINCT customer_id) as customers_with_issues
            FROM performance_issues
            WHERE resolved_at IS NULL
        """)
        issues_result = cursor.fetchone()

        # Get critical issue count
        cursor.execute("""
            SELECT COUNT(*) as critical_issues
            FROM performance_issues
            WHERE resolved_at IS NULL AND severity = 'critical'
        """)
        critical_result = cursor.fetchone()

        return jsonify({
            'total_customers': customer_counts['total_customers'] or 0,
            'active_customers': customer_counts['active_customers'] or 0,
            'customers_with_issues': issues_result['customers_with_issues'] or 0,
            'critical_issues': critical_result['critical_issues'] or 0
        })
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/api/fleet/customers')
@admin_required
def api_fleet_customers():
    """
    Paginated customer list with performance metrics.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)
        sort_by: Column to sort by (default: health_score)
        sort_order: asc or desc (default: asc)
        health_filter: all, healthy, warning, critical (default: all)

    Returns:
        JSON with customers array and pagination info
    """
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(1, int(request.args.get('per_page', 20))))
    sort_by = request.args.get('sort_by', 'health_score')
    sort_order = request.args.get('sort_order', 'asc').lower()
    health_filter = request.args.get('health_filter', 'all').lower()

    # Validate sort_by to prevent SQL injection
    allowed_sort_columns = {
        'health_score': 'COALESCE(c.last_health_score, 0)',
        'domain': 'c.domain',
        'platform': 'c.platform',
        'cpu_percent': 'COALESCE(ps.cpu_percent, 0)',
        'memory_percent': 'COALESCE(ps.memory_percent, 0)',
        'open_issues_count': 'open_issues_count',
        'last_check': 'ps.timestamp'
    }
    sort_column = allowed_sort_columns.get(sort_by, 'COALESCE(c.last_health_score, 0)')
    sort_direction = 'DESC' if sort_order == 'desc' else 'ASC'

    # Build health filter condition
    health_condition = ""
    if health_filter == 'healthy':
        health_condition = "AND COALESCE(c.last_health_score, 0) >= 80"
    elif health_filter == 'warning':
        health_condition = "AND COALESCE(c.last_health_score, 0) >= 50 AND COALESCE(c.last_health_score, 0) < 80"
    elif health_filter == 'critical':
        health_condition = "AND COALESCE(c.last_health_score, 0) < 50"

    conn = get_db_connection(read_only=True)
    cursor = conn.cursor(dictionary=True)

    try:
        # Get total count with filter
        count_query = f"""
            SELECT COUNT(*) as total
            FROM customers c
            WHERE c.status = 'active' {health_condition}
        """
        cursor.execute(count_query)
        total = cursor.fetchone()['total']

        # Get paginated customers with latest performance snapshot and open issues count
        offset = (page - 1) * per_page
        query = f"""
            SELECT
                c.id,
                c.domain,
                c.platform,
                COALESCE(c.last_health_score, 0) as health_score,
                ps.cpu_percent,
                ps.memory_percent,
                ps.timestamp as last_check,
                COALESCE(issue_counts.open_issues_count, 0) as open_issues_count
            FROM customers c
            LEFT JOIN (
                SELECT ps1.customer_id, ps1.cpu_percent, ps1.memory_percent, ps1.timestamp
                FROM performance_snapshots ps1
                INNER JOIN (
                    SELECT customer_id, MAX(timestamp) as max_timestamp
                    FROM performance_snapshots
                    GROUP BY customer_id
                ) ps2 ON ps1.customer_id = ps2.customer_id AND ps1.timestamp = ps2.max_timestamp
            ) ps ON c.id = ps.customer_id
            LEFT JOIN (
                SELECT customer_id, COUNT(*) as open_issues_count
                FROM performance_issues
                WHERE resolved_at IS NULL
                GROUP BY customer_id
            ) issue_counts ON c.id = issue_counts.customer_id
            WHERE c.status = 'active' {health_condition}
            ORDER BY {sort_column} {sort_direction}
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (per_page, offset))
        customers = cursor.fetchall()

        # Convert datetime objects to strings
        for c in customers:
            if c.get('last_check'):
                c['last_check'] = c['last_check'].isoformat()
            # Convert Decimal to float for JSON serialization
            if c.get('cpu_percent') is not None:
                c['cpu_percent'] = float(c['cpu_percent'])
            if c.get('memory_percent') is not None:
                c['memory_percent'] = float(c['memory_percent'])

        return jsonify({
            'customers': customers,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 0
        })
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/api/fleet/health-distribution')
@admin_required
def api_fleet_health_distribution():
    """
    Health score distribution across the fleet.

    Returns:
        JSON with healthy_count, warning_count, critical_count
        - healthy: health_score >= 80
        - warning: health_score 50-79
        - critical: health_score < 50
    """
    conn = get_db_connection(read_only=True)
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                SUM(CASE WHEN COALESCE(last_health_score, 0) >= 80 THEN 1 ELSE 0 END) as healthy_count,
                SUM(CASE WHEN COALESCE(last_health_score, 0) >= 50 AND COALESCE(last_health_score, 0) < 80 THEN 1 ELSE 0 END) as warning_count,
                SUM(CASE WHEN COALESCE(last_health_score, 0) < 50 THEN 1 ELSE 0 END) as critical_count
            FROM customers
            WHERE status = 'active'
        """)
        result = cursor.fetchone()

        return jsonify({
            'healthy_count': result['healthy_count'] or 0,
            'warning_count': result['warning_count'] or 0,
            'critical_count': result['critical_count'] or 0
        })
    finally:
        cursor.close()
        conn.close()


# =============================================================================
# Admin Intervention Playbook API Endpoints
# =============================================================================

@admin_bp.route('/api/interventions')
@admin_required
def api_interventions():
    """
    List recent admin interventions across all customers.

    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)
        customer_id: Optional filter by customer ID

    Returns:
        JSON with interventions array and pagination info:
        {
            'interventions': [
                {
                    'id': int,
                    'customer_id': int,
                    'customer_domain': str,
                    'admin_email': str,
                    'playbook_name': str,
                    'executed_at': str (ISO format),
                    'success': bool,
                    'reason': str or null
                },
                ...
            ],
            'total': int,
            'page': int,
            'per_page': int,
            'total_pages': int
        }
    """
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(1, int(request.args.get('per_page', 20))))
    customer_id = request.args.get('customer_id')

    conn = get_db_connection(read_only=True)
    cursor = conn.cursor(dictionary=True)

    try:
        # Build query with optional customer filter
        where_clause = ""
        params = []
        if customer_id:
            where_clause = "WHERE ai.customer_id = %s"
            params.append(int(customer_id))

        # Get total count
        count_query = f"""
            SELECT COUNT(*) as total
            FROM admin_interventions ai
            {where_clause}
        """
        cursor.execute(count_query, tuple(params) if params else ())
        total = cursor.fetchone()['total']

        # Get paginated interventions with related data
        offset = (page - 1) * per_page
        query = f"""
            SELECT
                ai.id,
                ai.customer_id,
                ai.admin_user_id,
                ai.playbook_name,
                ai.executed_at,
                ai.reason,
                ai.result,
                c.domain as customer_domain,
                au.email as admin_email
            FROM admin_interventions ai
            JOIN customers c ON ai.customer_id = c.id
            JOIN admin_users au ON ai.admin_user_id = au.id
            {where_clause}
            ORDER BY ai.executed_at DESC
            LIMIT %s OFFSET %s
        """
        query_params = params + [per_page, offset]
        cursor.execute(query, tuple(query_params))
        rows = cursor.fetchall()

        interventions = []
        for row in rows:
            # Parse result JSON to extract success status
            result_data = row.get('result')
            success = False
            if result_data:
                import json
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except json.JSONDecodeError:
                        result_data = {}
                success = result_data.get('success', False)

            interventions.append({
                'id': row['id'],
                'customer_id': row['customer_id'],
                'customer_domain': row.get('customer_domain'),
                'admin_email': row.get('admin_email'),
                'playbook_name': row['playbook_name'],
                'executed_at': row['executed_at'].isoformat() if row.get('executed_at') else None,
                'success': success,
                'reason': row.get('reason')
            })

        return jsonify({
            'interventions': interventions,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 0
        })
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/api/intervention/<int:customer_id>/<playbook_name>', methods=['POST'])
@admin_required
def api_execute_intervention(customer_id, playbook_name):
    """
    Execute an admin intervention playbook on a customer.

    URL Parameters:
        customer_id: The customer ID to run the playbook on
        playbook_name: Name of the playbook to execute
            - optimize_store: Full optimization pass
            - emergency_stabilize: Emergency stabilization
            - clear_caches: Clear all caches
            - restart_services: Restart PHP-FPM and related services

    Request Body (JSON):
        {
            "reason": "Optional reason text for the intervention"
        }

    Returns:
        JSON with playbook execution result:
        {
            'success': bool,
            'playbook_name': str,
            'customer_id': int,
            'executed_by': int,
            'actions': [
                {'name': str, 'success': bool, 'message': str, 'duration_ms': int},
                ...
            ],
            'error': str or null,
            'duration_ms': int
        }
    """
    from webapp.performance.admin_playbooks import execute_admin_playbook

    admin_user_id = session.get('admin_user_id')
    if not admin_user_id:
        return jsonify({'error': 'Admin user not authenticated'}), 401

    # Get optional reason from request body
    reason = None
    if request.is_json and request.json:
        reason = request.json.get('reason')

    # Execute the playbook
    result = execute_admin_playbook(
        customer_id=customer_id,
        admin_user_id=admin_user_id,
        playbook_name=playbook_name,
        reason=reason
    )

    # Return appropriate status code based on success
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code


@admin_bp.route('/api/playbooks')
@admin_required
def api_playbooks():
    """
    List available admin intervention playbooks.

    Returns:
        JSON with list of available playbooks:
        {
            'playbooks': [
                {'name': 'optimize_store', 'description': '...'},
                {'name': 'emergency_stabilize', 'description': '...'},
                {'name': 'clear_caches', 'description': '...'},
                {'name': 'restart_services', 'description': '...'}
            ]
        }
    """
    from webapp.performance.admin_playbooks import get_available_playbooks

    playbooks = get_available_playbooks()
    return jsonify({'playbooks': playbooks})
