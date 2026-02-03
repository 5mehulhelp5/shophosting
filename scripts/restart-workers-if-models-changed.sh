#!/bin/bash
#
# Restart Python workers if models.py has changed since last deploy.
# Called after git pull or deploy operations.
#
# Usage: ./restart-workers-if-models-changed.sh [commit_before] [commit_after]
#        If no args provided, compares HEAD~1 to HEAD
#

set -e

MODELS_FILE="webapp/models.py"
WORKERS=(
    "shophosting-backup-worker"
    "shophosting-provisioning-worker"
    "shophosting-staging-worker"
)

# Get commit range
BEFORE="${1:-HEAD~1}"
AFTER="${2:-HEAD}"

# Check if models.py changed
if git diff --name-only "$BEFORE" "$AFTER" | grep -q "^${MODELS_FILE}$"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - models.py changed, restarting workers..."

    for worker in "${WORKERS[@]}"; do
        if systemctl is-active --quiet "$worker" 2>/dev/null; then
            echo "  Restarting $worker..."
            sudo systemctl restart "$worker"
            sleep 2

            if systemctl is-active --quiet "$worker"; then
                echo "  ✓ $worker restarted successfully"
            else
                echo "  ✗ $worker failed to restart!"
                journalctl -u "$worker" -n 5 --no-pager
            fi
        else
            echo "  - $worker not running, skipping"
        fi
    done

    echo "$(date '+%Y-%m-%d %H:%M:%S') - Worker restart complete"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - models.py unchanged, no worker restart needed"
fi
