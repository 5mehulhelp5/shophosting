#!/bin/bash
#
# Wiki.js Setup Script for ShopHosting.io
# Sets up Wiki.js with PostgreSQL, nginx, and SSL
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="${1:-docs.shophosting.io}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check if running as root for nginx/certbot operations
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo)"
    exit 1
fi

log_info "Setting up Wiki.js for $DOMAIN..."

# Step 1: Start Wiki.js containers
log_info "Starting Wiki.js containers..."
cd "$SCRIPT_DIR"
docker compose up -d

# Wait for Wiki.js to be ready
log_info "Waiting for Wiki.js to start..."
for i in {1..60}; do
    if curl -sf http://127.0.0.1:9847/healthz > /dev/null 2>&1; then
        log_info "Wiki.js is ready!"
        break
    fi
    if [[ $i -eq 60 ]]; then
        log_error "Wiki.js failed to start. Check logs with: docker logs shophosting-wikijs"
        exit 1
    fi
    echo -n "."
    sleep 2
done
echo ""

# Step 2: Configure nginx
log_info "Configuring nginx..."

# Update domain in config if different
sed -i "s/docs.shophosting.io/$DOMAIN/g" "$SCRIPT_DIR/nginx-wikijs.conf"

# Copy nginx config
cp "$SCRIPT_DIR/nginx-wikijs.conf" "/etc/nginx/sites-available/$DOMAIN"

# Enable the site
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"

# Test nginx config
if ! nginx -t; then
    log_error "nginx configuration test failed!"
    exit 1
fi

# Reload nginx
systemctl reload nginx
log_info "nginx configured and reloaded"

# Step 3: Get SSL certificate
log_info "Obtaining SSL certificate..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@shophosting.io --redirect

log_info ""
log_info "=============================================="
log_info "Wiki.js setup complete!"
log_info "=============================================="
log_info ""
log_info "Access Wiki.js at: https://$DOMAIN"
log_info ""
log_info "First-time setup:"
log_info "  1. Go to https://$DOMAIN"
log_info "  2. Create your admin account"
log_info "  3. Configure site settings"
log_info ""
log_info "Recommended configuration:"
log_info "  - Enable local authentication"
log_info "  - Set up guest access for public pages"
log_info "  - Create groups: Customers, Developers, Internal"
log_info "  - Set up page rules for public/private sections"
log_info ""
log_info "Container management:"
log_info "  Start:   cd $SCRIPT_DIR && docker compose up -d"
log_info "  Stop:    cd $SCRIPT_DIR && docker compose down"
log_info "  Logs:    docker logs shophosting-wikijs -f"
log_info "  Backup:  docker exec shophosting-wikijs-db pg_dump -U wikijs wikijs > backup.sql"
