#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/copper-counter"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root: sudo bash install_on_server.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl rsync

mkdir -p "$APP_DIR"
rsync -a --delete "$SRC_DIR/app/" "$APP_DIR/app/"
cp "$SRC_DIR/app/requirements.txt" "$APP_DIR/requirements.txt"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

touch "$APP_DIR/counter.db"
chown -R www-data:www-data "$APP_DIR"

cp "$SRC_DIR/copper-counter.service" /etc/systemd/system/copper-counter.service
systemctl daemon-reload
systemctl enable --now copper-counter.service

cp "$SRC_DIR/nginx-copper-counter.conf" /etc/nginx/sites-available/copper-counter.conf
ln -sf /etc/nginx/sites-available/copper-counter.conf /etc/nginx/sites-enabled/copper-counter.conf
nginx -t
systemctl reload nginx

echo "Deploy finished. Service status:"
systemctl --no-pager --full status copper-counter.service || true
echo
echo "Local health check:"
curl -sS http://127.0.0.1/health || true
echo
echo "Public test URL: http://106.54.200.6/health"
