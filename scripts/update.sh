#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
[[ $EUID -eq 0 ]] || { echo 'Запусти через sudo'; exit 1; }
[[ -e /etc/yt-media-bot/config.json ]] || { echo 'Сначала install.sh'; exit 1; }
PYTHONPATH=app python3 -m unittest discover -s tests -v
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/var/backups/yt-media-$stamp"
install -d -m 0700 "$backup"
cp -a /opt/yt-media-bot "$backup/app"
cp -a /etc/systemd/system/yt-media-*.service /etc/systemd/system/yt-media-subscription.timer "$backup/"
if [[ -d /etc/systemd/system/yt-media-bot.service.d ]]; then
  cp -a /etc/systemd/system/yt-media-bot.service.d "$backup/"
fi
cp -a /usr/local/sbin/yt-media-{vpn,token}-setup /usr/local/sbin/yt-media-setup "$backup/"
cp -a /etc/nginx/sites-available/yt-media "$backup/nginx.conf"
if [[ -f /etc/nginx/snippets/yt-media-locations.conf ]]; then
  cp -a /etc/nginx/snippets/yt-media-locations.conf "$backup/nginx-locations.conf"
fi
python3 scripts/upgrade_nginx.py /etc/nginx/sites-available/yt-media "$backup/nginx-candidate.conf"
apt-get update
apt-get install -y python3-venv
python3 -m venv /opt/yt-media-bot/yandex-venv
/opt/yt-media-bot/yandex-venv/bin/python -m pip install --disable-pip-version-check -r requirements-yandex.txt
/opt/yt-media-bot/yandex-venv/bin/python -c 'from yandex_music import Client; assert callable(Client.device_auth)'
# Dependencies are updated only when explicitly requested.
if [[ ${1:-} == --tools ]]; then python3 scripts/download_tools.py; fi
systemctl stop yt-media-bot
install -m 0644 app/*.py /opt/yt-media-bot/
install -d -m 0755 /opt/yt-media-bot/web /etc/nginx/snippets
install -m 0644 web/index.html /opt/yt-media-bot/web/index.html
install -m 0644 config/nginx-media.locations /etc/nginx/snippets/yt-media-locations.conf
install -m 0644 "$backup/nginx-candidate.conf" /etc/nginx/sites-available/yt-media
if ! nginx -t; then
  cp -a "$backup/nginx.conf" /etc/nginx/sites-available/yt-media
  if [[ -f $backup/nginx-locations.conf ]]; then
    cp -a "$backup/nginx-locations.conf" /etc/nginx/snippets/yt-media-locations.conf
  fi
  echo "Ошибка nginx. Конфигурация восстановлена; бот остановлен. Резервная копия: $backup"
  exit 1
fi
systemctl reload nginx
install -m 0755 scripts/vpn_setup.py /usr/local/sbin/yt-media-vpn-setup
install -m 0755 scripts/token_setup.py /usr/local/sbin/yt-media-token-setup
install -m 0755 scripts/setup.py /usr/local/sbin/yt-media-setup
install -m 0644 systemd/* /etc/systemd/system/
systemctl daemon-reload
if python3 -c 'import json; raise SystemExit(not json.load(open("/etc/yt-media-bot/config.json")).get("proxy_enabled"))'; then
  systemctl restart yt-media-proxy
fi
systemctl start yt-media-bot
systemctl is-active yt-media-bot
echo "Резервная копия кода и служб: $backup"
