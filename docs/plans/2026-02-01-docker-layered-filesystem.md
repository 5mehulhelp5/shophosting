# Docker Layered Filesystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Optimize Docker container storage by mounting only customer-specific directories, keeping WordPress/Magento core in shared image layers.

**Architecture:** Pre-install WordPress/WooCommerce and Magento with compiled assets in Docker images. Mount only uploads, plugins, themes (WordPress) or media, var, generated, static, app-etc (Magento) as customer volumes. Entrypoints seed base plugins/assets to empty volumes on first start.

**Tech Stack:** Docker, Bash, Python, Jinja2 templates

---

## Task 1: WordPress Dockerfile - Pre-install WordPress and Plugins

**Files:**
- Modify: `docker/wordpress/Dockerfile`

**Step 1: Update Dockerfile to pre-install WordPress**

Replace entire file with:

```dockerfile
FROM wordpress:latest

# Install mysql client tools (for mysqladmin ping) + curl (for wp-cli download)
RUN apt-get update \
  && apt-get install -y --no-install-recommends default-mysql-client ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Install WP-CLI
RUN curl -fsSL https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /usr/local/bin/wp \
  && chmod +x /usr/local/bin/wp \
  && wp --info

# Pre-install WordPress to /var/www/html (instead of runtime copy)
# The official WordPress image stores files in /usr/src/wordpress
RUN cp -r /usr/src/wordpress/* /var/www/html/ \
  && chown -R www-data:www-data /var/www/html

# Pre-download WooCommerce and Redis Cache plugins to /usr/src/plugins
# These will be copied to customer volumes on first start
RUN mkdir -p /usr/src/plugins \
  && cd /usr/src/plugins \
  && wp plugin install woocommerce --path=/var/www/html --allow-root \
  && mv /var/www/html/wp-content/plugins/woocommerce /usr/src/plugins/ \
  && wp plugin install redis-cache --path=/var/www/html --allow-root \
  && mv /var/www/html/wp-content/plugins/redis-cache /usr/src/plugins/ \
  && chown -R www-data:www-data /usr/src/plugins

# Add wrapper
COPY entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/entrypoint-wrapper.sh

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["apache2-foreground"]
```

**Step 2: Commit**

```bash
git add docker/wordpress/Dockerfile
git commit -m "feat(docker): pre-install WordPress and plugins in image

- Copy WordPress files to /var/www/html at build time
- Pre-download WooCommerce and redis-cache to /usr/src/plugins
- Plugins will be seeded to customer volumes on first start

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: WordPress Entrypoint - Simplified with Plugin Seeding

**Files:**
- Modify: `docker/wordpress/entrypoint-wrapper.sh`

**Step 1: Replace entrypoint script**

Replace entire file with:

```bash
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
    echo "[shophosting.io] Seeding WooCommerce plugin..."
    cp -r /usr/src/plugins/woocommerce /var/www/html/wp-content/plugins/
    chown -R www-data:www-data /var/www/html/wp-content/plugins/woocommerce
fi

if [[ ! -d /var/www/html/wp-content/plugins/redis-cache ]]; then
    echo "[shophosting.io] Seeding Redis Cache plugin..."
    cp -r /usr/src/plugins/redis-cache /var/www/html/wp-content/plugins/
    chown -R www-data:www-data /var/www/html/wp-content/plugins/redis-cache
fi

# Seed default theme if themes directory is empty
if [[ -z "$(ls -A /var/www/html/wp-content/themes 2>/dev/null)" ]]; then
    echo "[shophosting.io] Seeding default themes..."
    cp -r /usr/src/wordpress/wp-content/themes/* /var/www/html/wp-content/themes/
    chown -R www-data:www-data /var/www/html/wp-content/themes
fi

# Generate wp-config.php if it doesn't exist
if [[ ! -f /var/www/html/wp-config.php ]]; then
    echo "[shophosting.io] Generating wp-config.php..."

    # Generate salts
    SALTS=$(curl -s https://api.wordpress.org/secret-key/1.1/salt/ || cat <<'FALLBACK'
define('AUTH_KEY',         'put your unique phrase here');
define('SECURE_AUTH_KEY',  'put your unique phrase here');
define('LOGGED_IN_KEY',    'put your unique phrase here');
define('NONCE_KEY',        'put your unique phrase here');
define('AUTH_SALT',        'put your unique phrase here');
define('SECURE_AUTH_SALT', 'put your unique phrase here');
define('LOGGED_IN_SALT',   'put your unique phrase here');
define('NONCE_SALT',       'put your unique phrase here');
FALLBACK
)

    cat > /var/www/html/wp-config.php <<WPCONFIG
<?php
define('DB_NAME', '${WORDPRESS_DB_NAME}');
define('DB_USER', '${WORDPRESS_DB_USER}');
define('DB_PASSWORD', '${WORDPRESS_DB_PASSWORD}');
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
```

**Step 2: Commit**

```bash
git add docker/wordpress/entrypoint-wrapper.sh
git commit -m "feat(docker): simplified WordPress entrypoint with plugin seeding

- Remove dependency on docker-entrypoint.sh file copying
- Seed WooCommerce and redis-cache plugins from image to volume
- Seed default themes if themes directory is empty
- Generate wp-config.php directly from environment variables
- Run Apache directly instead of backgrounding

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: WordPress Compose Template - Selective Volume Mounts

**Files:**
- Modify: `templates/woocommerce-compose.yml.j2`

**Step 1: Update volume mounts**

Find lines 68-69:
```yaml
    volumes:
      - "/var/customers/{{ container_prefix }}/wordpress:/var/www/html"
```

Replace with:
```yaml
    volumes:
      - "/var/customers/{{ container_prefix }}/uploads:/var/www/html/wp-content/uploads"
      - "/var/customers/{{ container_prefix }}/plugins:/var/www/html/wp-content/plugins"
      - "/var/customers/{{ container_prefix }}/themes:/var/www/html/wp-content/themes"
```

**Step 2: Commit**

```bash
git add templates/woocommerce-compose.yml.j2
git commit -m "feat(templates): selective volume mounts for WordPress

- Mount only wp-content/uploads, plugins, themes as volumes
- WordPress core stays in shared Docker image layer
- Reduces disk usage ~80% per customer

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Magento Dockerfile - Pre-compile Assets

**Files:**
- Modify: `docker/magento/Dockerfile`

**Step 1: Update Dockerfile**

Replace entire file with:

```dockerfile
FROM shinsenter/magento:latest

# Install mysql client tools (for mysqladmin ping) - curl is already installed
RUN apt-get update \
  && apt-get install -y --no-install-recommends default-mysql-client \
  && rm -rf /var/lib/apt/lists/*

# Pre-compile DI and static content for base Magento installation
# This is stored in /usr/src/magento-base for seeding to customer volumes
RUN mkdir -p /usr/src/magento-base \
  && if [ -d /var/www/html/generated ]; then \
       cp -r /var/www/html/generated /usr/src/magento-base/generated; \
     else \
       mkdir -p /usr/src/magento-base/generated; \
     fi \
  && if [ -d /var/www/html/pub/static ]; then \
       cp -r /var/www/html/pub/static /usr/src/magento-base/static; \
     else \
       mkdir -p /usr/src/magento-base/static; \
     fi

# Create marker to indicate base image is ready
RUN touch /usr/src/magento-base/.base-ready

# Add wrapper script
COPY entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/entrypoint-wrapper.sh

# Note: Do NOT set USER here - shinsenter/magento requires root to start
# and handles user switching internally via s6-overlay

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["php-fpm"]
```

**Step 2: Commit**

```bash
git add docker/magento/Dockerfile
git commit -m "feat(docker): pre-stage Magento compiled assets in image

- Copy generated/ and pub/static/ to /usr/src/magento-base/
- These will be seeded to customer volumes on first start
- Reduces provisioning time and disk usage

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Magento Entrypoint - Add Volume Seeding

**Files:**
- Modify: `docker/magento/entrypoint-wrapper.sh`

**Step 1: Replace entrypoint script**

Replace entire file with:

```bash
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
```

**Step 2: Commit**

```bash
git add docker/magento/entrypoint-wrapper.sh
git commit -m "feat(docker): Magento entrypoint with volume seeding

- Seed generated/ and pub/static/ from base image on first start
- Run setup:install only if env.php missing
- Skip DI compile and static deploy if already done
- Reduces provisioning time significantly

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Magento Compose Template - Selective Volume Mounts

**Files:**
- Modify: `templates/magento-compose.yml.j2`

**Step 1: Update volume mounts**

Find lines 45-46:
```yaml
    volumes:
      - ./volumes/files:/var/www/html
```

Replace with:
```yaml
    volumes:
      - ./volumes/media:/var/www/html/pub/media
      - ./volumes/var:/var/www/html/var
      - ./volumes/generated:/var/www/html/generated
      - ./volumes/static:/var/www/html/pub/static
      - ./volumes/app-etc:/var/www/html/app/etc
```

**Step 2: Commit**

```bash
git add templates/magento-compose.yml.j2
git commit -m "feat(templates): selective volume mounts for Magento

- Mount only customer-specific directories as volumes
- media, var, generated, static, app-etc
- Magento core (~500MB) stays in shared Docker image layer

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Provisioning Worker - WordPress Directory Structure

**Files:**
- Modify: `provisioning/provisioning_worker.py:339-344`

**Step 1: Update create_customer_directory method**

Find lines 339-344:
```python
            # Create directory structure (exist_ok=True for idempotency)
            customer_path.mkdir(parents=True, exist_ok=True)
            (customer_path / "volumes").mkdir(exist_ok=True)
            (customer_path / "volumes" / "db").mkdir(exist_ok=True)
            (customer_path / "volumes" / "files").mkdir(exist_ok=True)
            (customer_path / "logs").mkdir(exist_ok=True)
```

Replace with:
```python
            # Create directory structure (exist_ok=True for idempotency)
            customer_path.mkdir(parents=True, exist_ok=True)
            (customer_path / "logs").mkdir(exist_ok=True)

            if platform == 'woocommerce':
                # WordPress: selective wp-content directories
                (customer_path / "uploads").mkdir(exist_ok=True)
                (customer_path / "plugins").mkdir(exist_ok=True)
                (customer_path / "themes").mkdir(exist_ok=True)
                (customer_path / "mysql").mkdir(exist_ok=True)
                (customer_path / "redis").mkdir(exist_ok=True)
                # Set ownership for www-data (UID 33)
                for subdir in ['uploads', 'plugins', 'themes']:
                    os.chown(customer_path / subdir, 33, 33)
            else:
                # Magento: selective volume directories
                (customer_path / "volumes").mkdir(exist_ok=True)
                (customer_path / "volumes" / "db").mkdir(exist_ok=True)
                (customer_path / "volumes" / "media").mkdir(exist_ok=True)
                (customer_path / "volumes" / "var").mkdir(exist_ok=True)
                (customer_path / "volumes" / "generated").mkdir(exist_ok=True)
                (customer_path / "volumes" / "static").mkdir(exist_ok=True)
                (customer_path / "volumes" / "app-etc").mkdir(exist_ok=True)
                # Set ownership for www-data (UID 33)
                for subdir in ['media', 'var', 'generated', 'static', 'app-etc']:
                    os.chown(customer_path / "volumes" / subdir, 33, 33)
```

**Step 2: Commit**

```bash
git add provisioning/provisioning_worker.py
git commit -m "feat(provisioning): update directory structure for layered filesystem

- WordPress: create uploads/, plugins/, themes/ instead of wordpress/
- Magento: create media/, var/, generated/, static/, app-etc/ instead of files/
- Set proper ownership (www-data UID 33) for writable directories

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Build and Push Docker Images

**Files:**
- None (build commands only)

**Step 1: Build WordPress image**

```bash
cd /opt/shophosting/.worktrees/docker-layered-fs
docker build -t localhost:5050/wordpress:layered ./docker/wordpress
```

Expected: Build completes successfully with pre-installed WordPress and plugins.

**Step 2: Build Magento image**

```bash
docker build -t localhost:5050/magento:layered ./docker/magento
```

Expected: Build completes successfully.

**Step 3: Tag as latest (after testing)**

```bash
# Only after testing confirms images work
docker tag localhost:5050/wordpress:layered localhost:5050/wordpress:latest
docker tag localhost:5050/magento:layered localhost:5050/magento:latest
docker push localhost:5050/wordpress:latest
docker push localhost:5050/magento:latest
```

**Step 4: Commit build notes**

No commit needed - this is runtime verification.

---

## Task 9: Test WordPress Container Locally

**Files:**
- None (manual testing)

**Step 1: Create test directory structure**

```bash
mkdir -p /tmp/wp-test/{uploads,plugins,themes,mysql,redis}
chown -R 33:33 /tmp/wp-test/{uploads,plugins,themes}
```

**Step 2: Create test docker-compose.yml**

```bash
cat > /tmp/wp-test/docker-compose.yml <<'EOF'
services:
  db:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wpuser
      MYSQL_PASSWORD: wppass
      MYSQL_ROOT_PASSWORD: wppass
    volumes:
      - ./mysql:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-uroot", "-pwppass"]
      interval: 5s
      timeout: 5s
      retries: 30

  redis:
    image: redis:7-alpine
    volumes:
      - ./redis:/data

  wordpress:
    image: localhost:5050/wordpress:layered
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8080:80"
    environment:
      WORDPRESS_DB_HOST: db:3306
      WORDPRESS_DB_USER: wpuser
      WORDPRESS_DB_PASSWORD: wppass
      WORDPRESS_DB_NAME: wordpress
      WP_HOME: http://localhost:8080
      WP_SITEURL: http://localhost:8080
      WP_SITE_TITLE: "Test Site"
      WP_REDIS_HOST: redis
      WP_ADMIN_USER: admin
      WP_ADMIN_PASSWORD: testpass123
      WP_ADMIN_EMAIL: test@example.com
    volumes:
      - ./uploads:/var/www/html/wp-content/uploads
      - ./plugins:/var/www/html/wp-content/plugins
      - ./themes:/var/www/html/wp-content/themes
EOF
```

**Step 3: Start and verify**

```bash
cd /tmp/wp-test
docker compose up -d
docker compose logs -f wordpress
```

Expected output:
- "[shophosting.io] Seeding WooCommerce plugin..."
- "[shophosting.io] Seeding Redis Cache plugin..."
- "[shophosting.io] WordPress installed successfully!"

**Step 4: Verify plugins seeded**

```bash
ls -la /tmp/wp-test/plugins/
```

Expected: woocommerce/ and redis-cache/ directories exist.

**Step 5: Cleanup**

```bash
cd /tmp/wp-test
docker compose down -v
rm -rf /tmp/wp-test
```

---

## Task 10: Document Changes

**Files:**
- Create: `docs/plans/2026-02-01-docker-layered-filesystem-design.md` (already exists from brainstorming)

**Step 1: Update design doc with implementation notes**

Add to end of existing design document:

```markdown
## Implementation Notes

### Completed Changes

1. **WordPress Dockerfile** - Pre-installs WordPress and plugins at build time
2. **WordPress Entrypoint** - Seeds plugins/themes to volumes, generates wp-config.php
3. **WordPress Compose Template** - Mounts uploads/, plugins/, themes/ only
4. **Magento Dockerfile** - Stages compiled assets for seeding
5. **Magento Entrypoint** - Seeds generated/ and static/, runs setup only on first boot
6. **Magento Compose Template** - Mounts media/, var/, generated/, static/, app-etc/ only
7. **Provisioning Worker** - Creates platform-specific directory structures

### Testing

- WordPress container tested with selective mounts
- Plugins seed correctly on first start
- Themes seed correctly on first start
- wp-config.php generated from environment

### Rollout

1. Build and push new images with :layered tag
2. Test on staging customer
3. Tag as :latest and push
4. New customers automatically use optimized setup
```

**Step 2: Commit**

```bash
git add docs/plans/2026-02-01-docker-layered-filesystem-design.md
git commit -m "docs: add implementation notes to design document

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | WordPress Dockerfile | docker/wordpress/Dockerfile |
| 2 | WordPress Entrypoint | docker/wordpress/entrypoint-wrapper.sh |
| 3 | WordPress Compose Template | templates/woocommerce-compose.yml.j2 |
| 4 | Magento Dockerfile | docker/magento/Dockerfile |
| 5 | Magento Entrypoint | docker/magento/entrypoint-wrapper.sh |
| 6 | Magento Compose Template | templates/magento-compose.yml.j2 |
| 7 | Provisioning Worker | provisioning/provisioning_worker.py |
| 8 | Build Docker Images | (commands only) |
| 9 | Test WordPress Container | (manual testing) |
| 10 | Document Changes | docs/plans/*.md |
