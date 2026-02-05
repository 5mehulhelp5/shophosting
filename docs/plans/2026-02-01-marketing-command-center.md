# Marketing Command Center Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a proprietary marketing module with Claude AI integration, KPI dashboards, content generation, and multi-platform publishing.

**Architecture:** Flask nested blueprint under `/admin/marketing`, with Claude SDK for web chat and MCP server for CLI access. All files gitignored for proprietary protection. New `marketing` role with granular permissions, `super_admin` inherits all.

**Tech Stack:** Flask, MySQL (raw queries matching existing patterns), Redis/RQ for background tasks, Anthropic Claude SDK, WeasyPrint for PDFs, platform APIs (Twitter, Mailchimp, Buffer).

---

## Phase 1: Foundation

### Task 1: Add Gitignore Rules

**Files:**
- Modify: `/opt/shophosting/.gitignore`

**Step 1: Add marketing gitignore rules**

Add to `.gitignore`:
```gitignore
# ===================
# Marketing Module (Proprietary)
# ===================

# All marketing code
webapp/admin/marketing/

# Marketing templates
webapp/templates/admin/marketing/

# Marketing documentation
docs/plans/*-marketing-*.md

# MCP config (contains marketing server)
.mcp.json

# Generated reports
webapp/admin/marketing/reports/*.pdf
```

**Step 2: Verify gitignore works**

Run: `git status`
Expected: This plan file should now show as untracked (if it was added before gitignore)

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add gitignore rules for proprietary marketing module

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Add Marketing Role to Admin Models

**Files:**
- Modify: `/opt/shophosting/webapp/admin/models.py:21-36`

**Step 1: Update ADMIN_ROLES list**

Change lines 21-27 from:
```python
ADMIN_ROLES = [
    'super_admin',    # Everything - full system access including settings
    'admin',          # Everything except system settings
    'finance_admin',  # Billing & revenue only (read-only)
    'acquisition',    # Leads & migration previews only (NEW - for sales/marketing)
    'support',        # Tickets & limited refunds
]
```

To:
```python
ADMIN_ROLES = [
    'super_admin',    # Everything - full system access including settings
    'admin',          # Everything except system settings
    'marketing',      # Marketing Command Center access
    'finance_admin',  # Billing & revenue only (read-only)
    'acquisition',    # Leads & migration previews only (for sales)
    'support',        # Tickets & limited refunds
]
```

**Step 2: Update ROLE_DESCRIPTIONS**

Change lines 29-36 from:
```python
ROLE_DESCRIPTIONS = {
    'super_admin': 'Full system access including settings',
    'admin': 'Full access except system settings',
    'finance_admin': 'Billing and revenue (read-only)',
    'acquisition': 'Leads and migration previews only',
    'support': 'Tickets and limited refunds',
}
```

To:
```python
ROLE_DESCRIPTIONS = {
    'super_admin': 'Full system access including settings',
    'admin': 'Full access except system settings',
    'marketing': 'Marketing Command Center - content, analytics, campaigns',
    'finance_admin': 'Billing and revenue (read-only)',
    'acquisition': 'Leads and migration previews only',
    'support': 'Tickets and limited refunds',
}
```

**Step 3: Verify no syntax errors**

Run: `cd /opt/shophosting && python -c "from webapp.admin.models import ADMIN_ROLES, ROLE_DESCRIPTIONS; print(ADMIN_ROLES); print(ROLE_DESCRIPTIONS)"`
Expected: Lists printed with 'marketing' included

**Step 4: Commit**

```bash
git add webapp/admin/models.py
git commit -m "feat(admin): add marketing role to admin roles

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Add Marketing Decorator to Admin Routes

**Files:**
- Modify: `/opt/shophosting/webapp/admin/routes.py:81-90`

**Step 1: Add marketing_or_admin_required decorator**

After the `acquisition_or_admin_required` decorator (after line 90), add:

```python


def marketing_or_admin_required(f):
    """Require marketing, admin, or super_admin role for Marketing Command Center access"""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = session.get('admin_user_role')
        if role not in ['marketing', 'admin', 'super_admin']:
            flash('This action requires marketing or admin privileges.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated
```

**Step 2: Verify import works**

Run: `cd /opt/shophosting && python -c "from webapp.admin.routes import marketing_or_admin_required; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add webapp/admin/routes.py
git commit -m "feat(admin): add marketing_or_admin_required decorator

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 4: Create Database Tables

**Files:**
- Create: `/opt/shophosting/migrations/add_marketing_tables.sql`

**Step 1: Write migration SQL**

```sql
-- Marketing Command Center Tables
-- Run: mysql -u root -p shophosting < migrations/add_marketing_tables.sql

-- Content Library
CREATE TABLE IF NOT EXISTS marketing_content (
    id INT AUTO_INCREMENT PRIMARY KEY,
    content_type ENUM('blog_post', 'reddit_post', 'twitter_post',
                      'linkedin_post', 'email', 'ad_copy', 'pdf_report') NOT NULL,
    title VARCHAR(255),
    body TEXT,
    markdown TEXT,
    html TEXT,
    pdf_path VARCHAR(500),

    campaign_id INT,
    segment ENUM('budget_refugees', 'time_starved', 'growth_stage', 'tech_conscious'),
    content_pillar ENUM('troubleshooting', 'comparison', 'success_stories', 'how_to'),

    status ENUM('draft', 'approved', 'scheduled', 'published', 'archived') DEFAULT 'draft',
    scheduled_for TIMESTAMP NULL,
    published_at TIMESTAMP NULL,
    published_url VARCHAR(500),
    platform VARCHAR(50),

    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_status (status),
    INDEX idx_content_type (content_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Campaigns
CREATE TABLE IF NOT EXISTS marketing_campaigns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    campaign_type ENUM('speed_battle_promo', 'migration_offer',
                       'thought_leadership', 'custom') NOT NULL,
    status ENUM('planning', 'active', 'paused', 'completed') DEFAULT 'planning',
    start_date DATE,
    end_date DATE,
    goals JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add foreign key for campaign_id
ALTER TABLE marketing_content
ADD CONSTRAINT fk_content_campaign
FOREIGN KEY (campaign_id) REFERENCES marketing_campaigns(id) ON DELETE SET NULL;

-- Task Queue
CREATE TABLE IF NOT EXISTS marketing_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_type ENUM('generate_content', 'analyze_kpis', 'draft_email_sequence',
                   'publish', 'report', 'review_draft') NOT NULL,
    description TEXT,
    priority ENUM('low', 'normal', 'high', 'urgent') DEFAULT 'normal',
    status ENUM('pending', 'in_progress', 'awaiting_approval',
                'approved', 'completed', 'failed') DEFAULT 'pending',

    input_data JSON,
    output_content_id INT,

    scheduled_for TIMESTAMP NULL,
    due_date TIMESTAMP NULL,
    assigned_to ENUM('claude', 'human'),

    created_by INT,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_status (status),
    INDEX idx_priority (priority),
    INDEX idx_scheduled (scheduled_for),

    CONSTRAINT fk_task_content
    FOREIGN KEY (output_content_id) REFERENCES marketing_content(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- KPI Snapshots
CREATE TABLE IF NOT EXISTS marketing_kpis (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source ENUM('google_analytics', 'search_console', 'google_ads',
                'mailchimp', 'speed_battle', 'stripe', 'social') NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(15,2),
    metric_meta JSON,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_source_metric (source, metric_name),
    INDEX idx_recorded (recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Chat history for context preservation
CREATE TABLE IF NOT EXISTS marketing_chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    admin_user_id INT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_session (session_id),
    INDEX idx_admin_user (admin_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Step 2: Run migration**

Run: `mysql -u root -p shophosting < /opt/shophosting/migrations/add_marketing_tables.sql`
Expected: No errors

**Step 3: Verify tables created**

Run: `mysql -u root -p -e "SHOW TABLES LIKE 'marketing%'" shophosting`
Expected: 5 tables listed

**Step 4: Commit migration file (not gitignored)**

```bash
git add migrations/add_marketing_tables.sql
git commit -m "feat(db): add marketing module database tables

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 5: Create Marketing Module Directory Structure

**Files:**
- Create: `/opt/shophosting/webapp/admin/marketing/__init__.py`
- Create: `/opt/shophosting/webapp/admin/marketing/models.py`
- Create: `/opt/shophosting/webapp/admin/marketing/routes.py`
- Create: `/opt/shophosting/webapp/templates/admin/marketing/` (directory)

**Step 1: Create directory structure**

Run:
```bash
mkdir -p /opt/shophosting/webapp/admin/marketing/integrations
mkdir -p /opt/shophosting/webapp/admin/marketing/publishers
mkdir -p /opt/shophosting/webapp/admin/marketing/context
mkdir -p /opt/shophosting/webapp/admin/marketing/reports
mkdir -p /opt/shophosting/webapp/templates/admin/marketing
```

**Step 2: Create __init__.py with permissions**

Create `/opt/shophosting/webapp/admin/marketing/__init__.py`:
```python
"""
Marketing Command Center Module
Proprietary - All files in this directory are gitignored
"""

from flask import Blueprint, session, redirect, url_for, flash
from functools import wraps

marketing_bp = Blueprint('marketing', __name__, url_prefix='/marketing')

# Marketing-specific permissions
MARKETING_PERMISSIONS = {
    'marketing.view_dashboard',
    'marketing.view_content',
    'marketing.create_content',
    'marketing.edit_content',
    'marketing.approve_content',
    'marketing.publish_content',
    'marketing.manage_campaigns',
    'marketing.view_tasks',
    'marketing.manage_tasks',
    'marketing.use_chat',
    'marketing.access_mcp',
    'marketing.manage_integrations',
}

# Role permission mapping
ROLE_PERMISSIONS = {
    'marketing': MARKETING_PERMISSIONS - {'marketing.manage_integrations'},
    'admin': MARKETING_PERMISSIONS,
    'super_admin': MARKETING_PERMISSIONS,
}


def has_marketing_permission(permission):
    """Check if current user has a marketing permission."""
    role = session.get('admin_user_role')
    if not role:
        return False

    if role == 'super_admin':
        return True

    role_perms = ROLE_PERMISSIONS.get(role, set())
    return permission in role_perms


def marketing_permission_required(permission):
    """Decorator for routes requiring specific marketing permission."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('admin_user_id'):
                flash('Please log in to access the admin panel.', 'error')
                return redirect(url_for('admin.login'))
            if not has_marketing_permission(permission):
                flash('You do not have permission for this action.', 'error')
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def marketing_required(f):
    """Decorator: requires marketing, admin, or super_admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_user_id'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))
        role = session.get('admin_user_role')
        if role not in ('marketing', 'admin', 'super_admin'):
            flash('This action requires marketing privileges.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# Import routes after blueprint is defined
from . import routes
```

**Step 3: Verify module imports**

Run: `cd /opt/shophosting && python -c "from webapp.admin.marketing import marketing_bp, marketing_required; print('OK')"`
Expected: `OK`

**Step 4: No git commit (gitignored)**

Note: These files are gitignored and won't be committed.

---

### Task 6: Create Marketing Models

**Files:**
- Create: `/opt/shophosting/webapp/admin/marketing/models.py`

**Step 1: Write models.py**

Create `/opt/shophosting/webapp/admin/marketing/models.py`:
```python
"""
Marketing Module Data Models
Uses raw MySQL queries to match existing codebase patterns
"""

import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from models import get_db_connection


class MarketingContent:
    """Content library model for marketing assets."""

    CONTENT_TYPES = ['blog_post', 'reddit_post', 'twitter_post',
                     'linkedin_post', 'email', 'ad_copy', 'pdf_report']
    SEGMENTS = ['budget_refugees', 'time_starved', 'growth_stage', 'tech_conscious']
    PILLARS = ['troubleshooting', 'comparison', 'success_stories', 'how_to']
    STATUSES = ['draft', 'approved', 'scheduled', 'published', 'archived']

    def __init__(self, id=None, content_type=None, title=None, body=None,
                 markdown=None, html=None, pdf_path=None, campaign_id=None,
                 segment=None, content_pillar=None, status='draft',
                 scheduled_for=None, published_at=None, published_url=None,
                 platform=None, created_by=None, created_at=None, updated_at=None):
        self.id = id
        self.content_type = content_type
        self.title = title
        self.body = body
        self.markdown = markdown
        self.html = html
        self.pdf_path = pdf_path
        self.campaign_id = campaign_id
        self.segment = segment
        self.content_pillar = content_pillar
        self.status = status
        self.scheduled_for = scheduled_for
        self.published_at = published_at
        self.published_url = published_url
        self.platform = platform
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at

    def save(self):
        """Insert or update content."""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if self.id:
                cursor.execute("""
                    UPDATE marketing_content SET
                        content_type = %s, title = %s, body = %s, markdown = %s,
                        html = %s, pdf_path = %s, campaign_id = %s, segment = %s,
                        content_pillar = %s, status = %s, scheduled_for = %s,
                        published_at = %s, published_url = %s, platform = %s
                    WHERE id = %s
                """, (self.content_type, self.title, self.body, self.markdown,
                      self.html, self.pdf_path, self.campaign_id, self.segment,
                      self.content_pillar, self.status, self.scheduled_for,
                      self.published_at, self.published_url, self.platform, self.id))
            else:
                cursor.execute("""
                    INSERT INTO marketing_content
                    (content_type, title, body, markdown, html, pdf_path, campaign_id,
                     segment, content_pillar, status, scheduled_for, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (self.content_type, self.title, self.body, self.markdown,
                      self.html, self.pdf_path, self.campaign_id, self.segment,
                      self.content_pillar, self.status, self.scheduled_for, self.created_by))
                self.id = cursor.lastrowid

            conn.commit()
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_by_id(content_id):
        """Get content by ID."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("SELECT * FROM marketing_content WHERE id = %s", (content_id,))
            row = cursor.fetchone()
            return MarketingContent(**row) if row else None
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_all(status=None, content_type=None, limit=50, offset=0):
        """Get all content with optional filters."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            conditions = []
            params = []

            if status and status != 'all':
                conditions.append("status = %s")
                params.append(status)
            if content_type and content_type != 'all':
                conditions.append("content_type = %s")
                params.append(content_type)

            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

            cursor.execute(f"""
                SELECT * FROM marketing_content
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])

            rows = cursor.fetchall()
            return [MarketingContent(**row) for row in rows]
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_recent(limit=10):
        """Get most recent content."""
        return MarketingContent.get_all(limit=limit)

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'content_type': self.content_type,
            'title': self.title,
            'body': self.body,
            'markdown': self.markdown,
            'status': self.status,
            'segment': self.segment,
            'content_pillar': self.content_pillar,
            'platform': self.platform,
            'published_url': self.published_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class MarketingCampaign:
    """Campaign model."""

    TYPES = ['speed_battle_promo', 'migration_offer', 'thought_leadership', 'custom']
    STATUSES = ['planning', 'active', 'paused', 'completed']

    def __init__(self, id=None, name=None, campaign_type=None, status='planning',
                 start_date=None, end_date=None, goals=None, created_at=None):
        self.id = id
        self.name = name
        self.campaign_type = campaign_type
        self.status = status
        self.start_date = start_date
        self.end_date = end_date
        self.goals = goals if goals else {}
        self.created_at = created_at

    def save(self):
        """Insert or update campaign."""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            goals_json = json.dumps(self.goals) if isinstance(self.goals, dict) else self.goals

            if self.id:
                cursor.execute("""
                    UPDATE marketing_campaigns SET
                        name = %s, campaign_type = %s, status = %s,
                        start_date = %s, end_date = %s, goals = %s
                    WHERE id = %s
                """, (self.name, self.campaign_type, self.status,
                      self.start_date, self.end_date, goals_json, self.id))
            else:
                cursor.execute("""
                    INSERT INTO marketing_campaigns
                    (name, campaign_type, status, start_date, end_date, goals)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (self.name, self.campaign_type, self.status,
                      self.start_date, self.end_date, goals_json))
                self.id = cursor.lastrowid

            conn.commit()
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_by_id(campaign_id):
        """Get campaign by ID."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("SELECT * FROM marketing_campaigns WHERE id = %s", (campaign_id,))
            row = cursor.fetchone()
            if row:
                if row.get('goals') and isinstance(row['goals'], str):
                    row['goals'] = json.loads(row['goals'])
                return MarketingCampaign(**row)
            return None
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_active():
        """Get active campaigns."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM marketing_campaigns
                WHERE status = 'active'
                ORDER BY start_date DESC
            """)
            rows = cursor.fetchall()
            campaigns = []
            for row in rows:
                if row.get('goals') and isinstance(row['goals'], str):
                    row['goals'] = json.loads(row['goals'])
                campaigns.append(MarketingCampaign(**row))
            return campaigns
        finally:
            cursor.close()
            conn.close()


class MarketingTask:
    """Task queue model."""

    TYPES = ['generate_content', 'analyze_kpis', 'draft_email_sequence',
             'publish', 'report', 'review_draft']
    PRIORITIES = ['low', 'normal', 'high', 'urgent']
    STATUSES = ['pending', 'in_progress', 'awaiting_approval',
                'approved', 'completed', 'failed']

    def __init__(self, id=None, task_type=None, description=None,
                 priority='normal', status='pending', input_data=None,
                 output_content_id=None, scheduled_for=None, due_date=None,
                 assigned_to=None, created_by=None, completed_at=None, created_at=None):
        self.id = id
        self.task_type = task_type
        self.description = description
        self.priority = priority
        self.status = status
        self.input_data = input_data if input_data else {}
        self.output_content_id = output_content_id
        self.scheduled_for = scheduled_for
        self.due_date = due_date
        self.assigned_to = assigned_to
        self.created_by = created_by
        self.completed_at = completed_at
        self.created_at = created_at

    def save(self):
        """Insert or update task."""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            input_json = json.dumps(self.input_data) if isinstance(self.input_data, dict) else self.input_data

            if self.id:
                cursor.execute("""
                    UPDATE marketing_tasks SET
                        task_type = %s, description = %s, priority = %s,
                        status = %s, input_data = %s, output_content_id = %s,
                        scheduled_for = %s, due_date = %s, assigned_to = %s,
                        completed_at = %s
                    WHERE id = %s
                """, (self.task_type, self.description, self.priority,
                      self.status, input_json, self.output_content_id,
                      self.scheduled_for, self.due_date, self.assigned_to,
                      self.completed_at, self.id))
            else:
                cursor.execute("""
                    INSERT INTO marketing_tasks
                    (task_type, description, priority, status, input_data,
                     output_content_id, scheduled_for, due_date, assigned_to, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (self.task_type, self.description, self.priority,
                      self.status, input_json, self.output_content_id,
                      self.scheduled_for, self.due_date, self.assigned_to, self.created_by))
                self.id = cursor.lastrowid

            conn.commit()
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_by_id(task_id):
        """Get task by ID."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("SELECT * FROM marketing_tasks WHERE id = %s", (task_id,))
            row = cursor.fetchone()
            if row:
                if row.get('input_data') and isinstance(row['input_data'], str):
                    row['input_data'] = json.loads(row['input_data'])
                return MarketingTask(**row)
            return None
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_pending(limit=20):
        """Get pending and awaiting_approval tasks."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM marketing_tasks
                WHERE status IN ('pending', 'awaiting_approval')
                ORDER BY
                    FIELD(priority, 'urgent', 'high', 'normal', 'low'),
                    created_at ASC
                LIMIT %s
            """, (limit,))

            rows = cursor.fetchall()
            tasks = []
            for row in rows:
                if row.get('input_data') and isinstance(row['input_data'], str):
                    row['input_data'] = json.loads(row['input_data'])
                tasks.append(MarketingTask(**row))
            return tasks
        finally:
            cursor.close()
            conn.close()


class MarketingKPI:
    """KPI snapshot model."""

    SOURCES = ['google_analytics', 'search_console', 'google_ads',
               'mailchimp', 'speed_battle', 'stripe', 'social']

    def __init__(self, id=None, source=None, metric_name=None,
                 metric_value=None, metric_meta=None, recorded_at=None):
        self.id = id
        self.source = source
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.metric_meta = metric_meta if metric_meta else {}
        self.recorded_at = recorded_at

    def save(self):
        """Insert KPI record."""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            meta_json = json.dumps(self.metric_meta) if isinstance(self.metric_meta, dict) else self.metric_meta

            cursor.execute("""
                INSERT INTO marketing_kpis
                (source, metric_name, metric_value, metric_meta)
                VALUES (%s, %s, %s, %s)
            """, (self.source, self.metric_name, self.metric_value, meta_json))
            self.id = cursor.lastrowid

            conn.commit()
            return self.id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_latest(source, metric_name):
        """Get most recent KPI value for a source/metric."""
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM marketing_kpis
                WHERE source = %s AND metric_name = %s
                ORDER BY recorded_at DESC
                LIMIT 1
            """, (source, metric_name))
            row = cursor.fetchone()
            if row:
                if row.get('metric_meta') and isinstance(row['metric_meta'], str):
                    row['metric_meta'] = json.loads(row['metric_meta'])
                return MarketingKPI(**row)
            return None
        finally:
            cursor.close()
            conn.close()
```

**Step 2: Verify models work**

Run: `cd /opt/shophosting && python -c "from webapp.admin.marketing.models import MarketingContent, MarketingTask; print('OK')"`
Expected: `OK`

---

### Task 7: Create Basic Routes

**Files:**
- Create: `/opt/shophosting/webapp/admin/marketing/routes.py`

**Step 1: Write routes.py**

Create `/opt/shophosting/webapp/admin/marketing/routes.py`:
```python
"""
Marketing Command Center Routes
"""

from flask import render_template, request, jsonify, session
from . import marketing_bp, marketing_required, marketing_permission_required
from .models import MarketingContent, MarketingCampaign, MarketingTask


@marketing_bp.route('/')
@marketing_required
def dashboard():
    """Main marketing dashboard."""

    # Get recent content
    recent_content = MarketingContent.get_recent(limit=10)

    # Get pending tasks
    pending_tasks = MarketingTask.get_pending(limit=10)

    # Get active campaigns
    active_campaigns = MarketingCampaign.get_active()

    # Placeholder KPIs until integrations are built
    kpis = {
        'speed_battle': {
            'tests_run': 0,
            'leads_captured': 0,
            'conversion_rate': 0,
            'win_rate': 0,
        },
        'stripe': {
            'mrr': 0,
            'new_customers': 0,
        }
    }

    return render_template(
        'admin/marketing/dashboard.html',
        kpis=kpis,
        recent_content=recent_content,
        pending_tasks=pending_tasks,
        active_campaigns=active_campaigns
    )


@marketing_bp.route('/content')
@marketing_permission_required('marketing.view_content')
def content_library():
    """Content library view."""
    status_filter = request.args.get('status', 'all')
    type_filter = request.args.get('type', 'all')

    content = MarketingContent.get_all(
        status=status_filter,
        content_type=type_filter,
        limit=50
    )

    return render_template(
        'admin/marketing/content_library.html',
        content=content,
        status_filter=status_filter,
        type_filter=type_filter,
        content_types=MarketingContent.CONTENT_TYPES,
        statuses=MarketingContent.STATUSES
    )


@marketing_bp.route('/content/<int:content_id>')
@marketing_permission_required('marketing.view_content')
def content_detail(content_id):
    """View single content item."""
    content = MarketingContent.get_by_id(content_id)
    if not content:
        return "Content not found", 404

    return render_template(
        'admin/marketing/content_detail.html',
        content=content
    )


@marketing_bp.route('/content/<int:content_id>/approve', methods=['POST'])
@marketing_permission_required('marketing.approve_content')
def approve_content(content_id):
    """Approve content for publishing."""
    content = MarketingContent.get_by_id(content_id)
    if not content:
        return jsonify({'error': 'Content not found'}), 404

    content.status = 'approved'
    content.save()

    return jsonify({'status': 'approved', 'id': content_id})


@marketing_bp.route('/campaigns')
@marketing_permission_required('marketing.manage_campaigns')
def campaigns():
    """Campaign management view."""
    # TODO: Implement campaign list
    return render_template('admin/marketing/campaigns.html')


@marketing_bp.route('/tasks')
@marketing_permission_required('marketing.view_tasks')
def tasks():
    """Task queue view."""
    tasks = MarketingTask.get_pending(limit=50)
    return render_template(
        'admin/marketing/tasks.html',
        tasks=tasks
    )
```

**Step 2: Verify routes import**

Run: `cd /opt/shophosting && python -c "from webapp.admin.marketing.routes import dashboard; print('OK')"`
Expected: `OK`

---

### Task 8: Register Marketing Blueprint

**Files:**
- Modify: `/opt/shophosting/webapp/admin/__init__.py`

**Step 1: Update __init__.py to conditionally register marketing**

Change the file from:
```python
"""
Admin Panel Blueprint
Provides administrative interface for monitoring the provisioning system
"""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from . import routes
from . import api
from .mail_routes import mail_bp
from .leads_routes import leads_admin_bp

# Register nested blueprints
admin_bp.register_blueprint(mail_bp)
admin_bp.register_blueprint(leads_admin_bp)
```

To:
```python
"""
Admin Panel Blueprint
Provides administrative interface for monitoring the provisioning system
"""

import os
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from . import routes
from . import api
from .mail_routes import mail_bp
from .leads_routes import leads_admin_bp

# Register nested blueprints
admin_bp.register_blueprint(mail_bp)
admin_bp.register_blueprint(leads_admin_bp)

# Conditionally register marketing blueprint (gitignored/proprietary)
_marketing_init = os.path.join(os.path.dirname(__file__), 'marketing', '__init__.py')
if os.path.exists(_marketing_init):
    try:
        from .marketing import marketing_bp
        admin_bp.register_blueprint(marketing_bp)
    except ImportError as e:
        import logging
        logging.getLogger(__name__).warning(f"Marketing module not loaded: {e}")
```

**Step 2: Verify blueprint registration**

Run: `cd /opt/shophosting && python -c "from webapp.admin import admin_bp; print([r.rule for r in admin_bp.url_map.iter_rules() if 'marketing' in r.rule][:3])"`
Expected: List with marketing routes or empty list if not loaded

**Step 3: Commit (only the __init__.py change)**

```bash
git add webapp/admin/__init__.py
git commit -m "feat(admin): conditionally register marketing blueprint

Marketing module is gitignored and loaded only if present.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 9: Create Dashboard Template

**Files:**
- Create: `/opt/shophosting/webapp/templates/admin/marketing/dashboard.html`

**Step 1: Write dashboard template**

Create `/opt/shophosting/webapp/templates/admin/marketing/dashboard.html`:
```html
{% extends "admin/base_admin.html" %}

{% block title %}Marketing Command Center{% endblock %}
{% block page_title %}Marketing Command Center{% endblock %}

{% block extra_css %}
<style>
    .marketing-dashboard {
        padding: 0;
    }

    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 20px;
        margin-bottom: 30px;
    }

    .kpi-card {
        background: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }

    .kpi-card h3 {
        margin: 0 0 10px 0;
        font-size: 0.9rem;
        color: #666;
        text-transform: uppercase;
    }

    .kpi-value {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1a1a2e;
    }

    .kpi-label {
        color: #666;
        font-size: 0.9rem;
    }

    .kpi-secondary {
        margin-top: 10px;
        font-size: 0.85rem;
        color: #888;
    }

    .text-success { color: #28a745; }

    .dashboard-grid {
        display: grid;
        grid-template-columns: 1fr 400px;
        gap: 20px;
    }

    .card {
        background: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }

    .card h3 {
        margin: 0 0 15px 0;
        font-size: 1.1rem;
        color: #1a1a2e;
    }

    /* Quick Actions */
    .action-buttons {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
    }

    .btn-action {
        padding: 10px 15px;
        border: 1px solid #ddd;
        border-radius: 6px;
        background: white;
        cursor: pointer;
        transition: all 0.2s;
        font-size: 0.9rem;
    }

    .btn-action:hover {
        background: #f0f0f0;
        border-color: #bbb;
    }

    .btn-action:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    /* Task List */
    .task-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .task-item {
        padding: 10px 0;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .task-item:last-child {
        border-bottom: none;
    }

    .task-type {
        background: #e3f2fd;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        color: #1976d2;
    }

    .task-desc {
        flex: 1;
        font-size: 0.9rem;
    }

    .priority-urgent .task-type { background: #ffebee; color: #c62828; }
    .priority-high .task-type { background: #fff3e0; color: #ef6c00; }

    /* Content List */
    .content-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .content-item {
        padding: 10px 0;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .content-item:last-child {
        border-bottom: none;
    }

    .content-status {
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        text-transform: uppercase;
    }

    .status-draft { background: #f5f5f5; color: #666; }
    .status-approved { background: #e8f5e9; color: #2e7d32; }
    .status-published { background: #e3f2fd; color: #1976d2; }
    .status-scheduled { background: #fff3e0; color: #ef6c00; }

    .content-type {
        font-size: 0.8rem;
        color: #888;
    }

    /* Chat Widget */
    .chat-widget {
        position: sticky;
        top: 20px;
        height: calc(100vh - 200px);
        min-height: 400px;
        display: flex;
        flex-direction: column;
    }

    .chat-messages {
        flex: 1;
        overflow-y: auto;
        padding: 10px;
        border: 1px solid #eee;
        border-radius: 4px;
        margin-bottom: 10px;
        background: #fafafa;
    }

    .message {
        margin-bottom: 15px;
        padding: 10px 15px;
        border-radius: 8px;
        max-width: 90%;
    }

    .message.user {
        background: #e3f2fd;
        margin-left: auto;
    }

    .message.assistant {
        background: white;
        border: 1px solid #eee;
    }

    .message.typing {
        color: #888;
        font-style: italic;
    }

    .chat-input {
        display: flex;
        gap: 10px;
    }

    .chat-input textarea {
        flex: 1;
        padding: 10px;
        border: 1px solid #ddd;
        border-radius: 6px;
        resize: none;
        font-family: inherit;
    }

    .chat-input button {
        padding: 10px 20px;
        background: #1976d2;
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
    }

    .chat-input button:hover {
        background: #1565c0;
    }

    @media (max-width: 1200px) {
        .kpi-grid {
            grid-template-columns: repeat(2, 1fr);
        }
        .dashboard-grid {
            grid-template-columns: 1fr;
        }
        .chat-widget {
            position: static;
            height: 500px;
        }
    }
</style>
{% endblock %}

{% block content %}
<div class="marketing-dashboard">

    <!-- KPI Cards Row -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <h3>Speed Battle</h3>
            <div class="kpi-value">{{ kpis.speed_battle.tests_run }}</div>
            <div class="kpi-label">Tests Run (30d)</div>
            <div class="kpi-secondary">
                {{ kpis.speed_battle.conversion_rate }}% &rarr; Leads
            </div>
        </div>

        <div class="kpi-card">
            <h3>Win Rate</h3>
            <div class="kpi-value {% if kpis.speed_battle.win_rate > 70 %}text-success{% endif %}">
                {{ kpis.speed_battle.win_rate }}%
            </div>
            <div class="kpi-label">ShopHosting Faster</div>
        </div>

        <div class="kpi-card">
            <h3>MRR</h3>
            <div class="kpi-value">${{ "{:,.0f}".format(kpis.stripe.mrr) }}</div>
            <div class="kpi-label">Monthly Recurring</div>
            <div class="kpi-secondary">
                +{{ kpis.stripe.new_customers }} customers (30d)
            </div>
        </div>

        <div class="kpi-card">
            <h3>Leads</h3>
            <div class="kpi-value">{{ kpis.speed_battle.leads_captured }}</div>
            <div class="kpi-label">Captured (30d)</div>
        </div>
    </div>

    <!-- Main Content Area -->
    <div class="dashboard-grid">

        <!-- Left: Quick Actions + Tasks + Content -->
        <div class="dashboard-left">

            <!-- Quick Action Buttons -->
            <div class="card quick-actions">
                <h3>Quick Actions</h3>
                <div class="action-buttons">
                    <button class="btn-action" data-action="weekly_report">
                        Weekly Report
                    </button>
                    <button class="btn-action" data-action="blog_ideas">
                        Blog Ideas
                    </button>
                    <button class="btn-action" data-action="social_batch">
                        Social Batch
                    </button>
                    <button class="btn-action" data-action="competitor_check">
                        Competitor Check
                    </button>
                    <button class="btn-action" data-action="email_draft" data-segment="budget_refugees">
                        Email Draft
                    </button>
                </div>
            </div>

            <!-- Pending Tasks -->
            <div class="card tasks-panel">
                <h3>Pending Tasks</h3>
                {% if pending_tasks %}
                <ul class="task-list">
                    {% for task in pending_tasks %}
                    <li class="task-item priority-{{ task.priority }}">
                        <span class="task-type">{{ task.task_type }}</span>
                        <span class="task-desc">{{ task.description }}</span>
                        {% if task.status == 'awaiting_approval' %}
                        <button class="btn-action btn-sm" data-task-id="{{ task.id }}">
                            Approve
                        </button>
                        {% endif %}
                    </li>
                    {% endfor %}
                </ul>
                {% else %}
                <p style="color: #888; font-size: 0.9rem;">No pending tasks.</p>
                {% endif %}
            </div>

            <!-- Recent Content -->
            <div class="card content-panel">
                <h3>Recent Content</h3>
                {% if recent_content %}
                <ul class="content-list">
                    {% for item in recent_content %}
                    <li class="content-item">
                        <span class="content-status status-{{ item.status }}">
                            {{ item.status }}
                        </span>
                        <a href="{{ url_for('admin.marketing.content_detail', content_id=item.id) }}">
                            {{ item.title or '(Untitled)' }}
                        </a>
                        <span class="content-type">{{ item.content_type }}</span>
                    </li>
                    {% endfor %}
                </ul>
                {% else %}
                <p style="color: #888; font-size: 0.9rem;">No content yet.</p>
                {% endif %}
                <a href="{{ url_for('admin.marketing.content_library') }}"
                   style="display: block; margin-top: 15px; font-size: 0.9rem;">
                    View all content &rarr;
                </a>
            </div>
        </div>

        <!-- Right: Claude Chat Widget -->
        <div class="dashboard-right">
            <div class="card chat-widget">
                <h3>Marketing AI</h3>

                <div class="chat-messages" id="chatMessages">
                    <div class="message assistant">
                        Ready to help with marketing. I have access to your current KPIs,
                        content library, and know the ShopHosting product. What would you like to work on?
                    </div>
                </div>

                <div class="chat-input">
                    <textarea
                        id="chatInput"
                        placeholder="Ask anything... Generate content, analyze metrics, plan campaigns"
                        rows="3"
                    ></textarea>
                    <button id="chatSend">Send</button>
                </div>
            </div>
        </div>

    </div>
</div>

<!-- DOMPurify for safe HTML rendering -->
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');
let conversationHistory = [];

chatSend.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    appendMessage('user', message);
    chatInput.value = '';

    conversationHistory.push({ role: 'user', content: message });

    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant typing';
    typingDiv.textContent = 'Thinking...';
    chatMessages.appendChild(typingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
        const response = await fetch('/admin/marketing/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: conversationHistory })
        });

        const data = await response.json();
        typingDiv.remove();

        if (data.error) {
            appendMessage('assistant', 'Error: ' + data.error);
        } else {
            appendMessage('assistant', data.response);
            conversationHistory.push({ role: 'assistant', content: data.response });
        }

    } catch (error) {
        typingDiv.textContent = 'Error: ' + error.message;
    }
}

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    // Sanitize HTML output with DOMPurify to prevent XSS
    const rawHtml = marked.parse(content);
    div.innerHTML = DOMPurify.sanitize(rawHtml);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Quick action buttons
document.querySelectorAll('.btn-action').forEach(btn => {
    btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        const segment = btn.dataset.segment;

        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = 'Working...';

        try {
            const response = await fetch('/admin/marketing/quick-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, segment })
            });

            const result = await response.json();

            if (result.error) {
                appendMessage('assistant', '**Error:** ' + result.error);
            } else if (result.content) {
                appendMessage('assistant', result.content);
            } else {
                appendMessage('assistant', '**Generated content ID:** ' + result.content_id);
            }

        } catch (error) {
            appendMessage('assistant', '**Error:** ' + error.message);
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    });
});
</script>
{% endblock %}
```

**Step 2: Create placeholder templates**

Create `/opt/shophosting/webapp/templates/admin/marketing/content_library.html`:
```html
{% extends "admin/base_admin.html" %}

{% block title %}Content Library{% endblock %}
{% block page_title %}Content Library{% endblock %}

{% block content %}
<div class="card">
    <h3>Content Library</h3>

    <div style="margin-bottom: 20px;">
        <form method="get" style="display: flex; gap: 10px;">
            <select name="status">
                <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Status</option>
                {% for s in statuses %}
                <option value="{{ s }}" {% if status_filter == s %}selected{% endif %}>{{ s|title }}</option>
                {% endfor %}
            </select>
            <select name="type">
                <option value="all" {% if type_filter == 'all' %}selected{% endif %}>All Types</option>
                {% for t in content_types %}
                <option value="{{ t }}" {% if type_filter == t %}selected{% endif %}>{{ t|replace('_', ' ')|title }}</option>
                {% endfor %}
            </select>
            <button type="submit">Filter</button>
        </form>
    </div>

    {% if content %}
    <table style="width: 100%; border-collapse: collapse;">
        <thead>
            <tr style="border-bottom: 2px solid #ddd;">
                <th style="text-align: left; padding: 10px;">Title</th>
                <th style="text-align: left; padding: 10px;">Type</th>
                <th style="text-align: left; padding: 10px;">Status</th>
                <th style="text-align: left; padding: 10px;">Created</th>
            </tr>
        </thead>
        <tbody>
            {% for item in content %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">
                    <a href="{{ url_for('admin.marketing.content_detail', content_id=item.id) }}">
                        {{ item.title or '(Untitled)' }}
                    </a>
                </td>
                <td style="padding: 10px;">{{ item.content_type|replace('_', ' ')|title }}</td>
                <td style="padding: 10px;">
                    <span class="content-status status-{{ item.status }}">{{ item.status }}</span>
                </td>
                <td style="padding: 10px;">{{ item.created_at.strftime('%Y-%m-%d') if item.created_at else '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color: #888;">No content found.</p>
    {% endif %}
</div>

<style>
    .content-status {
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        text-transform: uppercase;
    }
    .status-draft { background: #f5f5f5; color: #666; }
    .status-approved { background: #e8f5e9; color: #2e7d32; }
    .status-published { background: #e3f2fd; color: #1976d2; }
</style>
{% endblock %}
```

Create `/opt/shophosting/webapp/templates/admin/marketing/content_detail.html`:
```html
{% extends "admin/base_admin.html" %}

{% block title %}{{ content.title or 'Content Detail' }}{% endblock %}
{% block page_title %}Content Detail{% endblock %}

{% block content %}
<div class="card">
    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 20px;">
        <div>
            <h2 style="margin: 0;">{{ content.title or '(Untitled)' }}</h2>
            <p style="color: #888; margin: 5px 0;">
                {{ content.content_type|replace('_', ' ')|title }} |
                <span class="content-status status-{{ content.status }}">{{ content.status }}</span>
            </p>
        </div>
        <div>
            {% if content.status == 'draft' %}
            <button onclick="approveContent({{ content.id }})" class="btn-action">Approve</button>
            {% endif %}
        </div>
    </div>

    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; white-space: pre-wrap;">{{ content.body or content.markdown or '(No content)' }}</div>

    <div style="margin-top: 20px; color: #888; font-size: 0.9rem;">
        <p>Segment: {{ content.segment or '-' }}</p>
        <p>Pillar: {{ content.content_pillar or '-' }}</p>
        <p>Created: {{ content.created_at.strftime('%Y-%m-%d %H:%M') if content.created_at else '-' }}</p>
    </div>
</div>

<a href="{{ url_for('admin.marketing.content_library') }}">&larr; Back to Content Library</a>

<style>
    .content-status {
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        text-transform: uppercase;
    }
    .status-draft { background: #f5f5f5; color: #666; }
    .status-approved { background: #e8f5e9; color: #2e7d32; }
    .status-published { background: #e3f2fd; color: #1976d2; }
    .btn-action {
        padding: 10px 15px;
        border: 1px solid #ddd;
        border-radius: 6px;
        background: white;
        cursor: pointer;
    }
</style>

<script>
async function approveContent(contentId) {
    try {
        const response = await fetch(`/admin/marketing/content/${contentId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
            location.reload();
        } else {
            alert('Failed to approve content');
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}
</script>
{% endblock %}
```

Create `/opt/shophosting/webapp/templates/admin/marketing/campaigns.html`:
```html
{% extends "admin/base_admin.html" %}

{% block title %}Campaigns{% endblock %}
{% block page_title %}Campaigns{% endblock %}

{% block content %}
<div class="card">
    <h3>Campaign Management</h3>
    <p style="color: #888;">Campaign management coming soon.</p>
</div>
{% endblock %}
```

Create `/opt/shophosting/webapp/templates/admin/marketing/tasks.html`:
```html
{% extends "admin/base_admin.html" %}

{% block title %}Task Queue{% endblock %}
{% block page_title %}Task Queue{% endblock %}

{% block content %}
<div class="card">
    <h3>Marketing Tasks</h3>

    {% if tasks %}
    <table style="width: 100%; border-collapse: collapse;">
        <thead>
            <tr style="border-bottom: 2px solid #ddd;">
                <th style="text-align: left; padding: 10px;">Type</th>
                <th style="text-align: left; padding: 10px;">Description</th>
                <th style="text-align: left; padding: 10px;">Priority</th>
                <th style="text-align: left; padding: 10px;">Status</th>
            </tr>
        </thead>
        <tbody>
            {% for task in tasks %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">{{ task.task_type|replace('_', ' ')|title }}</td>
                <td style="padding: 10px;">{{ task.description }}</td>
                <td style="padding: 10px;">{{ task.priority }}</td>
                <td style="padding: 10px;">{{ task.status }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color: #888;">No tasks in queue.</p>
    {% endif %}
</div>
{% endblock %}
```

**Step 3: Verify templates render**

Run Flask app and navigate to `/admin/marketing/`
Expected: Dashboard renders with KPI cards and empty state messages

---

### Task 10: Add Marketing Link to Admin Sidebar

**Files:**
- Modify: `/opt/shophosting/webapp/templates/admin/base_admin.html`

**Step 1: Find the sidebar navigation section and add marketing link**

Find the navigation section in base_admin.html and add after the Leads section:

```html
<!-- Marketing (if available) -->
{% if session.get('admin_user_role') in ['marketing', 'admin', 'super_admin'] %}
<div class="nav-section">
    <div class="nav-section-title">Marketing</div>
    <a href="{{ url_for('admin.marketing.dashboard') }}"
       class="nav-link {% if request.path.startswith('/admin/marketing') %}active{% endif %}">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20V10"></path>
            <path d="M18 20V4"></path>
            <path d="M6 20v-4"></path>
        </svg>
        Command Center
    </a>
    <a href="{{ url_for('admin.marketing.content_library') }}"
       class="nav-link {% if '/content' in request.path and 'marketing' in request.path %}active{% endif %}">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        Content Library
    </a>
</div>
{% endif %}
```

**Step 2: Test sidebar appears for marketing role**

Log in as super_admin or marketing role user
Expected: Marketing section visible in sidebar

**Step 3: Commit sidebar change**

```bash
git add webapp/templates/admin/base_admin.html
git commit -m "feat(admin): add marketing section to admin sidebar

Only visible to marketing, admin, and super_admin roles.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 2-5: Remaining Implementation

The remaining phases (Integrations, Claude Integration, MCP Server, Background Tasks) follow the same pattern. Each task includes:

1. **Files** - Exact paths to create/modify
2. **Steps** - Atomic actions with code
3. **Verification** - Command to test
4. **Commit** - If not gitignored

See the design document sections 4-8 for full implementation details of:

- Task 11-12: Internal integrations (Speed Battle, Stripe)
- Task 13: Update dashboard with real KPIs
- Task 14: Create context files
- Task 15: Claude client implementation
- Task 16: Chat and quick-action endpoints
- Task 17: MCP server for CLI access
- Tasks 18-26: Background tasks and publishing (deferred)

---

## Verification Checklist

After completing Phase 1-4:

- [ ] Marketing role exists in ADMIN_ROLES
- [ ] Marketing link appears in sidebar for authorized users
- [ ] `/admin/marketing/` loads dashboard with KPI cards
- [ ] Speed Battle metrics display real data
- [ ] Stripe MRR displays real data
- [ ] Chat widget connects to Claude
- [ ] Quick action buttons generate content
- [ ] Content library shows generated content
- [ ] MCP server starts and lists tools

---

## Files Summary

**Committed (not gitignored):**
- `.gitignore` - Updated with marketing rules
- `webapp/admin/models.py` - Marketing role added
- `webapp/admin/routes.py` - Marketing decorator added
- `webapp/admin/__init__.py` - Conditional blueprint registration
- `webapp/templates/admin/base_admin.html` - Sidebar link
- `migrations/add_marketing_tables.sql` - Database schema

**Gitignored (proprietary):**
- `webapp/admin/marketing/` - Entire module
- `webapp/templates/admin/marketing/` - All templates
- `.mcp.json` - MCP configuration
- `docs/plans/*-marketing-*.md` - This plan
