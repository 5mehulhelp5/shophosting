#!/bin/bash
# Fail2Ban Daily Digest - sends a single daily summary of banned IPs
# Add to crontab: 0 8 * * * /opt/shophosting/scripts/cron/f2b_daily_digest.sh

set -e

LOG_FILE="/opt/shophosting/logs/f2b_digest.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting F2B daily digest" >> "$LOG_FILE"

set -a
source /opt/shophosting/security/.env 2>/dev/null || true
source /opt/shophosting/.env 2>/dev/null || true
set +a

cd /opt/shophosting/security
/opt/shophosting/security/venv/bin/python3 -c "
from models import init_db
from api.webhooks import send_f2b_daily_digest
init_db()
send_f2b_daily_digest()
" >> "$LOG_FILE" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') - F2B daily digest completed" >> "$LOG_FILE"
