#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ $EUID -eq 0 ]] || { echo 'Запусти: sudo bash install.sh'; exit 1; }
# shellcheck source=/dev/null
source /etc/os-release
[[ $ID == ubuntu && ( $VERSION_ID == 22.04 || $VERSION_ID == 24.04 ) ]] || { echo 'Поддерживается Ubuntu 22.04/24.04 LTS'; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'Этот установщик рассчитан на x86_64'; exit 1; }
[[ ! -e /etc/yt-media-bot/config.json && ! -e /opt/yt-media-bot/bot.py ]] || { echo 'Установка уже существует. Для обновления используй scripts/update.sh'; exit 1; }
[[ -t 0 ]] || { echo 'Нужен интерактивный терминал'; exit 1; }
read -rp 'Домен для файлов (например media.example.com), DNS A уже указывает на сервер: ' domain
[[ $domain =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && $domain == *.* && $domain != *..* ]] || { echo 'Неверный домен'; exit 1; }
read -rp 'Email для HTTPS-сертификата: ' email
[[ $email == *@*.* && $email != -* && $email != *' '* ]] || { echo 'Неверный email'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv ca-certificates curl ffmpeg nginx certbot python3-certbot-nginx
for account in yt-media yt-media-proxy; do
  id "$account" &>/dev/null || useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$account"
done
install -d -m 0755 /opt/yt-media-bot /etc/yt-media-bot
install -d -o yt-media -g yt-media -m 0711 /var/lib/yt-media-bot
install -d -o yt-media -g yt-media -m 0700 /var/lib/yt-media-bot/{jobs,archive}
install -d -o yt-media -g yt-media -m 0755 /var/lib/yt-media-bot/public
install -m 0644 app/*.py /opt/yt-media-bot/
python3 -m venv /opt/yt-media-bot/yandex-venv
/opt/yt-media-bot/yandex-venv/bin/python -m pip install --disable-pip-version-check -r requirements-yandex.txt
/opt/yt-media-bot/yandex-venv/bin/python -c 'from yandex_music import Client; assert callable(Client.device_auth)'
install -d -m 0755 /opt/yt-media-bot/web
install -m 0644 web/index.html /opt/yt-media-bot/web/index.html
python3 scripts/download_tools.py
install -m 0755 scripts/vpn_setup.py /usr/local/sbin/yt-media-vpn-setup
install -m 0755 scripts/token_setup.py /usr/local/sbin/yt-media-token-setup
install -m 0755 scripts/setup.py /usr/local/sbin/yt-media-setup
python3 - "$domain" <<'PY'
import json,pathlib,sys
c=json.loads(pathlib.Path('config/config.example.json').read_text())
c.update(owner_id=None,public_base_url='https://'+sys.argv[1]+'/mp/')
p=pathlib.Path('/etc/yt-media-bot/config.json');p.write_text(json.dumps(c,indent=2)+'\n');p.chmod(0o644)
PY
[[ ! -e /etc/nginx/sites-available/yt-media ]] || { echo 'Конфигурация nginx yt-media уже существует'; exit 1; }
install -d -m 0755 /etc/nginx/snippets
install -m 0644 config/nginx-media.locations /etc/nginx/snippets/yt-media-locations.conf
python3 scripts/render_nginx.py "$domain" config/nginx.conf.template /etc/nginx/sites-available/yt-media
chmod 0644 /etc/nginx/sites-available/yt-media
ln -s /etc/nginx/sites-available/yt-media /etc/nginx/sites-enabled/yt-media
nginx -t
systemctl enable --now nginx
systemctl reload nginx
certbot --nginx -d "$domain" --email "$email" --agree-tos --non-interactive --redirect
install -m 0644 systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable yt-media-bot
echo 'yt-dlp, FFmpeg, Deno, Xray и службы установлены.'
echo 'Перехожу к мастеру сети и бота. Секреты вводятся со скрытым вводом.'
/usr/local/sbin/yt-media-setup
