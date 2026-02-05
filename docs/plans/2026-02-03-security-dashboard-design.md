# Security Dashboard Design

**Date:** 2026-02-03
**Status:** Approved
**Author:** Claude + Nathan

## Overview

A standalone security application for ShopHosting that provides malware scanning, penetration testing, lockdown procedures, and comprehensive security monitoring with a cyberpunk "hacking the mainframe" aesthetic.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Security Dashboard                            │
│                  (Flask app, port 8443)                         │
├─────────────────────────────────────────────────────────────────┤
│  Dashboard  │  Malware  │  Pen Tests  │  Lockdown  │  History  │
└──────┬──────────┬───────────┬─────────────┬───────────┬────────┘
       │          │           │             │           │
       ▼          ▼           ▼             ▼           ▼
┌──────────┐ ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────────┐
│ Metrics  │ │ ClamAV  │ │  ZAP    │ │  Docker   │ │ SQLite/  │
│ Aggreg.  │ │  + LMD  │ │  Nmap   │ │  iptables │ │ Postgres │
│          │ │         │ │  Nikto  │ │  nginx    │ │          │
└──────────┘ └─────────┘ └─────────┘ └───────────┘ └──────────┘
       │          │           │             │
       └──────────┴───────────┴─────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │     Opsbot       │
              │  (Telegram API)  │
              └──────────────────┘
```

**Components:**
- **Flask application** - Admin-only access, 2FA required
- **Redis queue** - Background job processing for scans
- **ClamAV daemon** - Always running, signatures auto-updated
- **LMD** - Integrated with ClamAV for web-specific malware
- **Docker socket** - For container inspection and lockdown
- **Opsbot webhook** - Push alerts to existing Telegram bot

## Malware Scanning System

### Scanning Engine Stack

| Component | Purpose | Location |
|-----------|---------|----------|
| ClamAV daemon (clamd) | Core scan engine, signature matching | Host system |
| freshclam | Auto-update virus definitions (hourly) | Host system |
| clamonacc | Real-time on-access scanning | Host system |
| LMD (maldet) | Web-specific malware signatures | Host system |

### Scan Types

1. **Real-time monitoring** (always active)
   - Watches all customer container volumes via fanotify
   - Watches platform config directories
   - Immediate alert on detection, auto-quarantine

2. **Scheduled full scans** (daily at 3 AM)
   - Deep scan of all container filesystems
   - Platform directories (/opt/shophosting)
   - Results logged and compared to previous scan

3. **On-demand scans** (from dashboard)
   - Scan specific customer container
   - Scan specific path
   - Full platform scan

### Detection Response

```
Threat Detected → Quarantine File → Log Event → Alert Opsbot → Dashboard Update
                         ↓
              (if critical) → Auto-isolate Container
```

**Quarantine location:** `/var/quarantine/malware/YYYY-MM-DD/`

## Penetration Testing System

### Tool Stack

| Tool | Purpose | Scan Time |
|------|---------|-----------|
| OWASP ZAP | Web app vulnerabilities (SQLi, XSS, CSRF) | 2-20 min |
| Nmap | Port scanning, service detection | 1-5 min |
| Nikto | Web server misconfigurations, outdated software | 3-10 min |

### Scan Profiles

1. **Quick Scan** (~3 min)
   - ZAP baseline (passive)
   - Nmap top 100 ports
   - Good for regular checks

2. **Standard Scan** (~15 min)
   - ZAP baseline + active (limited)
   - Nmap top 1000 ports + service detection
   - Nikto scan
   - Recommended for weekly checks

3. **Deep Scan** (~30-45 min)
   - ZAP full active scan
   - Nmap all ports + OS detection + scripts
   - Nikto with all plugins
   - For thorough audits

### Scannable Targets

- `https://shophosting.io` (platform)
- `https://*.shophosting.io` (subdomains)
- Customer sites: `https://{customer}.shophosting.io` or custom domains

### Scan Execution

```
Dashboard Request → Redis Queue → Docker Container (isolated)
                                        ↓
                              Run ZAP/Nmap/Nikto
                                        ↓
                              Parse Results → Store DB
                                        ↓
                              Alert if Critical Findings
```

Each scan runs in an isolated Docker container to prevent interference.

## Lockdown Procedures

### Container-Level Lockdown

| Action | Implementation | Reversible |
|--------|----------------|------------|
| **Isolate Network** | `docker network disconnect` - cuts container off from all networks | Yes |
| **Read-Only Mode** | Remount container filesystem as read-only | Yes |
| **Suspend** | `docker pause` - freezes all processes | Yes |
| **Stop** | `docker stop` - full shutdown | Yes |
| **Quarantine Files** | Move infected files to `/var/quarantine/` with metadata | Yes |

### Platform-Level Lockdown

| Action | Implementation | Reversible |
|--------|----------------|------------|
| **Block IP** | Add to iptables DROP + nginx deny list | Yes |
| **Block IP Range** | CIDR block via iptables | Yes |
| **Maintenance Mode** | Toggle nginx to serve maintenance page | Yes |
| **Disable Signups** | Set flag in webapp config, API returns 503 | Yes |
| **Disable Logins** | Emergency auth lockout (admin bypass via token) | Yes |

### Automated Responses (configurable)

```
Threat Level    │ Auto Response
────────────────┼─────────────────────────────────────
LOW             │ Log + Dashboard alert
MEDIUM          │ Log + Quarantine file + Telegram alert
HIGH            │ Log + Quarantine + Isolate container + Telegram
CRITICAL        │ Log + Quarantine + Stop container + Telegram + Email
```

**Lockdown Audit Log:** Every action logged with timestamp, admin user, reason, and reversal status.

## Dashboard Features & UI

### Navigation

```
┌──────────────────────────────────────────────────────────────────┐
│ ◉ SHOPHOSTING SECURITY                    [Admin] [⚡ LOCKDOWN]  │
├────────┬────────┬────────┬────────┬────────┬────────────────────┤
│ THREAT │ MALWARE│ PENTEST│LOCKDOWN│ HISTORY│                    │
│ CENTER │ SCANS  │ SCANS  │ CONTROL│  LOGS  │                    │
└────────┴────────┴────────┴────────┴────────┴────────────────────┘
```

### Pages

**1. Threat Center (Home)**
- Live threat level indicator (GREEN/YELLOW/RED)
- Real-time feed of security events (matrix-style scrolling)
- Active scans status with progress bars
- Container health grid (visual map of all containers)
- Quick stats: threats today, quarantined files, blocked IPs

**2. Malware Scans**
- Start scan: select target (platform/customer/path)
- Active scan progress with live file count
- Recent scan results with threat breakdown
- Quarantine manager: view, restore, or delete quarantined files

**3. Pentest Scans**
- Start scan: select target URL + scan profile
- Live scan output (terminal-style)
- Results viewer: PASS/WARN/FAIL with expandable details
- Compare scans over time

**4. Lockdown Control**
- Container grid with one-click isolate/suspend/stop
- IP blocklist manager
- Platform toggles (maintenance mode, signups, logins)
- Active lockdowns with timer and release button

**5. History & Logs**
- Searchable security event log (90-day retention)
- Scan history with downloadable reports
- Lockdown audit trail

### UI Theme

**Cyberpunk "Hacking the Mainframe" Aesthetic:**
- Dark background with terminal greens and cyan accents
- Scan lines and CRT effects
- Matrix-style data flows
- Glowing elements and neon highlights
- Monospace fonts for data displays
- Animated progress indicators

## Opsbot Integration

### Alert Flow

```
Security Event → Security Dashboard DB → Webhook → Opsbot → Telegram
```

### Alert Types

| Event Type | Telegram Message |
|------------|------------------|
| Malware detected | 🔴 MALWARE: `{filename}` in `{container}` - `{threat_name}` |
| Container auto-isolated | ⚠️ ISOLATED: `{container}` due to `{reason}` |
| Pen test critical finding | 🔴 PENTEST: Critical vulnerability found on `{target}` |
| IP auto-blocked | 🛡️ BLOCKED: IP `{ip}` - `{reason}` |
| Lockdown activated | 🔒 LOCKDOWN: `{type}` activated by `{admin}` |
| Lockdown released | 🔓 RELEASED: `{type}` released by `{admin}` |
| Scan completed | ✅ SCAN: `{type}` on `{target}` - `{summary}` |

### New Opsbot Commands

| Command | Action |
|---------|--------|
| `security status` | Current threat level + active issues |
| `security scan <target>` | Trigger quick malware scan |
| `security block <ip>` | Block an IP address |
| `security lockdown <container>` | Isolate a container |
| `security release <container>` | Release container isolation |

### Implementation

- New file: `/opt/shophosting/opsbot/server_tools/security.py`
- Webhook endpoint on security dashboard: `POST /api/webhook/opsbot`
- Opsbot polls or receives push notifications for new alerts

## File Structure

```
/opt/shophosting/security/
├── app.py                    # Flask application entry
├── config.py                 # Configuration (DB, paths, thresholds)
├── requirements.txt
├── venv/
├── templates/
│   ├── base.html             # Cyberpunk base template
│   ├── threat_center.html
│   ├── malware_scans.html
│   ├── pentest_scans.html
│   ├── lockdown_control.html
│   └── history.html
├── static/
│   ├── css/
│   │   └── security.css      # Matrix/hacker aesthetic
│   └── js/
│       └── security.js       # Real-time updates, animations
├── scanners/
│   ├── __init__.py
│   ├── malware.py            # ClamAV/LMD integration
│   ├── pentest.py            # ZAP/Nmap/Nikto orchestration
│   └── realtime.py           # fanotify/inotify monitoring
├── lockdown/
│   ├── __init__.py
│   ├── container.py          # Docker container controls
│   ├── network.py            # iptables/nginx controls
│   └── platform.py           # Maintenance mode, auth controls
├── models.py                 # DB models (scans, threats, lockdowns)
├── worker.py                 # Redis queue worker for scans
└── api/
    ├── __init__.py
    └── webhooks.py           # Opsbot webhook endpoint
```

## Tech Stack

- **Backend:** Flask + Redis Queue (RQ)
- **Database:** SQLite (simple, file-based, sufficient for security logs)
- **Scanning:** ClamAV, LMD, ZAP (Docker), Nmap, Nikto
- **Real-time:** fanotify + inotify via Python watchdog
- **Frontend:** Vanilla JS + CSS (cyberpunk theme)
- **Auth:** Standalone with 2FA (TOTP)

## Deployment

### New Services

1. `security-dashboard.service` - Main web application (port 8443)
2. `security-worker.service` - Background scan processor (Redis queue)
3. `clamav-daemon.service` - Malware scanning engine
4. `security-monitor.service` - Real-time file monitoring

### Nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name security.shophosting.io;

    # SSL config (same certs as main site)

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # WebSocket support for real-time updates
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Documentation Updates

- Update Wiki.js services page with all 4 new services
- Add security dashboard to architecture documentation

## Data Retention

- Scan results: 90 days
- Security event logs: 90 days
- Quarantined files: Manual cleanup (with metadata preserved)
- Lockdown audit trail: 90 days

## Resource Requirements

Based on server specs (8 CPU, 62GB RAM):

| Component | Memory | CPU |
|-----------|--------|-----|
| ClamAV daemon | 1-1.5GB | ~1% idle |
| Real-time monitor | 50-100MB | 2-5% |
| Security dashboard | 100-200MB | ~1% |
| Scan workers | 200-500MB during scans | Variable |

**Total additional overhead:** ~2GB RAM, 5-10% CPU during active scanning

## Implementation Phases

### Phase 1: Foundation
- Set up directory structure
- Install ClamAV and LMD
- Create Flask app skeleton
- Implement database models
- Basic authentication

### Phase 2: Malware Scanning
- ClamAV integration
- LMD integration
- On-demand scanning
- Scheduled scanning
- Real-time monitoring

### Phase 3: Penetration Testing
- ZAP integration
- Nmap integration
- Nikto integration
- Scan profiles
- Results parsing and storage

### Phase 4: Lockdown System
- Container controls
- Network controls (iptables)
- Platform controls
- Automated responses
- Audit logging

### Phase 5: Dashboard UI
- Cyberpunk theme implementation
- Threat Center
- All dashboard pages
- Real-time updates (WebSocket)

### Phase 6: Opsbot Integration
- Security tools for opsbot
- Webhook endpoint
- Alert notifications
- Command handlers

### Phase 7: Deployment
- Systemd services
- Nginx configuration
- Wiki.js documentation
- Testing and validation
