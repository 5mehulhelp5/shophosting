#!/bin/bash
#
# bootstrap.sh - ShopHosting Server Bootstrap Script
#
# Sets up a fresh Ubuntu 22.04/24.04 server with all ShopHosting components.
# The repo must already be cloned to /opt/shophosting before running.
#
# Usage:
#   sudo ./scripts/bootstrap.sh                    # Full setup
#   sudo ./scripts/bootstrap.sh --phase=5          # Run only phase 5
#   sudo ./scripts/bootstrap.sh --skip-phase=15    # Skip SSL phase
#   sudo ./scripts/bootstrap.sh --skip-phase=9 --skip-phase=10  # Skip multiple
#   sudo ./scripts/bootstrap.sh --dry-run          # Show what would be done
#   sudo ./scripts/bootstrap.sh --help             # Show usage
#
# Phases:
#   1  - System Packages       9  - Docker Images
#   2  - Users & Permissions  10  - Docker Services
#   3  - Firewall (UFW)       11  - Nginx Configuration
#   4  - MySQL                12  - Fail2Ban
#   5  - Redis HA             13  - Systemd Services
#   6  - Directories          14  - Cron Jobs
#   7  - Python Environments  15  - SSL Certificates
#   8  - Environment Config   16  - Verification
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

source "${SCRIPT_DIR}/bootstrap-lib.sh"

# ═══════════════════════════════════════════════════════════════════════════
# Preflight Checks
# ═══════════════════════════════════════════════════════════════════════════
preflight_checks() {
    # Must be root
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root (use: sudo ./scripts/bootstrap.sh)"
    fi

    # Must be Ubuntu 22.04 or 24.04
    if [[ ! -f /etc/os-release ]]; then
        die "Cannot detect OS version (/etc/os-release not found)"
    fi
    source /etc/os-release
    case "${VERSION_ID:-}" in
        22.04|24.04)
            log_info "Detected Ubuntu ${VERSION_ID} (${PRETTY_NAME})"
            ;;
        *)
            die "Unsupported OS: ${PRETTY_NAME:-unknown}. Requires Ubuntu 22.04 or 24.04."
            ;;
    esac

    # Repo must exist (check for scripts/ which is present in all roles)
    if [[ ! -d "${REPO_ROOT}/scripts" ]]; then
        die "ShopHosting repo not found at ${REPO_ROOT}. Clone it first:
  git clone git@github.com:NathanJHarrell/shophosting.git ${REPO_ROOT}"
    fi

    # Create log directory early
    mkdir -p "${REPO_ROOT}/logs"

    log_info "Bootstrap started at $(date)"
    log_info "Repo: ${REPO_ROOT}"
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: System Packages
# ═══════════════════════════════════════════════════════════════════════════
phase_system_packages() {
    phase_start 1 "System Packages" || return 0

    # 1a. Update package lists
    log_info "Updating package lists..."
    apt-get update -y

    # 1b. Install core packages
    log_info "Installing system packages..."
    local PACKAGES=(
        # Web server & database
        nginx mysql-server
        # Security
        fail2ban ufw
        # SSL
        certbot python3-certbot-nginx
        # Python
        python3-venv python3-pip python3-dev
        # Build tools
        git curl wget build-essential pkg-config
        libmysqlclient-dev libffi-dev libssl-dev
        # Utilities
        jq htop unzip logrotate rsync
        # Antivirus
        clamav clamav-daemon clamav-freshclam
        # Backups
        restic
    )
    apt-get install -y "${PACKAGES[@]}"
    log_success "System packages installed"

    # 1c. Docker CE
    if command_exists docker; then
        log_info "Docker already installed ($(docker --version))"
    else
        log_info "Installing Docker CE..."
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc

        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
            > /etc/apt/sources.list.d/docker.list

        apt-get update -y
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        systemctl enable docker
        systemctl start docker
        log_success "Docker CE installed"
    fi

    # 1d. Node.js via nvm (for agileweb user)
    if user_exists "$SERVICE_USER"; then
        if su - "$SERVICE_USER" -c "command -v node" &>/dev/null; then
            local node_ver
            node_ver=$(su - "$SERVICE_USER" -c "node --version" 2>/dev/null || echo "unknown")
            log_info "Node.js already installed (${node_ver})"
        else
            log_info "Installing Node.js via nvm..."
            su - "$SERVICE_USER" -c 'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash' || true
            su - "$SERVICE_USER" -c '
                export NVM_DIR="$HOME/.nvm"
                [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
                nvm install 24
            '
            log_success "Node.js installed"
        fi
    else
        log_warn "User ${SERVICE_USER} does not exist yet — Node.js will be installed in Phase 2"
    fi

    # 1e. Update ClamAV signatures
    log_info "Updating ClamAV virus signatures..."
    systemctl stop clamav-freshclam 2>/dev/null || true
    freshclam 2>/dev/null || log_warn "ClamAV signature update failed (will retry on next freshclam run)"
    systemctl start clamav-freshclam 2>/dev/null || true

    phase_end 1
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Users & Permissions
# ═══════════════════════════════════════════════════════════════════════════
phase_users_permissions() {
    phase_start 2 "Users & Permissions" || return 0

    # 2a. Create service user
    if user_exists "$SERVICE_USER"; then
        log_info "User ${SERVICE_USER} already exists"
    else
        useradd -m -s /bin/bash "$SERVICE_USER"
        log_success "Created user ${SERVICE_USER}"
    fi

    # 2b. Add to required groups
    usermod -aG docker "$SERVICE_USER" 2>/dev/null || true
    usermod -aG sudo "$SERVICE_USER" 2>/dev/null || true
    usermod -aG adm "$SERVICE_USER" 2>/dev/null || true
    log_success "User groups configured (docker, sudo, adm)"

    # 2c. SSH key for GitHub
    local SSH_DIR="/home/${SERVICE_USER}/.ssh"
    if [[ ! -f "${SSH_DIR}/id_ed25519" ]]; then
        if prompt_confirm "Generate SSH key for GitHub access?"; then
            su - "$SERVICE_USER" -c "ssh-keygen -t ed25519 -C '${SERVICE_USER}@shophosting' -f ~/.ssh/id_ed25519 -N ''"
            echo ""
            echo -e "${BOLD}Add this public key to GitHub:${NC}"
            echo ""
            cat "${SSH_DIR}/id_ed25519.pub"
            echo ""
            prompt_confirm "Press Y when the key has been added to GitHub" || true
        fi
    else
        log_info "SSH key already exists"
    fi

    # 2d. Install Node.js if user was just created and Phase 1 skipped it
    if ! su - "$SERVICE_USER" -c "command -v node" &>/dev/null; then
        log_info "Installing Node.js via nvm for ${SERVICE_USER}..."
        su - "$SERVICE_USER" -c 'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash' || true
        su - "$SERVICE_USER" -c '
            export NVM_DIR="$HOME/.nvm"
            [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
            nvm install 24
        '
    fi

    # 2e. Sudoers rules
    local SUDOERS_FILE="/etc/sudoers.d/shophosting"
    if [[ ! -f "$SUDOERS_FILE" ]]; then
        cat > "$SUDOERS_FILE" <<EOF
# ShopHosting sudoers rules
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/fail2ban-client *
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
EOF
        chmod 440 "$SUDOERS_FILE"
        if visudo -c -f "$SUDOERS_FILE" &>/dev/null; then
            log_success "Sudoers rules created"
        else
            rm -f "$SUDOERS_FILE"
            log_warn "Sudoers validation failed — removed invalid file"
        fi
    else
        log_info "Sudoers rules already exist"
    fi

    # 2f. Set repo ownership
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$REPO_ROOT"
    log_success "Repo ownership set to ${SERVICE_USER}"

    phase_end 2
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: Firewall (UFW)
# ═══════════════════════════════════════════════════════════════════════════
phase_firewall() {
    phase_start 3 "Firewall (UFW)" || return 0

    # 3a. Reset to clean state
    log_info "Configuring firewall..."
    ufw --force reset &>/dev/null
    ufw default deny incoming &>/dev/null
    ufw default allow outgoing &>/dev/null

    # 3b. SSH
    ufw allow 22/tcp comment "SSH" &>/dev/null
    log_success "SSH (22) allowed"

    # 3c. Fetch Cloudflare IP ranges
    log_info "Fetching Cloudflare IP ranges..."
    local CF_V4 CF_V6
    CF_V4=$(curl -sf https://www.cloudflare.com/ips-v4 2>/dev/null || echo "")
    CF_V6=$(curl -sf https://www.cloudflare.com/ips-v6 2>/dev/null || echo "")

    if [[ -z "$CF_V4" ]]; then
        log_warn "Could not fetch Cloudflare IPs. Using fallback ranges."
        CF_V4="173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22"
        CF_V6="2400:cb00::/32
2606:4700::/32
2803:f800::/32
2405:b500::/32
2405:8100::/32
2a06:98c0::/29
2c0f:f248::/32"
    fi

    # 3d. Allow web traffic from Cloudflare
    local cf_count=0
    while IFS= read -r cidr; do
        cidr=$(echo "$cidr" | tr -d '[:space:]')
        [[ -z "$cidr" ]] && continue
        ufw allow from "$cidr" to any port 80,443 proto tcp comment "Cloudflare" &>/dev/null
        ((cf_count++))
    done <<< "$CF_V4"

    while IFS= read -r cidr; do
        cidr=$(echo "$cidr" | tr -d '[:space:]')
        [[ -z "$cidr" ]] && continue
        ufw allow from "$cidr" to any port 80,443 proto tcp comment "Cloudflare" &>/dev/null
        ((cf_count++))
    done <<< "$CF_V6"

    log_success "${cf_count} Cloudflare IP ranges allowed for ports 80,443"

    # 3e. Admin IP fallback
    local ADMIN_IP
    prompt_required ADMIN_IP "Your admin IP address (for direct access fallback)"
    ufw allow from "$ADMIN_IP" to any port 80,443 proto tcp comment "Admin IP" &>/dev/null
    log_success "Admin IP ${ADMIN_IP} allowed for ports 80,443"

    # Save admin IP for later phases
    echo "$ADMIN_IP" > "${REPO_ROOT}/.bootstrap-admin-ip"
    chmod 600 "${REPO_ROOT}/.bootstrap-admin-ip"

    # 3f. Internal service ports (Docker bridge access to WAF backend)
    ufw allow from 172.16.0.0/12 to any port 8081 proto tcp comment "Docker WAF backend" &>/dev/null

    # 3g. Enable
    ufw --force enable &>/dev/null
    log_success "UFW enabled"

    phase_end 3
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: MySQL
# ═══════════════════════════════════════════════════════════════════════════
phase_mysql() {
    phase_start 4 "MySQL" || return 0

    if is_worker; then
        log_info "Worker node — skipping MySQL (connects to primary)"
        phase_end 4
        return 0
    fi

    # 4a. Ensure MySQL is running
    systemctl enable mysql &>/dev/null
    systemctl start mysql
    log_info "MySQL is running"

    # 4b. Check if database already exists
    if mysql -u root -e "USE shophosting_db" &>/dev/null; then
        log_info "Database shophosting_db already exists — skipping"
        phase_end 4
        return 0
    fi

    # 4c. Get password
    local DB_PASSWORD
    prompt_secret DB_PASSWORD "Choose a MySQL password for the shophosting_app user"

    # 4d. Create database and user
    log_info "Creating database and user..."
    mysql -u root <<EOSQL
CREATE DATABASE IF NOT EXISTS shophosting_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'shophosting_app'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON shophosting_db.* TO 'shophosting_app'@'localhost';
GRANT ALL PRIVILEGES ON \`customer_%\`.* TO 'shophosting_app'@'localhost';
FLUSH PRIVILEGES;
EOSQL
    log_success "Database and user created"

    # 4e. Run schema
    if [[ -f "${REPO_ROOT}/schema.sql" ]]; then
        mysql -u root shophosting_db < "${REPO_ROOT}/schema.sql"
        log_success "Schema applied"
    else
        log_warn "schema.sql not found — skipping schema import"
    fi

    # 4f. Copy MySQL tuning config
    if [[ -f "${REPO_ROOT}/configs/mysql/primary.cnf" ]]; then
        cp "${REPO_ROOT}/configs/mysql/primary.cnf" /etc/mysql/mysql.conf.d/shophosting.cnf
        log_info "MySQL config copied (restart MySQL to apply replication settings)"
    fi

    # 4g. Save password for Phase 8
    echo "$DB_PASSWORD" > "${REPO_ROOT}/.bootstrap-db-password"
    chmod 600 "${REPO_ROOT}/.bootstrap-db-password"

    phase_end 4
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: Redis HA
# ═══════════════════════════════════════════════════════════════════════════
phase_redis() {
    phase_start 5 "Redis HA" || return 0

    if is_worker; then
        log_info "Worker node — skipping Redis (connects to primary)"
        phase_end 5
        return 0
    fi

    if is_docker_running "redis-master"; then
        log_info "Redis master already running — skipping"
        phase_end 5
        return 0
    fi

    local REDIS_DIR="${REPO_ROOT}/redis"
    if [[ -f "${REDIS_DIR}/setup-sentinel.sh" ]]; then
        log_info "Starting Redis Sentinel cluster..."
        cd "$REDIS_DIR"
        bash setup-sentinel.sh
        cd "$REPO_ROOT"
        log_success "Redis Sentinel cluster started"
    elif [[ -f "${REDIS_DIR}/docker-compose.yml" ]]; then
        log_info "Starting Redis via docker compose..."
        cd "$REDIS_DIR"
        docker compose up -d
        cd "$REPO_ROOT"
        log_success "Redis started"
    else
        log_warn "No Redis setup found at ${REDIS_DIR} — skipping"
    fi

    phase_end 5
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 6: Directories & Permissions
# ═══════════════════════════════════════════════════════════════════════════
phase_directories() {
    phase_start 6 "Directories & Permissions" || return 0

    # Customer data directory
    mkdir -p "$CUSTOMERS_DIR"
    chown "${SERVICE_USER}:${SERVICE_USER}" "$CUSTOMERS_DIR"
    chmod 750 "$CUSTOMERS_DIR"
    log_success "/var/customers/ created"

    # Application logs
    mkdir -p "${REPO_ROOT}/logs"
    chown "${SERVICE_USER}:www-data" "${REPO_ROOT}/logs"
    chmod 775 "${REPO_ROOT}/logs"
    log_success "Logs directory configured"

    # WAF logs (Docker needs write access)
    mkdir -p /var/log/modsecurity
    chmod 777 /var/log/modsecurity
    log_success "/var/log/modsecurity/ created"

    # Nginx logs
    mkdir -p /var/log/nginx
    chown www-data:adm /var/log/nginx
    log_success "/var/log/nginx/ configured"

    # Logrotate
    if [[ -f "${REPO_ROOT}/configs/logrotate/shophosting" ]]; then
        cp "${REPO_ROOT}/configs/logrotate/shophosting" /etc/logrotate.d/shophosting
        chmod 644 /etc/logrotate.d/shophosting
        log_success "Logrotate config installed"
    fi

    phase_end 6
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 7: Python Virtual Environments
# ═══════════════════════════════════════════════════════════════════════════
phase_python_envs() {
    phase_start 7 "Python Virtual Environments" || return 0

    local COMPONENTS=("webapp" "security" "provisioning" "opsbot")

    for component in "${COMPONENTS[@]}"; do
        local venv_path="${REPO_ROOT}/${component}/venv"
        local req_path="${REPO_ROOT}/${component}/requirements.txt"

        if [[ ! -d "${REPO_ROOT}/${component}" ]]; then
            log_warn "Directory ${component}/ not found — skipping"
            continue
        fi

        # Create venv
        if [[ ! -d "$venv_path" ]]; then
            log_info "Creating venv for ${component}..."
            su - "$SERVICE_USER" -c "python3 -m venv '${venv_path}'"
        fi

        # Install requirements
        if [[ -f "$req_path" ]]; then
            log_info "Installing requirements for ${component}..."
            su - "$SERVICE_USER" -c "'${venv_path}/bin/pip' install --upgrade pip -q"
            su - "$SERVICE_USER" -c "'${venv_path}/bin/pip' install -r '${req_path}' -q"
            log_success "${component} dependencies installed"
        else
            log_warn "No requirements.txt for ${component}"
        fi
    done

    phase_end 7
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 8: Environment Configuration
# ═══════════════════════════════════════════════════════════════════════════
phase_env_config() {
    phase_start 8 "Environment Configuration" || return 0

    local ENV_FILE="${REPO_ROOT}/.env"
    local ENV_EXAMPLE="${REPO_ROOT}/.env.example"

    # Main .env
    if [[ -f "$ENV_FILE" ]]; then
        if ! prompt_confirm ".env already exists. Overwrite?"; then
            log_info "Keeping existing .env"
        else
            _generate_env "$ENV_FILE" "$ENV_EXAMPLE"
        fi
    else
        _generate_env "$ENV_FILE" "$ENV_EXAMPLE"
    fi

    # Security dashboard .env
    local SEC_ENV="${REPO_ROOT}/security/.env"
    local SEC_EXAMPLE="${REPO_ROOT}/security/.env.example"
    if [[ -f "$SEC_EXAMPLE" && ! -f "$SEC_ENV" ]]; then
        cp "$SEC_EXAMPLE" "$SEC_ENV"
        local sec_secret
        sec_secret=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        sed -i "s/^SECURITY_SECRET_KEY=.*/SECURITY_SECRET_KEY=${sec_secret}/" "$SEC_ENV" 2>/dev/null || true
        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=${sec_secret}/" "$SEC_ENV" 2>/dev/null || true
        chown "${SERVICE_USER}:${SERVICE_USER}" "$SEC_ENV"
        chmod 600 "$SEC_ENV"
        log_success "Security dashboard .env created"
    fi

    # Monitoring .env
    local MON_ENV="${REPO_ROOT}/monitoring/.env"
    local MON_EXAMPLE="${REPO_ROOT}/monitoring/.env.example"
    if [[ -f "$MON_EXAMPLE" && ! -f "$MON_ENV" ]]; then
        cp "$MON_EXAMPLE" "$MON_ENV"
        local grafana_pw
        prompt_secret grafana_pw "Grafana admin password"
        sed -i "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=${grafana_pw}/" "$MON_ENV" 2>/dev/null || true
        sed -i "s/^GF_SECURITY_ADMIN_PASSWORD=.*/GF_SECURITY_ADMIN_PASSWORD=${grafana_pw}/" "$MON_ENV" 2>/dev/null || true
        chown "${SERVICE_USER}:${SERVICE_USER}" "$MON_ENV"
        chmod 600 "$MON_ENV"
        log_success "Monitoring .env created"
    fi

    # Cleanup temp files from earlier phases
    rm -f "${REPO_ROOT}/.bootstrap-db-password"

    phase_end 8
}

_generate_env() {
    local env_file="$1"
    local example="$2"

    if [[ ! -f "$example" ]]; then
        log_warn ".env.example not found — creating minimal .env"
        touch "$env_file"
    else
        cp "$example" "$env_file"
    fi

    # Auto-generate SECRET_KEY
    local secret_key
    secret_key=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=${secret_key}/" "$env_file"

    # DB_PASSWORD
    local db_pw=""
    if [[ -f "${REPO_ROOT}/.bootstrap-db-password" ]]; then
        db_pw=$(cat "${REPO_ROOT}/.bootstrap-db-password")
    else
        prompt_secret db_pw "MySQL password for shophosting_app"
    fi
    sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=${db_pw}/" "$env_file"

    # Optional integrations
    echo ""
    log_info "Optional configuration (press Enter to skip any):"

    local stripe_sk stripe_pk stripe_wh anthropic_key restic_repo
    prompt_optional stripe_sk "Stripe Secret Key (sk_...)"
    prompt_optional stripe_pk "Stripe Publishable Key (pk_...)"
    prompt_optional stripe_wh "Stripe Webhook Secret (whsec_...)"
    prompt_optional anthropic_key "Anthropic API Key"
    prompt_optional restic_repo "Restic backup repository" "sftp:sh-backup@backup-server:/home/sh-backup/backups"

    [[ -n "$stripe_sk" ]] && sed -i "s/^STRIPE_SECRET_KEY=.*/STRIPE_SECRET_KEY=${stripe_sk}/" "$env_file"
    [[ -n "$stripe_pk" ]] && sed -i "s/^STRIPE_PUBLISHABLE_KEY=.*/STRIPE_PUBLISHABLE_KEY=${stripe_pk}/" "$env_file"
    [[ -n "$stripe_wh" ]] && sed -i "s/^STRIPE_WEBHOOK_SECRET=.*/STRIPE_WEBHOOK_SECRET=${stripe_wh}/" "$env_file"
    [[ -n "$anthropic_key" ]] && sed -i "s/^ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=${anthropic_key}/" "$env_file"
    [[ -n "$restic_repo" ]] && sed -i "s|^RESTIC_REPOSITORY=.*|RESTIC_REPOSITORY=${restic_repo}|" "$env_file"

    chown "${SERVICE_USER}:${SERVICE_USER}" "$env_file"
    chmod 600 "$env_file"
    log_success ".env created and secured"
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 9: Docker Images
# ═══════════════════════════════════════════════════════════════════════════
phase_docker_images() {
    phase_start 9 "Docker Images" || return 0

    # 9a. Local Docker registry
    if is_docker_running "registry"; then
        log_info "Docker registry already running"
    else
        log_info "Starting local Docker registry..."
        docker run -d -p 127.0.0.1:5050:5000 \
            --restart=unless-stopped \
            --name registry \
            registry:2
        log_success "Docker registry started on localhost:5050"
    fi

    # 9b. Build WordPress image
    local WP_DOCKERFILE="${REPO_ROOT}/docker/wordpress/Dockerfile"
    if [[ -f "$WP_DOCKERFILE" ]]; then
        log_info "Building WordPress image..."
        docker build -t localhost:5050/wordpress:latest "${REPO_ROOT}/docker/wordpress/"
        docker push localhost:5050/wordpress:latest
        log_success "WordPress image built and pushed"
    else
        log_warn "WordPress Dockerfile not found — skipping"
    fi

    # 9c. Build Magento image
    local MG_DOCKERFILE="${REPO_ROOT}/docker/magento/Dockerfile"
    if [[ -f "$MG_DOCKERFILE" ]]; then
        log_info "Building Magento image..."
        docker build -t localhost:5050/magento:latest "${REPO_ROOT}/docker/magento/"
        docker push localhost:5050/magento:latest
        log_success "Magento image built and pushed"
    else
        log_warn "Magento Dockerfile not found — skipping"
    fi

    # 9d. Pull third-party images
    log_info "Pulling WPScan image..."
    docker pull wpscanteam/wpscan:latest
    log_success "WPScan image pulled"

    if is_primary; then
        log_info "Pulling ModSecurity WAF image..."
        docker pull owasp/modsecurity-crs:nginx
        log_success "ModSecurity image pulled"
    fi

    phase_end 9
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 10: Docker Services
# ═══════════════════════════════════════════════════════════════════════════
phase_docker_services() {
    phase_start 10 "Docker Services" || return 0

    if is_worker; then
        log_info "Worker node — skipping Docker platform services (primary only)"
        phase_end 10
        return 0
    fi

    # Helper to start a docker compose stack
    _start_compose() {
        local name="$1"
        local dir="$2"
        local required="${3:-false}"

        if [[ ! -f "${dir}/docker-compose.yml" ]]; then
            if [[ "$required" == "true" ]]; then
                log_warn "${name}: docker-compose.yml not found at ${dir}"
            fi
            return 0
        fi

        # Check if .env is needed but missing
        if [[ -f "${dir}/.env.example" && ! -f "${dir}/.env" ]]; then
            log_warn "${name}: .env not found — skipping (create .env from .env.example first)"
            return 0
        fi

        log_info "Starting ${name}..."
        cd "$dir"
        docker compose up -d
        cd "$REPO_ROOT"
        log_success "${name} started"
    }

    # 10a. Monitoring stack
    _start_compose "Monitoring (Prometheus/Grafana/Loki)" "${REPO_ROOT}/monitoring"

    # 10b. Wiki.js
    _start_compose "Wiki.js" "${REPO_ROOT}/wikijs"

    # 10c. OpenProject
    _start_compose "OpenProject" "${REPO_ROOT}/openproject"

    # 10d. ModSecurity WAF
    _start_compose "ModSecurity WAF" "${REPO_ROOT}/security/modsec" "true"

    # 10e. Vaultwarden
    _start_compose "Vaultwarden" "${REPO_ROOT}/vault"

    # 10f. Portainer
    if is_docker_running "portainer"; then
        log_info "Portainer already running"
    else
        log_info "Starting Portainer..."
        docker volume create portainer_data 2>/dev/null || true
        docker run -d \
            -p 127.0.0.1:9000:9000 \
            -p 127.0.0.1:9443:9443 \
            --name=portainer \
            --restart=unless-stopped \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v portainer_data:/data \
            portainer/portainer-ce:latest
        log_success "Portainer started"
    fi

    # 10g. cAdvisor
    if is_docker_running "cadvisor"; then
        log_info "cAdvisor already running"
    else
        log_info "Starting cAdvisor..."
        docker run -d \
            --name=cadvisor \
            --restart=unless-stopped \
            -p 127.0.0.1:8888:8080 \
            --volume=/:/rootfs:ro \
            --volume=/var/run:/var/run:ro \
            --volume=/sys:/sys:ro \
            --volume=/var/lib/docker/:/var/lib/docker:ro \
            gcr.io/cadvisor/cadvisor:latest
        log_success "cAdvisor started"
    fi

    phase_end 10
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 11: Nginx Configuration
# ═══════════════════════════════════════════════════════════════════════════
phase_nginx() {
    phase_start 11 "Nginx Configuration" || return 0

    local NGINX_AVAIL="/etc/nginx/sites-available"
    local NGINX_ENABLED="/etc/nginx/sites-enabled"

    # 11a. Rate limiting config
    if [[ -f "${REPO_ROOT}/deploy/nginx/security-ratelimit.conf" ]]; then
        cp "${REPO_ROOT}/deploy/nginx/security-ratelimit.conf" /etc/nginx/conf.d/security-ratelimit.conf
        log_success "Rate limiting config installed"
    else
        echo "limit_req_zone \$binary_remote_addr zone=security_api:10m rate=10r/s;" \
            > /etc/nginx/conf.d/security-ratelimit.conf
        log_success "Rate limiting config generated"
    fi

    # 11b. Upstream config
    if [[ -f "${REPO_ROOT}/configs/nginx/shophosting-upstream.conf" ]]; then
        cp "${REPO_ROOT}/configs/nginx/shophosting-upstream.conf" /etc/nginx/conf.d/
        log_success "Upstream config installed"
    fi

    # 11c. Main shophosting site (primary only)
    if is_primary; then
        if [[ ! -f "${NGINX_AVAIL}/shophosting" ]]; then
            log_info "Generating main site nginx config..."
            cat > "${NGINX_AVAIL}/shophosting" <<'NGINX'
server {
    listen 80;
    server_name shophosting.io www.shophosting.io;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /static/ {
        alias /opt/shophosting/webapp/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location /backrest/ {
        proxy_pass http://127.0.0.1:9898/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /grafana/ {
        proxy_pass http://127.0.0.1:6479/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGINX
            log_success "Main site config generated (HTTP — run certbot for HTTPS)"
        else
            log_info "Main site config already exists"
        fi

        # Security dashboard config (primary only)
        if [[ -f "${REPO_ROOT}/security/deploy/security.shophosting.io.conf" ]]; then
            cp "${REPO_ROOT}/security/deploy/security.shophosting.io.conf" "${NGINX_AVAIL}/"
            log_success "Security dashboard nginx config installed"
        fi

        # WAF backend config (primary only)
        if [[ -f "${REPO_ROOT}/deploy/nginx/waf-backend.conf" ]]; then
            cp "${REPO_ROOT}/deploy/nginx/waf-backend.conf" "${NGINX_AVAIL}/"
            log_success "WAF backend config installed"
        fi
    fi

    # 11d. Enable sites
    for site in shophosting waf-backend.conf; do
        if [[ -f "${NGINX_AVAIL}/${site}" ]]; then
            ln -sf "${NGINX_AVAIL}/${site}" "${NGINX_ENABLED}/${site}"
        fi
    done

    if [[ -f "${NGINX_AVAIL}/security.shophosting.io.conf" ]]; then
        ln -sf "${NGINX_AVAIL}/security.shophosting.io.conf" "${NGINX_ENABLED}/security.shophosting.io.conf"
    fi

    # Remove default if it exists
    rm -f "${NGINX_ENABLED}/default"

    # 11g. Test and reload
    if nginx -t 2>/dev/null; then
        systemctl enable nginx &>/dev/null
        systemctl reload nginx
        log_success "Nginx configured and reloaded"
    else
        log_error "Nginx config test failed — check with: nginx -t"
        nginx -t
    fi

    phase_end 11
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 12: Fail2Ban
# ═══════════════════════════════════════════════════════════════════════════
phase_fail2ban() {
    phase_start 12 "Fail2Ban" || return 0

    # 12a. Get admin IP
    local ADMIN_IP=""
    if [[ -f "${REPO_ROOT}/.bootstrap-admin-ip" ]]; then
        ADMIN_IP=$(cat "${REPO_ROOT}/.bootstrap-admin-ip")
    else
        prompt_required ADMIN_IP "Admin IP for fail2ban ignoreip"
    fi

    # 12b. Deploy jail.local with admin IP
    if [[ -f "${REPO_ROOT}/configs/fail2ban-jail.local" ]]; then
        local JAIL_LOCAL="/etc/fail2ban/jail.local"
        cp "${REPO_ROOT}/configs/fail2ban-jail.local" "$JAIL_LOCAL"
        # Inject admin IP into ignoreip
        if [[ -n "$ADMIN_IP" ]]; then
            sed -i "s|^ignoreip = 127.0.0.1/8 ::1|ignoreip = 127.0.0.1/8 ::1 ${ADMIN_IP}|" "$JAIL_LOCAL"
        fi
        chmod 644 "$JAIL_LOCAL"
        log_success "jail.local deployed with admin IP ${ADMIN_IP}"
    fi

    # 12c. Deploy web jails
    mkdir -p /etc/fail2ban/jail.d
    if [[ -f "${REPO_ROOT}/deploy/fail2ban/jail.d/nginx-web.conf" ]]; then
        cp "${REPO_ROOT}/deploy/fail2ban/jail.d/nginx-web.conf" /etc/fail2ban/jail.d/
        log_success "Web jails deployed"
    fi

    # 12d. Deploy custom filters
    if [[ -d "${REPO_ROOT}/deploy/fail2ban/filter.d" ]]; then
        cp "${REPO_ROOT}/deploy/fail2ban/filter.d/"*.conf /etc/fail2ban/filter.d/
        log_success "Custom filters deployed"
    fi

    # 12e. Validate and restart
    if fail2ban-client -t &>/dev/null; then
        log_success "Fail2Ban config validated"
        systemctl enable fail2ban &>/dev/null
        systemctl restart fail2ban
        sleep 2

        if is_service_active fail2ban; then
            local jail_count
            jail_count=$(fail2ban-client status 2>/dev/null | grep "Number of jail" | awk '{print $NF}' || echo "?")
            log_success "Fail2Ban running with ${jail_count} jails"
        else
            log_error "Fail2Ban failed to start"
        fi
    else
        log_error "Fail2Ban config validation failed"
        fail2ban-client -t || true
    fi

    phase_end 12
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 13: Systemd Services
# ═══════════════════════════════════════════════════════════════════════════
phase_systemd_services() {
    phase_start 13 "Systemd Services" || return 0

    local SYSTEMD="/etc/systemd/system"

    # 13a. Copy service files from repo root
    local ROOT_SERVICES=(
        "shophosting-webapp.service"
        "shophosting-backup-worker.service"
        "shophosting-backup.service"
        "shophosting-backup.timer"
        "shophosting-dir-backup.service"
        "shophosting-dir-backup.timer"
        "provisioning-worker.service"
    )
    for svc in "${ROOT_SERVICES[@]}"; do
        if [[ -f "${REPO_ROOT}/${svc}" ]]; then
            cp "${REPO_ROOT}/${svc}" "${SYSTEMD}/${svc}"
        fi
    done

    # Provisioning sub-workers
    for svc in resource-worker.service monitoring-worker.service; do
        if [[ -f "${REPO_ROOT}/provisioning/${svc}" ]]; then
            cp "${REPO_ROOT}/provisioning/${svc}" "${SYSTEMD}/${svc}"
        fi
    done

    # Security services
    for svc in security-dashboard.service security-worker.service security-monitor.service; do
        if [[ -f "${REPO_ROOT}/security/deploy/${svc}" ]]; then
            cp "${REPO_ROOT}/security/deploy/${svc}" "${SYSTEMD}/${svc}"
        fi
    done

    # 13b. Copy deploy/ service files
    if [[ -d "${REPO_ROOT}/deploy/systemd" ]]; then
        for svc_file in "${REPO_ROOT}/deploy/systemd/"*; do
            if [[ -f "$svc_file" ]]; then
                cp "$svc_file" "${SYSTEMD}/$(basename "$svc_file")"
            fi
        done
        log_success "All service files copied to ${SYSTEMD}"
    fi

    # 13c. Reload systemd
    systemctl daemon-reload
    log_success "Systemd daemon reloaded"

    # 13d. Enable and start services in dependency order
    log_info "Starting services..."

    if is_primary; then
        # Primary: Core webapp
        _enable_start "shophosting-webapp.service"
    fi

    # Provisioning workers (both roles)
    for svc in provisioning-worker resource-worker monitoring-worker; do
        _enable_start "${svc}.service"
    done

    # Application workers (both roles)
    for svc in shophosting-backup-worker shophosting-performance-worker; do
        _enable_start "${svc}.service"
    done

    if is_primary; then
        # Primary-only workers
        for svc in leads-worker subscription-worker; do
            _enable_start "${svc}.service"
        done
    fi

    # Security services (both roles)
    for svc in security-worker security-monitor; do
        _enable_start "${svc}.service"
    done

    if is_primary; then
        _enable_start "security-dashboard.service"
    fi

    # Timers
    log_info "Enabling timers..."
    for timer in shophosting-backup shophosting-dir-backup shophosting-system-backup \
                 security-waf-sync security-f2b-sync; do
        _enable_start "${timer}.timer"
    done

    if is_primary; then
        _enable_start "shophosting-marketing-queue.timer"
    fi

    phase_end 13
}

_enable_start() {
    local unit="$1"
    if [[ ! -f "/etc/systemd/system/${unit}" ]]; then
        log_warn "Unit file not found: ${unit} — skipping"
        return 0
    fi
    systemctl enable "$unit" &>/dev/null || true
    systemctl start "$unit" &>/dev/null || true
    if is_service_active "$unit"; then
        log_success "${unit} started"
    else
        log_warn "${unit} may not have started correctly"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 14: Cron Jobs
# ═══════════════════════════════════════════════════════════════════════════
phase_cron_jobs() {
    phase_start 14 "Cron Jobs" || return 0

    # 14a. Stripe sync cron — primary only
    if is_primary; then
        local AGILEWEB_CRON
        AGILEWEB_CRON=$(crontab -u "$SERVICE_USER" -l 2>/dev/null || echo "")

        if ! echo "$AGILEWEB_CRON" | grep -q "stripe_sync.sh"; then
            (echo "$AGILEWEB_CRON"; echo "# Stripe data sync - daily at 4am"; echo "0 4 * * * /opt/shophosting/scripts/cron/stripe_sync.sh >> /opt/shophosting/logs/stripe_sync.log 2>&1") | \
                crontab -u "$SERVICE_USER" -
            log_success "Stripe sync cron added for ${SERVICE_USER}"
        else
            log_info "Stripe sync cron already exists"
        fi
    fi

    # 14b. System backup cron (root)
    local ROOT_CRON
    ROOT_CRON=$(crontab -l 2>/dev/null || echo "")

    if ! echo "$ROOT_CRON" | grep -q "system-backup.sh"; then
        (echo "$ROOT_CRON"; echo "# System backup - daily at 3am"; echo "0 3 * * * /opt/shophosting/scripts/system-backup.sh >> /var/log/shophosting-system-backup.log 2>&1") | \
            crontab -
        log_success "System backup cron added for root"
    else
        log_info "System backup cron already exists"
    fi

    log_info "Customer backup crons will be added as customers are provisioned"

    phase_end 14
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 15: SSL Certificates
# ═══════════════════════════════════════════════════════════════════════════
phase_ssl() {
    phase_start 15 "SSL Certificates" || return 0

    local DOMAINS
    prompt_optional DOMAINS "Domains for SSL (space-separated, e.g. 'shophosting.io www.shophosting.io')"

    if [[ -z "$DOMAINS" ]]; then
        log_info "No domains specified — skipping SSL setup"
        log_info "Run later: sudo certbot --nginx -d yourdomain.com"
        phase_end 15
        return 0
    fi

    local ADMIN_EMAIL
    prompt_required ADMIN_EMAIL "Email for Let's Encrypt notifications" "admin@shophosting.io"

    for domain in $DOMAINS; do
        log_info "Getting certificate for ${domain}..."
        if certbot --nginx -d "$domain" --non-interactive --agree-tos --email "$ADMIN_EMAIL" 2>/dev/null; then
            log_success "SSL certificate obtained for ${domain}"
        else
            log_warn "Certbot failed for ${domain} (DNS may not be pointed yet)"
        fi
    done

    # Test auto-renewal
    log_info "Testing certificate auto-renewal..."
    certbot renew --dry-run 2>/dev/null || log_warn "Renewal dry-run failed"

    phase_end 15
}

# ═══════════════════════════════════════════════════════════════════════════
# Phase 16: Verification
# ═══════════════════════════════════════════════════════════════════════════
phase_verification() {
    phase_start 16 "Verification" || return 0

    local PASS=0
    local FAIL=0

    _check() {
        local desc="$1"
        shift
        if "$@" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} ${desc}"
            ((PASS++))
        else
            echo -e "  ${RED}✗${NC} ${desc}"
            ((FAIL++))
        fi
    }

    echo -e "\n${BOLD}System Services${NC}"
    _check "nginx" is_service_active nginx
    _check "fail2ban" is_service_active fail2ban
    _check "provisioning-worker" is_service_active provisioning-worker
    _check "monitoring-worker" is_service_active monitoring-worker
    _check "resource-worker" is_service_active resource-worker
    _check "shophosting-backup-worker" is_service_active shophosting-backup-worker
    _check "shophosting-performance-worker" is_service_active shophosting-performance-worker
    _check "security-worker" is_service_active security-worker
    _check "security-monitor" is_service_active security-monitor

    if is_primary; then
        _check "mysql" is_service_active mysql
        _check "shophosting-webapp" is_service_active shophosting-webapp
        _check "security-dashboard" is_service_active security-dashboard
    fi

    echo -e "\n${BOLD}Docker Containers${NC}"
    _check "registry" is_docker_running registry

    if is_primary; then
        _check "redis-master" is_docker_running redis-master
        _check "redis-replica" is_docker_running redis-replica
        _check "redis-sentinel-1" is_docker_running redis-sentinel-1
        _check "shophosting-waf" is_docker_running shophosting-waf
        _check "shophosting-prometheus" is_docker_running shophosting-prometheus
        _check "shophosting-grafana" is_docker_running shophosting-grafana
        _check "portainer" is_docker_running portainer
    fi

    echo -e "\n${BOLD}Timers${NC}"
    for timer in shophosting-backup shophosting-dir-backup shophosting-system-backup \
                 security-waf-sync security-f2b-sync; do
        _check "${timer}.timer" is_service_active "${timer}.timer"
    done

    if is_primary; then
        _check "shophosting-marketing-queue.timer" is_service_active "shophosting-marketing-queue.timer"
    fi

    echo -e "\n${BOLD}Infrastructure${NC}"
    _check "UFW active" bash -c "ufw status | grep -q 'Status: active'"
    _check "/var/customers exists" test -d /var/customers
    _check "Logs directory exists" test -d /opt/shophosting/logs
    _check ".env exists" test -f /opt/shophosting/.env

    if is_primary; then
        _check "/var/log/modsecurity exists" test -d /var/log/modsecurity
    fi

    # Summary
    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  Bootstrap Verification Summary (${SERVER_ROLE})${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}Passed: ${PASS}${NC}"
    echo -e "  ${RED}Failed: ${FAIL}${NC}"
    echo ""

    if [[ $FAIL -eq 0 ]]; then
        echo -e "  ${GREEN}${BOLD}All checks passed!${NC}"
    else
        echo -e "  ${YELLOW}${FAIL} check(s) failed — review output above${NC}"
    fi

    if is_primary; then
        echo ""
        echo -e "${BOLD}Access URLs:${NC}"
        echo "  Main app:           https://shophosting.io"
        echo "  Security dashboard: https://security.shophosting.io"
        echo "  Grafana:            https://shophosting.io/grafana"
        echo "  Portainer:          https://localhost:9443"
        echo "  Prometheus:         http://localhost:9090"
    fi
    echo ""

    phase_end 16
}

# ═══════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════
cleanup_temp_files() {
    rm -f "${REPO_ROOT}/.bootstrap-admin-ip"
    rm -f "${REPO_ROOT}/.bootstrap-db-password"
}

# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
main() {
    parse_args "$@"
    preflight_checks

    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║     ShopHosting Server Bootstrap                    ║${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""

    log_info "Role: ${SERVER_ROLE}"

    local skip_count=${#SKIP_PHASES[@]}
    if [[ -n "$ONLY_PHASE" ]]; then
        log_info "Running only Phase ${ONLY_PHASE}"
    elif [[ $skip_count -gt 0 ]]; then
        log_info "Skipping ${skip_count} phase(s): ${SKIP_PHASES[*]}"
    fi

    phase_system_packages    # 1
    phase_users_permissions  # 2
    phase_firewall           # 3
    phase_mysql              # 4
    phase_redis              # 5
    phase_directories        # 6
    phase_python_envs        # 7
    phase_env_config         # 8
    phase_docker_images      # 9
    phase_docker_services    # 10
    phase_nginx              # 11
    phase_fail2ban           # 12
    phase_systemd_services   # 13
    phase_cron_jobs          # 14
    phase_ssl                # 15
    phase_verification       # 16

    cleanup_temp_files

    echo ""
    echo -e "${GREEN}${BOLD}Bootstrap complete!${NC} $(date)"
    echo -e "Logs saved to: ${LOG_FILE}"
    echo ""
}

main "$@"
