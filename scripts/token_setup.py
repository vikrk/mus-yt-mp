#!/usr/bin/python3
"""Validate the bot, discover its owner from a fresh private /start, then save."""
import getpass,json,os,pathlib,re,secrets,subprocess,time,urllib.request,urllib.error,warnings
ROOT=pathlib.Path('/etc/yt-media-bot')
STATE=pathlib.Path('/var/lib/yt-media-bot')

def owner_from_update(update,started):
    message=update.get('message',{})
    user=message.get('from',{});chat=message.get('chat',{})
    uid=user.get('id');date=message.get('date')
    text=message.get('text','')
    if type(uid) is not int or uid<=0 or user.get('is_bot') or chat.get('type')!='private' or chat.get('id')!=uid:return None
    if type(date) is not int or date<started or not isinstance(text,str) or text.strip()!='/start':return None
    return {'id':uid,'username':user.get('username',''),'first_name':user.get('first_name','')}

def discover_owner(api,username,wait_seconds=300):
    # Acknowledge the old queue before asking the installer to send a fresh /start.
    previous=api('getUpdates',{'offset':-1,'timeout':0,'allowed_updates':['message']})
    offset=max((u['update_id']+1 for u in previous),default=0)
    started=int(time.time())
    print('Открой https://t.me/'+username+' и отправь /start в личном чате.')
    print('ID владельца определится автоматически. Ожидаю до 5 минут…',flush=True)
    deadline=time.monotonic()+wait_seconds
    while time.monotonic()<deadline:
        updates=api('getUpdates',{'offset':offset,'timeout':20,'allowed_updates':['message']})
        for update in updates:
            offset=max(offset,update['update_id']+1)
            owner=owner_from_update(update,started)
            if owner is None:continue
            # JSON escapes terminal control sequences in user-controlled profile fields.
            print('Найден пользователь:',json.dumps(owner,ensure_ascii=True))
            if input('Это ваш аккаунт и владелец бота? Введи YES: ').strip()=='YES':return owner['id']
            print('Пользователь не назначен. Отправь /start с нужного аккаунта.',flush=True)
    raise SystemExit('Время ожидания /start истекло. ID и токен не сохранены. Повтори мастер установки.')

def atomic(path,text,mode):
    tmp=path.with_name('.'+path.name+'-'+secrets.token_hex(8))
    fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,mode)
    try:
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
        tmp.chmod(mode)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def main():
    if os.geteuid()!=0:raise SystemExit('Запусти через sudo или под root.')
    os.umask(0o077)
    cfg=json.loads((ROOT/'config.json').read_text());proxy_url=None
    if cfg.get('proxy_enabled'):
        if not (ROOT/'proxy-url').exists():raise SystemExit('Сначала настрой сеть: sudo /usr/local/sbin/yt-media-setup')
        proxy_url=(ROOT/'proxy-url').read_text().strip()
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try:token=getpass.getpass('Токен бота от BotFather (ввод скрыт): ').strip()
        except (getpass.GetPassWarning,EOFError):raise SystemExit('Нет терминала со скрытым вводом. Подключись по SSH с TTY.')
    if not re.fullmatch(r'\d{5,16}:[A-Za-z0-9_-]{25,80}',token):raise SystemExit('Неверный формат токена. Ничего не сохранено.')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy_url,'http':proxy_url} if proxy_url else {}))
    def api(method,data=None):
        req=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=json.dumps(data or {}).encode(),headers={'Content-Type':'application/json'})
        try:
            with opener.open(req,timeout=35) as response:result=json.load(response)
        except urllib.error.HTTPError as error:raise SystemExit('Telegram HTTP '+str(error.code)+'. Настройка остановлена; токен не сохранён.') from None
        except Exception:raise SystemExit('Нет связи с Telegram. Настройка остановлена; токен не сохранён.') from None
        if not result.get('ok'):raise SystemExit('Telegram отклонил запрос. Ничего не сохранено.')
        return result['result']
    me=api('getMe');webhook=api('getWebhookInfo')
    if webhook.get('url'):raise SystemExit('У бота уже есть webhook. Настройка остановлена.')
    print('Проверен бот: @'+me['username'])
    subprocess.run(['systemctl','stop','yt-media-bot.service'],check=True)
    owner_id=discover_owner(api,me['username'])
    cfg['owner_id']=owner_id
    atomic(ROOT/'config.json',json.dumps(cfg,indent=2)+'\n',0o644)
    atomic(ROOT/'telegram-token',token+'\n',0o600)
    (STATE/'offset').unlink(missing_ok=True)
    subprocess.run(['systemctl','restart','yt-media-bot.service'],check=True)
    subprocess.run(['systemctl','is-active','yt-media-bot.service'],check=True)
    print('Владелец подтверждён, бот запущен. Отправь ему ссылку YouTube.')

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('\nОтменено. Повтори мастер для завершения настройки.')
