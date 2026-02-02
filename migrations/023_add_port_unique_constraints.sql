-- Migration 023: Add unique constraints on port columns to prevent race conditions
-- This ensures atomic port allocation even with concurrent requests
-- The FOR UPDATE clause in the application code provides row-level locking,
-- but this constraint provides a database-level guarantee as a safety net.

-- Add unique constraint on customers.web_port
-- Using ALTER IGNORE to skip if constraint already exists (MySQL 5.7+)
-- Note: NULL values are allowed and don't violate UNIQUE constraints in MySQL

ALTER TABLE customers
ADD CONSTRAINT unique_customer_web_port UNIQUE (web_port);

-- Add unique constraint on staging_environments.web_port
ALTER TABLE staging_environments
ADD CONSTRAINT unique_staging_web_port UNIQUE (web_port);
