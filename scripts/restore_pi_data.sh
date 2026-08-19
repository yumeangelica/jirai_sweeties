#!/usr/bin/env bash
#
# Restore a verified Pi data snapshot into a new, stopped discord-bot container.
# The container's /app/data mount must be empty; existing data is never replaced.
#
# Usage:
#   ./scripts/restore_pi_data.sh backups/pi-data-YYYYMMDD-HHMMSS
#   ./scripts/restore_pi_data.sh backups/pi-data-YYYYMMDD-HHMMSS --start
#
# Override connection defaults without editing this tracked file:
#   PI_HOST=192.168.1.50 PI_USER=pi ./scripts/restore_pi_data.sh <snapshot> --start
#
set -Eeuo pipefail

PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_USER="${PI_USER:-pi}"
PI_CONTAINER="${PI_CONTAINER:-discord-bot}"
PI="${PI_USER}@${PI_HOST}"

SNAPSHOT_INPUT=""
SNAPSHOT_DIR=""
START_AFTER="no"
REMOTE_IMAGE=""
RESTORE_STARTED="no"

usage() {
  sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

info() { printf '\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

verify_databases() {
  local data_dir="$1"

  python3 - "$data_dir" <<'PY'
import sqlite3
import sys
from pathlib import Path

data_dir = Path(sys.argv[1]).resolve()
for name in ("discord_db.sqlite", "store_db.sqlite"):
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

clear_partial_restore() {
  [ -n "$REMOTE_IMAGE" ] || return 1
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker run --rm --volumes-from '$PI_CONTAINER' --entrypoint python '$REMOTE_IMAGE' -c '
import shutil
from pathlib import Path
root = Path(\"/app/data\")
for path in root.iterdir():
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
'" >/dev/null
}

cleanup() {
  local exit_status=$?
  trap - EXIT

  if [ "$exit_status" -ne 0 ] && [ "$RESTORE_STARTED" = "yes" ]; then
    warn "Restore failed; removing the partial files from the previously empty Pi data mount"
    if clear_partial_restore; then
      ok "Partial Pi restore removed; container remains stopped"
    else
      warn "Could not clean the partial restore. Keep $PI_CONTAINER stopped and inspect /app/data before retrying."
    fi
  fi

  exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 130' INT TERM HUP

for arg in "$@"; do
  case "$arg" in
    --start) START_AFTER="yes" ;;
    -h|--help) usage; exit 0 ;;
    --*) die "Unknown option: $arg (use --help)" ;;
    *)
      [ -z "$SNAPSHOT_INPUT" ] || die "Provide exactly one snapshot directory"
      SNAPSHOT_INPUT="$arg"
      ;;
  esac
done

[ -n "$SNAPSHOT_INPUT" ] || die "Snapshot directory required (use --help)"
[[ "$PI_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || die "PI_CONTAINER contains unsupported characters"

for required_command in ssh tar python3 shasum; do
  command -v "$required_command" >/dev/null || die "$required_command not found"
done

[ -d "$SNAPSHOT_INPUT" ] || die "Snapshot directory not found: $SNAPSHOT_INPUT"
SNAPSHOT_DIR="$(cd "$SNAPSHOT_INPUT" && pwd)"
[ -d "$SNAPSHOT_DIR/remote-data" ] || die "Snapshot remote-data directory missing: $SNAPSHOT_DIR"
[ -f "$SNAPSHOT_DIR/SHA256SUMS" ] || die "Snapshot checksum manifest missing: $SNAPSHOT_DIR/SHA256SUMS"

info "Checking the local snapshot before contacting the Pi"
(cd "$SNAPSHOT_DIR" && shasum -a 256 -c SHA256SUMS)
verify_databases "$SNAPSHOT_DIR/remote-data"
ok "Local snapshot checksums and SQLite integrity verified"

info "Checking the new Pi container"
if ! SSH_PREFLIGHT_OUTPUT="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'true' 2>&1)"; then
  SSH_PREFLIGHT_ERROR="${SSH_PREFLIGHT_OUTPUT##*$'\n'}"
  [ -n "$SSH_PREFLIGHT_ERROR" ] || SSH_PREFLIGHT_ERROR="unknown SSH error"
  die "Cannot SSH to $PI non-interactively: $SSH_PREFLIGHT_ERROR"
fi

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
[ -n "$REMOTE_DATA_MOUNT" ] || die "Pi container has no volume or bind mount at /app/data"

REMOTE_RUNNING_VALUE="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker inspect -f '{{.State.Running}}' '$PI_CONTAINER'")"
[ "$REMOTE_RUNNING_VALUE" = "false" ] \
  || die "Pi container must be stopped before restore: ssh $PI 'docker stop $PI_CONTAINER'"

REMOTE_ENTRY_COUNT="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker run --rm --volumes-from '$PI_CONTAINER:ro' --entrypoint python '$REMOTE_IMAGE' -c '
from pathlib import Path
print(sum(1 for _ in Path(\"/app/data\").iterdir()))
'")"
[ "$REMOTE_ENTRY_COUNT" = "0" ] \
  || die "Pi /app/data is not empty ($REMOTE_ENTRY_COUNT entries). Back it up; this restore script never overwrites existing data."
ok "Stopped container has an empty data mount ($REMOTE_DATA_MOUNT -> /app/data)"

info "Restoring the snapshot into the Pi data mount"
RESTORE_STARTED="yes"
tar -C "$SNAPSHOT_DIR/remote-data" -cf - . \
  | ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker run --rm -i --volumes-from '$PI_CONTAINER' --entrypoint tar '$REMOTE_IMAGE' -C /app/data -xf -"

info "Checking both restored databases on the Pi"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
  "docker run --rm -i --volumes-from '$PI_CONTAINER:ro' --entrypoint python '$REMOTE_IMAGE' -" <<'PY'
import sqlite3
from pathlib import Path

for name in ("discord_db.sqlite", "store_db.sqlite"):
    path = Path("/app/data") / name
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchall()
    finally:
        connection.close()
    if result != [("ok",)]:
        raise SystemExit(f"integrity check failed for {path}: {result}")
    print(f"integrity ok: {name}")
PY
RESTORE_STARTED="no"
ok "Pi snapshot restored and verified"

if [ "$START_AFTER" = "yes" ]; then
  info "Starting the restored Pi container"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" "docker start '$PI_CONTAINER'" >/dev/null
  REMOTE_RUNNING_VALUE="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "docker inspect -f '{{.State.Running}}' '$PI_CONTAINER'")"
  [ "$REMOTE_RUNNING_VALUE" = "true" ] || die "Data is restored, but the Pi container did not start"
  ok "Pi container started"
else
  warn "Pi container left stopped; start it after reviewing the restore"
fi

printf '\033[1;32m✓ Pi data restore complete\033[0m\n'
echo "  Snapshot: $SNAPSHOT_DIR"
echo "  Target: $PI ($REMOTE_DATA_MOUNT -> /app/data)"
