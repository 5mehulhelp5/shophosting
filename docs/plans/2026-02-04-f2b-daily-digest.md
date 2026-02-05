# Fail2Ban Daily Digest Alert Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace per-ban Telegram alerts with a single daily summary message sent every 24 hours.

**Architecture:** Replace the real-time `alert_f2b_ban()` call in `sync_to_db()` with a cron-triggered Python script that queries `fail2ban_events` from the last 24 hours and sends one consolidated Telegram message. The existing `alert_f2b_ban()` function is replaced with a `send_f2b_daily_digest()` function. A small cron wrapper script runs the digest daily.

**Tech Stack:** Python 3.10, SQLite (existing security DB), existing webhook infrastructure, cron.

---

### Task 1: Write the daily digest function

**Files:**
- Modify: `security/api/webhooks.py:190-199` (replace `alert_f2b_ban`)

**Step 1: Write the failing test**

Create `security/tests/test_f2b_digest.py`:

```python
"""Tests for Fail2Ban daily digest alert."""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

os.environ['SECURITY_DB_PATH'] = ':memory:'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import init_db, close_db, Fail2BanEvent
from api.webhooks import send_f2b_daily_digest


class TestF2bDailyDigest:
    def setup_method(self):
        init_db()

    def teardown_method(self):
        close_db()

    @patch('api.webhooks.send_opsbot_alert')
    def test_digest_sends_nothing_when_no_bans(self, mock_alert):
        send_f2b_daily_digest()
        mock_alert.assert_not_called()

    @patch('api.webhooks.send_opsbot_alert')
    def test_digest_sends_summary_with_bans(self, mock_alert):
        Fail2BanEvent.create('sshd-aggressive', 'Ban', '1.2.3.4',
                             datetime.now().isoformat())
        Fail2BanEvent.create('sshd-aggressive', 'Ban', '5.6.7.8',
                             datetime.now().isoformat())
        Fail2BanEvent.create('wordpress-login', 'Ban', '9.10.11.12',
                             datetime.now().isoformat())

        send_f2b_daily_digest()

        mock_alert.assert_called_once()
        msg = mock_alert.call_args[0][0]
        assert 'DAILY DIGEST' in msg
        assert '3' in msg  # total bans
        assert 'sshd-aggressive' in msg
        assert 'wordpress-login' in msg
        assert '1.2.3.4' in msg

    @patch('api.webhooks.send_opsbot_alert')
    def test_digest_skips_unban_events(self, mock_alert):
        Fail2BanEvent.create('sshd', 'Ban', '1.2.3.4',
                             datetime.now().isoformat())
        Fail2BanEvent.create('sshd', 'Unban', '1.2.3.4',
                             datetime.now().isoformat())

        send_f2b_daily_digest()

        mock_alert.assert_called_once()
        msg = mock_alert.call_args[0][0]
        # Should count 1 ban, not the unban
        assert '1 IP' in msg or 'Total bans: 1' in msg

    @patch('api.webhooks.send_opsbot_alert')
    def test_digest_groups_by_jail(self, mock_alert):
        Fail2BanEvent.create('sshd-aggressive', 'Ban', '1.1.1.1',
                             datetime.now().isoformat())
        Fail2BanEvent.create('sshd-aggressive', 'Ban', '2.2.2.2',
                             datetime.now().isoformat())
        Fail2BanEvent.create('nginx-badbots', 'Ban', '3.3.3.3',
                             datetime.now().isoformat())

        send_f2b_daily_digest()

        msg = mock_alert.call_args[0][0]
        assert 'sshd-aggressive' in msg
        assert 'nginx-badbots' in msg
```

**Step 2: Run test to verify it fails**

Run: `cd /opt/shophosting/security && python -m pytest tests/test_f2b_digest.py -v`
Expected: FAIL — `ImportError: cannot import name 'send_f2b_daily_digest'`

**Step 3: Implement `send_f2b_daily_digest` and remove `alert_f2b_ban`**

In `security/api/webhooks.py`, replace the `alert_f2b_ban` function (lines 190-199) with:

```python
def send_f2b_daily_digest():
    """Send a single daily summary of all Fail2Ban bans from the last 24 hours.

    Queries the fail2ban_events table for Ban events in the past 24h,
    groups them by jail, and sends one consolidated Telegram message.
    Does nothing if there were no bans.
    """
    try:
        from models import Fail2BanEvent
    except ImportError:
        logger.warning("Fail2BanEvent model not available; cannot send digest")
        return

    events = Fail2BanEvent.get_recent_bans(hours=24)

    if not events:
        logger.info("No fail2ban bans in last 24h — skipping digest")
        return

    # Group by jail
    jails = {}
    for event in events:
        jail = event['jail']
        if jail not in jails:
            jails[jail] = []
        jails[jail].append(event['ip_address'])

    total = len(events)
    unique_ips = len({e['ip_address'] for e in events})

    # Build message
    lines = [f"📋 <b>FAIL2BAN: DAILY DIGEST</b>"]
    lines.append(f"Total bans: {total} ({unique_ips} unique IPs)\n")

    for jail, ips in sorted(jails.items(), key=lambda x: -len(x[1])):
        lines.append(f"<b>{jail}</b> — {len(ips)} bans")
        # Show up to 10 IPs per jail, then summarize
        shown = ips[:10]
        for ip in shown:
            lines.append(f"  <code>{ip}</code>")
        if len(ips) > 10:
            lines.append(f"  ... and {len(ips) - 10} more")
        lines.append("")

    msg = "\n".join(lines)
    send_opsbot_alert(msg, level='info')
```

**Step 4: Run test to verify it passes**

Run: `cd /opt/shophosting/security && python -m pytest tests/test_f2b_digest.py -v`
Expected: FAIL — `AttributeError: type object 'Fail2BanEvent' has no attribute 'get_recent_bans'`
(We still need the model method — see Task 2.)

---

### Task 2: Add `get_recent_bans()` to Fail2BanEvent model

**Files:**
- Modify: `security/models.py` (add method to `Fail2BanEvent` class, after `count_total`)

**Step 1: Write the failing test**

Add to `security/tests/test_f2b_digest.py`:

```python
class TestFail2BanEventGetRecentBans:
    def setup_method(self):
        init_db()

    def teardown_method(self):
        close_db()

    def test_returns_only_bans(self):
        Fail2BanEvent.create('sshd', 'Ban', '1.2.3.4',
                             datetime.now().isoformat())
        Fail2BanEvent.create('sshd', 'Unban', '1.2.3.4',
                             datetime.now().isoformat())
        bans = Fail2BanEvent.get_recent_bans(hours=24)
        assert len(bans) == 1
        assert bans[0]['action'] == 'Ban'

    def test_returns_empty_when_no_bans(self):
        bans = Fail2BanEvent.get_recent_bans(hours=24)
        assert bans == []
```

**Step 2: Run test to verify it fails**

Run: `cd /opt/shophosting/security && python -m pytest tests/test_f2b_digest.py::TestFail2BanEventGetRecentBans -v`
Expected: FAIL — `AttributeError`

**Step 3: Implement `get_recent_bans`**

Add this method to the `Fail2BanEvent` class in `security/models.py` after the existing `count_total` method:

```python
    @staticmethod
    def get_recent_bans(hours=24):
        """Get all Ban events from the last N hours."""
        db = get_db()
        rows = db.execute(
            """SELECT * FROM fail2ban_events
               WHERE action IN ('Ban', 'ban')
               AND timestamp >= datetime('now', ? || ' hours')
               ORDER BY timestamp DESC""",
            (f'-{hours}',)
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
```

**Step 4: Run ALL tests to verify everything passes**

Run: `cd /opt/shophosting/security && python -m pytest tests/test_f2b_digest.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add security/api/webhooks.py security/models.py security/tests/test_f2b_digest.py
git commit -m "feat(security): replace per-ban f2b alerts with daily digest

Replaces alert_f2b_ban() with send_f2b_daily_digest() that queries the
last 24h of ban events and sends one consolidated Telegram message
grouped by jail."
```

---

### Task 3: Remove per-ban alert call from sync_to_db

**Files:**
- Modify: `security/scanners/fail2ban.py:404-409`

**Step 1: Remove the real-time alert call**

In `security/scanners/fail2ban.py`, remove lines 404-409 (the `alert_f2b_ban` call inside `sync_to_db`):

```python
                # Notify opsbot of the ban
                try:
                    from api.webhooks import alert_f2b_ban
                    alert_f2b_ban(event['ip_address'], event['jail'])
                except Exception:
                    pass  # Don't fail sync over notification
```

This block fires on every single ban during sync — exactly the noise we're eliminating.

**Step 2: Run existing tests to verify nothing breaks**

Run: `cd /opt/shophosting/security && python -m pytest tests/ -v`
Expected: All pass.

**Step 3: Commit**

```bash
git add security/scanners/fail2ban.py
git commit -m "refactor(security): remove per-ban alert from sync_to_db

The per-ban Telegram notification is replaced by the daily digest
cron job, so the inline alert call is no longer needed."
```

---

### Task 4: Create the cron script and install it

**Files:**
- Create: `scripts/cron/f2b_daily_digest.sh`

**Step 1: Create the cron wrapper script**

```bash
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
```

**Step 2: Make executable and install cron entry**

```bash
chmod +x /opt/shophosting/scripts/cron/f2b_daily_digest.sh
# Add to agileweb crontab: run daily at 8:00 AM
(crontab -l; echo "0 8 * * * /opt/shophosting/scripts/cron/f2b_daily_digest.sh") | crontab -
```

**Step 3: Test manually**

Run: `/opt/shophosting/scripts/cron/f2b_daily_digest.sh`
Expected: Digest message appears in Telegram (or logs show "No fail2ban bans — skipping digest" if the DB is empty).

**Step 4: Commit**

```bash
git add scripts/cron/f2b_daily_digest.sh
git commit -m "feat(security): add daily fail2ban digest cron job

Runs at 8 AM daily, queries the last 24h of bans from the security DB,
and sends one consolidated summary to Telegram via opsbot."
```
