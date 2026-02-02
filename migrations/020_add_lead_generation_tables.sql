-- Migration: Add lead generation tables for speed test and migration preview funnel
-- Run: mysql -u root -p shophosting_db < migrations/020_add_lead_generation_tables.sql

USE shophosting_db;

-- Site scans table - stores results from the free speed test tool
CREATE TABLE IF NOT EXISTS site_scans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(500) NOT NULL,
    email VARCHAR(255) NULL,
    performance_score INT NULL,
    load_time_ms INT NULL,
    ttfb_ms INT NULL,
    pagespeed_data JSON NULL,
    custom_probe_data JSON NULL,
    estimated_revenue_loss DECIMAL(10,2) NULL,
    ip_address VARCHAR(45) NULL,
    converted_to_lead_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_email (email),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration preview requests table - stores requests from leads who want to see their site on ShopHosting
CREATE TABLE IF NOT EXISTS migration_preview_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_scan_id INT NOT NULL,
    email VARCHAR(255) NOT NULL,
    store_url VARCHAR(500) NOT NULL,
    store_platform ENUM('woocommerce', 'magento', 'unknown') DEFAULT 'unknown',
    monthly_revenue VARCHAR(50) NULL,
    current_host VARCHAR(100) NULL,
    status ENUM('pending', 'contacted', 'migrating', 'completed', 'rejected') DEFAULT 'pending',
    notes TEXT NULL,
    assigned_admin_id INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_status (status),
    INDEX idx_created_at (created_at),

    FOREIGN KEY (site_scan_id) REFERENCES site_scans(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_admin_id) REFERENCES admin_users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
