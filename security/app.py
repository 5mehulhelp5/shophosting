"""Security Dashboard Flask Application.

Factory-pattern Flask application with authentication, API endpoints,
and real-time WebSocket support for the security dashboard.
"""
import os
import json
import functools
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, g, Response
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from werkzeug.security import check_password_hash

import mysql.connector
from redis import Redis
from rq import Queue

from config import config as app_config
from models import (
    get_db, init_db, close_db, SecurityEvent, MalwareScan, PentestScan,
    Lockdown, QuarantinedFile, BlockedIP, Fail2BanEvent, WPScanRecord, WAFEvent
)
from jobs import run_malware_scan, run_pentest_scan, run_wpscan
from scanners.fail2ban import Fail2BanMonitor
from reports.pentest_pdf import generate_pentest_pdf

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
socketio = SocketIO()


def login_required(f):
    """Decorator to require authentication for a route."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def create_app(config_name=None):
    """Application factory.

    Args:
        config_name: Configuration to use ('development', 'production', 'testing').
                     Defaults to FLASK_ENV environment variable or 'development'.

    Returns:
        Configured Flask application instance.
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    app.config.from_object(app_config[config_name])

    # Initialize extensions
    csrf.init_app(app)
    limiter.init_app(app)
    socketio.init_app(app, async_mode='eventlet', cors_allowed_origins='*')

    # Redis queue for background scan jobs
    redis_conn = Redis.from_url(app.config.get('REDIS_URL', 'redis://localhost:6379/1'))
    scan_queue = Queue('security-scans', connection=redis_conn)

    # ----------------------------------------------------------------
    # Database lifecycle
    # ----------------------------------------------------------------
    @app.before_request
    def before_request():
        g.db = get_db()

    @app.teardown_appcontext
    def teardown_db(exception):
        close_db()

    # ----------------------------------------------------------------
    # Page routes (all require login except /login)
    # ----------------------------------------------------------------
    @app.route('/')
    @login_required
    def index():
        return redirect(url_for('threat_center'))

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit("10 per minute")
    def login():
        error = None
        if request.method == 'POST':
            email = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            # Authenticate against main webapp MySQL admin_users table
            row = None
            try:
                conn = mysql.connector.connect(
                    host=app.config['MYSQL_HOST'],
                    user=app.config['MYSQL_USER'],
                    password=app.config['MYSQL_PASSWORD'],
                    database=app.config['MYSQL_DB']
                )
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, email, password_hash, full_name, role FROM admin_users WHERE email = %s AND is_active = 1",
                    (email,)
                )
                row = cursor.fetchone()
                cursor.close()
                conn.close()
            except mysql.connector.Error as e:
                app.logger.error(f'MySQL auth error: {e}')

            if row and check_password_hash(row['password_hash'], password):
                session['admin_id'] = row['id']
                session['admin_user'] = row['full_name']
                session['admin_email'] = row['email']
                session['admin_role'] = row['role']
                session.permanent = True

                SecurityEvent.create(
                    event_type='auth',
                    severity='low',
                    source='dashboard',
                    message=f'Admin login: {row["full_name"]} ({email})',
                    metadata={'ip': request.remote_addr}
                )
                return redirect(url_for('threat_center'))

            error = 'Invalid credentials'
            SecurityEvent.create(
                event_type='auth',
                severity='medium',
                source='dashboard',
                message=f'Failed login attempt: {email}',
                metadata={'ip': request.remote_addr}
            )

        return render_template('login.html', error=error)

    @app.route('/logout')
    def logout():
        admin_user = session.get('admin_user', 'unknown')
        session.clear()
        SecurityEvent.create(
            event_type='auth',
            severity='low',
            source='dashboard',
            message=f'Admin logout: {admin_user}'
        )
        return redirect(url_for('login'))

    @app.route('/threat-center')
    @login_required
    def threat_center():
        return render_template('threat_center.html')

    @app.route('/malware')
    @login_required
    def malware():
        return render_template('malware_scans.html')

    @app.route('/pentest')
    @login_required
    def pentest():
        return render_template('pentest_scans.html')

    @app.route('/lockdown')
    @login_required
    def lockdown():
        return render_template('lockdown_control.html')

    @app.route('/history')
    @login_required
    def history():
        return render_template('history.html')

    @app.route('/malware/<int:scan_id>')
    @login_required
    def malware_report(scan_id):
        scan = MalwareScan.get_by_id(scan_id)
        if not scan:
            return render_template('error.html', code=404, message='Scan not found'), 404
        if scan.get('results'):
            try:
                scan['parsed_results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_results'] = {}
        else:
            scan['parsed_results'] = {}
        return render_template('malware_report.html', scan=scan)

    @app.route('/pentest/<int:scan_id>')
    @login_required
    def pentest_report(scan_id):
        scan = PentestScan.get_by_id(scan_id)
        if not scan:
            return render_template('error.html', code=404, message='Scan not found'), 404
        if scan.get('results'):
            try:
                scan['parsed_results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_results'] = {}
        else:
            scan['parsed_results'] = {}
        if scan.get('tools_used'):
            try:
                scan['parsed_tools'] = json.loads(scan['tools_used'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_tools'] = []
        else:
            scan['parsed_tools'] = []
        return render_template('pentest_report.html', scan=scan)

    @app.route('/pentest/<int:scan_id>/pdf')
    @login_required
    def pentest_report_pdf(scan_id):
        scan = PentestScan.get_by_id(scan_id)
        if not scan:
            return render_template('error.html', code=404, message='Scan not found'), 404
        if scan.get('results'):
            try:
                scan['parsed_results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_results'] = {}
        else:
            scan['parsed_results'] = {}
        if scan.get('tools_used'):
            try:
                scan['parsed_tools'] = json.loads(scan['tools_used'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_tools'] = []
        else:
            scan['parsed_tools'] = []
        pdf_bytes = generate_pentest_pdf(scan)
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="pentest-scan-{scan_id}.pdf"'
            }
        )

    @app.route('/fail2ban')
    @login_required
    def fail2ban_page():
        return render_template('fail2ban.html')

    @app.route('/wpscan')
    @login_required
    def wpscan_page():
        return render_template('wpscan.html')

    @app.route('/wpscan/<int:scan_id>')
    @login_required
    def wpscan_report(scan_id):
        scan = WPScanRecord.get_by_id(scan_id)
        if not scan:
            return render_template('error.html', code=404, message='Scan not found'), 404
        if scan.get('results'):
            try:
                scan['parsed_results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                scan['parsed_results'] = {}
        else:
            scan['parsed_results'] = {}
        return render_template('wpscan_report.html', scan=scan)

    @app.route('/waf')
    @login_required
    def waf_page():
        return render_template('waf.html')

    # ----------------------------------------------------------------
    # API routes
    # ----------------------------------------------------------------

    @app.route('/api/health')
    @csrf.exempt
    def api_health():
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat()
        })

    @app.route('/api/status')
    @csrf.exempt
    @login_required
    def api_status():
        active_lockdowns = Lockdown.get_active()
        blocked_ips = BlockedIP.get_active()
        quarantined = QuarantinedFile.get_active()
        events = SecurityEvent.get_recent(limit=10)
        severity_counts = SecurityEvent.count_by_severity(hours=24)

        # Determine threat level from recent events
        if severity_counts.get('critical', 0) > 0:
            threat_level = 'critical'
        elif severity_counts.get('high', 0) > 0:
            threat_level = 'high'
        elif severity_counts.get('medium', 0) > 0:
            threat_level = 'medium'
        else:
            threat_level = 'low'

        # Fail2Ban and WAF counts for status
        try:
            f2b_bans_24h = Fail2BanEvent.count_total(hours=24)
        except Exception:
            f2b_bans_24h = 0
        try:
            waf_blocks_24h = WAFEvent.count_total(hours=24)
        except Exception:
            waf_blocks_24h = 0

        return jsonify({
            'threat_level': threat_level,
            'active_lockdowns': len(active_lockdowns),
            'blocked_ips': len(blocked_ips),
            'quarantined_files': len(quarantined),
            'recent_events': events,
            'severity_counts': severity_counts,
            'fail2ban_bans_24h': f2b_bans_24h,
            'waf_blocks_24h': waf_blocks_24h,
        })

    @app.route('/api/scans/malware', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_malware_scan():
        data = request.get_json(force=True)
        target = data.get('target')
        scan_type = data.get('scan_type', 'quick')

        if not target:
            return jsonify({'error': 'target is required'}), 400

        scan = MalwareScan.create(scan_type=scan_type, target=target)

        SecurityEvent.create(
            event_type='scan',
            severity='low',
            source='dashboard',
            message=f'Malware scan initiated: {scan_type} on {target}',
            metadata={'scan_id': scan['id']}
        )

        job = scan_queue.enqueue(
            run_malware_scan,
            scan['id'], target, scan_type,
            job_timeout=1800
        )

        return jsonify({
            'scan_id': scan['id'],
            'job_id': job.id,
            'status': 'queued',
            'message': f'Malware scan queued: {scan_type} on {target}'
        }), 202

    @app.route('/api/scans/pentest', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_pentest_scan():
        data = request.get_json(force=True)
        target_url = data.get('target_url')
        profile = data.get('profile', 'baseline')

        if not target_url:
            return jsonify({'error': 'target_url is required'}), 400

        scan = PentestScan.create(scan_profile=profile, target_url=target_url)

        SecurityEvent.create(
            event_type='scan',
            severity='low',
            source='dashboard',
            message=f'Pentest scan initiated: {profile} on {target_url}',
            metadata={'scan_id': scan['id']}
        )

        job = scan_queue.enqueue(
            run_pentest_scan,
            scan['id'], target_url, profile,
            job_timeout=1800
        )

        return jsonify({
            'scan_id': scan['id'],
            'job_id': job.id,
            'status': 'queued',
            'message': f'Pentest scan queued: {profile} on {target_url}'
        }), 202

    @app.route('/api/lockdown/container', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_lockdown_container():
        data = request.get_json(force=True)
        container = data.get('container')
        action = data.get('action', 'isolate')

        if not container:
            return jsonify({'error': 'container is required'}), 400

        admin_user = session.get('admin_user', 'system')

        lockdown_record = Lockdown.create(
            lockdown_type='container',
            target=container,
            reason=f'Manual {action} via dashboard',
            initiated_by=admin_user
        )

        SecurityEvent.create(
            event_type='lockdown',
            severity='high',
            source='dashboard',
            message=f'Container lockdown: {action} on {container}',
            metadata={'lockdown_id': lockdown_record['id'], 'action': action}
        )

        # TODO: Call ContainerLockdown engine
        # ContainerLockdown(container).isolate()

        return jsonify({
            'lockdown_id': lockdown_record['id'],
            'status': 'active',
            'message': f'Container {container} locked down ({action})'
        })

    @app.route('/api/lockdown/block-ip', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_block_ip():
        data = request.get_json(force=True)
        ip = data.get('ip')
        reason = data.get('reason', 'Manual block via dashboard')

        if not ip:
            return jsonify({'error': 'ip is required'}), 400

        # Check if already blocked
        existing = BlockedIP.get_by_ip(ip)
        if existing:
            return jsonify({'error': f'IP {ip} is already blocked'}), 409

        admin_user = session.get('admin_user', 'system')
        blocked = BlockedIP.create(
            ip_address=ip,
            reason=reason,
            blocked_by=admin_user
        )

        SecurityEvent.create(
            event_type='lockdown',
            severity='high',
            source='dashboard',
            message=f'IP blocked: {ip}',
            metadata={'blocked_ip_id': blocked['id'], 'reason': reason}
        )

        # TODO: Call NetworkLockdown engine
        # NetworkLockdown().block_ip(ip)

        return jsonify({
            'blocked_ip_id': blocked['id'],
            'status': 'blocked',
            'message': f'IP {ip} has been blocked'
        })

    @app.route('/api/lockdown/release', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_lockdown_release():
        data = request.get_json(force=True)
        container = data.get('container')

        if not container:
            return jsonify({'error': 'container is required'}), 400

        admin_user = session.get('admin_user', 'system')

        # Find active lockdown for this container
        db = get_db()
        row = db.execute(
            "SELECT * FROM lockdowns WHERE target = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (container,)
        ).fetchone()

        if not row:
            return jsonify({'error': f'No active lockdown found for {container}'}), 404

        Lockdown.release(row['id'], released_by=admin_user)

        SecurityEvent.create(
            event_type='lockdown',
            severity='medium',
            source='dashboard',
            message=f'Lockdown released: {container}',
            metadata={'lockdown_id': row['id']}
        )

        # TODO: Call ContainerLockdown release
        # ContainerLockdown(container).release()

        return jsonify({
            'lockdown_id': row['id'],
            'status': 'released',
            'message': f'Lockdown on {container} has been released'
        })

    @app.route('/api/events')
    @csrf.exempt
    @login_required
    def api_events():
        limit = request.args.get('limit', 50, type=int)
        event_type = request.args.get('type')
        severity = request.args.get('severity')

        events = SecurityEvent.get_recent(
            limit=min(limit, 200),
            event_type=event_type,
            severity=severity
        )

        return jsonify({
            'events': events,
            'count': len(events)
        })

    @app.route('/api/malware/scans')
    @csrf.exempt
    @login_required
    def api_malware_scans_list():
        limit = request.args.get('limit', 20, type=int)
        scans = MalwareScan.get_recent(limit=min(limit, 100))
        return jsonify({'scans': scans, 'count': len(scans)})

    @app.route('/api/pentest/scans')
    @csrf.exempt
    @login_required
    def api_pentest_scans_list():
        limit = request.args.get('limit', 20, type=int)
        scans = PentestScan.get_recent(limit=min(limit, 100))
        return jsonify({'scans': scans, 'count': len(scans)})

    @app.route('/api/scans/malware/<int:scan_id>')
    @csrf.exempt
    @login_required
    def api_malware_scan_detail(scan_id):
        scan = MalwareScan.get_by_id(scan_id)
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        if scan.get('results'):
            try:
                scan['results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify({'scan': scan})

    @app.route('/api/scans/pentest/<int:scan_id>')
    @csrf.exempt
    @login_required
    def api_pentest_scan_detail(scan_id):
        scan = PentestScan.get_by_id(scan_id)
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        if scan.get('results'):
            try:
                scan['results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                pass
        if scan.get('tools_used'):
            try:
                scan['tools_used'] = json.loads(scan['tools_used'])
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify({'scan': scan})

    # ----------------------------------------------------------------
    # Fail2Ban API routes
    # ----------------------------------------------------------------

    @app.route('/api/fail2ban/status')
    @csrf.exempt
    @login_required
    def api_fail2ban_status():
        monitor = Fail2BanMonitor()
        jails = monitor.get_all_jails()
        statuses = []
        for jail in jails:
            statuses.append(monitor.get_jail_status(jail))
        return jsonify({'jails': statuses, 'count': len(statuses)})

    @app.route('/api/fail2ban/jail/<name>')
    @csrf.exempt
    @login_required
    def api_fail2ban_jail(name):
        monitor = Fail2BanMonitor()
        status = monitor.get_jail_status(name)
        return jsonify(status)

    @app.route('/api/fail2ban/events')
    @csrf.exempt
    @login_required
    def api_fail2ban_events():
        limit = request.args.get('limit', 50, type=int)
        jail = request.args.get('jail')
        events = Fail2BanEvent.get_recent(limit=min(limit, 200), jail=jail)
        return jsonify({'events': events, 'count': len(events)})

    @app.route('/api/fail2ban/ban', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_fail2ban_ban():
        data = request.get_json(force=True)
        jail = data.get('jail')
        ip = data.get('ip')
        if not jail or not ip:
            return jsonify({'error': 'jail and ip are required'}), 400
        monitor = Fail2BanMonitor()
        success = monitor.ban_ip(jail, ip)
        if success:
            admin_user = session.get('admin_user', 'system')
            SecurityEvent.create(
                event_type='fail2ban_manual_ban',
                severity='medium',
                source='dashboard',
                message=f'Manual ban: {ip} in [{jail}] by {admin_user}',
                metadata={'jail': jail, 'ip': ip, 'by': admin_user}
            )
            return jsonify({'status': 'banned', 'ip': ip, 'jail': jail})
        return jsonify({'error': f'Failed to ban {ip} in {jail}'}), 500

    @app.route('/api/fail2ban/unban', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_fail2ban_unban():
        data = request.get_json(force=True)
        jail = data.get('jail')
        ip = data.get('ip')
        if not jail or not ip:
            return jsonify({'error': 'jail and ip are required'}), 400
        monitor = Fail2BanMonitor()
        success = monitor.unban_ip(jail, ip)
        if success:
            admin_user = session.get('admin_user', 'system')
            SecurityEvent.create(
                event_type='fail2ban_manual_unban',
                severity='low',
                source='dashboard',
                message=f'Manual unban: {ip} from [{jail}] by {admin_user}',
                metadata={'jail': jail, 'ip': ip, 'by': admin_user}
            )
            return jsonify({'status': 'unbanned', 'ip': ip, 'jail': jail})
        return jsonify({'error': f'Failed to unban {ip} from {jail}'}), 500

    # ----------------------------------------------------------------
    # WPScan API routes
    # ----------------------------------------------------------------

    @app.route('/api/scans/wpscan', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_wpscan_scan():
        data = request.get_json(force=True)
        target_url = data.get('target_url')
        profile = data.get('profile', 'standard')
        if not target_url:
            return jsonify({'error': 'target_url is required'}), 400

        scan = WPScanRecord.create(scan_profile=profile, target_url=target_url)
        SecurityEvent.create(
            event_type='scan',
            severity='low',
            source='dashboard',
            message=f'WPScan initiated: {profile} on {target_url}',
            metadata={'scan_id': scan['id']}
        )
        job = scan_queue.enqueue(
            run_wpscan,
            scan['id'], target_url, profile,
            job_timeout=1800
        )
        return jsonify({
            'scan_id': scan['id'],
            'job_id': job.id,
            'status': 'queued',
            'message': f'WPScan queued: {profile} on {target_url}'
        }), 202

    @app.route('/api/wpscan/scans')
    @csrf.exempt
    @login_required
    def api_wpscan_scans_list():
        limit = request.args.get('limit', 20, type=int)
        scans = WPScanRecord.get_recent(limit=min(limit, 100))
        return jsonify({'scans': scans, 'count': len(scans)})

    @app.route('/api/scans/wpscan/<int:scan_id>')
    @csrf.exempt
    @login_required
    def api_wpscan_scan_detail(scan_id):
        scan = WPScanRecord.get_by_id(scan_id)
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        if scan.get('results'):
            try:
                scan['results'] = json.loads(scan['results'])
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify({'scan': scan})

    # ----------------------------------------------------------------
    # WAF API routes
    # ----------------------------------------------------------------

    @app.route('/api/waf/events')
    @csrf.exempt
    @login_required
    def api_waf_events():
        limit = request.args.get('limit', 50, type=int)
        events = WAFEvent.get_recent(limit=min(limit, 200))
        return jsonify({'events': events, 'count': len(events)})

    @app.route('/api/waf/stats')
    @csrf.exempt
    @login_required
    def api_waf_stats():
        return jsonify({
            'total_blocks_24h': WAFEvent.count_total(hours=24),
            'top_rules': WAFEvent.count_by_rule(hours=24),
            'top_ips': WAFEvent.count_by_ip(hours=24),
        })

    # ----------------------------------------------------------------
    # Error handlers
    # ----------------------------------------------------------------
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('error.html', code=404, message='Page not found'), 404

    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('error.html', code=500, message='Internal server error'), 500

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'CSRF token missing or invalid'}), 400
        return render_template('error.html', code=400, message='CSRF token missing or invalid'), 400

    return app


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        init_db()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
