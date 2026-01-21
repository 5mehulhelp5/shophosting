-- Migration: Add admin_users table for admin panel
-- Run: mysql -u root -p shophosting_db < migrations/002_add_admin_users.sql

USE shophosting_db;

-- Admin users table
CREATE TABLE IF NOT EXISTS admin_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role ENUM('super_admin', 'admin', 'support') DEFAULT 'admin',
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_email (email),
    INDEX idx_role (role),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Extend audit_log for admin action tracking
ALTER TABLE audit_log
    ADD COLUMN admin_user_id INT NULL AFTER customer_id,
    ADD COLUMN entity_type VARCHAR(50) NULL AFTER action,
    ADD COLUMN entity_id INT NULL AFTER entity_type;
