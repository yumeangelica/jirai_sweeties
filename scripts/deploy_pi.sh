#!/usr/bin/env bash
#
# Build the arm64 image on this Mac and deploy it to Raspberry Pi.
# The safe default keeps both databases. Existing Pi data is snapshotted to
# this Mac before the remote container is replaced.
#
# Usage:
#   ./scripts/deploy_pi.sh
#   ./scripts/deploy_pi.sh --keep-db --logs
#   ./scripts/deploy_pi.sh --replace-db
#   ./scripts/deploy_pi.sh --fresh-db
#
# Override connection defaults without editing this tracked file:
#   PI_HOST=192.168.1.50 PI_USER=pi ./scripts/deploy_pi.sh --logs
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_USER="${PI_USER:-pi}"
PI_DIR="${PI_DIR:-programs/jirai_sweeties}"
PI_CONTAINER="${PI_CONTAINER:-discord-bot}"
IMAGE="discord-bot:latest"
PI="${PI_USER}@${PI_HOST}"

DB_MODE="keep"
FOLLOW_LOGS="no"
REMOTE_CONTAINER_EXISTS="no"

usage() {
  sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

info() { printf '\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --keep-db) DB_MODE="keep" ;;
    --replace-db) DB_MODE="replace" ;;
    --fresh-db) DB_MODE="fresh" ;;
    --logs) FOLLOW_LOGS="yes" ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $arg (use --help)" ;;
  esac
done

[[ "$PI_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || die "PI_CONTAINER contains unsupported characters"
[[ "$PI_DIR" =~ ^[A-Za-z0-9._/-]+$ ]] \
  || die "PI_DIR contains unsupported characters"
case "/$PI_DIR/" in
  *"/../"*|*"/./"*) die "PI_DIR must not contain . or .. path segments" ;;
esac
case "$PI_DIR" in
  /*) die "PI_DIR must be relative to the Pi user's home" ;;
esac

cd "$REPO_DIR"

info "Preflight checks"
for required_command in docker ssh scp gzip tar python3; do
  command -v "$required_command" >/dev/null || die "$required_command not found"
done
docker info >/dev/null 2>&1 || die "Docker daemon is not running"
docker buildx version >/dev/null 2>&1 || die "docker buildx is not available"

for required_file in \
  .env \
  docker-compose.yml \
  bot/config/settings.json \
  bot/config/welcome_messages.txt \
  store_data_extractor/config/stores.json \
  store_data_extractor/config/user_agents.txt; do
  [ -f "$required_file" ] || die "Required local file missing: $REPO_DIR/$required_file"
done

if [ "$DB_MODE" = "replace" ]; then
  [ -f data/store_db.sqlite ] || die "data/store_db.sqlite is missing"
  LOCAL_CONTAINER_RUNNING="$(docker inspect -f '{{.State.Running}}' "$PI_CONTAINER" 2>/dev/null || printf false)"
  [ "$LOCAL_CONTAINER_RUNNING" != "true" ] \
    || die "Local $PI_CONTAINER container is running. Stop it before using --replace-db."
  python3 - "$REPO_DIR/data/store_db.sqlite" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA integrity_check").fetchall()
finally:
    connection.close()
if result != [("ok",)]:
    raise SystemExit(f"local store database integrity check failed: {result}")
print("local store database integrity ok")
PY
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'true' >/dev/null 2>&1; then
  die "Cannot SSH to $PI without a password. Run scripts/setup_pi_ssh.sh first."
fi
ok "SSH key authentication works"

ARCH="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'uname -m')"
[ "$ARCH" = "aarch64" ] || die "Pi reports '$ARCH'; this image requires aarch64"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  'command -v docker >/dev/null && docker compose version >/dev/null 2>&1' \
  || die "Docker Engine or Docker Compose is missing on the Pi"

REMOTE_PROJECT_DIR="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "mkdir -p \"\$HOME/$PI_DIR\" && cd \"\$HOME/$PI_DIR\" && pwd")"
[ -n "$REMOTE_PROJECT_DIR" ] || die "Could not resolve the Pi project directory"
ok "Pi is aarch64 and project path is $REMOTE_PROJECT_DIR"

if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker inspect '$PI_CONTAINER' >/dev/null 2>&1"; then
  REMOTE_CONTAINER_EXISTS="yes"

  info "Creating a verified off-device snapshot before deploy"
  PI_HOST="$PI_HOST" PI_USER="$PI_USER" PI_CONTAINER="$PI_CONTAINER" \
    "$SCRIPT_DIR/backup_pi_data.sh"
  ok "Pre-deploy Pi snapshot is safe on this Mac"

  REMOTE_MOUNT_METADATA="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker inspect -f '{{range .Mounts}}{{if eq .Destination \"/app/data\"}}{{println .Type}}{{println .Source}}{{end}}{{end}}' '$PI_CONTAINER'")"
  REMOTE_MOUNT_TYPE="${REMOTE_MOUNT_METADATA%%$'\n'*}"
  REMOTE_MOUNT_SOURCE="${REMOTE_MOUNT_METADATA#*$'\n'}"
  REMOTE_MOUNT_SOURCE="${REMOTE_MOUNT_SOURCE%$'\n'}"
  EXPECTED_MOUNT_SOURCE="$REMOTE_PROJECT_DIR/data"

  if [ "$REMOTE_MOUNT_TYPE" != "bind" ] || [ "$REMOTE_MOUNT_SOURCE" != "$EXPECTED_MOUNT_SOURCE" ]; then
    die "Refusing deploy: current /app/data is $REMOTE_MOUNT_TYPE:$REMOTE_MOUNT_SOURCE, but Compose would use bind:$EXPECTED_MOUNT_SOURCE. Follow docs/raspberry-pi-runbook.md to restore or migrate without changing data sources implicitly."
  fi
  ok "Existing container uses the canonical data bind mount"
elif [ "$DB_MODE" = "keep" ]; then
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "test -f '$REMOTE_PROJECT_DIR/data/discord_db.sqlite' && test -f '$REMOTE_PROJECT_DIR/data/store_db.sqlite'"; then
    die "No existing Pi databases were found. After a reinstall, follow docs/raspberry-pi-runbook.md and restore a snapshot before deploy. Use --fresh-db only for an intentionally empty installation."
  fi
  ok "Both existing Pi databases found in the canonical data directory"
fi

info "Building the linux/arm64 image"
docker buildx build --platform linux/arm64 -t "$IMAGE" --load .
ok "Image built: $IMAGE"

ARCHIVE_PATH="$REPO_DIR/discord-bot.tar.gz"
info "Saving and copying the image, Compose file, and environment"
docker save "$IMAGE" | gzip > "$ARCHIVE_PATH"
scp -q "$ARCHIVE_PATH" docker-compose.yml .env "$PI:$REMOTE_PROJECT_DIR/"
ok "Deployment files copied"

info "Loading the new image on the Pi"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" "
  set -eu
  cd '$REMOTE_PROJECT_DIR'
  chmod 600 .env
  gunzip -f discord-bot.tar.gz
  docker image load -i discord-bot.tar
  rm -f discord-bot.tar
"
ok "New image loaded"

if [ "$REMOTE_CONTAINER_EXISTS" = "yes" ]; then
  info "Stopping the old container"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "cd '$REMOTE_PROJECT_DIR' && docker compose down"

  REMOTE_BACKUP_NAME="data.backup.$(date +%Y%m%d-%H%M%S)"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" "
    set -eu
    cd '$REMOTE_PROJECT_DIR'
    cp -a data '$REMOTE_BACKUP_NAME'
  "
  ok "On-Pi rollback copy created: $REMOTE_PROJECT_DIR/$REMOTE_BACKUP_NAME"
fi

case "$DB_MODE" in
  keep)
    ok "Keeping both Pi databases"
    ;;
  replace)
    info "Replacing only store_db.sqlite with the verified local database"
    STORE_FILES=(store_db.sqlite)
    [ ! -f data/store_db.sqlite-wal ] || STORE_FILES+=(store_db.sqlite-wal)
    [ ! -f data/store_db.sqlite-shm ] || STORE_FILES+=(store_db.sqlite-shm)
    REMOTE_STORE_STAGE=".store-db-from-mac.$(date +%Y%m%d-%H%M%S)"
    tar -C data -cf - "${STORE_FILES[@]}" \
      | ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" "
          set -eu
          cd '$REMOTE_PROJECT_DIR'
          mkdir '$REMOTE_STORE_STAGE'
          tar -C '$REMOTE_STORE_STAGE' -xf -
          rm -f data/store_db.sqlite data/store_db.sqlite-wal data/store_db.sqlite-shm
          cp -a '$REMOTE_STORE_STAGE'/\. data/
          rm -rf '$REMOTE_STORE_STAGE'
        "
    ok "Pi store database replaced; Discord database kept"
    ;;
  fresh)
    warn "Removing the Pi store database by explicit request"
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
      "cd '$REMOTE_PROJECT_DIR' && rm -f data/store_db.sqlite data/store_db.sqlite-wal data/store_db.sqlite-shm"
    ;;
esac

info "Starting the new container"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "cd '$REMOTE_PROJECT_DIR' && docker compose up -d --no-build --pull never"
sleep 3
REMOTE_RUNNING="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker inspect -f '{{.State.Running}}' '$PI_CONTAINER' 2>/dev/null || printf false")"
if [ "$REMOTE_RUNNING" != "true" ]; then
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker logs --tail 100 '$PI_CONTAINER' 2>&1 || true" >&2
  die "The new Pi container is not running"
fi
ok "Pi container is running"

printf '\033[1;32m✓ Deployment complete\033[0m\n'
echo "  Target: $PI:$REMOTE_PROJECT_DIR"
echo "  Logs: ssh $PI 'docker logs -f $PI_CONTAINER'"

if [ "$FOLLOW_LOGS" = "yes" ]; then
  info "Following logs (Ctrl-C stops log viewing, not the bot)"
  ssh -o BatchMode=yes "$PI" "docker logs -f '$PI_CONTAINER'"
fi
