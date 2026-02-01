-- Marketing Command Center Tables
-- Run: mysql -u root -p shophosting < migrations/022_add_marketing_tables.sql

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

-- Add foreign key for campaign_id (only if not exists)
-- Note: We check if the constraint exists to make this idempotent
SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'marketing_content'
    AND CONSTRAINT_NAME = 'fk_content_campaign'
);

SET @sql = IF(@constraint_exists = 0,
    'ALTER TABLE marketing_content ADD CONSTRAINT fk_content_campaign FOREIGN KEY (campaign_id) REFERENCES marketing_campaigns(id) ON DELETE SET NULL',
    'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

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
    INDEX idx_scheduled (scheduled_for)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add foreign key for output_content_id (only if not exists)
SET @constraint_exists = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'marketing_tasks'
    AND CONSTRAINT_NAME = 'fk_task_content'
);

SET @sql = IF(@constraint_exists = 0,
    'ALTER TABLE marketing_tasks ADD CONSTRAINT fk_task_content FOREIGN KEY (output_content_id) REFERENCES marketing_content(id) ON DELETE SET NULL',
    'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

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
