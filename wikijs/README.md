# Wiki.js Documentation Platform

Wiki.js instance for ShopHosting.io documentation serving customers, developers, and internal team.

## Quick Start

```bash
# Run setup (as root)
sudo ./setup.sh docs.shophosting.io
```

This will:
1. Start Wiki.js and PostgreSQL containers
2. Configure nginx reverse proxy
3. Obtain SSL certificate from Let's Encrypt

## First-Time Configuration

After setup, visit https://docs.shophosting.io to complete initial configuration:

### 1. Create Admin Account

- Fill in your admin email and password
- This will be the super administrator account

### 2. Configure Site Settings

Go to **Administration** → **General**:
- Site Title: `ShopHosting Documentation`
- Site URL: `https://docs.shophosting.io`

### 3. Configure Authentication

Go to **Administration** → **Authentication**:

1. **Local Authentication** (enabled by default)
   - Allow self-registration: `No` (for internal users, invite only)

2. **Guest Access** (for public pages)
   - Go to **Administration** → **Groups** → **Guests**
   - Enable guest access
   - This allows unauthenticated users to view public pages

### 4. Set Up User Groups

Go to **Administration** → **Groups** and create:

| Group | Purpose | Permissions |
|-------|---------|-------------|
| Guests | Public visitors | Read public pages only |
| Customers | Registered customers | Read customer docs |
| Developers | API/Integration developers | Read developer docs |
| Internal | Team members | Read/write all pages |
| Administrators | Doc admins | Full access |

### 5. Configure Page Rules

Go to **Administration** → **Groups** → Select group → **Page Rules**

#### Guest Group (Public Access)
```
Allow READ on path: /en/getting-started/*
Allow READ on path: /en/guides/*
Allow READ on path: /en/faq/*
Allow READ on path: /en/api/*
Deny READ on path: /en/internal/*
```

#### Internal Group (Team Only)
```
Allow READ on path: *
Allow WRITE on path: *
Allow MANAGE on path: /en/internal/*
```

## Recommended Page Structure

```
/
├── getting-started/           # PUBLIC - Customer onboarding
│   ├── quick-start
│   ├── first-store
│   └── dashboard-overview
│
├── guides/                    # PUBLIC - How-to guides
│   ├── staging-environments
│   ├── dns-setup
│   ├── backups
│   └── 2fa-setup
│
├── faq/                       # PUBLIC - Common questions
│   ├── billing
│   ├── technical
│   └── troubleshooting
│
├── api/                       # PUBLIC - Developer docs
│   ├── authentication
│   ├── webhooks
│   ├── endpoints
│   └── examples
│
├── developers/                # PUBLIC - Integration guides
│   ├── woocommerce
│   ├── magento
│   └── custom-themes
│
└── internal/                  # PRIVATE - Team only
    ├── runbooks/
    │   ├── incident-response
    │   ├── customer-provisioning
    │   └── disaster-recovery
    ├── architecture/
    │   ├── system-overview
    │   └── infrastructure
    └── processes/
        ├── onboarding
        └── support-procedures
```

## Container Management

```bash
# Start
cd /opt/shophosting/wikijs
docker compose up -d

# Stop
docker compose down

# View logs
docker logs shophosting-wikijs -f

# Restart
docker compose restart

# Update Wiki.js
docker compose pull
docker compose up -d
```

## Backup & Restore

### Backup
```bash
# Manual backup
./backup.sh

# Backups are stored in ./backups/
```

### Restore
```bash
# Restore database
gunzip -c backups/wikijs_db_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i shophosting-wikijs-db psql -U wikijs wikijs

# Restore files
docker run --rm \
  -v shophosting_wikijs_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/wikijs_data_YYYYMMDD_HHMMSS.tar.gz -C /data
```

## Git Sync (Optional)

Wiki.js can sync content with a Git repository for version control:

1. Go to **Administration** → **Storage**
2. Enable **Git** storage
3. Configure:
   - Repository URL: `git@github.com:NathanJHarrell/shophosting-docs.git`
   - Branch: `main`
   - SSH Key: Generate and add to GitHub as deploy key

This enables:
- Version history for all pages
- Pull request workflow for doc changes
- Disaster recovery from Git

## Customization

### Custom Logo
1. Go to **Administration** → **Theme**
2. Upload your logo (recommended: 200x50px PNG)

### Custom CSS
Add custom styles in **Administration** → **Theme** → **Inject CSS**

```css
/* Example: Brand colors */
.v-application {
  --v-primary-base: #2196F3;
}
```

### Custom Homepage
1. Create a page at `/home`
2. Set as homepage in **Administration** → **Navigation**

## Troubleshooting

### Wiki.js won't start
```bash
# Check logs
docker logs shophosting-wikijs

# Check database
docker logs shophosting-wikijs-db

# Restart everything
docker compose down
docker compose up -d
```

### Database connection issues
```bash
# Check if PostgreSQL is healthy
docker exec shophosting-wikijs-db pg_isready -U wikijs

# Check network
docker network inspect shophosting_wikijs-net
```

### SSL certificate renewal
```bash
# Certbot auto-renews, but to manually renew:
sudo certbot renew
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKIJS_DB_PASSWORD` | changeme | PostgreSQL password |

Edit `.env` file to change these values, then restart:
```bash
docker compose down
docker compose up -d
```
