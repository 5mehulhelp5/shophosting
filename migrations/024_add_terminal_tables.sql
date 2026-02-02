-- Migration: Add terminal tables for WP-CLI terminal feature
-- Date: 2026-02-01

-- Terminal sessions for tracking current working directory
CREATE TABLE IF NOT EXISTS terminal_sessions (
    id VARCHAR(36) PRIMARY KEY,
    customer_id INT NOT NULL,
    current_directory VARCHAR(512) DEFAULT '/var/www/html',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_customer_id (customer_id),
    INDEX idx_last_activity (last_activity_at),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Terminal command audit log for security tracking
CREATE TABLE IF NOT EXISTS terminal_audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    session_id VARCHAR(36) NOT NULL,
    command TEXT NOT NULL,
    command_hash VARCHAR(64),
    working_directory VARCHAR(512) NOT NULL,
    exit_code INT,
    execution_time_ms INT,
    output_size_bytes INT,
    blocked BOOLEAN DEFAULT FALSE,
    block_reason VARCHAR(255),
    ip_address VARCHAR(45),
    user_agent VARCHAR(512),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_customer_id (customer_id),
    INDEX idx_session_id (session_id),
    INDEX idx_created_at (created_at),
    INDEX idx_blocked (blocked),

    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
