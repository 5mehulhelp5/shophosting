#!/bin/bash
# ShopHosting.io Restore Script
# Restores data from restic backup

set -euo pipefail

# Configuration
RESTIC_REPOSITORY="sftp:sh-backup@15.204.249.219:/home/sh-backup/backups"
RESTIC_PASSWORD_FILE="/root/.restic-password"

export RESTIC_REPOSITORY
export RESTIC_PASSWORD_FILE

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "ShopHosting.io Restore Tool"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  list                     List all available snapshots"
    echo "  show <snapshot-id>       Show contents of a snapshot"
    echo "  restore-customer <id> <snapshot-id>  Restore a specific customer"
    echo "  restore-file <path> <snapshot-id>    Restore a specific file/directory"
    echo "  restore-db <db-name> <snapshot-id>   Restore a database from SQL dump"
    echo "  restore-all <snapshot-id>            Full disaster recovery (CAUTION!)"
    echo ""
    echo "Examples:"
    echo "  $0 list"
    echo "  $0 show latest"
    echo "  $0 restore-customer 12 latest"
    echo "  $0 restore-file /var/customers/customer-12/wordpress latest"
    echo "  $0 restore-db shophosting_db latest"
    echo ""
    exit 1
}

list_snapshots() {
    echo -e "${GREEN}Available snapshots:${NC}"
    restic snapshots
}

show_snapshot() {
    local snapshot_id="${1:-latest}"
    echo -e "${GREEN}Contents of snapshot $snapshot_id:${NC}"
    restic ls "$snapshot_id" | head -100
    echo ""
    echo "(Showing first 100 entries. Use 'restic ls $snapshot_id' for full listing)"
}

restore_customer() {
    local customer_id="$1"
    local snapshot_id="${2:-latest}"
    local customer_path="/var/customers/customer-${customer_id}"
    local restore_target="/tmp/restore-customer-${customer_id}"

    echo -e "${YELLOW}Restoring customer $customer_id from snapshot $snapshot_id${NC}"

    # Create restore directory
    mkdir -p "$restore_target"

    # Restore customer files
    echo "Restoring customer files..."
    restic restore "$snapshot_id" \
        --target "$restore_target" \
        --include "$customer_path"

    echo -e "${GREEN}Files restored to: $restore_target${NC}"
    echo ""
    echo "To complete the restore:"
    echo "  1. Stop the customer containers: cd $customer_path && docker compose down"
    echo "  2. Backup current data: mv $customer_path ${customer_path}.old"
    echo "  3. Move restored data: mv ${restore_target}${customer_path} $customer_path"
    echo "  4. Start containers: cd $customer_path && docker compose up -d"
    echo "  5. Cleanup: rm -rf ${customer_path}.old $restore_target"
}

restore_file() {
    local file_path="$1"
    local snapshot_id="${2:-latest}"
    local restore_target="/tmp/restore-$(date +%Y%m%d-%H%M%S)"

    echo -e "${YELLOW}Restoring $file_path from snapshot $snapshot_id${NC}"

    mkdir -p "$restore_target"

    restic restore "$snapshot_id" \
        --target "$restore_target" \
        --include "$file_path"

    echo -e "${GREEN}Restored to: $restore_target${NC}"
}

restore_db() {
    local db_name="$1"
    local snapshot_id="${2:-latest}"
    local restore_target="/tmp/restore-db-$(date +%Y%m%d-%H%M%S)"

    echo -e "${YELLOW}Restoring database $db_name from snapshot $snapshot_id${NC}"

    # Load DB credentials
    source /opt/shophosting/.env

    mkdir -p "$restore_target"

    # Restore the SQL dump
    restic restore "$snapshot_id" \
        --target "$restore_target" \
        --include "/tmp/shophosting-db-dumps/${db_name}.sql"

    local sql_file="$restore_target/tmp/shophosting-db-dumps/${db_name}.sql"

    if [ ! -f "$sql_file" ]; then
        echo -e "${RED}Error: SQL dump not found in snapshot${NC}"
        exit 1
    fi

    echo "SQL dump restored: $sql_file"
    echo ""
    echo "To import the database, run:"
    echo "  mysql -h ${DB_HOST:-localhost} -u ${DB_USER:-shophosting_app} -p $db_name < $sql_file"
    echo ""
    echo -e "${YELLOW}WARNING: This will overwrite the existing database!${NC}"
}

restore_all() {
    local snapshot_id="${1:-latest}"

    echo -e "${RED}============================================${NC}"
    echo -e "${RED}    FULL DISASTER RECOVERY MODE${NC}"
    echo -e "${RED}============================================${NC}"
    echo ""
    echo "This will restore ALL data from snapshot $snapshot_id"
    echo "This is a destructive operation!"
    echo ""
    read -p "Type 'YES' to continue: " confirm

    if [ "$confirm" != "YES" ]; then
        echo "Aborted."
        exit 1
    fi

    local restore_target="/tmp/full-restore-$(date +%Y%m%d-%H%M%S)"

    echo "Restoring to $restore_target..."
    restic restore "$snapshot_id" --target "$restore_target"

    echo -e "${GREEN}Full restore complete!${NC}"
    echo ""
    echo "Restored data is in: $restore_target"
    echo ""
    echo "Manual steps to complete recovery:"
    echo "  1. Stop all services"
    echo "  2. Replace /var/customers with restored data"
    echo "  3. Replace nginx configs"
    echo "  4. Import database dumps"
    echo "  5. Restore SSL certificates"
    echo "  6. Restart all services"
}

# Main
case "${1:-}" in
    list)
        list_snapshots
        ;;
    show)
        show_snapshot "${2:-latest}"
        ;;
    restore-customer)
        [ -z "${2:-}" ] && usage
        restore_customer "$2" "${3:-latest}"
        ;;
    restore-file)
        [ -z "${2:-}" ] && usage
        restore_file "$2" "${3:-latest}"
        ;;
    restore-db)
        [ -z "${2:-}" ] && usage
        restore_db "$2" "${3:-latest}"
        ;;
    restore-all)
        restore_all "${2:-latest}"
        ;;
    *)
        usage
        ;;
esac
