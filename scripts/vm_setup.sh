#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 VM (DigitalOcean or Vultr) for the FixOnce demo.
# Run as root on the VM:
#   curl -fsSL https://raw.githubusercontent.com/visheshgupta0404/FixOnce/<branch>/scripts/vm_setup.sh | BRANCH=<branch> bash
# Then put the keys in /opt/FixOnce/.env and run: cd /opt/FixOnce && docker compose up -d --build
set -euo pipefail
BRANCH="${BRANCH:-main}"
DIR=/opt/FixOnce

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# Firewall: SSH and the app only. (The compose file binds the shop to 127.0.0.1, because
# Docker-published ports skip ufw.)
if command -v ufw >/dev/null; then
  ufw allow OpenSSH
  ufw allow 8000/tcp
  ufw --force enable
fi

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH" && git -C "$DIR" checkout "$BRANCH" && git -C "$DIR" pull --ff-only
else
  git clone --branch "$BRANCH" https://github.com/visheshgupta0404/FixOnce.git "$DIR"
fi
[ -f "$DIR/.env" ] || { cp "$DIR/.env.example" "$DIR/.env"; chmod 600 "$DIR/.env"; }

echo
echo "Next: edit $DIR/.env (MEKO_API_KEY, MEKO_DATAPACK_ID, GEMINI_API_KEY), then"
echo "  cd $DIR && docker compose up -d --build"
echo "  docker compose exec backend python -m fixonce.seed   # only if the product datapack is not seeded yet"
echo "  FIXONCE_URL=http://localhost:8000 scripts/demo_smoke.sh"
