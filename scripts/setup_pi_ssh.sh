#!/usr/bin/env bash
#
# One-time SSH key setup for password-free deploys to the Raspberry Pi.
#
# Creates an SSH key if you don't have one, installs it on the Pi, and verifies
# that key auth works. After this, scripts/deploy_pi.sh does not ask for a password.
#
# Usage:
#   ./scripts/setup_pi_ssh.sh
#   PI_HOST=192.168.1.50 PI_USER=pi ./scripts/setup_pi_ssh.sh
#   SSH_KEY=~/.ssh/jirai-deploy PI_HOST=192.168.1.50 PI_USER=pi ./scripts/setup_pi_ssh.sh
#
set -euo pipefail

PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_USER="${PI_USER:-pi}"
PI="${PI_USER}@${PI_HOST}"
KEY="${SSH_KEY:-${HOME}/.ssh/jirai-deploy}"

info() { printf '\033[1;36m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

usage() {
  sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $arg (use --help)" ;;
  esac
done

# 1) Create a key if none exists (no passphrase, fixed path — no prompts)
if [ -f "$KEY" ]; then
  ok "SSH key already exists at $KEY"
else
  info "Creating an SSH key at $KEY"
  ssh-keygen -t ed25519 -C "jirai-deploy" -f "$KEY" -N ""
  ok "Key created"
fi

# 2) Already working?
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'true' 2>/dev/null; then
  ok "Key auth to $PI already works — nothing to do"
  exit 0
fi

# 3) Install the key on the Pi (this is the ONE time it asks for the password)
info "Installing the key on $PI (enter the Pi password once when prompted)"
ssh-copy-id -i "${KEY}.pub" "$PI" || die "ssh-copy-id failed. Is the Pi reachable? Try: ping $PI_HOST"

# 4) Verify
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'echo ok' >/dev/null 2>&1; then
  ARCH="$(ssh -o BatchMode=yes "$PI" 'uname -m')"
  ok "Password-free SSH works. Pi architecture: $ARCH"
  [ "$ARCH" = "aarch64" ] || printf '\033[1;33m! Pi is %s, not aarch64 — the arm64 image will not run.\033[0m\n' "$ARCH"
  echo "You can now run: ./scripts/deploy_pi.sh"
else
  die "Key installed but password-free SSH still fails. Check the Pi's ~/.ssh permissions."
fi
