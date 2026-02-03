#!/bin/bash
# Send notification to Telegram
# Usage: notify-telegram.sh "message"
#    or: echo "message" | notify-telegram.sh
#
# Reads TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USERS from opsbot's .env
# This script is standalone and works even if opsbot is down.

set -e

# Load config from opsbot
OPSBOT_ENV="/opt/shophosting/opsbot/.env"

if [[ ! -f "$OPSBOT_ENV" ]]; then
    echo "Error: Opsbot .env file not found at $OPSBOT_ENV" >&2
    exit 1
fi

# Source only the needed variables
eval "$(grep -E '^TELEGRAM_BOT_TOKEN=|^TELEGRAM_ALLOWED_USERS=' "$OPSBOT_ENV")"

if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
    echo "Error: TELEGRAM_BOT_TOKEN not found in $OPSBOT_ENV" >&2
    exit 1
fi

if [[ -z "$TELEGRAM_ALLOWED_USERS" ]]; then
    echo "Error: TELEGRAM_ALLOWED_USERS not found in $OPSBOT_ENV" >&2
    exit 1
fi

# Get message from argument or stdin
MESSAGE="${1:-$(cat)}"

if [[ -z "$MESSAGE" ]]; then
    echo "Error: No message provided" >&2
    echo "Usage: $0 \"message\" or echo \"message\" | $0" >&2
    exit 1
fi

# Send to all allowed users
for CHAT_ID in ${TELEGRAM_ALLOWED_USERS//,/ }; do
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=${MESSAGE}" \
        -d "parse_mode=HTML" > /dev/null
done
