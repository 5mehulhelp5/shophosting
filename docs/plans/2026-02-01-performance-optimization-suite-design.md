# Performance Optimization Suite — Design Document

**Date**: 2026-02-01
**Status**: Draft
**Branch**: `feature/performance-optimization-suite`

## Executive Summary

A comprehensive performance optimization toolset for ShopHosting.io spanning three layers:
1. **Customer Self-Service** — Tiered dashboard tools (simple for basic plans, advanced for premium)
2. **Proactive Automation** — Customer-configurable auto-remediation system
3. **Admin Console** — Fleet-wide visibility, benchmarking, and intervention tools

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CUSTOMER DASHBOARD                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Health Score│  │ One-Click   │  │ Advanced Controls       │ │
│  │ & Insights  │  │ Optimize    │  │ (Premium Plans)         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                   AUTOMATION ENGINE                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Issue       │  │ Auto-Fix    │  │ Customer Automation     │ │
│  │ Detection   │  │ Playbooks   │  │ Preferences             │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      ADMIN CONSOLE                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Fleet Health│  │ Hotspot &   │  │ Predictive Alerts &     │ │
│  │ Dashboard   │  │ Benchmarks  │  │ Intervention Playbooks  │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Metrics     │  │ Query       │  │ External Probes         │ │
│  │ Collector   │  │ Analyzer    │  │ (Lighthouse, etc.)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Core Principle**: Every metric collected serves at least two purposes — customer visibility AND admin insight.

---

## 1. Customer Self-Service Tools

### 1.1 Health Score Dashboard (All Plans)

A single 0-100 health score computed from weighted factors:

| Factor | Weight | Metrics |
|--------|--------|---------|
| Page Speed | 30% | TTFB, LCP, FCP from synthetic probes |
| Resource Usage | 25% | CPU %, Memory %, Disk % vs limits |
| Database Health | 20% | Slow query count, connection usage, table sizes |
| Cache Efficiency | 15% | Redis hit rate, Varnish hit rate (Magento) |
| Uptime | 10% | Last 24h availability |

**Display**: Large circular gauge with color coding (green 80+, yellow 50-79, red <50), trend arrow, and drill-down to each factor.

### 1.2 Performance Insights Feed (All Plans)

Real-time feed of detected issues and recommendations:

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚠️  Slow database queries detected                    2 min ago │
│     3 queries averaging >2s. View details →                     │
├─────────────────────────────────────────────────────────────────┤
│ 💡 Recommendation: Enable Redis object caching       15 min ago │
│     Could improve load time by ~40%. Enable now →               │
├─────────────────────────────────────────────────────────────────┤
│ ✅ Memory usage normalized                            1 hour ago │
│     Peak of 92% resolved after cache cleanup                    │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 One-Click Optimize (All Plans)

Single button that runs a battery of safe optimizations:

**WooCommerce**:
- Flush object cache
- Clear transients
- Optimize autoload options
- Restart PHP-FPM if memory high
- Rebuild permalink structure

**Magento**:
- Flush all caches (config, layout, block, full_page)
- Reindex if stale
- Clean generated files
- Purge Varnish cache
- Restart PHP-FPM if needed

**Safety**: All operations are reversible or recreatable. No data loss possible.

### 1.4 Advanced Controls (Premium Plans Only)

Detailed tuning panel exposing:

| Category | Controls |
|----------|----------|
| **PHP** | Memory limit (128M-1G), max execution time, OPcache settings |
| **MySQL** | Query cache size, max connections, slow query threshold |
| **Redis** | Max memory, eviction policy, persistence settings |
| **Varnish** | Cache TTL, grace period, purge patterns (Magento) |
| **Cron** | Schedule viewer, manual trigger, disable toggles |

**Guardrails**: Values constrained to safe ranges. Dangerous combinations blocked with explanations.

### 1.5 Database Tools (Premium Plans Only)

- **Slow Query Log**: Paginated list with query text, execution time, frequency
- **Table Analyzer**: Size, row count, index usage, optimization suggestions
- **One-Click Table Optimization**: OPTIMIZE TABLE for fragmented tables
- **Query Explain**: Paste a query, see execution plan with recommendations

### 1.6 Traffic Analytics (Premium Plans Only)

- **Real-time visitor map**: Geographic distribution
- **Bot vs Human**: Traffic classification with bot blocking recommendations
- **Peak Hours**: Heatmap of traffic patterns
- **Bandwidth breakdown**: By content type (images, scripts, API calls)

---

## 2. Automation Engine

### 2.1 Customer Automation Preferences

Three-tier preference system stored per customer:

| Level | Name | Behavior |
|-------|------|----------|
| 1 | **Notify Only** | Detect issues, send alerts, take no action |
| 2 | **Safe Auto-Fix** | Apply reversible fixes automatically, notify after |
| 3 | **Full Auto** | Aggressive optimization including restarts, scaling |

Default: Level 2 (Safe Auto-Fix) for all new customers.

**Database Schema**:
```sql
ALTER TABLE customers ADD COLUMN automation_level TINYINT DEFAULT 2;
ALTER TABLE customers ADD COLUMN automation_exceptions JSON DEFAULT NULL;
-- exceptions: {"skip_cache_clear": true, "skip_restarts": true, ...}
```

### 2.2 Issue Detection Rules

Continuous monitoring with threshold-based detection:

| Issue | Detection Rule | Severity |
|-------|----------------|----------|
| High Memory | >85% for 5 min | Warning |
| Critical Memory | >95% for 2 min | Critical |
| High CPU | >90% for 10 min | Warning |
| Slow Queries | >5 queries >3s in 5 min | Warning |
| Query Explosion | >100 queries >1s in 1 min | Critical |
| Cache Miss Storm | Hit rate <50% for 10 min | Warning |
| Disk Filling | >90% used | Warning |
| Disk Critical | >95% used | Critical |
| Connection Exhaustion | >80% max_connections | Warning |
| Container OOM | OOM killer triggered | Critical |
| Response Time Degradation | TTFB >3s for 5 min | Warning |

### 2.3 Auto-Fix Playbooks

Each issue maps to a playbook:

**Playbook: high_memory**
```yaml
name: High Memory Usage
trigger: memory_percent > 85 for 5 minutes
actions:
  - name: Clear application cache
    command: docker exec {container} wp cache flush || bin/magento cache:flush
    reversible: true
  - name: Clear expired transients (WooCommerce)
    command: docker exec {container} wp transient delete --expired --all
    reversible: false  # but safe
  - name: Restart PHP-FPM if still high
    condition: memory_percent > 85 after 2 minutes
    command: docker exec {container} pkill -USR2 php-fpm
    reversible: true
notifications:
  - type: email
    template: memory_optimization_applied
  - type: dashboard
    message: "Memory optimization applied automatically"
```

**Playbook: slow_queries**
```yaml
name: Slow Query Remediation
trigger: slow_query_count > 5 in 5 minutes
actions:
  - name: Log slow queries for analysis
    command: capture_slow_queries({customer_id})
    reversible: true
  - name: Kill long-running queries (>30s)
    condition: query_time > 30
    command: kill_query({query_id})
    reversible: false
  - name: Notify with recommendations
    action: generate_index_recommendations({queries})
notifications:
  - type: dashboard
    message: "Slow queries detected and logged. See recommendations."
```

**Playbook: disk_filling**
```yaml
name: Disk Space Recovery
trigger: disk_percent > 90
actions:
  - name: Clear old logs
    command: find /var/log -name "*.log.*" -mtime +7 -delete
    reversible: false
  - name: Clear cache directories
    command: rm -rf var/cache/* var/page_cache/* var/view_preprocessed/*
    reversible: true
  - name: Clear old backups
    condition: disk_percent > 95
    command: remove_old_local_backups({customer_id}, keep=1)
    reversible: false
notifications:
  - type: email
    template: disk_cleanup_applied
```

### 2.4 Automation Worker

New worker process: `performance_worker.py`

```python
# Runs every 60 seconds
def performance_check_cycle():
    for customer in get_active_customers():
        issues = detect_issues(customer)
        for issue in issues:
            if customer.automation_level == 1:  # Notify only
                create_alert(customer, issue)
            elif customer.automation_level >= 2:  # Auto-fix
                playbook = get_playbook(issue.type)
                if playbook.is_safe() or customer.automation_level == 3:
                    result = execute_playbook(playbook, customer)
                    log_automation_action(customer, playbook, result)
                    notify_customer(customer, playbook, result)
```

---

## 3. Admin Console

### 3.1 Fleet Health Dashboard

At-a-glance view of all customers:

```
┌─────────────────────────────────────────────────────────────────┐
│ Fleet Overview                                    Last 24 hours │
├─────────────────────────────────────────────────────────────────┤
│ Total Customers: 247    Active: 231    Issues: 12    Critical: 2│
├─────────────────────────────────────────────────────────────────┤
│ Health Distribution:                                            │
│ ████████████████████████████░░░░░░ 85% Healthy (>80)           │
│ ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 10% Warning (50-79)         │
│ ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  5% Critical (<50)          │
└─────────────────────────────────────────────────────────────────┘
```

**Sortable Table**:
| Customer | Platform | Health | CPU | Memory | Issues | Last Check |
|----------|----------|--------|-----|--------|--------|------------|
| acme-store | WooCommerce | 🔴 32 | 94% | 88% | 3 | 30s ago |
| widgets-inc | Magento | 🟡 67 | 45% | 72% | 1 | 45s ago |
| ... | ... | ... | ... | ... | ... | ... |

Click any row to drill down to customer detail view.

### 3.2 Resource Hotspot Detection

Identify customers consuming disproportionate resources:

**Hotspot Criteria**:
- CPU usage >2x plan allocation for extended periods
- Memory consistently >90% of limit
- Disk I/O significantly higher than peers
- Network bandwidth exceeding plan limits
- Database connections exhausted repeatedly

**Neighbor Impact Analysis**:
- Detect if one customer's resource usage affects others on same host
- Alert when host-level resources constrained
- Recommend migration to dedicated resources

### 3.3 Comparative Benchmarking

Compare each store against similar stores:

**Cohort Definition**:
- Same platform (WooCommerce/Magento)
- Similar catalog size (products within 20%)
- Similar traffic level (orders/day within 30%)
- Same hosting plan

**Benchmark Metrics**:
| Metric | This Store | Cohort Avg | Cohort Best | Percentile |
|--------|------------|------------|-------------|------------|
| TTFB | 1.2s | 0.8s | 0.3s | 25th |
| Memory Usage | 78% | 62% | 45% | 15th |
| Cache Hit Rate | 65% | 82% | 95% | 20th |
| Slow Queries/hr | 12 | 3 | 0 | 10th |

Stores performing significantly worse than peers flagged for admin review.

### 3.4 Intervention Playbooks

Pre-built admin actions:

| Playbook | Description | Actions |
|----------|-------------|---------|
| **Optimize Store** | Full optimization pass | Clear caches, optimize tables, restart services |
| **Emergency Stabilize** | Stop the bleeding | Kill runaway queries, restart containers, clear caches |
| **Migrate to Larger Plan** | Resource upgrade | Provision new containers, migrate data, update DNS |
| **Enable Premium Caching** | Add Varnish/Redis | Deploy additional caching layer |
| **Schedule Maintenance** | Planned optimization | Queue optimization for off-peak hours |
| **Contact Customer** | Outreach | Generate email with performance report and recommendations |

### 3.5 Predictive Alerts

ML-based forecasting using historical trends:

**Predictions**:
- "Customer X will hit memory limit in ~3 days based on 7-day growth trend"
- "Disk usage growing 2GB/week — will reach 90% in ~2 weeks"
- "Traffic pattern suggests flash sale — recommend pre-scaling"

**Implementation**:
- Linear regression on 7-day rolling metrics
- Anomaly detection for sudden changes
- Seasonal pattern recognition (weekly/monthly cycles)

**Alert Thresholds**:
- Warn admin 7 days before predicted limit breach
- Escalate at 3 days before predicted breach
- Auto-notify customer at 7 days with upgrade recommendations

---

## 4. Data Collection Layer

### 4.1 Metrics Collector

Extends existing `monitoring_worker.py`:

**New Metrics Collected**:
```python
PERFORMANCE_METRICS = {
    # Page speed (synthetic)
    'ttfb_ms': 'Time to first byte',
    'fcp_ms': 'First contentful paint',
    'lcp_ms': 'Largest contentful paint',

    # Database
    'slow_query_count': 'Queries > 1s in last interval',
    'active_connections': 'Current MySQL connections',
    'table_size_bytes': 'Total database size',

    # Cache
    'redis_hit_rate': 'Redis cache hit percentage',
    'redis_memory_bytes': 'Redis memory usage',
    'varnish_hit_rate': 'Varnish cache hit percentage',  # Magento

    # Resources (already collected)
    'cpu_percent': 'Container CPU usage',
    'memory_percent': 'Container memory usage',
    'disk_percent': 'Customer disk usage',
}
```

### 4.2 Query Analyzer

New component for database performance analysis:

```python
class QueryAnalyzer:
    def get_slow_queries(self, customer_id, threshold_ms=1000, limit=100):
        """Fetch slow queries from MySQL slow query log or performance_schema"""

    def analyze_query(self, query):
        """Run EXPLAIN and return optimization suggestions"""

    def get_table_stats(self, customer_id):
        """Return table sizes, row counts, index usage"""

    def suggest_indexes(self, queries):
        """Analyze query patterns and suggest missing indexes"""
```

### 4.3 External Probes

Synthetic monitoring for customer-facing metrics:

**Lighthouse Worker** (new):
```python
def run_lighthouse_probe(customer):
    """Run Lighthouse audit against customer's storefront"""
    # Use headless Chrome with Lighthouse
    # Collect: Performance score, FCP, LCP, CLS, TBT
    # Store results in performance_probes table
    # Run every 6 hours per customer (staggered)
```

**Uptime Probe** (existing, enhanced):
```python
def enhanced_uptime_probe(customer):
    """HTTP probe with detailed timing"""
    # Collect: DNS time, connect time, TTFB, total time
    # Track response codes and error types
    # Run every 60 seconds
```

---

## 5. Database Schema

### 5.1 New Tables

```sql
-- Performance snapshots (aggregated metrics)
CREATE TABLE performance_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    timestamp DATETIME NOT NULL,
    health_score TINYINT NOT NULL,  -- 0-100

    -- Page speed
    ttfb_ms INT,
    fcp_ms INT,
    lcp_ms INT,

    -- Resources
    cpu_percent DECIMAL(5,2),
    memory_percent DECIMAL(5,2),
    disk_percent DECIMAL(5,2),

    -- Database
    slow_query_count INT,
    active_connections INT,
    db_size_bytes BIGINT,

    -- Cache
    redis_hit_rate DECIMAL(5,2),
    varnish_hit_rate DECIMAL(5,2),

    INDEX idx_customer_time (customer_id, timestamp),
    INDEX idx_health (health_score, timestamp)
) ENGINE=InnoDB;

-- Detected issues
CREATE TABLE performance_issues (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    issue_type VARCHAR(50) NOT NULL,  -- 'high_memory', 'slow_queries', etc.
    severity ENUM('info', 'warning', 'critical') NOT NULL,
    detected_at DATETIME NOT NULL,
    resolved_at DATETIME,
    auto_fixed BOOLEAN DEFAULT FALSE,
    details JSON,

    INDEX idx_customer_open (customer_id, resolved_at),
    INDEX idx_severity (severity, detected_at)
) ENGINE=InnoDB;

-- Automation actions taken
CREATE TABLE automation_actions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    issue_id BIGINT,
    playbook_name VARCHAR(50) NOT NULL,
    action_name VARCHAR(100) NOT NULL,
    executed_at DATETIME NOT NULL,
    success BOOLEAN NOT NULL,
    result JSON,

    INDEX idx_customer_time (customer_id, executed_at),
    FOREIGN KEY (issue_id) REFERENCES performance_issues(id)
) ENGINE=InnoDB;

-- Slow queries log
CREATE TABLE slow_queries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    query_hash CHAR(32) NOT NULL,  -- MD5 of normalized query
    query_text TEXT NOT NULL,
    execution_time_ms INT NOT NULL,
    rows_examined BIGINT,
    rows_sent BIGINT,
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    occurrence_count INT DEFAULT 1,

    UNIQUE KEY uk_customer_query (customer_id, query_hash),
    INDEX idx_customer_time (customer_id, last_seen),
    INDEX idx_slow (execution_time_ms)
) ENGINE=InnoDB;

-- Lighthouse probe results
CREATE TABLE lighthouse_probes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    probed_at DATETIME NOT NULL,
    performance_score TINYINT,  -- 0-100
    fcp_ms INT,
    lcp_ms INT,
    cls DECIMAL(5,3),
    tbt_ms INT,
    full_report JSON,

    INDEX idx_customer_time (customer_id, probed_at)
) ENGINE=InnoDB;

-- Admin intervention log
CREATE TABLE admin_interventions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    admin_user_id INT NOT NULL,
    playbook_name VARCHAR(50) NOT NULL,
    executed_at DATETIME NOT NULL,
    reason TEXT,
    result JSON,

    INDEX idx_customer (customer_id),
    INDEX idx_admin (admin_user_id)
) ENGINE=InnoDB;
```

### 5.2 Customer Table Additions

```sql
ALTER TABLE customers
    ADD COLUMN automation_level TINYINT DEFAULT 2,
    ADD COLUMN automation_exceptions JSON DEFAULT NULL,
    ADD COLUMN last_health_score TINYINT DEFAULT NULL,
    ADD COLUMN health_score_updated_at DATETIME DEFAULT NULL;
```

---

## 6. Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
- [ ] Database schema migrations
- [ ] Enhanced metrics collection in monitoring_worker
- [ ] Health score calculation algorithm
- [ ] Customer dashboard: Health Score widget
- [ ] Customer dashboard: Insights feed (read-only)

### Phase 2: Customer Self-Service (Weeks 3-4)
- [ ] One-Click Optimize button (WooCommerce)
- [ ] One-Click Optimize button (Magento)
- [ ] Customer automation preferences UI
- [ ] Slow query viewer (premium)
- [ ] Table analyzer (premium)

### Phase 3: Automation Engine (Weeks 5-6)
- [ ] Issue detection rules
- [ ] Auto-fix playbooks (high_memory, slow_queries, disk_filling)
- [ ] Performance worker process
- [ ] Automation action logging
- [ ] Customer notification system

### Phase 4: Admin Console (Weeks 7-8)
- [ ] Fleet health dashboard
- [ ] Resource hotspot detection
- [ ] Comparative benchmarking
- [ ] Admin intervention playbooks
- [ ] Admin action logging

### Phase 5: Advanced Features (Weeks 9-10)
- [ ] Lighthouse probe worker
- [ ] Predictive alerts (ML-based)
- [ ] Advanced controls panel (premium)
- [ ] Traffic analytics (premium)
- [ ] Query EXPLAIN tool (premium)

### Phase 6: Polish & Rollout (Weeks 11-12)
- [ ] Performance testing under load
- [ ] Documentation for customers
- [ ] Admin runbook documentation
- [ ] Gradual rollout (10% → 50% → 100%)
- [ ] Monitoring of automation effectiveness

---

## 7. Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Avg Health Score | N/A | >80 | Computed daily |
| Support tickets (performance) | ? | -50% | Zendesk tags |
| Mean time to detect issues | Manual | <5 min | Issue detection timestamp |
| Mean time to resolve | ? | <30 min | Auto-fix success rate |
| Customer satisfaction (performance) | ? | >4.5/5 | Post-resolution survey |

---

## 8. Security Considerations

- **Query Analyzer**: Never expose raw query text outside admin console; hash/anonymize for customers
- **Auto-Fix Commands**: Run in containers with limited privileges; no host access
- **Admin Interventions**: Require MFA; log all actions with audit trail
- **Customer Data**: Health scores and metrics are per-customer isolated; no cross-customer data leakage
- **API Rate Limiting**: Performance endpoints rate-limited to prevent abuse

---

## 9. Dependencies

- **Existing**: Prometheus, Grafana, Redis, MySQL, Docker SDK
- **New**: Lighthouse CLI (for synthetic probes), scikit-learn (for predictive alerts)

---

## 10. Open Questions

1. **Lighthouse frequency**: 6 hours feels right, but may need adjustment based on resource usage
2. **Predictive ML model**: Start simple (linear regression) or invest in more sophisticated approach?
3. **Premium plan definition**: Which features exactly gate to which plan tiers?
4. **Notification channels**: Email + dashboard, or also SMS/Slack for critical auto-fixes?

---

*Document generated during brainstorming session on 2026-02-01*
