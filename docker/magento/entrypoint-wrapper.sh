#!/bin/bash
set -euo pipefail

echo "[shophosting.io] Magento entrypoint-wrapper starting..."

# Support both naming conventions for database config
DB_HOST="${MAGENTO_DATABASE_HOST:-${DB_HOST:-db}}"
DB_NAME="${MAGENTO_DATABASE_NAME:-${DB_NAME:-magento}}"
DB_USER="${MAGENTO_DATABASE_USER:-${DB_USER:-magento}}"
DB_PASSWORD="${MAGENTO_DATABASE_PASSWORD:-${DB_PASSWORD:-}}"
ES_HOST="${ELASTICSEARCH_HOST:-${OPENSEARCH_HOST:-elasticsearch}}"
ES_PORT="${ELASTICSEARCH_PORT:-${OPENSEARCH_PORT:-9200}}"

# Validate required environment variables
if [ -z "$DB_PASSWORD" ]; then
    echo "[shophosting.io] ERROR: Database password not set (MAGENTO_DATABASE_PASSWORD or DB_PASSWORD)"
    exit 1
fi

# Wait for MySQL to be ready
echo "[shophosting.io] Waiting for MySQL at ${DB_HOST}..."
MAX_MYSQL_RETRIES=150
MYSQL_RETRY_COUNT=0
until mysqladmin ping -h"${DB_HOST}" -u"${DB_USER}" -p"${DB_PASSWORD}" --silent 2>/dev/null; do
    MYSQL_RETRY_COUNT=$((MYSQL_RETRY_COUNT + 1))
    if [ $MYSQL_RETRY_COUNT -ge $MAX_MYSQL_RETRIES ]; then
        echo "[shophosting.io] ERROR: MySQL not available after ${MAX_MYSQL_RETRIES} attempts. Exiting."
        exit 1
    fi
    echo "[shophosting.io] MySQL not ready yet (attempt ${MYSQL_RETRY_COUNT}/${MAX_MYSQL_RETRIES})..."
    sleep 2
done
echo "[shophosting.io] MySQL is ready!"

# Wait for Elasticsearch/OpenSearch to be ready
echo "[shophosting.io] Waiting for Elasticsearch at ${ES_HOST}:${ES_PORT}..."
MAX_ES_RETRIES=150
ES_RETRY_COUNT=0
until curl -s "http://${ES_HOST}:${ES_PORT}/_cluster/health" | grep -q '"status"'; do
    ES_RETRY_COUNT=$((ES_RETRY_COUNT + 1))
    if [ $ES_RETRY_COUNT -ge $MAX_ES_RETRIES ]; then
        echo "[shophosting.io] ERROR: Elasticsearch not available after ${MAX_ES_RETRIES} attempts. Exiting."
        exit 1
    fi
    echo "[shophosting.io] Elasticsearch not ready yet (attempt ${ES_RETRY_COUNT}/${MAX_ES_RETRIES})..."
    sleep 2
done
echo "[shophosting.io] Elasticsearch is ready!"

echo "[shophosting.io] All dependencies ready. Setting up volumes..."

# Ensure volume directories exist with correct ownership
mkdir -p /var/www/html/pub/media
mkdir -p /var/www/html/var
mkdir -p /var/www/html/generated
mkdir -p /var/www/html/pub/static
mkdir -p /var/www/html/app/etc

# Seed generated/ from base image if empty
if [ ! -f /var/www/html/generated/.seeded ]; then
    echo "[shophosting.io] Seeding generated/ from base image..."
    if [ -d /usr/src/magento-base/generated ] && [ "$(ls -A /usr/src/magento-base/generated 2>/dev/null)" ]; then
        cp -r /usr/src/magento-base/generated/* /var/www/html/generated/ 2>/dev/null || true
    fi
    touch /var/www/html/generated/.seeded
fi

# Seed pub/static/ from base image if empty
if [ ! -f /var/www/html/pub/static/.seeded ]; then
    echo "[shophosting.io] Seeding pub/static/ from base image..."
    if [ -d /usr/src/magento-base/static ] && [ "$(ls -A /usr/src/magento-base/static 2>/dev/null)" ]; then
        cp -r /usr/src/magento-base/static/* /var/www/html/pub/static/ 2>/dev/null || true
    fi
    touch /var/www/html/pub/static/.seeded
fi

# Generate app/etc/env.php if missing (first boot)
if [ ! -f /var/www/html/app/etc/env.php ]; then
    echo "[shophosting.io] First boot detected - running Magento setup..."

    MAGENTO_HOST="${MAGENTO_HOST:-localhost}"
    MAGENTO_USERNAME="${MAGENTO_USERNAME:-admin}"
    MAGENTO_PASSWORD="${MAGENTO_PASSWORD:-Admin123!}"
    MAGENTO_EMAIL="${MAGENTO_EMAIL:-admin@example.com}"

    cd /var/www/html

    # Run Magento setup
    bin/magento setup:install \
        --base-url="https://${MAGENTO_HOST}/" \
        --db-host="${DB_HOST}" \
        --db-name="${DB_NAME}" \
        --db-user="${DB_USER}" \
        --db-password="${DB_PASSWORD}" \
        --admin-firstname="Admin" \
        --admin-lastname="User" \
        --admin-email="${MAGENTO_EMAIL}" \
        --admin-user="${MAGENTO_USERNAME}" \
        --admin-password="${MAGENTO_PASSWORD}" \
        --language=en_US \
        --currency=USD \
        --timezone=America/New_York \
        --use-rewrites=1 \
        --search-engine=elasticsearch7 \
        --elasticsearch-host="${ES_HOST}" \
        --elasticsearch-port="${ES_PORT}" \
        --no-interaction

    # Compile DI if not already done
    if [ ! -f /var/www/html/generated/metadata/global.php ]; then
        echo "[shophosting.io] Compiling DI..."
        bin/magento setup:di:compile --no-interaction || true
    fi

    # Deploy static content if needed
    if [ -z "$(ls -A /var/www/html/pub/static/frontend 2>/dev/null)" ]; then
        echo "[shophosting.io] Deploying static content..."
        bin/magento setup:static-content:deploy -f en_US --no-interaction || true
    fi

    echo "[shophosting.io] Magento setup complete!"
else
    echo "[shophosting.io] Magento already configured, skipping setup."
fi

# Fix permissions on writable directories
chown -R www-data:www-data /var/www/html/var /var/www/html/pub/media /var/www/html/generated /var/www/html/pub/static /var/www/html/app/etc 2>/dev/null || true

echo "[shophosting.io] Starting Magento..."

# Start background process to fix PHP-FPM socket permissions
(
    SOCKET_PATH="/run/php-fpm.sock"
    MAX_WAIT=120
    WAITED=0

    while [ ! -S "$SOCKET_PATH" ] && [ $WAITED -lt $MAX_WAIT ]; do
        sleep 1
        WAITED=$((WAITED + 1))
    done

    if [ -S "$SOCKET_PATH" ]; then
        chmod 0666 "$SOCKET_PATH"
        echo "[shophosting.io] Fixed PHP-FPM socket permissions"
    fi

    while true; do
        if [ -S "$SOCKET_PATH" ]; then
            PERMS=$(stat -c %a "$SOCKET_PATH" 2>/dev/null || echo "666")
            if [ "$PERMS" != "666" ]; then
                chmod 0666 "$SOCKET_PATH"
                echo "[shophosting.io] Re-fixed PHP-FPM socket permissions"
            fi
        fi
        sleep 30
    done
) &

# Run original docker-php-entrypoint
exec docker-php-entrypoint "$@"
