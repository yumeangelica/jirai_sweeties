#!/usr/bin/env bash
#
# Create an off-device snapshot of the Raspberry Pi's complete data directory.
# The remote Discord bot is stopped while SQLite files are copied. A verified
# snapshot can optionally replace the local data directory.
#
# Usage:
#   ./scripts/backup_pi_data.sh
#   ./scripts/backup_pi_data.sh --update-local
#   ./scripts/backup_pi_data.sh --update-local --leave-stopped
#
# Override defaults without editing this tracked file:
#   PI_HOST=192.168.1.50 PI_USER=pi ./scripts/backup_pi_data.sh --update-local
#   BACKUP_ROOT=/path/to/backups ./scripts/backup_pi_data.sh
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_USER="${PI_USER:-pi}"
PI_CONTAINER="${PI_CONTAINER:-discord-bot}"
BACKUP_ROOT="${BACKUP_ROOT:-$REPO_DIR/backups}"
PI="${PI_USER}@${PI_HOST}"

UPDATE_LOCAL="no"
LEAVE_STOPPED="no"
REMOTE_WAS_RUNNING="no"
REMOTE_STOPPED_BY_US="no"
STAGING_DIR=""
LOCAL_NEW_DIR=""

usage() {
  sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

info() { printf '\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

safe_remove_dir() {
  local target="$1"

  [ -n "$target" ] || return 0
  case "$target" in
    "$BACKUP_ROOT"/.pi-data-*.partial.*|"$REPO_DIR"/.data-from-pi.*|"$REPO_DIR"/.data-before-pi-*)
      rm -rf -- "$target"
      ;;
    *)
      warn "Refusing to remove unexpected temporary path: $target"
      return 1
      ;;
  esac
}

restore_remote_state() {
  if [ "$REMOTE_STOPPED_BY_US" != "yes" ] || [ "$REMOTE_WAS_RUNNING" != "yes" ]; then
    return 0
  fi

  info "Restoring the Pi container to its original running state"
  if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker start '$PI_CONTAINER'" >/dev/null; then
    ok "Pi container restarted"
    return 0
  fi

  warn "Could not restart the Pi container. Run: ssh $PI 'docker start $PI_CONTAINER'"
  return 1
}

cleanup() {
  local exit_status=$?
  trap - EXIT

  if [ "$exit_status" -ne 0 ]; then
    safe_remove_dir "$STAGING_DIR" || true
    safe_remove_dir "$LOCAL_NEW_DIR" || true
  fi

  if [ "$REMOTE_STOPPED_BY_US" = "yes" ] && [ "$REMOTE_WAS_RUNNING" = "yes" ]; then
    if [ "$exit_status" -eq 0 ] && [ "$LEAVE_STOPPED" = "yes" ]; then
      warn "Pi container left stopped by request"
    elif ! restore_remote_state; then
      exit_status=1
    fi
  fi

  exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 130' INT TERM HUP

verify_databases() {
  local data_dir="$1"

  python3 - "$data_dir" <<'PY'
import sqlite3
import sys
from pathlib import Path

data_dir = Path(sys.argv[1]).resolve()
database_names = ("discord_db.sqlite", "store_db.sqlite")

for name in database_names:
    path = data_dir / name
    if not path.is_file():
        raise SystemExit(f"missing database: {path}")

    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchall()
    finally:
        connection.close()

    if result != [("ok",)]:
        raise SystemExit(f"integrity check failed for {path}: {result}")
    print(f"integrity ok: {name}")
PY
}

write_checksums() {
  local snapshot_dir="$1"

  python3 - "$snapshot_dir" <<'PY'
import hashlib
import sys
from pathlib import Path

snapshot_dir = Path(sys.argv[1]).resolve()
data_dir = snapshot_dir / "remote-data"
checksum_file = snapshot_dir / "SHA256SUMS"

with checksum_file.open("w", encoding="utf-8") as output:
    for path in sorted(item for item in data_dir.rglob("*") if item.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        output.write(f"{digest.hexdigest()}  {path.relative_to(snapshot_dir)}\n")
PY
}

compare_data_directories() {
  local snapshot_data="$1"
  local active_data="$2"

  python3 - "$snapshot_data" "$active_data" <<'PY'
import hashlib
import sys
from pathlib import Path

snapshot_data = Path(sys.argv[1]).resolve()
active_data = Path(sys.argv[2]).resolve()

snapshot_files = sorted(
    path.relative_to(snapshot_data)
    for path in snapshot_data.rglob("*")
    if path.is_file()
)
active_files = sorted(
    path.relative_to(active_data)
    for path in active_data.rglob("*")
    if path.is_file()
)
if active_files != snapshot_files:
    raise SystemExit(
        "file list mismatch after local update: "
        f"snapshot={snapshot_files}, active={active_files}"
    )

for relative_path in snapshot_files:
    expected = hashlib.sha256((snapshot_data / relative_path).read_bytes()).hexdigest()
    actual = hashlib.sha256((active_data / relative_path).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"checksum mismatch after local update: {relative_path}")
print(f"local snapshot matches all {len(snapshot_files)} transferred files")
PY
}

for arg in "$@"; do
  case "$arg" in
    --update-local) UPDATE_LOCAL="yes" ;;
    --leave-stopped) LEAVE_STOPPED="yes" ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $arg (use --help)" ;;
  esac
done

[[ "$PI_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || die "PI_CONTAINER contains unsupported characters"

for required_command in ssh tar mktemp python3; do
  command -v "$required_command" >/dev/null || die "$required_command not found"
done

if [ "$UPDATE_LOCAL" = "yes" ] && command -v docker >/dev/null; then
  LOCAL_CONTAINER_RUNNING="$(docker inspect -f '{{.State.Running}}' discord-bot 2>/dev/null || printf 'false')"
  [ "$LOCAL_CONTAINER_RUNNING" != "true" ] \
    || die "Local discord-bot container is running. Stop it before using --update-local."
fi

info "Preflight checks"
if ! SSH_PREFLIGHT_OUTPUT="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'true' 2>&1)"; then
  SSH_PREFLIGHT_ERROR="${SSH_PREFLIGHT_OUTPUT##*$'\n'}"
  [ -n "$SSH_PREFLIGHT_ERROR" ] || SSH_PREFLIGHT_ERROR="unknown SSH error"
  die "Cannot SSH to $PI non-interactively: $SSH_PREFLIGHT_ERROR"
fi
ok "SSH key authentication works"

if ! REMOTE_METADATA="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" "
  command -v docker >/dev/null || { printf '%s\n' 'docker command missing on Pi'; exit 11; }
  docker inspect '$PI_CONTAINER' >/dev/null 2>&1 || { printf '%s\n' 'container missing: $PI_CONTAINER'; exit 12; }
  REMOTE_IMAGE_VALUE=\$(docker inspect -f '{{.Config.Image}}' '$PI_CONTAINER')
  REMOTE_MOUNT_VALUE=\$(docker inspect -f '{{range .Mounts}}{{if eq .Destination \"/app/data\"}}{{.Type}}:{{.Source}}{{end}}{{end}}' '$PI_CONTAINER')
  test -n \"\$REMOTE_MOUNT_VALUE\" || { printf '%s\n' 'container has no mount at /app/data'; exit 13; }
  printf '%s\n%s\n' \"\$REMOTE_IMAGE_VALUE\" \"\$REMOTE_MOUNT_VALUE\"
" 2>&1)"; then
  REMOTE_PREFLIGHT_ERROR="${REMOTE_METADATA##*$'\n'}"
  [ -n "$REMOTE_PREFLIGHT_ERROR" ] || REMOTE_PREFLIGHT_ERROR="unknown remote preflight error"
  die "Pi preflight failed: $REMOTE_PREFLIGHT_ERROR"
fi
REMOTE_IMAGE="${REMOTE_METADATA%%$'\n'*}"
REMOTE_DATA_MOUNT="${REMOTE_METADATA#*$'\n'}"
[[ "$REMOTE_IMAGE" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] \
  || die "Pi container uses an unsupported image name: $REMOTE_IMAGE"
[ -n "$REMOTE_DATA_MOUNT" ] \
  || die "Pi container has no volume or bind mount at /app/data"

if ! REMOTE_PREFLIGHT_OUTPUT="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker run --rm --volumes-from '$PI_CONTAINER:ro' --entrypoint sh '$REMOTE_IMAGE' -c '
    test -f /app/data/discord_db.sqlite || { printf \"%s\\n\" \"database missing: /app/data/discord_db.sqlite\"; exit 13; }
    test -f /app/data/store_db.sqlite || { printf \"%s\\n\" \"database missing: /app/data/store_db.sqlite\"; exit 14; }
  '" 2>&1)"; then
  REMOTE_PREFLIGHT_ERROR="${REMOTE_PREFLIGHT_OUTPUT##*$'\n'}"
  [ -n "$REMOTE_PREFLIGHT_ERROR" ] || REMOTE_PREFLIGHT_ERROR="unknown container data error"
  die "Pi preflight failed: $REMOTE_PREFLIGHT_ERROR"
fi
ok "Pi container and both databases found ($REMOTE_DATA_MOUNT -> /app/data)"

REMOTE_RUNNING_VALUE="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker inspect -f '{{.State.Running}}' '$PI_CONTAINER' 2>/dev/null || printf 'false'")"
if [ "$REMOTE_RUNNING_VALUE" = "true" ]; then
  REMOTE_WAS_RUNNING="yes"
fi

mkdir -p "$BACKUP_ROOT"
BACKUP_ROOT="$(cd "$BACKUP_ROOT" && pwd)"
[ "$BACKUP_ROOT" != "/" ] || die "BACKUP_ROOT cannot be the filesystem root"
case "$BACKUP_ROOT/" in
  "$REPO_DIR/data/"*) die "BACKUP_ROOT cannot be inside the active local data directory" ;;
esac
SNAPSHOT_ID="$(date +%Y%m%d-%H%M%S)"
FINAL_BACKUP_DIR="$BACKUP_ROOT/pi-data-$SNAPSHOT_ID"
[ ! -e "$FINAL_BACKUP_DIR" ] || die "Backup already exists: $FINAL_BACKUP_DIR"
STAGING_DIR="$(mktemp -d "$BACKUP_ROOT/.pi-data-$SNAPSHOT_ID.partial.XXXXXX")"

if [ "$REMOTE_WAS_RUNNING" = "yes" ]; then
  info "Stopping the Pi container for a consistent SQLite snapshot"
  REMOTE_STOPPED_BY_US="yes"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker stop '$PI_CONTAINER'" >/dev/null
  ok "Pi container stopped"
else
  warn "Pi container was already stopped"
fi

info "Copying the complete Pi data directory"
mkdir "$STAGING_DIR/remote-data"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker run --rm --volumes-from '$PI_CONTAINER:ro' --entrypoint tar '$REMOTE_IMAGE' -C /app/data -cf - ." \
  | tar -C "$STAGING_DIR/remote-data" -xf -
ok "Pi data copied to staging"

info "Checking both SQLite databases"
verify_databases "$STAGING_DIR/remote-data"
write_checksums "$STAGING_DIR"
ok "SQLite integrity and checksums verified"

mv "$STAGING_DIR" "$FINAL_BACKUP_DIR"
STAGING_DIR=""
ok "Backup finalized: $FINAL_BACKUP_DIR"

if [ "$UPDATE_LOCAL" = "yes" ]; then
  info "Preparing the verified Pi snapshot as local data"
  [ ! -e "$REPO_DIR/data" ] || [ -d "$REPO_DIR/data" ] \
    || die "Local data path exists but is not a directory: $REPO_DIR/data"
  LOCAL_NEW_DIR="$(mktemp -d "$REPO_DIR/.data-from-pi.XXXXXX")"
  cp -a "$FINAL_BACKUP_DIR/remote-data/." "$LOCAL_NEW_DIR/"
  verify_databases "$LOCAL_NEW_DIR"
  compare_data_directories "$FINAL_BACKUP_DIR/remote-data" "$LOCAL_NEW_DIR"

  if [ -e "$REPO_DIR/data" ]; then
    cp -a "$REPO_DIR/data" "$FINAL_BACKUP_DIR/local-data-before-update"
    LOCAL_OLD_DIR="$REPO_DIR/.data-before-pi-$SNAPSHOT_ID"
    [ ! -e "$LOCAL_OLD_DIR" ] || die "Temporary local backup path already exists: $LOCAL_OLD_DIR"
    mv "$REPO_DIR/data" "$LOCAL_OLD_DIR"
    if mv "$LOCAL_NEW_DIR" "$REPO_DIR/data"; then
      LOCAL_NEW_DIR=""
      safe_remove_dir "$LOCAL_OLD_DIR"
    else
      mv "$LOCAL_OLD_DIR" "$REPO_DIR/data" || true
      die "Could not activate Pi data; the previous local data was restored"
    fi
  else
    mv "$LOCAL_NEW_DIR" "$REPO_DIR/data"
    LOCAL_NEW_DIR=""
  fi

  compare_data_directories "$FINAL_BACKUP_DIR/remote-data" "$REPO_DIR/data"
  ok "Local data now matches the verified Pi snapshot"
fi

if [ "$REMOTE_STOPPED_BY_US" = "yes" ] && [ "$REMOTE_WAS_RUNNING" = "yes" ]; then
  if [ "$LEAVE_STOPPED" = "yes" ]; then
    warn "Pi container left stopped by request"
    REMOTE_STOPPED_BY_US="no"
  elif restore_remote_state; then
    REMOTE_STOPPED_BY_US="no"
  else
    REMOTE_STOPPED_BY_US="no"
    die "Backup succeeded, but the Pi container could not be restarted"
  fi
fi

printf '\033[1;32m✓ Pi data backup complete\033[0m\n'
echo "  Snapshot: $FINAL_BACKUP_DIR"
if [ "$UPDATE_LOCAL" = "yes" ]; then
  echo "  Active local data: $REPO_DIR/data"
fi
