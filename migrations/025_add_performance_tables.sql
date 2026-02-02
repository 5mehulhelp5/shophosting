-- Migration: Add performance optimization tables
-- Date: 2026-02-01
-- Description: Creates tables for the Performance Optimization Suite (Phase 1)
--   - performance_snapshots: aggregated health scores and metrics
--   - performance_issues: detected issues with severity and resolution tracking
--   - automation_actions: playbook execution log
--   - slow_queries: query log with hash-based deduplication
--   - lighthouse_probes: synthetic performance test results
--   - admin_interventions: admin action audit log
--   - customers table additions for automation preferences

-- Performance snapshots (aggregated metrics)
CREATE TABLE IF NOT EXISTS performance_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    timestamp DATETIME NOT NULL,
    health_score TINYINT NOT NULL,  -- 0-100

    -- Page speed
    ttfb_ms INT,
    fcp_ms INT,
    lcp_ms INT,

    -- Resources
    cpu_percent DECIMAL(5,2),
    memory_percent DECIMAL(5,2),
    disk_percent DECIMAL(5,2),

    -- Database
    slow_query_count INT,
    active_connections INT,
    db_size_bytes BIGINT,

    -- Cache
    redis_hit_rate DECIMAL(5,2),
    varnish_hit_rate DECIMAL(5,2),

    INDEX idx_customer_time (customer_id, timestamp),
    INDEX idx_health (health_score, timestamp),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Detected issues
CREATE TABLE IF NOT EXISTS performance_issues (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    issue_type VARCHAR(50) NOT NULL,  -- 'high_memory', 'slow_queries', etc.
    severity ENUM('info', 'warning', 'critical') NOT NULL,
    detected_at DATETIME NOT NULL,
    resolved_at DATETIME,
    auto_fixed BOOLEAN DEFAULT FALSE,
    details JSON,

    INDEX idx_customer_open (customer_id, resolved_at),
    INDEX idx_severity (severity, detected_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Automation actions taken
CREATE TABLE IF NOT EXISTS automation_actions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    issue_id BIGINT,
    playbook_name VARCHAR(50) NOT NULL,
    action_name VARCHAR(100) NOT NULL,
    executed_at DATETIME NOT NULL,
    success BOOLEAN NOT NULL,
    result JSON,

    INDEX idx_customer_time (customer_id, executed_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (issue_id) REFERENCES performance_issues(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Slow queries log
CREATE TABLE IF NOT EXISTS slow_queries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    query_hash CHAR(32) NOT NULL,  -- MD5 of normalized query
    query_text TEXT NOT NULL,
    execution_time_ms INT NOT NULL,
    rows_examined BIGINT,
    rows_sent BIGINT,
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    occurrence_count INT DEFAULT 1,

    UNIQUE KEY uk_customer_query (customer_id, query_hash),
    INDEX idx_customer_time (customer_id, last_seen),
    INDEX idx_slow (execution_time_ms),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lighthouse probe results
CREATE TABLE IF NOT EXISTS lighthouse_probes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    probed_at DATETIME NOT NULL,
    performance_score TINYINT,  -- 0-100
    fcp_ms INT,
    lcp_ms INT,
    cls DECIMAL(5,3),
    tbt_ms INT,
    full_report JSON,

    INDEX idx_customer_time (customer_id, probed_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Admin intervention log
CREATE TABLE IF NOT EXISTS admin_interventions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    admin_user_id INT NOT NULL,
    playbook_name VARCHAR(50) NOT NULL,
    executed_at DATETIME NOT NULL,
    reason TEXT,
    result JSON,

    INDEX idx_customer (customer_id),
    INDEX idx_admin (admin_user_id),
    INDEX idx_executed_at (executed_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add automation preference columns to customers table
-- Using conditional column addition for idempotency
SET @dbname = DATABASE();
SET @tablename = 'customers';

-- Add automation_level column if not exists
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'automation_level');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN automation_level TINYINT DEFAULT 2', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add automation_exceptions column if not exists
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'automation_exceptions');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN automation_exceptions JSON DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add last_health_score column if not exists
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'last_health_score');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN last_health_score TINYINT DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add health_score_updated_at column if not exists
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = @dbname AND table_name = @tablename AND column_name = 'health_score_updated_at');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN health_score_updated_at DATETIME DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
