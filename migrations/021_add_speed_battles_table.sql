-- Migration: Add speed_battles table for viral lead generation feature
-- Run: mysql -u root -p shophosting_db < migrations/021_add_speed_battles_table.sql

USE shophosting_db;

-- Speed battles table - stores head-to-head speed comparisons for viral lead generation
CREATE TABLE IF NOT EXISTS speed_battles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    battle_uid VARCHAR(12) NOT NULL UNIQUE,

    -- Challenger (user's store)
    challenger_url VARCHAR(500) NOT NULL,
    challenger_scan_id INT NULL,
    challenger_score INT NULL,

    -- Opponent (competitor store)
    opponent_url VARCHAR(500) NOT NULL,
    opponent_scan_id INT NULL,
    opponent_score INT NULL,

    -- Battle results
    winner ENUM('challenger', 'opponent', 'tie') NULL,
    margin INT NULL,

    -- Lead capture
    email VARCHAR(255) NULL,
    email_segment ENUM('won_dominant', 'won_close', 'lost_close', 'lost_dominant') NULL,

    -- Viral tracking
    referrer_battle_id INT NULL,
    share_clicks_twitter INT DEFAULT 0,
    share_clicks_facebook INT DEFAULT 0,
    share_clicks_linkedin INT DEFAULT 0,
    share_clicks_copy INT DEFAULT 0,

    -- Status tracking
    status ENUM('pending', 'scanning', 'completed', 'failed') DEFAULT 'pending',
    error_message TEXT NULL,

    -- Request metadata
    ip_address VARCHAR(45) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,

    -- Indexes
    INDEX idx_battle_uid (battle_uid),
    INDEX idx_email (email),
    INDEX idx_status (status),
    INDEX idx_email_status (email, status),
    INDEX idx_created_at (created_at),
    INDEX idx_referrer_battle_id (referrer_battle_id),

    -- Foreign keys
    FOREIGN KEY (challenger_scan_id) REFERENCES site_scans(id) ON DELETE SET NULL,
    FOREIGN KEY (opponent_scan_id) REFERENCES site_scans(id) ON DELETE SET NULL,
    FOREIGN KEY (referrer_battle_id) REFERENCES speed_battles(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
