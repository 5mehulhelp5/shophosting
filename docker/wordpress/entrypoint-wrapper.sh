#!/usr/bin/env bash
set -euo pipefail

echo "[shophosting.io] entrypoint-wrapper starting..."

# Require DB env vars (these come from docker compose 'environment:')
: "${WORDPRESS_DB_HOST:?Missing WORDPRESS_DB_HOST}"
: "${WORDPRESS_DB_USER:?Missing WORDPRESS_DB_USER}"
: "${WORDPRESS_DB_PASSWORD:?Missing WORDPRESS_DB_PASSWORD}"
: "${WORDPRESS_DB_NAME:?Missing WORDPRESS_DB_NAME}"

# Parse host and port (WORDPRESS_DB_HOST can be "host:port" or just "host")
DB_HOST="${WORDPRESS_DB_HOST%%:*}"
DB_PORT="${WORDPRESS_DB_HOST##*:}"
if [[ "$DB_PORT" == "$DB_HOST" ]]; then
    DB_PORT="3306"
fi

echo "[shophosting.io] waiting for MySQL at ${DB_HOST}:${DB_PORT}..."
for i in {1..150}; do
    if mysqladmin ping -h"${DB_HOST}" -P"${DB_PORT}" -u"${WORDPRESS_DB_USER}" -p"${WORDPRESS_DB_PASSWORD}" --silent --skip-ssl 2>/dev/null; then
        echo "[shophosting.io] MySQL is up."
        break
    fi

    if [[ "$i" -eq 150 ]]; then
        echo "[shophosting.io] ERROR: MySQL did not become ready in time." >&2
        exit 1
    fi
    sleep 2
done

# Ensure wp-content subdirectories exist (they are mounted as volumes)
echo "[shophosting.io] Setting up wp-content directories..."
mkdir -p /var/www/html/wp-content/uploads
mkdir -p /var/www/html/wp-content/plugins
mkdir -p /var/www/html/wp-content/themes
chown -R www-data:www-data /var/www/html/wp-content

# Seed base plugins from image if volumes are empty
if [[ ! -d /var/www/html/wp-content/plugins/woocommerce ]]; then
    if [[ -d /usr/src/plugins/woocommerce ]]; then
        echo "[shophosting.io] Seeding WooCommerce plugin..."
        cp -r /usr/src/plugins/woocommerce /var/www/html/wp-content/plugins/
        chown -R www-data:www-data /var/www/html/wp-content/plugins/woocommerce
    else
        echo "[shophosting.io] WARNING: WooCommerce plugin not found in image" >&2
    fi
fi

if [[ ! -d /var/www/html/wp-content/plugins/redis-cache ]]; then
    if [[ -d /usr/src/plugins/redis-cache ]]; then
        echo "[shophosting.io] Seeding Redis Cache plugin..."
        cp -r /usr/src/plugins/redis-cache /var/www/html/wp-content/plugins/
        chown -R www-data:www-data /var/www/html/wp-content/plugins/redis-cache
    else
        echo "[shophosting.io] WARNING: Redis Cache plugin not found in image" >&2
    fi
fi

# Seed default theme if themes directory is empty
if [[ -z "$(ls -A /var/www/html/wp-content/themes 2>/dev/null)" ]]; then
    if [[ -d /usr/src/wordpress/wp-content/themes ]]; then
        echo "[shophosting.io] Seeding default themes..."
        cp -r /usr/src/wordpress/wp-content/themes/* /var/www/html/wp-content/themes/
        chown -R www-data:www-data /var/www/html/wp-content/themes
    else
        echo "[shophosting.io] WARNING: Default themes not found in image" >&2
    fi
fi

# Generate wp-config.php if it doesn't exist
if [[ ! -f /var/www/html/wp-config.php ]]; then
    echo "[shophosting.io] Generating wp-config.php..."

    # Escape single quotes in password for PHP string
    DB_PASSWORD_ESCAPED="${WORDPRESS_DB_PASSWORD//\'/\\\'}"

    # Generate salts with timeout and secure fallback
    SALTS=$(curl -s --connect-timeout 5 --max-time 10 https://api.wordpress.org/secret-key/1.1/salt/) || {
        echo "[shophosting.io] WARNING: Could not fetch salts from WordPress API, generating local salts..."
        SALTS=""
        for key in AUTH_KEY SECURE_AUTH_KEY LOGGED_IN_KEY NONCE_KEY AUTH_SALT SECURE_AUTH_SALT LOGGED_IN_SALT NONCE_SALT; do
            SALT_VALUE=$(head -c 64 /dev/urandom | base64 | tr -d '\n' | head -c 64)
            SALTS="${SALTS}define('${key}', '${SALT_VALUE}');"$'\n'
        done
    }

    cat > /var/www/html/wp-config.php <<WPCONFIG
<?php
define('DB_NAME', '${WORDPRESS_DB_NAME}');
define('DB_USER', '${WORDPRESS_DB_USER}');
define('DB_PASSWORD', '${DB_PASSWORD_ESCAPED}');
define('DB_HOST', '${WORDPRESS_DB_HOST}');
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');

${SALTS}

\$table_prefix = 'wp_';

define('WP_DEBUG', false);
define('WP_HOME', '${WP_HOME:-http://localhost}');
define('WP_SITEURL', '${WP_SITEURL:-http://localhost}');

// Redis configuration
define('WP_REDIS_HOST', '${WP_REDIS_HOST:-redis}');
define('WP_REDIS_PORT', ${WP_REDIS_PORT:-6379});

if (!defined('ABSPATH')) {
    define('ABSPATH', __DIR__ . '/');
}

require_once ABSPATH . 'wp-settings.php';
WPCONFIG
    chown www-data:www-data /var/www/html/wp-config.php
fi

# Check if WordPress is already installed
if ! wp core is-installed --allow-root 2>/dev/null; then
    echo "[shophosting.io] Installing WordPress..."

    # Get admin credentials from environment (with defaults)
    WP_ADMIN_USER="${WP_ADMIN_USER:-admin}"
    WP_ADMIN_PASSWORD="${WP_ADMIN_PASSWORD:-changeme}"
    WP_ADMIN_EMAIL="${WP_ADMIN_EMAIL:-admin@example.com}"
    WP_HOME="${WP_HOME:-http://localhost}"
    WP_SITE_TITLE="${WP_SITE_TITLE:-My Site}"

    # Install WordPress core
    wp core install \
        --url="${WP_HOME}" \
        --title="${WP_SITE_TITLE}" \
        --admin_user="${WP_ADMIN_USER}" \
        --admin_password="${WP_ADMIN_PASSWORD}" \
        --admin_email="${WP_ADMIN_EMAIL}" \
        --skip-email \
        --allow-root

    echo "[shophosting.io] WordPress installed successfully!"

    # Activate plugins
    echo "[shophosting.io] Activating plugins..."
    wp plugin activate woocommerce --allow-root || echo "[shophosting.io] WooCommerce activation skipped"
    wp plugin activate redis-cache --allow-root || echo "[shophosting.io] Redis cache activation skipped"

    # Enable Redis cache if WP_REDIS_HOST is set
    if [[ -n "${WP_REDIS_HOST:-}" ]]; then
        wp redis enable --allow-root 2>/dev/null || echo "[shophosting.io] Redis enable skipped"
    fi

    echo "[shophosting.io] WordPress setup complete!"
else
    echo "[shophosting.io] WordPress already installed, skipping installation."
fi

# Start Apache in foreground
exec apache2-foreground
