#!/usr/bin/python3
"""Interactive ordered setup: optional subscription, network, API, token."""
import json, os, pathlib, subprocess, urllib.request, urllib.error

ROOT=pathlib.Path('/etc/yt-media-bot')
DROPIN=pathlib.Path('/etc/systemd/system/yt-media-bot.service.d/media-proxy.conf')

def direct_api_check():
    print('Подписка и проверка VPN-сервера пропущены. Проверяю прямой доступ к Telegram API…',flush=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('https://api.telegram.org/bot0:probe/getMe',timeout=20) as response:
            if response.status==200:return
    except urllib.error.HTTPError as error:
        if error.code in (400,401,403,404):
            print('Telegram API доступен. Теперь можно настроить бота.');return
    except Exception:pass
    raise SystemExit('STOP: прямой доступ к Telegram API не подтверждён. Токен бота не запрашивался. Выбери режим с подпиской и повтори мастер.')

def main():
    if os.geteuid()!=0:raise SystemExit('Запусти через sudo')
    os.umask(0o077)
    print('1 — Подписка → проверка VPN-соединения → Telegram API → бот')
    print('2 — Без подписки: пропустить подписку и проверку VPN-сервера → Telegram API напрямую → бот')
    mode=input('Режим [1]: ').strip() or '1'
    if mode not in ('1','2'):raise SystemExit('Неверный режим. Настройка остановлена.')
    cfg=json.loads((ROOT/'config.json').read_text())
    if mode=='1':
        # This command validates external HTTPS via Xray before Telegram API.
        subprocess.run(['/usr/local/sbin/yt-media-vpn-setup','--configure-only'],check=True)
        DROPIN.parent.mkdir(parents=True,exist_ok=True)
        DROPIN.write_text('[Unit]\nAfter=yt-media-proxy.service\nRequires=yt-media-proxy.service\n[Service]\nLoadCredential=proxy_url:/etc/yt-media-bot/proxy-url\n')
        DROPIN.chmod(0o644)
        subprocess.run(['systemctl','enable','yt-media-proxy'],check=True)
    else:
        direct_api_check()
        cfg['proxy_enabled']=False;cfg['proxy_scope']='none'
        target=ROOT/'config.json';tmp=ROOT/'.config-direct.tmp'
        tmp.write_text(json.dumps(cfg,indent=2)+'\n');tmp.chmod(0o644);tmp.replace(target)
        DROPIN.unlink(missing_ok=True)
        subprocess.run(['systemctl','disable','--now','yt-media-subscription.timer'],check=True)
        subprocess.run(['systemctl','disable','--now','yt-media-proxy'],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    # Token setup is reached only after the selected network path passed API checks.
    subprocess.run(['/usr/local/sbin/yt-media-token-setup'],check=True)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('\nОтменено.')
    except subprocess.CalledProcessError:raise SystemExit('STOP: предыдущий шаг не завершился. Следующие шаги не выполняются.')
