-- Migration: Add customer notifications table
-- Date: 2026-02-02
-- Description: Creates table for customer notification system (Phase 3 Performance)
--   - customer_notifications: stores notifications for dashboard display
--   - Supports notification triggers: issue detected, auto-fix executed, issue resolved
--   - Prepares structure for future email notifications

-- Customer notifications table
CREATE TABLE IF NOT EXISTS customer_notifications (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- 'issue_detected', 'auto_fix_executed', 'issue_resolved'
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    severity ENUM('info', 'warning', 'critical', 'success') NOT NULL DEFAULT 'info',
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at DATETIME DEFAULT NULL,
    link_url VARCHAR(512) DEFAULT NULL,  -- Optional link to related section
    link_text VARCHAR(100) DEFAULT NULL, -- Text for the link
    related_issue_id BIGINT DEFAULT NULL,  -- Reference to performance_issues if applicable
    metadata JSON DEFAULT NULL,  -- Additional data for email templates, etc.
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_customer_unread (customer_id, is_read, created_at),
    INDEX idx_customer_created (customer_id, created_at DESC),
    INDEX idx_event_type (event_type, created_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (related_issue_id) REFERENCES performance_issues(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add notification preferences to customers table
-- email_notifications_enabled: future use for email notifications
SET @dbname = DATABASE();
SET @tablename = 'customers';

-- Add email_notifications_enabled column if not exists
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'email_notifications_enabled');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add notification_email column if not exists (for customers who want notifications to a different email)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'notification_email');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN notification_email VARCHAR(255) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
