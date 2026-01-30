#!/bin/bash
#
# Wiki.js Backup Script
# Backs up the PostgreSQL database and uploaded files
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${1:-$SCRIPT_DIR/backups}"
DATE=$(date +%Y%m%d_%H%M%S)

# Colors
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }

# Create backup directory
mkdir -p "$BACKUP_DIR"

log_info "Backing up Wiki.js..."

# Backup PostgreSQL database
log_info "Dumping database..."
docker exec shophosting-wikijs-db pg_dump -U wikijs wikijs > "$BACKUP_DIR/wikijs_db_$DATE.sql"

# Compress the backup
gzip "$BACKUP_DIR/wikijs_db_$DATE.sql"

# Backup uploaded files (from Docker volume)
log_info "Backing up uploaded files..."
docker run --rm \
    -v shophosting_wikijs_data:/data:ro \
    -v "$BACKUP_DIR":/backup \
    alpine tar czf "/backup/wikijs_data_$DATE.tar.gz" -C /data .

# Clean up old backups (keep last 7 days)
find "$BACKUP_DIR" -name "wikijs_*.sql.gz" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "wikijs_*.tar.gz" -mtime +7 -delete 2>/dev/null || true

log_info "Backup complete!"
log_info "  Database: $BACKUP_DIR/wikijs_db_$DATE.sql.gz"
log_info "  Files:    $BACKUP_DIR/wikijs_data_$DATE.tar.gz"
