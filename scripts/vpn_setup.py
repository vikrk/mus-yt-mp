#!/usr/bin/python3
"""Private subscription input, Xray HTTP egress, and periodic refresh. Never prints URLs/keys."""
import sys,os,pathlib,json,secrets,getpass,warnings,urllib.request,urllib.parse,urllib.error,ipaddress,socket,subprocess,time,fcntl
sys.path.insert(0,'/opt/yt-media-bot')
from vless_parser import _maybe_b64_vless,vless_outbound
R=pathlib.Path('/etc/yt-media-bot');XRAY='/opt/yt-media-bot/xray'
class SetupError(Exception):pass

def atomic(path,text):
 p=path.with_name('.'+path.name+'-'+secrets.token_hex(6));fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
 os.replace(p,path)

def public_host(host):
 try:addresses={x[4][0] for x in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)}
 except Exception:raise SetupError('Не удалось определить адрес сервера подписки/узла.') from None
 if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise SetupError('Допускаются только внешние публичные адреса, не локальная сеть.')

def validate_url(url,allow_http=False):
 try:u=urllib.parse.urlsplit(url);port=u.port
 except Exception:raise SetupError('Некорректная ссылка подписки.') from None
 if u.scheme not in (('https','http') if allow_http else ('https',)) or not u.hostname or u.username or u.password:raise SetupError('Нужна HTTPS-ссылка подписки без user:password в адресе.')
 public_host(u.hostname)

class Redirect(urllib.request.HTTPRedirectHandler):
 def __init__(self,allow_http):self.allow_http=allow_http
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  validate_url(newurl,self.allow_http)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,allow_http=False):
 if url.startswith('vless://'):raw=url
 else:
  validate_url(url,allow_http)
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect(allow_http))
  req=urllib.request.Request(url,headers={'User-Agent':'v2rayN','Accept':'text/plain,*/*'})
  try:
   with op.open(req,timeout=30) as r:data=r.read(1024*1024+1)
  except Exception:raise SetupError('Не удалось загрузить подписку. Проверь адрес, доступность и сертификат; секретная ссылка не выводится.') from None
  if len(data)>1024*1024:raise SetupError('Подписка слишком большая.')
  raw=data.decode('utf-8','replace')
 raw=_maybe_b64_vless(raw)
 links=[]
 for line in raw.replace('\r','\n').splitlines():
  line=line.strip()
  if line.startswith('vless://') and line not in links:links.append(line)
 if not links:raise SetupError('Не найдены VLESS-узлы. Нужна обычная URI/base64-подписка 3x-ui, не ссылка панели, Clash YAML или страница входа.')
 out=[]
 for link in links[:30]:
  ob=vless_outbound(link,'node_'+str(len(out)+1))
  if not ob:continue
  host=ob['settings']['vnext'][0]['address'];public_host(host)
  out.append(ob)
 if not out:raise SetupError('Нет поддерживаемых защищённых VLESS узлов TLS/Reality. allowInsecure и открытый транспорт не используются.')
 return out

def build(out,proxy_url):
 p=urllib.parse.urlsplit(proxy_url);tags=[x['tag'] for x in out]
 cfg={'log':{'loglevel':'none'},'inbounds':[{'tag':'media-http','listen':'127.0.0.1','port':18189,'protocol':'http','settings':{'accounts':[{'user':p.username,'pass':p.password}]},'sniffing':{'enabled':False}}],'outbounds':out+[{'tag':'block','protocol':'blackhole'}], 'routing':{'domainStrategy':'AsIs','rules':[]}}
 if len(out)==1:cfg['routing']['rules']=[{'type':'field','inboundTag':['media-http'],'outboundTag':tags[0]}]
 else:
  cfg['observatory']={'subjectSelector':['node_'],'probeURL':'https://www.cloudflare.com/cdn-cgi/trace','probeInterval':'2m','enableConcurrency':True}
  cfg['routing']['balancers']=[{'tag':'media-balancer','selector':['node_'],'strategy':{'type':'leastPing'},'fallbackTag':tags[0]}]
  cfg['routing']['rules']=[{'type':'field','inboundTag':['media-http'],'balancerTag':'media-balancer'}]
 return cfg

def apply(url,allow_http=False):
 out=fetch(url,allow_http)
 proxy_path=R/'proxy-url'
 proxy_url=proxy_path.read_text().strip() if proxy_path.exists() else 'http://media:'+secrets.token_urlsafe(32)+'@127.0.0.1:18189'
 candidate=R/'.proxy-candidate.json';atomic(candidate,json.dumps(build(out,proxy_url)))
 try:
  r=subprocess.run([XRAY,'run','-test','-config',str(candidate)],capture_output=True,timeout=20)
  if r.returncode:raise SetupError('Xray отклонил параметры подписки. Старый маршрут не изменён; ключи не выводятся.')
  target=R/'proxy-config.json';changed=not target.exists() or candidate.read_bytes()!=target.read_bytes()
  if changed:candidate.replace(target)
  if not proxy_path.exists():atomic(proxy_path,proxy_url+'\n')
  if changed or subprocess.run(['systemctl','is-active','--quiet','yt-media-proxy'],check=False).returncode:
   subprocess.run(['systemctl','restart','yt-media-proxy'],check=True)
  c=json.loads((R/'config.json').read_text());c['proxy_enabled']=True;c['proxy_scope']='telegram';atomic(R/'config.json',json.dumps(c));(R/'config.json').chmod(0o644)
  return proxy_url,len(out)
 finally:candidate.unlink(missing_ok=True)

def test(proxy_url):
 print('[1/4] Проверяю запуск отдельной службы Xray...',flush=True)
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  if subprocess.run(['systemctl','is-active','--quiet','yt-media-proxy'],check=False).returncode==0:break
  time.sleep(1)
 else:raise SetupError('Отдельный Xray не запущен. Проверь yt-media-proxy; до Telegram API проверка не дошла.')
 print('[2/4] Проверяю локальный прокси 127.0.0.1:18189...',flush=True)
 try:
  with socket.create_connection(('127.0.0.1',18189),timeout=3):pass
 except Exception:raise SetupError('Локальный прокси не слушает порт; до Telegram API проверка не дошла.') from None
 op=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy_url,'http':proxy_url}))
 print('[3/4] Проверяю внешний HTTPS через туннель (до 75 секунд)...',flush=True)
 deadline=time.monotonic()+75;connected=False
 while time.monotonic()<deadline:
  try:
   with op.open('https://www.cloudflare.com/cdn-cgi/trace',timeout=6) as r:
    raw=r.read(16384).decode('utf-8','replace')
    if r.status==200:
     fields=dict(l.split('=',1) for l in raw.splitlines() if '=' in l)
     if fields.get('ip'):
      ip=ipaddress.ip_address(fields['ip'])
      print('Внешний выход через прокси: '+str(ip)+'; страна '+fields.get('loc','?')[:2],flush=True)
      connected=True;break
  except Exception:pass
  time.sleep(2)
 if not connected:raise SetupError('Xray работает локально, но внешний HTTPS через узел не проходит. Проверь параметры клиента/узла. Telegram API ещё не проверялся.')
 print('[4/4] Туннель работает. Теперь проверяю Telegram API...',flush=True)
 deadline=time.monotonic()+40
 while time.monotonic()<deadline:
  try:
   with op.open('https://api.telegram.org/bot0:probe/getMe',timeout=8) as r:
    print('Telegram API отвечает HTTP '+str(r.status)+'.',flush=True);return
  except urllib.error.HTTPError as e:
   if e.code in (400,401,403,404):
    print('Telegram API отвечает HTTP '+str(e.code)+' — связь есть, это проверка без настоящего токена.',flush=True);return
  except Exception:pass
  time.sleep(2)
 raise SetupError('Внешний HTTPS через туннель работает, но именно Telegram API не отвечает. Попробуй другой зарубежный узел/подписку; токен здесь ещё не проверялся.')

def main():
 if os.geteuid()!=0:raise SetupError('Запусти через sudo или под root.')
 os.umask(0o077);refresh='--refresh' in sys.argv;resume='--resume' in sys.argv;check='--check' in sys.argv
 if check:
  test((R/'proxy-url').read_text().strip())
  return
 with (R/'proxy-setup.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if refresh or resume:
   url=(R/'subscription-url').read_text().strip();allow_http=(R/'subscription-http-approved').exists()
  else:
   with warnings.catch_warnings():
    warnings.simplefilter('error',getpass.GetPassWarning)
    try:url=getpass.getpass('Подписка 3x-ui или VLESS-ссылка (ввод скрыт): ').strip()
    except (getpass.GetPassWarning,EOFError):raise SetupError('Нет скрытого ввода. Подключись в Termius с TTY.') from None
   if not url:raise SetupError('Пустая подписка не сохранена.')
   allow_http=False
   if url.startswith('http://'):
    print('Внимание: HTTP передаст секретную подписку без TLS. Лучше HTTPS. Для явного разрешения введи ALLOW_HTTP.')
    allow_http=input('Подтверждение: ').strip()=='ALLOW_HTTP'
    if not allow_http:raise SetupError('HTTP не разрешён. Ничего не сохранено.')
  proxy_url,count=apply(url,allow_http)
  if not refresh and not resume and not check:
   atomic(R/'subscription-url',url+'\n')
   if allow_http:atomic(R/'subscription-http-approved','Explicit owner approval\n')
   else:(R/'subscription-http-approved').unlink(missing_ok=True)
  test(proxy_url)
  print('Подписка настроена. Защищённых VLESS-узлов:',count,'Telegram через локальный прокси доступен.')
  if not refresh and not check:
   subprocess.run(['systemctl','enable','--now','yt-media-subscription.timer'],check=True,capture_output=True)
   if '--configure-only' in sys.argv:return
   if not (R/'telegram-token').exists():
    subprocess.run(['/usr/local/sbin/yt-media-token-setup'],check=True)
   else:
    subprocess.run(['systemctl','restart','yt-media-bot'],check=True)
    print('Бот перезапущен с сохранённым токеном. Открой его в Telegram и нажми Start.')
if __name__=='__main__':
 try:main()
 except SetupError as e:print('STOP:',e);sys.exit(1)
 except KeyboardInterrupt:print('\nОтменено. Секреты в вывод не попали.');sys.exit(1)
 except Exception:print('STOP: ошибка настройки; значения подписки и токена не выводятся.');sys.exit(1)
