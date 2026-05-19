#!/usr/bin/env bash
set -Eeuo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RESET='\033[0m'   C_BOLD='\033[1m'     C_DIM='\033[2m'
  C_GREEN='\033[0;32m'  C_BGREEN='\033[1;32m'
  C_CYAN='\033[0;36m'   C_BCYAN='\033[1;36m'
  C_YELLOW='\033[1;33m'
  C_RED='\033[0;31m'    C_BRED='\033[1;31m'
else
  C_RESET=''; C_BOLD=''; C_DIM=''
  C_GREEN=''; C_BGREEN=''; C_CYAN=''; C_BCYAN=''
  C_YELLOW=''; C_RED=''; C_BRED=''
fi

APP_NAME="awg-panel"
INSTALL_DIR="${INSTALL_DIR:-/opt/awg-panel}"
PROJECT_SRC="${PROJECT_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
case "${INSTALL_MODE:-panel}" in
  agent|api|headless) INSTALL_MODE="agent" ;;
  *) INSTALL_MODE="panel" ;;
esac
PANEL_HTTP_BIND="${PANEL_HTTP_BIND:-0.0.0.0}"
PANEL_HTTP_PORT="${PANEL_HTTP_PORT:-8080}"
BACKEND_BIND="${BACKEND_BIND:-}"
BACKEND_PORT="${BACKEND_PORT:-8090}"
NETWORK_NAME="${NETWORK_NAME:-awg-panel-net}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-awg-admin-backend}"
FRONTEND_CONTAINER="${FRONTEND_CONTAINER:-awg-admin-frontend}"
BACKEND_IMAGE="${BACKEND_IMAGE:-awg-panel-backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-awg-panel-frontend}"
LEGACY_QR_CONTAINER="${LEGACY_QR_CONTAINER:-awg-admin-qr-renderer}"
BACKUP_DIR="${BACKUP_DIR:-/opt/awg-panel-backups}"
SKIP_DOCKER_INSTALL="${SKIP_DOCKER_INSTALL:-0}"
FORCE_PORT="${FORCE_PORT:-0}"

STEP_N=0
_SPIN_PID=''

frontend_enabled() { [ "$INSTALL_MODE" = "panel" ]; }

normalize_mode() {
  if [ "$INSTALL_MODE" = "agent" ]; then
    : "${BACKEND_BIND:=0.0.0.0}"
  else
    : "${BACKEND_BIND:=127.0.0.1}"
  fi
}

# ─── Logging ──────────────────────────────────────────────────────────────────
log()      { printf "  ${C_BGREEN}▶${C_RESET}  ${C_BOLD}%s${C_RESET}\n" "$*"; }
log_ok()   { printf "  ${C_BGREEN}✓${C_RESET}  %s\n" "$*"; }
log_dim()  { printf "  ${C_DIM}   %s${C_RESET}\n" "$*"; }
log_warn() { printf "  ${C_YELLOW}⚠${C_RESET}  %s\n" "$*"; }

step() {
  STEP_N=$(( STEP_N + 1 ))
  printf "\n  ${C_BCYAN}${C_BOLD}◈  Step %d  —  %s${C_RESET}\n" "$STEP_N" "$*"
  printf "  ${C_DIM}──────────────────────────────────────────────────${C_RESET}\n\n"
}

fail() {
  spin_stop 2>/dev/null || true
  printf "\n  ${C_BRED}${C_BOLD}✗  ERROR:${C_RESET}  ${C_RED}%s${C_RESET}\n\n" "$*" >&2
  exit 1
}

# ─── Spinner ──────────────────────────────────────────────────────────────────
spin_start() {
  [ -t 1 ] || return 0
  local msg="${1:-}"
  (
    local -a fr=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local n=0
    while true; do
      printf "\r  \033[36m%s\033[0m  %s  " "${fr[$n]}" "$msg"
      n=$(( (n+1) % 10 ))
      sleep 0.1
    done
  ) &
  _SPIN_PID=$!
}

spin_stop() {
  if [ -n "$_SPIN_PID" ]; then
    kill "$_SPIN_PID" 2>/dev/null || true
    wait "$_SPIN_PID" 2>/dev/null || true
    _SPIN_PID=''
    printf "\r\033[2K"
  fi
}

trap 'spin_stop 2>/dev/null || true' EXIT

# ─── Banner ───────────────────────────────────────────────────────────────────
banner() {
  printf "\n"
  printf "  ${C_BCYAN}╔════════════════════════════════════════════╗${C_RESET}\n"
  printf "  ${C_BCYAN}║${C_RESET}                                            ${C_BCYAN}║${C_RESET}\n"
  printf "  ${C_BCYAN}║${C_RESET}    ${C_BOLD}◈  AmneziaWG Panel  ·  Installer${C_RESET}       ${C_BCYAN}║${C_RESET}\n"
  printf "  ${C_BCYAN}║${C_RESET}                                            ${C_BCYAN}║${C_RESET}\n"
  printf "  ${C_BCYAN}╚════════════════════════════════════════════╝${C_RESET}\n"
  printf "\n"
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "Run as root: sudo bash scripts/install-vps.sh"
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ─── Docker install ───────────────────────────────────────────────────────────
install_docker_if_missing() {
  if have_cmd docker; then return; fi
  if [ "$SKIP_DOCKER_INSTALL" = "1" ]; then
    fail "Docker is not installed. Install Docker first or unset SKIP_DOCKER_INSTALL."
  fi
  have_cmd apt-get || fail "Docker is missing and automatic install only supports apt-get systems."
  step "Installing Docker"
  apt-get update -qq
  apt-get install -y -qq docker.io ca-certificates curl
  systemctl enable --now docker
  log_ok "Docker installed"
}

# ─── Compose detection ────────────────────────────────────────────────────────
compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    printf 'docker compose'; return
  fi
  if have_cmd docker-compose; then
    printf 'docker-compose'; return
  fi
  printf ''
}

# ─── Port helpers ─────────────────────────────────────────────────────────────
port_is_busy() {
  local port="$1"
  if have_cmd ss; then
    ss -ltn "sport = :$port" | awk 'NR > 1 {found=1} END {exit found ? 0 : 1}'; return
  fi
  if have_cmd netstat; then
    netstat -ltn | awk -v p=":$port" '$4 ~ p "$" {found=1} END {exit found ? 0 : 1}'; return
  fi
  return 1
}

check_ports() {
  if [ "$FORCE_PORT" = "1" ]; then return; fi
  if frontend_enabled && port_is_busy "$PANEL_HTTP_PORT"; then
    local owner
    owner="$(docker ps --filter "publish=$PANEL_HTTP_PORT" --format '{{.Names}}' 2>/dev/null | head -n 1 || true)"
    if [ "$owner" != "$FRONTEND_CONTAINER" ]; then
      fail "Port $PANEL_HTTP_PORT is already in use. Set PANEL_HTTP_PORT=8081 or FORCE_PORT=1."
    fi
  fi
  if port_is_busy "$BACKEND_PORT"; then
    local owner
    owner="$(docker ps --filter "publish=$BACKEND_PORT" --format '{{.Names}}' 2>/dev/null | head -n 1 || true)"
    if [ "$owner" != "$BACKEND_CONTAINER" ]; then
      fail "Port $BACKEND_PORT is already in use. Set BACKEND_PORT=8091 or FORCE_PORT=1."
    fi
  fi
}

# ─── File copy ────────────────────────────────────────────────────────────────
copy_project() {
  step "Installing files"
  log "Destination: $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR" "$BACKUP_DIR"
  if [ -d "$INSTALL_DIR/backend" ] || [ -d "$INSTALL_DIR/frontend" ]; then
    local ts
    ts="$(date +%Y%m%d-%H%M%S)"
    tar -czf "$BACKUP_DIR/awg-panel-$ts.tar.gz" -C "$(dirname "$INSTALL_DIR")" "$(basename "$INSTALL_DIR")"
    log_dim "Backup saved → $BACKUP_DIR/awg-panel-$ts.tar.gz"
  fi
  spin_start "Copying project files…"
  tar \
    --exclude='.git' \
    --exclude='.agents' \
    --exclude='.codex' \
    --exclude='.env' \
    --exclude='qr-renderer' \
    --exclude='backend/.venv' \
    --exclude='backend/tests' \
    --exclude='backend/.pytest_cache' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='backend/__pycache__' \
    --exclude='backend/app/__pycache__' \
    -C "$PROJECT_SRC" -czf /tmp/awg-panel-install.tar.gz .
  rm -rf "$INSTALL_DIR/qr-renderer"
  tar -xzf /tmp/awg-panel-install.tar.gz -C "$INSTALL_DIR"
  rm -f /tmp/awg-panel-install.tar.gz
  spin_stop
  mkdir -p "$INSTALL_DIR/data/clients"
  log_ok "Files installed"
}

# ─── Detection helpers ────────────────────────────────────────────────────────
detect_awg_container() {
  if [ -n "${AWG_DOCKER_CONTAINER:-}" ]; then printf '%s' "$AWG_DOCKER_CONTAINER"; return; fi
  docker ps --format '{{.Names}}' | grep -E 'amnezia.*awg|^awg[0-9]*$|^awg[-_]' | grep -Ev '^awg-admin-' | head -n 1 || true
}

detect_udp_port() {
  local container="$1"
  if [ -n "${AWG_PORT:-}" ]; then printf '%s' "$AWG_PORT"; return; fi
  docker port "$container" 2>/dev/null | awk -F: '/udp/ {print $NF; exit}' || true
}

_valid_ipv4() { printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; }

detect_public_ip() {
  if [ -n "${SERVER_IP:-}" ]; then printf '%s' "$SERVER_IP"; return; fi
  local ip=""
  # External services first — they return the real internet-facing IP,
  # not the LAN address that hostname -I / ip route would show on NAT setups.
  if have_cmd curl; then
    ip="$(curl -s --connect-timeout 4 --max-time 6 https://api.ipify.org 2>/dev/null | tr -d '[:space:]' || true)"
    _valid_ipv4 "$ip" || ip=""
    if [ -z "$ip" ]; then
      ip="$(curl -s --connect-timeout 4 --max-time 6 https://ifconfig.me 2>/dev/null | tr -d '[:space:]' || true)"
      _valid_ipv4 "$ip" || ip=""
    fi
    if [ -z "$ip" ]; then
      ip="$(curl -s --connect-timeout 4 --max-time 6 https://icanhazip.com 2>/dev/null | tr -d '[:space:]' || true)"
      _valid_ipv4 "$ip" || ip=""
    fi
  fi
  if [ -z "$ip" ] && have_cmd wget; then
    ip="$(wget -qO- --timeout=6 https://api.ipify.org 2>/dev/null | tr -d '[:space:]' || true)"
    _valid_ipv4 "$ip" || ip=""
    if [ -z "$ip" ]; then
      ip="$(wget -qO- --timeout=6 https://ifconfig.me 2>/dev/null | tr -d '[:space:]' || true)"
      _valid_ipv4 "$ip" || ip=""
    fi
  fi
  # Fallback: source IP from routing table (works on direct-attach VPS)
  if [ -z "$ip" ]; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}')"
    _valid_ipv4 "$ip" || ip=""
  fi
  # Last resort: first IP from hostname -I
  if [ -z "$ip" ]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    _valid_ipv4 "$ip" || ip=""
  fi
  printf '%s' "${ip:-127.0.0.1}"
}

detect_awg_config_path() {
  local container="$1"
  local iface="${AWG_INTERFACE:-awg0}"
  if [ -n "${AWG_CONTAINER_CONFIG_PATH:-}" ]; then printf '%s' "$AWG_CONTAINER_CONFIG_PATH"; return; fi
  docker exec "$container" sh -lc '
    iface="$1"
    for path in \
      "/opt/amnezia/awg/${iface}.conf" \
      "/opt/amnezia/amneziawg/${iface}.conf" \
      "/etc/amnezia/amneziawg/${iface}.conf" \
      "/etc/wireguard/${iface}.conf" \
      "/config/${iface}.conf" \
      "/opt/amnezia/awg/awg0.conf" \
      "/opt/amnezia/amneziawg/awg0.conf" \
      "/etc/amnezia/amneziawg/awg0.conf" \
      "/etc/wireguard/awg0.conf" \
      "/etc/wireguard/wg0.conf"; do
      [ -f "$path" ] && printf "%s" "$path" && exit 0
    done
    find /opt/amnezia /etc/amnezia /etc/wireguard /config \
      -maxdepth 4 -type f \( -name "*.conf" -o -name "wg*.conf" -o -name "awg*.conf" \) \
      2>/dev/null | head -n 1
  ' sh "$iface" 2>/dev/null || true
}

# ─── .env management ──────────────────────────────────────────────────────────
ensure_env_key() {
  local env_path="$1" key="$2" value="$3"
  grep -q "^${key}=" "$env_path" && return
  printf '%s=%s\n' "$key" "$value" >> "$env_path"
}

set_env_key() {
  local env_path="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$env_path"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$env_path"
    return
  fi
  printf '%s=%s\n' "$key" "$value" >> "$env_path"
}

interface_from_config_path() { basename "$1" .conf; }

update_existing_env() {
  local env_path="$1"
  local awg_container awg_config_path awg_iface
  awg_container="$(env_value AWG_DOCKER_CONTAINER)"
  [ -n "$awg_container" ] || awg_container="$(detect_awg_container)"
  [ -n "$awg_container" ] || return 0
  awg_config_path="$(env_value AWG_CONTAINER_CONFIG_PATH)"
  [ -n "$awg_config_path" ] || awg_config_path="$(detect_awg_config_path "$awg_container")"
  [ -n "$awg_config_path" ] || return 0
  awg_iface="${AWG_INTERFACE:-$(interface_from_config_path "$awg_config_path")}"
  set_env_key "$env_path" "AWG_INTERFACE" "$awg_iface"

  # Add new variables that may be missing in older installations
  ensure_env_key "$env_path" "DB_PATH" "/data/panel.db"
  ensure_env_key "$env_path" "WEBHOOK_URL" ""
  ensure_env_key "$env_path" "WEBHOOK_SECRET" ""

  # Always refresh SERVER_ENDPOINT with the current public IP.
  # On reinstall the old .env may have a stale IP from a previous server —
  # redetect unconditionally so the endpoint stays correct.
  local new_ep="${SERVER_ENDPOINT:-}"
  if [ -z "$new_ep" ]; then
    local current_ip; current_ip="$(detect_public_ip)"
    local old_ep; old_ep="$(sed -n 's/^SERVER_ENDPOINT=//p' "$env_path" | head -n1)"
    local port="${AWG_PORT:-${old_ep##*:}}"
    [ -n "$current_ip" ] && [ -n "$port" ] && new_ep="$current_ip:$port"
  fi
  [ -n "$new_ep" ] && set_env_key "$env_path" "SERVER_ENDPOINT" "$new_ep" && log_dim "SERVER_ENDPOINT updated → $new_ep"
}

write_env_if_missing() {
  local env_path="$INSTALL_DIR/.env"
  if [ -f "$env_path" ]; then
    log "Keeping existing $env_path"
    update_existing_env "$env_path"
    chmod 600 "$env_path"
    return
  fi

  step "Creating configuration"
  local awg_container awg_port server_ip awg_config_path awg_iface admin_token admin_password
  awg_container="$(detect_awg_container)"
  [ -n "$awg_container" ] || fail "Could not detect AmneziaWG container. Run with AWG_DOCKER_CONTAINER=<name>."
  log_dim "AmneziaWG container → $awg_container"

  awg_port="$(detect_udp_port "$awg_container")"
  [ -n "$awg_port" ] || awg_port="${AWG_PORT:-51820}"

  server_ip="$(detect_public_ip)"
  log_dim "Server IP → $server_ip"

  awg_config_path="$(detect_awg_config_path "$awg_container")"
  [ -n "$awg_config_path" ] || fail "Could not detect AmneziaWG config in container '$awg_container'.\nRun with AWG_CONTAINER_CONFIG_PATH=/path/to/awg0.conf."
  log_dim "AWG config → $awg_config_path"

  awg_iface="${AWG_INTERFACE:-$(interface_from_config_path "$awg_config_path")}"

  if have_cmd openssl; then
    admin_token="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
    admin_password="$(openssl rand -base64 24 | tr '+/' '-_' | tr -d '=')"
  else
    admin_token="$(head -c 48 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=' | head -c 43)"
    admin_password="$(head -c 36 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=' | head -c 32)"
  fi

  cat > "$env_path" <<EOF_ENV
ADMIN_TOKEN=$admin_token
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
ADMIN_PASSWORD=$admin_password
AWG_INTERFACE=$awg_iface
MOCK_AWG=false
AWG_BIN=${AWG_BIN:-awg}
AWG_CONTAINER_NAME=$awg_container
AWG_DOCKER_CONTAINER=$awg_container
AWG_CONFIG_PATH=${AWG_CONFIG_PATH:-$awg_config_path}
AWG_CONTAINER_CONFIG_PATH=$awg_config_path
CLIENTS_DIR=/data/clients
DB_PATH=/data/panel.db
SERVER_ENDPOINT=${SERVER_ENDPOINT:-$server_ip:$awg_port}
CLIENT_DNS=${CLIENT_DNS:-1.1.1.1}
CLIENT_ALLOWED_IPS=${CLIENT_ALLOWED_IPS:-0.0.0.0/0, ::/0}
CLIENT_PERSISTENT_KEEPALIVE=${CLIENT_PERSISTENT_KEEPALIVE:-25}
RELOAD_COMMAND=${RELOAD_COMMAND:-docker restart $awg_container}
PANEL_HTTP_BIND=$PANEL_HTTP_BIND
PANEL_HTTP_PORT=$PANEL_HTTP_PORT
BACKEND_BIND=$BACKEND_BIND
BACKEND_PORT=$BACKEND_PORT
INSTALL_MODE=$INSTALL_MODE
# Webhooks — POST на этот URL при создании/удалении/истечении клиентов и заказов
WEBHOOK_URL=${WEBHOOK_URL:-}
WEBHOOK_SECRET=${WEBHOOK_SECRET:-}
EOF_ENV
  chmod 600 "$env_path"
  log_ok "Config written → $env_path"
}

# ─── Start containers ─────────────────────────────────────────────────────────
start_with_compose() {
  local cmd="$1"
  local services="backend"
  frontend_enabled && services="backend frontend"
  step "Building & starting containers"
  log_dim "Using: $cmd"
  cd "$INSTALL_DIR"
  docker rm -f "$FRONTEND_CONTAINER" "$BACKEND_CONTAINER" "$LEGACY_QR_CONTAINER" >/dev/null 2>&1 || true
  $cmd up -d --build $services
}

start_manually() {
  step "Building & starting containers"
  log_dim "docker compose unavailable — building manually"
  docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME" >/dev/null

  local _log; _log="$(mktemp)"

  spin_start "Building backend image…"
  if ! docker build -t "$BACKEND_IMAGE" "$INSTALL_DIR/backend" >"$_log" 2>&1; then
    spin_stop; cat "$_log" >&2; rm -f "$_log"
    fail "Backend image build failed."
  fi
  spin_stop; rm -f "$_log"
  log_ok "Backend image built"

  if frontend_enabled; then
    spin_start "Building frontend image…"
    if ! docker build -t "$FRONTEND_IMAGE" "$INSTALL_DIR/frontend" >"$_log" 2>&1; then
      spin_stop; cat "$_log" >&2; rm -f "$_log"
      fail "Frontend image build failed."
    fi
    spin_stop; rm -f "$_log"
    log_ok "Frontend image built"
  fi

  docker rm -f "$FRONTEND_CONTAINER" "$BACKEND_CONTAINER" "$LEGACY_QR_CONTAINER" >/dev/null 2>&1 || true

  log "Starting backend container…"
  docker run -d \
    --name "$BACKEND_CONTAINER" \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    --network-alias backend \
    --env-file "$INSTALL_DIR/.env" \
    -v "$INSTALL_DIR/data:/data" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -p "$BACKEND_BIND:$BACKEND_PORT:8090" \
    "$BACKEND_IMAGE" >/dev/null
  log_ok "Backend started"

  if frontend_enabled; then
    log "Starting frontend container…"
    docker run -d \
      --name "$FRONTEND_CONTAINER" \
      --restart unless-stopped \
      --network "$NETWORK_NAME" \
      -p "$PANEL_HTTP_BIND:$PANEL_HTTP_PORT:80" \
      "$FRONTEND_IMAGE" >/dev/null
    log_ok "Frontend started"
  fi
}

# ─── HTTP helper (curl or wget) ───────────────────────────────────────────────
http_ok() {
  local url="$1"
  if have_cmd curl; then curl -fsS "$url" >/dev/null 2>&1; return; fi
  if have_cmd wget; then wget -q -O /dev/null "$url" 2>&1; return; fi
  fail "Neither curl nor wget found — cannot run healthcheck."
}

http_head_ok() {
  local url="$1"
  if have_cmd curl; then curl -fsSI "$url" >/dev/null 2>&1; return; fi
  if have_cmd wget; then wget -q --spider "$url" 2>&1; return; fi
  return 1
}

# ─── Healthcheck ──────────────────────────────────────────────────────────────
healthcheck() {
  step "Verifying installation"
  local attempt
  spin_start "Waiting for backend to start…"
  for attempt in $(seq 1 35); do
    if http_ok "http://127.0.0.1:$BACKEND_PORT/api/health"; then
      spin_stop
      log_ok "Backend is up"
      break
    fi
    if [ "$attempt" = "35" ]; then
      spin_stop
      docker logs --tail 80 "$BACKEND_CONTAINER" >&2 || true
      fail "Backend healthcheck failed after 35 attempts."
    fi
    sleep 1
  done

  docker exec "$BACKEND_CONTAINER" sh -lc '
    case "${MOCK_AWG:-false}" in 1|true|yes|on) exit 0;; esac
    command -v docker >/dev/null || { echo "docker CLI missing in backend container" >&2; exit 1; }
    test -S /var/run/docker.sock || { echo "/var/run/docker.sock not mounted as socket" >&2; exit 1; }
    if [ -n "${AWG_DOCKER_CONTAINER:-}" ]; then
      docker inspect "$AWG_DOCKER_CONTAINER" >/dev/null 2>&1 || { echo "AWG container not visible: $AWG_DOCKER_CONTAINER" >&2; exit 1; }
      docker exec "$AWG_DOCKER_CONTAINER" test -f "$AWG_CONTAINER_CONFIG_PATH" || { echo "AWG config not visible: $AWG_DOCKER_CONTAINER:$AWG_CONTAINER_CONFIG_PATH" >&2; exit 1; }
    fi
  ' || fail "Backend cannot reach Docker or AmneziaWG config.\nCheck /var/run/docker.sock, AWG_DOCKER_CONTAINER, and AWG_CONTAINER_CONFIG_PATH."

  if frontend_enabled; then
    spin_start "Checking frontend…"
    if ! http_head_ok "http://127.0.0.1:$PANEL_HTTP_PORT"; then
      spin_stop
      fail "Frontend healthcheck failed."
    fi
    spin_stop
    log_ok "Frontend is up"
  fi

  printf "\n"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' \
    | grep -E "${FRONTEND_CONTAINER}|${BACKEND_CONTAINER}|NAMES" || true
}

# ─── Read .env value ──────────────────────────────────────────────────────────
env_value() {
  local key="$1"
  local env_path="$INSTALL_DIR/.env"
  [ -f "$env_path" ] || return 0
  sed -n "s/^${key}=//p" "$env_path" | head -n 1
}

# ─── Summary ──────────────────────────────────────────────────────────────────
print_summary() {
  local admin_token admin_username admin_password server_endpoint awg_container panel_url mode_label
  admin_token="$(env_value ADMIN_TOKEN)"
  admin_username="$(env_value ADMIN_USERNAME)"
  admin_password="$(env_value ADMIN_PASSWORD)"
  server_endpoint="$(env_value SERVER_ENDPOINT)"
  awg_container="$(env_value AWG_DOCKER_CONTAINER)"

  if frontend_enabled; then
    panel_url="http://$(detect_public_ip):$PANEL_HTTP_PORT"
    mode_label="Full panel"
  else
    panel_url="http://$(detect_public_ip):$BACKEND_PORT"
    mode_label="Agent API"
  fi

  local S="══════════════════════════════════════════════════"
  printf "\n"
  printf "  ${C_BCYAN}╔%s${C_RESET}\n" "$S"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_BGREEN}✓${C_RESET}  ${C_BOLD}AmneziaWG Panel — Installation Complete${C_RESET}\n"
  printf "  ${C_BCYAN}╠%s${C_RESET}\n" "$S"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  %s\n"                    "Mode"          "$mode_label"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  ${C_BOLD}%s${C_RESET}\n" "Panel URL"     "$panel_url"
  printf "  ${C_BCYAN}╠%s${C_RESET}\n" "$S"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  %s\n"                    "Username"      "${admin_username:-admin}"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  ${C_YELLOW}%s${C_RESET}\n" "Password"    "$admin_password"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  ${C_YELLOW}%s${C_RESET}\n" "Token"       "$admin_token"
  printf "  ${C_BCYAN}╠%s${C_RESET}\n" "$S"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  %s\n"                    "WG Endpoint"   "$server_endpoint"
  printf "  ${C_BCYAN}║${C_RESET}  ${C_DIM}%-14s${C_RESET}  %s\n"                    "AWG Container"  "$awg_container"
  printf "  ${C_BCYAN}╚%s${C_RESET}\n" "$S"
  printf "\n"
  printf "  ${C_DIM}To add this VPS to another panel: Panel URL + Token above.${C_RESET}\n"
  printf "  ${C_DIM}Audit log: /api/audit-log  ·  CSV export: /api/clients/export.csv${C_RESET}\n"
  local webhook_url; webhook_url="$(env_value WEBHOOK_URL)"
  if [ -n "$webhook_url" ]; then
    printf "  ${C_DIM}Webhooks enabled → %s${C_RESET}\n" "$webhook_url"
  else
    printf "  ${C_DIM}Webhooks: set WEBHOOK_URL in .env to enable event notifications.${C_RESET}\n"
  fi
  printf "\n"
}

# ─── Interactive wizard ───────────────────────────────────────────────────────
wizard() {
  [ -t 0 ] || return 0
  [ "${INTERACTIVE:-1}" = "0" ] && return 0

  step "Configuration wizard"
  printf "  ${C_DIM}Press Enter to accept the default shown in [brackets].${C_RESET}\n\n"

  local _ans

  # ── Install mode ──────────────────────────────────────────────────────────
  printf "  ${C_BOLD}Install mode${C_RESET}\n"
  printf "    ${C_CYAN}1${C_RESET}  Full panel   ${C_DIM}(frontend + backend + web UI)${C_RESET}\n"
  printf "    ${C_CYAN}2${C_RESET}  Agent only   ${C_DIM}(backend API, no UI — for additional VPS)${C_RESET}\n"
  local _mode_default=1
  [ "$INSTALL_MODE" = "agent" ] && _mode_default=2
  printf "\n  ${C_DIM}Choice${C_RESET} [${C_CYAN}%s${C_RESET}]: " "$_mode_default"
  read -r _ans
  case "${_ans:-$_mode_default}" in
    2) INSTALL_MODE="agent" ;;
    *) INSTALL_MODE="panel" ;;
  esac

  if [ "$INSTALL_MODE" = "agent" ]; then
    BACKEND_BIND="${BACKEND_BIND:-0.0.0.0}"
  else
    BACKEND_BIND="${BACKEND_BIND:-127.0.0.1}"
  fi

  printf "\n"

  # ── Server public IP ──────────────────────────────────────────────────────
  local _detected_ip
  _detected_ip="$(detect_public_ip)"
  local _default_ip="${SERVER_IP:-$_detected_ip}"
  printf "  ${C_BOLD}Server public IP${C_RESET}     [${C_CYAN}%s${C_RESET}]: " "$_default_ip"
  read -r _ans
  SERVER_IP="${_ans:-$_default_ip}"

  # ── Port(s) ───────────────────────────────────────────────────────────────
  if [ "$INSTALL_MODE" = "panel" ]; then
    printf "  ${C_BOLD}Panel HTTP port${C_RESET}      [${C_CYAN}%s${C_RESET}]: " "$PANEL_HTTP_PORT"
    read -r _ans
    PANEL_HTTP_PORT="${_ans:-$PANEL_HTTP_PORT}"
  else
    printf "  ${C_BOLD}Backend API port${C_RESET}     [${C_CYAN}%s${C_RESET}]: " "$BACKEND_PORT"
    read -r _ans
    BACKEND_PORT="${_ans:-$BACKEND_PORT}"

    printf "  ${C_DIM}    0.0.0.0 = accessible from network · 127.0.0.1 = local only${C_RESET}\n"
    printf "  ${C_BOLD}Backend bind${C_RESET}         [${C_CYAN}%s${C_RESET}]: " "$BACKEND_BIND"
    read -r _ans
    BACKEND_BIND="${_ans:-$BACKEND_BIND}"
  fi

  # ── AmneziaWG container ───────────────────────────────────────────────────
  local _detected_container
  _detected_container="$(detect_awg_container || true)"
  local _default_container="${AWG_DOCKER_CONTAINER:-${_detected_container:-amnezia-awg}}"
  printf "  ${C_BOLD}AmneziaWG container${C_RESET}  [${C_CYAN}%s${C_RESET}]: " "$_default_container"
  read -r _ans
  AWG_DOCKER_CONTAINER="${_ans:-$_default_container}"

  # ── AmneziaWG UDP port ────────────────────────────────────────────────────
  local _detected_port=""
  [ -n "$AWG_DOCKER_CONTAINER" ] && _detected_port="$(detect_udp_port "$AWG_DOCKER_CONTAINER" || true)"
  local _default_wgport="${AWG_PORT:-${_detected_port:-51820}}"
  printf "  ${C_BOLD}AmneziaWG UDP port${C_RESET}   [${C_CYAN}%s${C_RESET}]: " "$_default_wgport"
  read -r _ans
  AWG_PORT="${_ans:-$_default_wgport}"

  printf "\n"
}

# ─── Entrypoint ───────────────────────────────────────────────────────────────
main() {
  banner
  require_root
  install_docker_if_missing
  wizard
  normalize_mode
  check_ports
  copy_project
  write_env_if_missing

  local cmd
  cmd="$(compose_cmd)"
  if [ -n "$cmd" ]; then
    start_with_compose "$cmd"
  else
    start_manually
  fi

  healthcheck
  print_summary

  if frontend_enabled; then
    log_ok "Open in browser → ${C_BOLD}http://$(detect_public_ip):$PANEL_HTTP_PORT${C_RESET}"
  else
    log_ok "Done. Add this VPS to the central panel using the URL and Token above."
  fi
  printf "\n"
}

main "$@"
