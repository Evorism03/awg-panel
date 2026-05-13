#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="awg-panel"
INSTALL_DIR="${INSTALL_DIR:-/opt/awg-panel}"
PROJECT_SRC="${PROJECT_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_MODE="${INSTALL_MODE:-panel}"
PANEL_HTTP_BIND="${PANEL_HTTP_BIND:-0.0.0.0}"
PANEL_HTTP_PORT="${PANEL_HTTP_PORT:-8080}"
if [ "$INSTALL_MODE" = "agent" ] || [ "$INSTALL_MODE" = "api" ] || [ "$INSTALL_MODE" = "headless" ]; then
  INSTALL_MODE="agent"
  BACKEND_BIND="${BACKEND_BIND:-0.0.0.0}"
else
  INSTALL_MODE="panel"
  BACKEND_BIND="${BACKEND_BIND:-127.0.0.1}"
fi
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

frontend_enabled() {
  [ "$INSTALL_MODE" = "panel" ]
}

log() {
  printf '\n[%s] %s\n' "$APP_NAME" "$*"
}

fail() {
  printf '\n[%s] ERROR: %s\n' "$APP_NAME" "$*" >&2
  exit 1
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "Run as root: sudo bash scripts/install-vps.sh"
  fi
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_docker_if_missing() {
  if have_cmd docker; then
    return
  fi
  if [ "$SKIP_DOCKER_INSTALL" = "1" ]; then
    fail "Docker is not installed. Install Docker first or run without SKIP_DOCKER_INSTALL=1."
  fi
  have_cmd apt-get || fail "Docker is missing and automatic install supports only apt-get systems."
  log "Installing Docker packages with apt-get"
  apt-get update
  apt-get install -y docker.io ca-certificates curl
  systemctl enable --now docker
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    printf 'docker compose'
    return
  fi
  if have_cmd docker-compose; then
    printf 'docker-compose'
    return
  fi
  printf ''
}

port_is_busy() {
  local port="$1"
  if have_cmd ss; then
    ss -ltn "sport = :$port" | awk 'NR > 1 {found=1} END {exit found ? 0 : 1}'
    return
  fi
  if have_cmd netstat; then
    netstat -ltn | awk -v p=":$port" '$4 ~ p "$" {found=1} END {exit found ? 0 : 1}'
    return
  fi
  return 1
}

check_ports() {
  if [ "$FORCE_PORT" = "1" ]; then
    return
  fi
  if frontend_enabled && port_is_busy "$PANEL_HTTP_PORT"; then
    local owner
    owner="$(docker ps --filter "publish=$PANEL_HTTP_PORT" --format '{{.Names}}' | head -n 1 || true)"
    if [ "$owner" != "$FRONTEND_CONTAINER" ]; then
      fail "Port $PANEL_HTTP_PORT is already busy. Set PANEL_HTTP_PORT=8081 or FORCE_PORT=1."
    fi
  fi
  if port_is_busy "$BACKEND_PORT"; then
    local owner
    owner="$(docker ps --filter "publish=$BACKEND_PORT" --format '{{.Names}}' | head -n 1 || true)"
    if [ "$owner" != "$BACKEND_CONTAINER" ]; then
      fail "Port $BACKEND_PORT is already busy. Set BACKEND_PORT=8091 or FORCE_PORT=1."
    fi
  fi
}

copy_project() {
  log "Installing files to $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR" "$BACKUP_DIR"
  if [ -d "$INSTALL_DIR/backend" ] || [ -d "$INSTALL_DIR/frontend" ]; then
    local ts
    ts="$(date +%Y%m%d-%H%M%S)"
    tar -czf "$BACKUP_DIR/awg-panel-$ts.tar.gz" -C "$(dirname "$INSTALL_DIR")" "$(basename "$INSTALL_DIR")"
    log "Backup saved: $BACKUP_DIR/awg-panel-$ts.tar.gz"
  fi
  tar \
    --exclude='.git' \
    --exclude='.agents' \
    --exclude='.codex' \
    --exclude='.env' \
    --exclude='qr-renderer' \
    --exclude='backend/.venv' \
    --exclude='**/.venv' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='**/__pycache__' \
    -C "$PROJECT_SRC" -czf /tmp/awg-panel-install.tar.gz .
  rm -rf "$INSTALL_DIR/qr-renderer"
  tar -xzf /tmp/awg-panel-install.tar.gz -C "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR/data/clients"
}

detect_awg_container() {
  if [ -n "${AWG_DOCKER_CONTAINER:-}" ]; then
    printf '%s' "$AWG_DOCKER_CONTAINER"
    return
  fi
  docker ps --format '{{.Names}}' | grep -E 'amnezia.*awg|^awg[0-9]*$|^awg[-_]' | grep -Ev '^awg-admin-' | head -n 1 || true
}

detect_udp_port() {
  local container="$1"
  if [ -n "${AWG_PORT:-}" ]; then
    printf '%s' "$AWG_PORT"
    return
  fi
  docker port "$container" 2>/dev/null | awk -F: '/udp/ {print $NF; exit}' || true
}

detect_public_ip() {
  if [ -n "${SERVER_IP:-}" ]; then
    printf '%s' "$SERVER_IP"
    return
  fi
  hostname -I 2>/dev/null | awk '{print $1}'
}

write_env_if_missing() {
  local env_path="$INSTALL_DIR/.env"
  if [ -f "$env_path" ]; then
    log "Keeping existing $env_path"
    chmod 600 "$env_path"
    return
  fi

  local awg_container awg_port server_ip admin_token admin_password
  awg_container="$(detect_awg_container)"
  [ -n "$awg_container" ] || fail "Could not detect AmneziaWG container. Run with AWG_DOCKER_CONTAINER=name."
  awg_port="$(detect_udp_port "$awg_container")"
  [ -n "$awg_port" ] || awg_port="${AWG_PORT:-51820}"
  server_ip="$(detect_public_ip)"
  admin_token="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
  admin_password="$(openssl rand -base64 24 | tr '+/' '-_' | tr -d '=')"

  log "Creating $env_path"
  cat > "$env_path" <<EOF_ENV
ADMIN_TOKEN=$admin_token
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
ADMIN_PASSWORD=$admin_password
AWG_INTERFACE=${AWG_INTERFACE:-awg0}
MOCK_AWG=false
AWG_BIN=${AWG_BIN:-awg}
AWG_CONTAINER_NAME=$awg_container
AWG_DOCKER_CONTAINER=$awg_container
AWG_CONFIG_PATH=${AWG_CONFIG_PATH:-/opt/amnezia/awg/awg0.conf}
AWG_CONTAINER_CONFIG_PATH=${AWG_CONTAINER_CONFIG_PATH:-/opt/amnezia/awg/awg0.conf}
CLIENTS_DIR=/data/clients
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
EOF_ENV
  chmod 600 "$env_path"
  log "Admin login: ${ADMIN_USERNAME:-admin}"
  log "Admin password: $admin_password"
}

start_with_compose() {
  local cmd="$1"
  local services
  log "Starting with $cmd"
  cd "$INSTALL_DIR"
  docker rm -f "$FRONTEND_CONTAINER" "$BACKEND_CONTAINER" "$LEGACY_QR_CONTAINER" >/dev/null 2>&1 || true
  services="backend"
  if frontend_enabled; then
    services="backend frontend"
  fi
  $cmd up -d --build $services
}

start_manually() {
  log "docker compose is unavailable, starting containers manually"
  docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME" >/dev/null

  docker build -t "$BACKEND_IMAGE" "$INSTALL_DIR/backend"
  if frontend_enabled; then
    docker build -t "$FRONTEND_IMAGE" "$INSTALL_DIR/frontend"
  fi

  docker rm -f "$FRONTEND_CONTAINER" "$BACKEND_CONTAINER" "$LEGACY_QR_CONTAINER" >/dev/null 2>&1 || true

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

  if frontend_enabled; then
    docker run -d \
      --name "$FRONTEND_CONTAINER" \
      --restart unless-stopped \
      --network "$NETWORK_NAME" \
      -p "$PANEL_HTTP_BIND:$PANEL_HTTP_PORT:80" \
      "$FRONTEND_IMAGE" >/dev/null
  fi
}

healthcheck() {
  log "Checking installation"
  sleep 2
  curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null || fail "Backend healthcheck failed"
  docker exec "$BACKEND_CONTAINER" sh -lc 'case "${MOCK_AWG:-false}" in 1|true|yes|on) exit 0;; esac; if [ -n "${AWG_DOCKER_CONTAINER:-}" ]; then command -v docker >/dev/null && test -S /var/run/docker.sock && docker inspect "$AWG_DOCKER_CONTAINER" >/dev/null; fi' \
    || fail "Backend cannot access Docker. Check backend image docker-cli, /var/run/docker.sock mount, and AWG_DOCKER_CONTAINER."
  if frontend_enabled; then
    curl -fsSI "http://127.0.0.1:$PANEL_HTTP_PORT" >/dev/null || fail "Frontend healthcheck failed"
  fi
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E "$FRONTEND_CONTAINER|$BACKEND_CONTAINER|NAMES"
}

env_value() {
  local key="$1"
  local env_path="$INSTALL_DIR/.env"
  if [ ! -f "$env_path" ]; then
    return 0
  fi
  sed -n "s/^${key}=//p" "$env_path" | head -n 1
}

print_summary() {
  local admin_token admin_username admin_password server_endpoint awg_container awg_port panel_url mode_label
  admin_token="$(env_value ADMIN_TOKEN)"
  admin_username="$(env_value ADMIN_USERNAME)"
  admin_password="$(env_value ADMIN_PASSWORD)"
  server_endpoint="$(env_value SERVER_ENDPOINT)"
  awg_container="$(env_value AWG_DOCKER_CONTAINER)"
  awg_port="${server_endpoint##*:}"
  if frontend_enabled; then
    panel_url="http://$(detect_public_ip):$PANEL_HTTP_PORT"
    mode_label="full panel"
  else
    panel_url="http://$(detect_public_ip):$BACKEND_PORT"
    mode_label="agent API"
  fi

  log "Installation summary"
  log "Install mode: $mode_label"
  log "Panel URL: $panel_url"
  log "Panel token (ADMIN_TOKEN): $admin_token"
  log "Admin login: ${admin_username:-admin}"
  log "Admin password: $admin_password"
  log "WireGuard endpoint for this VPS: $server_endpoint"
  log "AmneziaWG container: $awg_container"
  log "AmneziaWG UDP port: $awg_port"
  log "To add this VPS to another panel, use Panel URL + Panel token."
}

main() {
  require_root
  install_docker_if_missing
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
    log "Done. Open: http://$(detect_public_ip):$PANEL_HTTP_PORT"
  else
    log "Done. Add this VPS in the central panel using Panel URL + Panel token."
  fi
  log "The installer did not modify system nginx, ports 80/443, or existing websites."
}

main "$@"
