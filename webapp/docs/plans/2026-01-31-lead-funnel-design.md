# Lead Funnel & Speed Test Tool Design

**Date:** 2026-01-31
**Status:** Approved
**Goal:** Customer acquisition through free performance analysis tools

---

## Overview

Build a lead generation funnel that attracts growing WooCommerce/Magento store owners who are hitting performance limits. The funnel consists of:

1. **Free Speed Test Tool** - Analyzes their store's performance
2. **Email-Gated Full Report** - Captures lead information
3. **Migration Preview Offer** - Converts leads to trials

---

## Target Audience

- Existing store owners with performance problems
- Already generating revenue (have budget)
- Frustrated with current hosting limitations
- Searching for solutions to slow load times

---

## User Flow

### Stage 1: Quick Speed Test (Public, No Signup)

**URL:** `/speed-test`

User enters store URL and sees within 10-15 seconds:
- Overall performance score (0-100)
- Load time in seconds
- Teaser: "3 critical issues detected" (blurred/locked)
- CTA: "Get your full free report" → email capture

### Stage 2: Full Audit Report (Email Required)

**URL:** `/report/<scan_id>`

After email submission:
- **Speed & Performance**: Load time breakdown, Core Web Vitals, render-blocking resources
- **Hosting Health Check**: PHP version, caching, CDN, SSL, server response time
- **Revenue Impact**: Estimated monthly revenue loss based on load time

Report delivered on-screen and via email.

### Stage 3: Migration Preview CTA

Throughout report, contextual CTAs next to each problem:
- "Your TTFB is 1.8s → ShopHosting averages 0.2s"
- Final CTA: "See your actual store running on ShopHosting"

Submits migration preview request to admin queue.

---

## Technical Implementation

### APIs Used

| API | Purpose | Limits |
|-----|---------|--------|
| Google PageSpeed Insights | Lighthouse scores, Core Web Vitals, recommendations | ~25,000 requests/day (free) |
| Custom HTTP Probes | TTFB, headers, tech detection, SSL check | No limits (self-hosted) |

### Data Model

```sql
-- Stores all scan results
CREATE TABLE site_scans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(500) NOT NULL,
    email VARCHAR(255),
    performance_score INT,
    load_time_ms INT,
    ttfb_ms INT,
    pagespeed_data JSON,
    custom_probe_data JSON,
    estimated_revenue_loss DECIMAL(10,2),
    ip_address VARCHAR(45),
    converted_to_lead_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_email (email),
    INDEX idx_created_at (created_at)
);

-- Tracks migration preview requests
CREATE TABLE migration_preview_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_scan_id INT NOT NULL,
    email VARCHAR(255) NOT NULL,
    store_url VARCHAR(500) NOT NULL,
    store_platform ENUM('woocommerce', 'magento', 'unknown') DEFAULT 'unknown',
    monthly_revenue VARCHAR(50),
    current_host VARCHAR(100),
    status ENUM('pending', 'contacted', 'migrating', 'completed', 'rejected') DEFAULT 'pending',
    notes TEXT,
    assigned_admin_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (site_scan_id) REFERENCES site_scans(id),
    FOREIGN KEY (assigned_admin_id) REFERENCES admin_users(id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);
```

### File Structure

```
webapp/
├── leads/
│   ├── __init__.py              # Blueprint registration
│   ├── routes.py                # Public speed test routes
│   ├── models.py                # SiteScan, MigrationPreviewRequest
│   ├── scanner.py               # PageSpeed API + custom probing
│   └── email_templates/         # Nurture email templates
├── admin/
│   └── leads_routes.py          # Admin lead management
├── templates/
│   ├── leads/
│   │   ├── speed_test.html      # Landing page
│   │   └── report.html          # Full report page
│   └── admin/
│       └── leads/               # Admin templates
```

### Routes

**Public:**
```
GET  /speed-test                    → Landing page
POST /speed-test/scan               → Submit URL, start scan
GET  /speed-test/scan/<id>/status   → Poll scan progress (AJAX)
POST /speed-test/scan/<id>/unlock   → Submit email, unlock report
GET  /report/<id>                   → Full report page
POST /report/<id>/request-preview   → Submit migration preview request
```

**Admin:**
```
GET  /admin/leads                   → Lead dashboard
GET  /admin/leads/analytics         → Conversion stats
GET  /admin/leads/<id>              → Lead detail view
POST /admin/leads/<id>/notes        → Add note
POST /admin/leads/<id>/status       → Update status
GET  /admin/leads/previews          → Preview request queue
POST /admin/leads/previews/<id>/start → Create staging for preview
```

### Background Jobs

- `run_site_scan` - Calls PageSpeed API + custom probes
- `send_lead_email` - Sends nurture emails
- `create_preview_staging` - Creates staging environment for preview

---

## Admin Panel - Lead Management

### New Role: `acquisition`

**Can access:**
- Lead dashboard and management
- Scan analytics
- Migration preview requests
- Create staging for previews
- Send templated emails to leads

**Cannot access:**
- Customer management
- Billing, invoices, refunds
- Server management
- Support tickets
- Admin user management
- System settings

### Lead Dashboard (`/admin/leads`)

- Summary stats: Scans today, emails captured, preview requests pending
- Filterable table: Email, URL, Score, Revenue Loss, Status, Created
- Quick filters: All / New / Contacted / Migration Requested
- Search by email or URL

### Lead Detail View (`/admin/leads/<id>`)

- Full scan results and timeline
- Admin actions: Add notes, change status, send follow-up, create preview

### Analytics (`/admin/leads/analytics`)

- Scans per day/week
- Email capture rate
- Migration request rate
- Common hosting providers detected

---

## Interactive Design Elements

### During Scan (Loading State)
- Animated progress with live steps appearing
- Metrics ticking up as discovered
- Speedometer visualization
- 10-15 second engaging experience

### Score Reveal
- Counter animates 0 → final score
- Color transitions (green/yellow/red)
- Issues flip in like cards
- Blurred items shimmer

### Report Page
- Sections fade in on scroll
- Charts animate on viewport entry
- Revenue loss counter ticks dramatically
- Progress indicator on side

### Overall Vibe
- Stripe's polish + Vercel's dark mode + gamification
- Premium but not corporate
- Technical but approachable

---

## Email Nurturing

### Immediate Emails

**On email capture:**
- Subject: "Your store performance report is ready"
- Link to report, key findings summary, preview CTA

**On preview request:**
- Subject: "We're setting up your preview - here's what to expect"
- Timeline, what to expect, what to prepare

### Follow-up Sequence (No Preview Request)

| Day | Subject | Focus |
|-----|---------|-------|
| 2 | "The #1 issue slowing down [store]" | Their biggest problem |
| 5 | "How [their host] compares to managed hosting" | Educational |
| 10 | "Quick question about your store" | Soft check-in |
| 20 | "Your performance score may have changed" | Invite re-scan |

### Follow-up Sequence (After Preview Request)

| Day | Subject | Focus |
|-----|---------|-------|
| 3 | "Your preview is ready" | Staging URL |
| 5 | "Did you check your preview?" | Reminder |
| 10 | "Questions about migrating?" | Offer help |
| 20 | "Preview expires in 7 days" | Urgency |

---

## Revenue Impact Calculation

Formula based on industry data:
- Every 1 second load time = ~7% conversion drop
- Inputs: Estimated traffic × average order value × conversion loss
- Output: Monthly revenue loss estimate

Doesn't need to be perfectly accurate - needs to be plausible and motivating.

---

## Deliverables

1. **Public Speed Test Tool** - Landing page, scanner, report
2. **Lead Management Admin** - Dashboard, detail view, analytics
3. **`acquisition` Role** - New admin role with lead-only access
4. **Database Tables** - `site_scans`, `migration_preview_requests`
5. **Email Templates** - Nurture sequences
6. **Wiki.js Documentation** - Feature explanation and workflow

---

## Configuration Required

- Google PageSpeed Insights API key
- Email templates configured
- Nurture sequence timing in settings

---

## Success Metrics

- Scans per day
- Email capture rate (scans → emails)
- Preview request rate (emails → preview requests)
- Conversion rate (previews → paying customers)
