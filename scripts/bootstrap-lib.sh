#!/bin/bash
#
# bootstrap-lib.sh - Shared utilities for ShopHosting bootstrap
#
# Sourced by bootstrap.sh. Provides logging, prompting, idempotency
# checks, and phase management functions.
#

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT="${REPO_ROOT:-/opt/shophosting}"
LOG_FILE="${REPO_ROOT}/logs/bootstrap.log"
CUSTOMERS_DIR="/var/customers"
SERVICE_USER="agileweb"

# Phase control (populated by parse_args in bootstrap.sh)
SKIP_PHASES=()
ONLY_PHASE=""
DRY_RUN=false

# Server role: "primary" = full install, "worker" = fleet node (no webapp/wiki/etc)
SERVER_ROLE="worker"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log() {
    local prefix="$1"
    shift
    local msg="$*"
    echo -e "${prefix} ${msg}${NC}"
    # Append to log file (strip ANSI codes)
    if [[ -d "$(dirname "$LOG_FILE")" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $(echo -e "$prefix $msg" | sed 's/\x1b\[[0-9;]*m//g')" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

log_info() {
    _log "${BLUE}[INFO]${NC}" "$@"
}

log_warn() {
    _log "${YELLOW}[WARN]${NC}" "$@"
}

log_error() {
    _log "${RED}[ERROR]${NC}" "$@"
}

log_success() {
    _log "${GREEN}  ✓${NC}" "$@"
}

log_phase() {
    local num="$1"
    shift
    local msg="$*"
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  Phase ${num}: ${msg}${NC}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${NC}"
    echo ""
    _log "${CYAN}[PHASE ${num}]${NC}" "$msg"
}

# ---------------------------------------------------------------------------
# User Interaction
# ---------------------------------------------------------------------------
prompt_required() {
    local -n _var=$1
    local description="$2"
    local default="${3:-}"

    while true; do
        if [[ -n "$default" ]]; then
            echo -ne "${BOLD}${description}${NC} [${default}]: "
        else
            echo -ne "${BOLD}${description}${NC}: "
        fi
        read -r _var
        if [[ -z "$_var" && -n "$default" ]]; then
            _var="$default"
        fi
        if [[ -n "$_var" ]]; then
            return 0
        fi
        echo -e "${YELLOW}  Value required. Please try again.${NC}"
    done
}

prompt_secret() {
    local -n _var=$1
    local description="$2"

    while true; do
        echo -ne "${BOLD}${description}${NC}: "
        read -rs _var
        echo ""
        if [[ -n "$_var" ]]; then
            return 0
        fi
        echo -e "${YELLOW}  Value required. Please try again.${NC}"
    done
}

prompt_confirm() {
    local message="$1"
    local response
    echo -ne "${BOLD}${message}${NC} [Y/n]: "
    read -r response
    case "$response" in
        [nN]|[nN][oO]) return 1 ;;
        *) return 0 ;;
    esac
}

prompt_optional() {
    local -n _var=$1
    local description="$2"
    local default="${3:-}"

    if [[ -n "$default" ]]; then
        echo -ne "${BOLD}${description}${NC} [${default}]: "
    else
        echo -ne "${BOLD}${description}${NC} (optional, press Enter to skip): "
    fi
    read -r _var
    if [[ -z "$_var" && -n "$default" ]]; then
        _var="$default"
    fi
}

# ---------------------------------------------------------------------------
# Idempotency Checks
# ---------------------------------------------------------------------------
is_installed() {
    dpkg -s "$1" &>/dev/null
}

is_service_active() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

is_service_enabled() {
    systemctl is-enabled --quiet "$1" 2>/dev/null
}

is_docker_running() {
    docker ps --filter "name=^${1}$" --format '{{.Names}}' 2>/dev/null | grep -q "^${1}$"
}

user_exists() {
    id "$1" &>/dev/null
}

command_exists() {
    command -v "$1" &>/dev/null
}

file_contains() {
    grep -q "$2" "$1" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------
die() {
    log_error "$@"
    exit 1
}

run_or_die() {
    local desc="$1"
    shift
    log_info "$desc"
    if "$@"; then
        log_success "$desc"
    else
        die "Failed: $desc"
    fi
}

run_warn_on_fail() {
    local desc="$1"
    shift
    if "$@"; then
        log_success "$desc"
    else
        log_warn "Failed (non-fatal): $desc"
    fi
}

# ---------------------------------------------------------------------------
# Phase Management
# ---------------------------------------------------------------------------
should_run_phase() {
    local phase_num="$1"

    # If --phase=N was given, only run that phase
    if [[ -n "$ONLY_PHASE" ]]; then
        [[ "$ONLY_PHASE" == "$phase_num" ]]
        return $?
    fi

    # Check skip list
    for skip in "${SKIP_PHASES[@]}"; do
        if [[ "$skip" == "$phase_num" ]]; then
            return 1
        fi
    done

    return 0
}

phase_start() {
    local num="$1"
    shift
    local desc="$*"

    if ! should_run_phase "$num"; then
        echo -e "${DIM}  Skipping Phase ${num}: ${desc}${NC}"
        return 1
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "${BLUE}  [DRY RUN] Would run Phase ${num}: ${desc}${NC}"
        return 1
    fi

    log_phase "$num" "$desc"
    return 0
}

phase_end() {
    local num="$1"
    log_success "Phase ${num} complete"
}

is_primary() {
    [[ "$SERVER_ROLE" == "primary" ]]
}

is_worker() {
    [[ "$SERVER_ROLE" == "worker" ]]
}

# ---------------------------------------------------------------------------
# Argument Parsing
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --role=*)
                SERVER_ROLE="${1#--role=}"
                if [[ "$SERVER_ROLE" != "primary" && "$SERVER_ROLE" != "worker" ]]; then
                    die "Invalid role: ${SERVER_ROLE} (must be 'primary' or 'worker')"
                fi
                ;;
            --phase=*)
                ONLY_PHASE="${1#--phase=}"
                ;;
            --skip-phase=*)
                SKIP_PHASES+=("${1#--skip-phase=}")
                ;;
            --dry-run)
                DRY_RUN=true
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                die "Unknown argument: $1 (use --help for usage)"
                ;;
        esac
        shift
    done
}

show_help() {
    cat <<'USAGE'
ShopHosting Server Bootstrap Script

Usage: sudo ./scripts/bootstrap.sh [OPTIONS]

Options:
  --role=ROLE        Server role: 'worker' (default) or 'primary'
                       worker  — fleet node for customer containers
                       primary — full install including webapp, monitoring, wiki
  --phase=N          Run only phase N
  --skip-phase=N     Skip phase N (can be repeated)
  --dry-run          Show what would be done without executing
  --help             Show this help message

Phases:
   1  System Packages        9  Docker Images
   2  Users & Permissions   10  Docker Services        (primary only)
   3  Firewall (UFW)        11  Nginx Configuration
   4  MySQL                 (primary only)
   5  Redis HA              (primary only)
   6  Directories           12  Fail2Ban
   7  Python Environments   13  Systemd Services
   8  Environment Config    14  Cron Jobs
                            15  SSL Certificates
                            16  Verification

Phases marked (primary only) are skipped when --role=worker.

Examples:
  sudo ./scripts/bootstrap.sh                     # Worker node setup (default)
  sudo ./scripts/bootstrap.sh --role=primary      # Full primary server setup
  sudo ./scripts/bootstrap.sh --phase=16          # Run verification only
  sudo ./scripts/bootstrap.sh --skip-phase=15     # Skip SSL setup
  sudo ./scripts/bootstrap.sh --dry-run           # Preview phases

Setup:
  # Worker node (sparse checkout — excludes webapp, wiki, etc.)
  git clone --no-checkout --filter=blob:none \
    git@github.com:NathanJHarrell/shophosting.git /opt/shophosting
  cd /opt/shophosting
  git sparse-checkout init --cone
  git sparse-checkout set scripts deploy configs docker provisioning security templates
  git checkout main
  sudo ./scripts/bootstrap.sh

  # Primary server (full clone)
  git clone git@github.com:NathanJHarrell/shophosting.git /opt/shophosting
  sudo ./scripts/bootstrap.sh --role=primary
USAGE
}
