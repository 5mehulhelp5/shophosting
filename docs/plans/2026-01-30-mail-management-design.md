# Mail Management Admin Interface Design

**Date:** 2026-01-30
**Status:** Approved
**Author:** Design Session

## Overview

Add a mailbox management interface to the super admin panel supporting mixed authentication (system PAM users + virtual MySQL users) with full-featured management capabilities.

## Requirements

- **User types:** Mixed - existing system users continue working, new virtual mailboxes from database
- **Features:** Full-featured - quotas, forwarding, aliases, catch-all, autoresponders, usage stats
- **Domain scope:** Single domain (`shophosting.io`)
- **Storage:** MySQL (existing database)

---

## Database Schema

```sql
-- Virtual mailboxes (email accounts)
CREATE TABLE mail_mailboxes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,        -- full address: user@shophosting.io
    username VARCHAR(64) NOT NULL UNIQUE,      -- local part: user
    password_hash VARCHAR(255) NOT NULL,       -- dovecot-compatible hash
    quota_mb INT DEFAULT 1024,                 -- mailbox size limit
    is_active BOOLEAN DEFAULT TRUE,
    is_system_user BOOLEAN DEFAULT FALSE,      -- TRUE = PAM auth, FALSE = virtual
    forward_to TEXT NULL,                      -- comma-separated addresses
    is_catch_all BOOLEAN DEFAULT FALSE,        -- receives unmatched mail
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Email aliases (multiple addresses → one mailbox)
CREATE TABLE mail_aliases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    alias VARCHAR(255) NOT NULL UNIQUE,        -- alias@shophosting.io
    destination_mailbox_id INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (destination_mailbox_id) REFERENCES mail_mailboxes(id) ON DELETE CASCADE
);

-- Autoresponders (vacation messages)
CREATE TABLE mail_autoresponders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mailbox_id INT NOT NULL UNIQUE,
    subject VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    start_date DATE NULL,
    end_date DATE NULL,
    FOREIGN KEY (mailbox_id) REFERENCES mail_mailboxes(id) ON DELETE CASCADE
);
```

The `is_system_user` flag distinguishes PAM users (existing Linux accounts) from pure virtual mailboxes. System users authenticate via PAM; virtual users authenticate against `password_hash`.

---

## Dovecot Configuration

### Auth Chain (`/etc/dovecot/conf.d/auth-mixed.conf.ext`)

```conf
# Virtual users from MySQL (checked first)
passdb {
  driver = sql
  args = /etc/dovecot/dovecot-sql.conf.ext
}

# Fall back to system users (PAM)
passdb {
  driver = pam
  args = dovecot
}

# Virtual user mailbox locations
userdb {
  driver = sql
  args = /etc/dovecot/dovecot-sql.conf.ext
}

# System user mailbox locations
userdb {
  driver = passwd
}
```

### SQL Config (`/etc/dovecot/dovecot-sql.conf.ext`)

```conf
driver = mysql
connect = host=localhost dbname=shophosting user=mailuser password=<secure>

# Password query - only for virtual users
password_query = SELECT email as user, password_hash as password \
  FROM mail_mailboxes \
  WHERE email = '%u' AND is_active = 1 AND is_system_user = 0

# User query - mailbox location for virtual users
user_query = SELECT '/var/mail/vhosts/%d/%n' as home, \
  5000 as uid, 5000 as gid, CONCAT('*:bytes=', quota_mb * 1024 * 1024) as quota_rule \
  FROM mail_mailboxes \
  WHERE email = '%u' AND is_active = 1 AND is_system_user = 0
```

### Changes to `10-auth.conf`

```conf
# Disable default system auth
#!include auth-system.conf.ext

# Use custom auth chain
!include auth-mixed.conf.ext
```

Virtual mailboxes stored in `/var/mail/vhosts/shophosting.io/<username>/` using Maildir format.

---

## Postfix Configuration

### Additions to `/etc/postfix/main.cf`

```conf
# Virtual mailbox configuration
virtual_mailbox_domains = shophosting.io
virtual_mailbox_base = /var/mail/vhosts
virtual_mailbox_maps = mysql:/etc/postfix/mysql-virtual-mailboxes.cf
virtual_alias_maps = mysql:/etc/postfix/mysql-virtual-aliases.cf
virtual_uid_maps = static:5000
virtual_gid_maps = static:5000

# Remove shophosting.io from mydestination (now virtual)
mydestination = $myhostname, localhost
```

### `/etc/postfix/mysql-virtual-mailboxes.cf`

```conf
hosts = localhost
user = mailuser
password = <secure>
dbname = shophosting
query = SELECT CONCAT(username, '/') FROM mail_mailboxes
        WHERE email = '%s' AND is_active = 1
```

### `/etc/postfix/mysql-virtual-aliases.cf`

```conf
hosts = localhost
user = mailuser
password = <secure>
dbname = shophosting

# Combines aliases + catch-all + forwarding
query = SELECT destination FROM (
    SELECT m.email as destination FROM mail_aliases a
    JOIN mail_mailboxes m ON a.destination_mailbox_id = m.id
    WHERE a.alias = '%s' AND a.is_active = 1
  UNION
    SELECT forward_to FROM mail_mailboxes
    WHERE email = '%s' AND forward_to IS NOT NULL AND is_active = 1
  UNION
    SELECT email FROM mail_mailboxes
    WHERE is_catch_all = 1 AND is_active = 1
    AND '%s' LIKE CONCAT('%%@', 'shophosting.io')
) combined LIMIT 1
```

---

## Admin Panel Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/mail` | GET | Dashboard - mailbox list, usage stats, quick actions |
| `/mail/mailboxes` | GET | Paginated mailbox list with search/filter |
| `/mail/mailboxes/create` | GET/POST | Create new mailbox form |
| `/mail/mailboxes/<id>/edit` | GET/POST | Edit mailbox (quota, password, status) |
| `/mail/mailboxes/<id>/delete` | POST | Delete mailbox (with confirmation) |
| `/mail/aliases` | GET | Alias list |
| `/mail/aliases/create` | GET/POST | Create alias |
| `/mail/aliases/<id>/delete` | POST | Delete alias |
| `/mail/catch-all` | GET/POST | Configure catch-all address |
| `/mail/autoresponders` | GET | List autoresponders |
| `/mail/autoresponders/<id>/edit` | GET/POST | Edit autoresponder |
| `/mail/api/stats` | GET | JSON endpoint for usage statistics |
| `/mail/api/usage/<id>` | GET | Individual mailbox disk usage |

---

## UI Templates

| Template | Purpose |
|----------|---------|
| `mail_dashboard.html` | Overview with stats cards |
| `mail_mailboxes.html` | Searchable/sortable mailbox table |
| `mail_mailbox_form.html` | Create/edit mailbox form |
| `mail_aliases.html` | Alias management table |
| `mail_autoresponder_form.html` | Vacation message editor |
| `mail_catch_all.html` | Catch-all configuration |

**UI Layout:**
- Sidebar gets new "Mail" section with sub-items
- Main mailbox list shows: email, quota used/limit, status, last login
- Detail view has tabs: Settings, Aliases, Autoresponder, Usage History
- Bulk actions: enable/disable multiple mailboxes

---

## Backend Implementation

### New Module: `/opt/shophosting/webapp/admin/mail.py`

```python
class Mailbox:
    @staticmethod
    def create(username, password, quota_mb=1024)
    def update(id, **kwargs)
    def delete(id)  # removes maildir too
    def set_password(id, new_password)  # dovecot-compatible hash
    def get_all(search=None, status=None, page=1)
    def get_by_id(id)
    def get_usage(id)  # disk usage from maildir

class Alias:
    @staticmethod
    def create(alias, destination_mailbox_id)
    def delete(id)
    def get_all()

class Autoresponder:
    @staticmethod
    def get_by_mailbox(mailbox_id)
    def save(mailbox_id, subject, body, start_date, end_date, is_active)
```

### Password Hashing (Dovecot-compatible)

```python
import subprocess

def hash_password(plain):
    result = subprocess.run(
        ['doveadm', 'pw', '-s', 'SHA512-CRYPT', '-p', plain],
        capture_output=True, text=True
    )
    return result.stdout.strip()
```

### Mailbox Usage Stats

```python
def get_maildir_size(username):
    path = f"/var/mail/vhosts/shophosting.io/{username}"
    result = subprocess.run(['du', '-sb', path], capture_output=True, text=True)
    return int(result.stdout.split()[0]) if result.returncode == 0 else 0
```

### Autoresponder Delivery

Handled via Dovecot Sieve - when autoresponder is enabled, write a `.sieve` file to the user's maildir that sends the vacation reply.

---

## Key Behaviors

1. **Existing system users** (like `agileweb`) keep working - imported as `is_system_user = TRUE`
2. **New virtual mailboxes** get Maildir at `/var/mail/vhosts/shophosting.io/<user>/`
3. **Quotas** enforced by Dovecot, displayed in admin UI
4. **Catch-all** receives mail for non-existent addresses
5. **Autoresponders** use Dovecot Sieve

---

## Implementation Checklist

- [ ] Create database migration for new tables
- [ ] Create `vmail` user (uid/gid 5000) and directory structure
- [ ] Configure Dovecot mixed auth
- [ ] Configure Postfix virtual delivery
- [ ] Create mail.py backend module
- [ ] Create admin routes in routes.py
- [ ] Create 6 admin templates
- [ ] Add sidebar navigation entry
- [ ] Import existing system user (agileweb) to mail_mailboxes
- [ ] Test virtual mailbox creation and delivery
- [ ] Test system user authentication still works
- [ ] Test aliases, forwarding, catch-all
- [ ] Test autoresponders with Sieve
