"""Per-approved-user Yandex accounts; private MP3 delivery, no public links."""
import asyncio,json,os,pathlib,re,secrets,shutil,time,urllib.parse
class YandexInputError(ValueError):pass
HOSTS={'music.yandex.ru','music.yandex.com','music.yandex.by','music.yandex.kz','music.yandex.uz'}
def is_yandex_link(text):
 try:return (urllib.parse.urlsplit(text.strip()).hostname or '').lower() in HOSTS
 except (ValueError,AttributeError):return False
def parse_yandex(text):
 if not isinstance(text,str) or len(text)>2048 or any(c.isspace() for c in text.strip()):raise YandexInputError('Отправь одну ссылку на трек Яндекс.Музыки.')
 try:u=urllib.parse.urlsplit(text.strip());port=u.port
 except ValueError:raise YandexInputError('Некорректная ссылка.')
 if u.scheme!='https' or u.username or u.password or port not in (None,443) or (u.hostname or '').lower() not in HOSTS:raise YandexInputError('Нужна HTTPS-ссылка на трек Яндекс.Музыки.')
 path=u.path.rstrip('/');m=re.fullmatch(r'/album/(\d{1,16})/track/(\d{1,16})',path)
 if m:album,track=m.groups()
 else:
  m=re.fullmatch(r'/track/(\d{1,16})',path)
  if not m:raise YandexInputError('Пока поддерживаются ссылки на отдельные треки, не альбомы и плейлисты.')
  track=m.group(1);album=None
 return {'source':'yandex','track':track,'album':album,'url':'https://music.yandex.ru/'+('album/'+album+'/' if album else '')+'track/'+track}
class YandexTools:
 def init_yandex(self):
  self.yamp=self.state/'yamp';self.yamp.mkdir(exist_ok=True,mode=0o700);self.yamp.chmod(0o700)
  self.yandex_accounts=self.state/'yandex-accounts';self.yandex_accounts.mkdir(exist_ok=True,mode=0o700);self.yandex_accounts.chmod(0o700)
  self.yandex_auth_tasks={};self.yandex_auth_rate={};self.yandex_confirm={}
 def yandex_user_dir(self,uid,base):
  if not isinstance(uid,int) or isinstance(uid,bool) or uid<=0:raise YandexInputError('Некорректный пользователь.')
  path=base/str(uid)
  if path.is_symlink():raise YandexInputError('Небезопасная папка аккаунта.')
  path.mkdir(mode=0o700,exist_ok=True);path.chmod(0o700);return path
 def yandex_credential(self,uid):return self.yandex_user_dir(uid,self.yandex_accounts)/'token.json'
 def yandex_account(self,uid):
  if not self.allowed(uid):return None
  try:
   p=self.yandex_credential(uid)
   if p.is_symlink() or not p.is_file() or p.stat().st_mode&0o077:return None
   data=json.loads(p.read_text())
   if isinstance(data.get('access_token'),str) and len(data['access_token'])>=16 and data.get('expires_at',0)>time.time()+60 and isinstance(data.get('account_id'),str):return data['account_id']
  except Exception:pass
  return None
 def yandex_ready(self,uid):return self.yandex_account(uid) is not None
 async def yandex_status(self,uid):
  if not self.allowed(uid):await self.closed(uid);return
  ready=self.yandex_ready(uid);auth=uid in self.yandex_auth_tasks
  text=('Твой аккаунт Яндекс.Музыки подключён. Отправь ссылку на отдельный трек и выбери MP3 192 или 320 кбит/с.' if ready else 'Подключи свой аккаунт Яндекс.Музыки. Бот выдаст персональный код: подтверди вход на странице Яндекса. Пароль и токен в Telegram не отправляй.')
  if auth:text+='\nПодтверждение входа уже ожидается. Код отправлен только в этот чат.'
  text+='\n\nИспользуется только твой аккаунт. MP3 хранятся в твоей закрытой папке yamp, публичных ссылок нет. До 50 МБ — файл в Telegram; больше — только приватное хранение. Нужен доступ к треку в твоём аккаунте.'
  rows=[]
  if not ready and not auth:rows.append([{'text':'Подключить Яндекс.Музыку','callback_data':'ya:connect'}])
  if ready or auth:rows.append([{'text':'Отключить аккаунт / отменить вход','callback_data':'ya:disconnect'}])
  await self.send(text,{'inline_keyboard':rows},chat=uid)
 async def yandex_account_callback(self,uid,parts,message):
  if not self.allowed(uid):await self.closed(uid);return
  if parts==['ya','connect']:
   if self.yandex_ready(uid):await self.yandex_status(uid);return
   if uid in self.yandex_auth_tasks:await self.send('Вход уже ожидает подтверждения. Используй выданный тебе код.',chat=uid);return
   if len(self.yandex_auth_tasks)>=3:await self.send('Сейчас подтверждаются другие аккаунты. Попробуй через несколько минут.',chat=uid);return
   if time.time()-self.yandex_auth_rate.get(uid,0)<60:await self.send('Повторный вход доступен через минуту.',chat=uid);return
   self.yandex_auth_rate[uid]=time.time();task=asyncio.create_task(self.yandex_authorize(uid));self.yandex_auth_tasks[uid]=task
  elif parts==['ya','disconnect']:
   nonce=secrets.token_hex(8);self.yandex_confirm[uid]=(nonce,time.time())
   await self.send('Отключить твой аккаунт? Сохранённый токен будет удалён из бота, твои задачи Яндекса отменятся. Уже сохранённые MP3 останутся приватными. Доступ приложения можно также отозвать в Яндекс ID.',{'inline_keyboard':[[{'text':'Да, отключить','callback_data':'ya:confirm:'+nonce},{'text':'Не отключать','callback_data':'ya:keep:'+nonce}]]},chat=uid)
  elif len(parts)==3 and parts[1] in ('confirm','keep'):
   confirm=self.yandex_confirm.get(uid)
   if not confirm or confirm[0]!=parts[2] or time.time()-confirm[1]>300:return
   self.yandex_confirm.pop(uid,None)
   if parts[1]=='confirm':await self.yandex_disconnect(uid);await self.send('Твой аккаунт отключён. Авторизация удалена из бота. /yandex — подключиться снова.',chat=uid)
   else:await self.send('Аккаунт не отключён.',chat=uid)
   try:await self.call('editMessageReplyMarkup',{'chat_id':uid,'message_id':message['message_id'],'reply_markup':{'inline_keyboard':[]}})
   except Exception:pass
 async def yandex_disconnect(self,uid):
  task=self.yandex_auth_tasks.pop(uid,None)
  if task:
   task.cancel()
   try:await task
   except asyncio.CancelledError:pass
  self.yandex_credential(uid).unlink(missing_ok=True)
  self.yandex_confirm.pop(uid,None)
  self.pending={k:v for k,v in self.pending.items() if not(v.get('source')=='yandex' and v.get('user')==uid)}
  if self.active and self.active.get('source')=='yandex' and self.active.get('user')==uid:self.cancel.set()
  keep=[]
  while not self.queue.empty():
   job=self.queue.get_nowait();self.queue.task_done()
   if not(job.get('source')=='yandex' and job.get('user')==uid):keep.append(job)
  for job in keep:self.queue.put_nowait(job)
 async def yandex_authorize(self,uid):
  proc=None;mid=None;directory=self.yandex_user_dir(uid,self.yandex_accounts);nonce=secrets.token_hex(16);stage=directory/('auth-'+nonce+'.json')
  try:
   proc=await asyncio.create_subprocess_exec('/opt/yt-media-bot/yandex-venv/bin/python','/opt/yt-media-bot/yandex_user_auth.py','--output',str(stage),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=self.childenv)
   first=await asyncio.wait_for(proc.stdout.readline(),40);data=json.loads(first)
   if data.get('state')!='awaiting_user':raise YandexInputError('Авторизация пока недоступна. Попробуй позже через /yandex.')
   url=data.get('verification_url','');u=urllib.parse.urlsplit(url);code=data.get('user_code','')
   if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or not(u.hostname in ('oauth.yandex.ru','oauth.yandex.com') or (u.hostname=='ya.ru' and u.path=='/device')) or u.query or u.fragment or not re.fullmatch(r'[A-Za-z0-9-]{4,32}',code):raise YandexInputError('Не удалось проверить страницу подтверждения.')
   if not self.allowed(uid):return
   sent=await self.send('Подключение ТВОЕЙ Яндекс.Музыки:\n1. Открой '+url+'\n2. Введи код: '+code+'\n3. Проверь аккаунт и запрашиваемые разрешения, затем подтверди вход.\nКод действует до 5 минут. Не пересылай его другим. Пароль и токен сюда не отправляй.',{'inline_keyboard':[[{'text':'Открыть Яндекс','url':url},{'text':'Отменить вход','callback_data':'ya:disconnect'}]]},chat=uid)
   if not sent:raise YandexInputError('Не удалось доставить код. Повтори /yandex.')
   mid=sent.get('message_id');last=await asyncio.wait_for(proc.stdout.readline(),330);result=json.loads(last);rc=await asyncio.wait_for(proc.wait(),10)
   if rc or result.get('state')!='authorized' or not self.allowed(uid) or not stage.is_file() or stage.is_symlink():raise YandexInputError('Вход не завершён или время кода истекло. Повтори /yandex.')
   token=json.loads(stage.read_text())
   if not isinstance(token.get('access_token'),str) or len(token['access_token'])<16 or token.get('expires_at',0)<=time.time()+60:raise YandexInputError('Не удалось завершить авторизацию.')
   token['account_id']=nonce;stage.write_text(json.dumps(token));stage.chmod(0o600);stage.replace(self.yandex_credential(uid))
   await self.send('✅ Твой аккаунт Яндекс.Музыки подключён. Отправь ссылку на отдельный трек. MP3 придёт только тебе, без публичной ссылки. /yandex — состояние и отключение аккаунта.',chat=uid)
  except asyncio.CancelledError:raise
  except Exception:
   if self.allowed(uid):await self.send('Вход в Яндекс не завершён: код мог истечь или сервис недоступен. Повтори /yandex. Пароль и токен в чат не отправляй.',chat=uid)
  finally:
   if proc and proc.returncode is None:
    try:proc.terminate();await asyncio.wait_for(proc.wait(),3)
    except (ProcessLookupError,asyncio.TimeoutError):
     if proc.returncode is None:proc.kill();await proc.wait()
   stage.unlink(missing_ok=True)
   if mid:
    try:await self.call('deleteMessage',{'chat_id':uid,'message_id':mid})
    except Exception:pass
   if self.yandex_auth_tasks.get(uid) is asyncio.current_task():self.yandex_auth_tasks.pop(uid,None)
 async def yandex_prepare(self,uid,text):
  if not self.allowed(uid):await self.closed(uid);return
  if not self.yandex_ready(uid):await self.yandex_status(uid);return
  try:info=parse_yandex(text)
  except YandexInputError as e:await self.send(str(e),chat=uid);return
  self.pending={k:v for k,v in self.pending.items() if time.time()-v['created']<=900}
  if sum(1 for v in self.pending.values() if v['user']==uid)>=5 or len(self.pending)>=50:await self.send('Слишком много невыбранных ссылок. Выбери качество или отправь /cancel.',chat=uid);return
  key=secrets.token_hex(8);self.pending[key]={**info,'created':time.time(),'user':uid,'account_id':self.yandex_account(uid)}
  await self.send('Яндекс.Музыка → MP3. Выбери качество. Файл будет сохранён приватно и отправлен без ссылки.',{'inline_keyboard':[[{'text':'MP3 · 192 кбит/с','callback_data':'ym:'+key+':192'},{'text':'MP3 · 320 кбит/с','callback_data':'ym:'+key+':320'}]]},chat=uid)
 async def yandex_callback(self,uid,parts,message):
  if not self.allowed(uid):await self.closed(uid);return
  if len(parts)!=3 or parts[2] not in ('192','320'):return
  task=self.pending.get(parts[1])
  if not task or task.get('source')!='yandex' or task.get('user')!=uid or time.time()-task['created']>900:await self.send('Кнопки устарели. Отправь ссылку ещё раз.',chat=uid);return
  if not self.yandex_ready(uid):await self.yandex_status(uid);return
  if task.get('account_id')!=self.yandex_account(uid):await self.send('Аккаунт изменился. Отправь ссылку заново.',chat=uid);return
  if self.queue.full():await self.send('Очередь заполнена. Попробуй после завершения текущих задач.',chat=uid);return
  recent=[t for t in self.rate.get(uid,[]) if time.time()-t<3600]
  if uid!=self.owner and len(recent)>=3:await self.send('Лимит пользователя: 3 задачи в час.',chat=uid);return
  self.rate[uid]=recent+[time.time()]
  self.pending.pop(parts[1],None);job={**task,'format':'mp3','quality':parts[2]};await self.queue.put(job)
  try:await self.call('editMessageReplyMarkup',{'chat_id':uid,'message_id':message['message_id'],'reply_markup':{'inline_keyboard':[]}})
  except Exception:pass
  await self.send('Принято: Яндекс.Музыка · MP3 '+parts[2]+' кбит/с. Сохранение в закрытой папке yamp, без публикации. В Telegram отправляются файлы до 50 МБ.',chat=uid)
 def storage_used(self):
  return sum(p.stat().st_size for directory in (self.public,self.archive,self.yamp) if directory.is_dir() for p in directory.rglob('*') if p.is_file() and not p.is_symlink())
 def store_private_yandex(self,out,job,max_archive):
  size=out.stat().st_size
  if self.storage_used()+size>max_archive:raise YandexInputError('Общая квота хранилища заполнена. Старые файлы автоматически не удаляются.')
  if shutil.disk_usage(self.yamp).free<2*1024**3:raise YandexInputError('Недостаточно свободного места для сохранения.')
  directory=self.yandex_user_dir(job['user'],self.yamp)
  target=directory/('ym_'+job['track']+'_'+job['quality']+'k_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+secrets.token_hex(8)+'.mp3')
  out.chmod(0o600);out.replace(target);return target,size
 async def yandex_run_job(self,job,work):
  if not self.allowed(job['user']):raise YandexInputError('Доступ отозван.')
  if not self.yandex_ready(job['user']) or job.get('account_id')!=self.yandex_account(job['user']):raise YandexInputError('Твоя авторизация отсутствует, истекла или изменилась. Используй /yandex.')
  from bot import MAX_SINGLE,MAX_RESULT,FFMPEG
  if shutil.disk_usage(self.jobs).free<6*1024**3:raise YandexInputError('Недостаточно свободного места: нужен резерв 6 ГиБ.')
  args=['/opt/yt-media-bot/yandex-venv/bin/python','/opt/yt-media-bot/yandex_download.py','--credential',str(self.yandex_credential(job['user'])),'--track',job['track'],'--quality',job['quality']]
  if job.get('album'):args+=['--album',job['album']]
  raw=await self.run_cmd(args,work,21600)
  try:data=json.loads(raw)
  except Exception:raise YandexInputError('Не удалось прочитать результат загрузки Яндекс.Музыки.')
  if not data.get('ok'):raise YandexInputError('Твоя авторизация Яндекса истекла или отозвана. Отключи аккаунт и подключи заново через /yandex' if data.get('reason')=='auth' else 'Трек недоступен для загрузки в MP3 с этим аккаунтом. Ограничения подписки и доступа не обходятся.')
  source=work/'source.mp3';out=work/'result.mp3';title=''.join(c for c in str(data.get('title','Яндекс.Музыка')) if c.isprintable())[:120] or 'Яндекс.Музыка'
  if not source.is_file() or source.is_symlink() or not source.stat().st_size:raise YandexInputError('Пустой результат загрузки.')
  if int(data.get('bitrate',0))==int(job['quality']):source.rename(out)
  else:await self.run_cmd([FFMPEG,'-hide_banner','-loglevel','error','-nostdin','-y','-threads','2','-protocol_whitelist','file,pipe','-i',str(source),'-vn','-c:a','libmp3lame','-b:a',job['quality']+'k','-threads','2',str(out)],work,21600)
  if self.cancel.is_set() or not self.allowed(job['user']) or job.get('account_id')!=self.yandex_account(job['user']):raise YandexInputError('Задача отменена или аккаунт отключён.')
  if out.stat().st_size>MAX_SINGLE:raise YandexInputError('Результат превысил лимит 3 ГиБ.')
  target,size=self.store_private_yandex(out,job,self.max_archive);print('YANDEX_JOB_SAVED bytes='+str(size),flush=True)
  if size>MAX_RESULT:await self.send('MP3 сохранён в закрытой папке yamp. Файл больше лимита Telegram 50 МБ, поэтому отправка невозможна. Публичная ссылка не создавалась.',chat=job['user']);return
  await self.send('📤 Отправляю MP3 из Яндекс.Музыки…',chat=job['user'])
  if self.cancel.is_set() or not self.allowed(job['user']) or job.get('account_id')!=self.yandex_account(job['user']):raise YandexInputError('Отправка отменена: аккаунт отключён.')
  try:
   sent=await asyncio.to_thread(self.api.upload,job['user'],target,'mp3',title+' · '+job['quality']+' кбит/с')
   if isinstance(sent,dict):self.record_message(job['user'],sent.get('message_id'))
  except Exception:await self.send('Telegram не подтвердил отправку. MP3 сохранён в закрытой папке yamp, публичной ссылки нет.',chat=job['user'])
  else:print('YANDEX_JOB_DELIVERED',flush=True)
