# ShopHosting.io Service Level Agreement (SLA)

**Last Updated:** February 2, 2026

This Service Level Agreement ("SLA") is part of the Terms of Service between ShopHosting.io ("Provider") and you ("Customer").

## 1. Uptime Guarantee

### 1.1 Commitment
ShopHosting.io guarantees **99.9% monthly uptime** for all hosting services.

### 1.2 Uptime Calculation
Monthly Uptime Percentage = ((Total Minutes in Month - Downtime Minutes) / Total Minutes in Month) × 100

**99.9% uptime allows for approximately:**
- 43.8 minutes of downtime per month
- 8.76 hours of downtime per year

### 1.3 What Counts as Downtime
Downtime is measured as the total minutes during which the Customer's primary website is inaccessible due to Provider infrastructure failure, as verified by our monitoring systems.

## 2. Service Credits

If we fail to meet the 99.9% uptime guarantee, you are eligible for service credits as follows:

| Monthly Uptime | Service Credit |
|----------------|----------------|
| 99.0% - 99.9%  | 10% of monthly fee |
| 95.0% - 99.0%  | 25% of monthly fee |
| 90.0% - 95.0%  | 50% of monthly fee |
| Below 90.0%    | 100% of monthly fee |

### 2.1 Credit Request Process
1. Submit a support ticket within 30 days of the incident
2. Include the date, time, and duration of the outage
3. Credits are applied to future invoices (not refunded as cash)

### 2.2 Credit Limitations
- Maximum credit per month: 100% of that month's fee
- Credits do not carry over or accumulate
- Credits cannot be transferred or exchanged for cash

## 3. Exclusions

The uptime guarantee does NOT apply to downtime caused by:

### 3.1 Scheduled Maintenance
- Routine maintenance with at least 48 hours advance notice
- Emergency security patches with reasonable notice
- Maintenance windows: Tuesdays and Thursdays, 2:00 AM - 6:00 AM EST

### 3.2 Customer-Caused Issues
- Errors in Customer code, plugins, or configurations
- Customer-initiated changes that cause instability
- Exceeding allocated resources (CPU, memory, storage, bandwidth)
- DDoS attacks targeting Customer specifically
- Account suspension due to Terms of Service violations
- Account suspension due to non-payment

### 3.3 Force Majeure Events
Circumstances beyond our reasonable control, including but not limited to:
- **Natural disasters:** Earthquakes, floods, hurricanes, tornadoes, wildfires
- **Civil unrest:** War, terrorism, riots, government actions
- **Infrastructure failures:** Power grid outages, internet backbone failures, telecommunications disruptions beyond our network
- **Pandemics:** Disease outbreaks affecting operations
- **Legal actions:** Court orders, regulatory requirements
- **Third-party failures:** Upstream provider outages, DNS registry issues, certificate authority problems

### 3.4 Other Exclusions
- Features labeled as "beta" or "experimental"
- Free tier or trial accounts
- Downtime during account migration at Customer's request

## 4. Support Response Times

### 4.1 Response Time Guarantee
We guarantee an initial response within **24 hours** for all support tickets.

### 4.2 Priority Levels

| Priority | Description | Target Response | Target Resolution |
|----------|-------------|-----------------|-------------------|
| Critical | Site completely down | 1 hour | 4 hours |
| High | Major functionality broken | 4 hours | 24 hours |
| Medium | Minor issues, degraded performance | 24 hours | 72 hours |
| Low | Questions, feature requests | 24 hours | Best effort |

### 4.3 Support Availability
- **Ticket Support:** 24/7/365
- **Live Chat:** Monday-Friday, 9 AM - 6 PM EST
- **Phone Support:** Available for Enterprise plans

## 5. Performance Standards

### 5.1 Server Performance
We target the following performance benchmarks:
- Time to First Byte (TTFB): < 200ms
- Server response time: < 500ms for uncached requests
- Backup completion: Within 4 hours of scheduled time

### 5.2 Resource Allocation
Each account receives guaranteed minimum resources as specified in your plan. Resources are not oversold beyond sustainable limits.

## 6. Monitoring and Reporting

### 6.1 Uptime Monitoring
We monitor all services at 1-minute intervals from multiple global locations.

### 6.2 Status Page
Real-time service status is available at: status.shophosting.io

### 6.3 Incident Communication
During outages, we will:
- Update the status page within 15 minutes
- Send email notifications for extended outages (>30 minutes)
- Provide post-incident reports for major outages

## 7. Data Protection

### 7.1 Backup Schedule
- **Daily backups:** Retained for 30 days
- **Database backups:** Every 6 hours
- **Off-site storage:** All backups replicated to geographically separate location

### 7.2 Recovery Time Objective (RTO)
In the event of data loss, we target restoration within 4 hours.

### 7.3 Recovery Point Objective (RPO)
Maximum data loss in a disaster scenario: 6 hours (time since last backup)

## 8. Security

### 8.1 Security Measures
- DDoS protection on all plans
- Web Application Firewall (WAF)
- SSL/TLS certificates included
- Regular security patching within 24 hours of critical vulnerabilities

### 8.2 Security Incident Response
We will notify affected customers within 72 hours of discovering a security breach that impacts their data.

## 9. SLA Modifications

We may modify this SLA with 30 days notice. Changes will not apply retroactively to existing incidents.

## 10. Contact

To report an outage or request SLA credits:
- **Support Portal:** support.shophosting.io
- **Email:** support@shophosting.io
- **Status Page:** status.shophosting.io
