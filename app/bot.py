#!/usr/bin/python3
"""Owner-only YouTube conversion bot. No shell, cookies, inbound listener or root worker."""
import asyncio, collections, json, math, mimetypes, os, pathlib, re, secrets, shutil, signal, subprocess, time, urllib.parse, urllib.request, urllib.error
MAX_RESULT=50_000_000
MAX_WORK=5*1024**3
MAX_SINGLE=3*1024**3
MAX_ARCHIVE=20*1024**3
PUBLIC_BASE_URL='https://media.example.com/mp/'
FORMATS={'mp3':'MP3','mp4':'MP4','mkv':'MKV'}
YTDLP='/usr/local/bin/yt-dlp';FFMPEG='/usr/bin/ffmpeg'
class UserError(Exception):pass
class ApiError(Exception):pass

def video_url(text):
    if not isinstance(text,str) or len(text)>2048 or any(c.isspace() for c in text.strip()):raise UserError('Отправь одну ссылку YouTube без дополнительного текста.')
    try:u=urllib.parse.urlsplit(text.strip());port=u.port
    except ValueError:raise UserError('Некорректная ссылка.')
    if u.scheme not in ('https','http') or u.username or u.password or port not in (None,80,443):raise UserError('Нужна обычная ссылка YouTube.')
    host=(u.hostname or '').lower();path=u.path.rstrip('/')
    if host in ('youtu.be','www.youtu.be'):vid=path.lstrip('/')
    elif host in ('youtube.com','www.youtube.com','m.youtube.com'):
        if path=='/watch':vid=urllib.parse.parse_qs(u.query).get('v',[''])[0]
        elif re.fullmatch(r'/(shorts|live|embed)/[A-Za-z0-9_-]{11}',path):vid=path.split('/')[-1]
        else:raise UserError('Нужна ссылка на одно видео, не канал или плейлист.')
    else:raise UserError('Поддерживаются только ссылки youtube.com и youtu.be.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid):raise UserError('Не удалось определить ID видео.')
    return 'https://www.youtube.com/watch?v='+vid

def safe_title(title):
    text=''.join(c for c in str(title or 'YouTube') if c.isprintable())
    return text[:120] or 'YouTube'

class API:
    def __init__(self,token,proxy_url=None):
        self.base='https://api.telegram.org/bot'+token+'/'
        self.proxy_url=proxy_url
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy_url,'http':proxy_url} if proxy_url else {}))
    def call(self,method,data=None,timeout=35):
        req=urllib.request.Request(self.base+method,data=json.dumps(data or {}).encode(),headers={'Content-Type':'application/json'})
        return self.request(req,timeout)
    def request(self,req,timeout):
        try:
            with self.opener.open(req,timeout=timeout) as r:res=json.load(r)
        except urllib.error.HTTPError as e:raise ApiError('Telegram HTTP '+str(e.code)) from None
        except Exception:raise ApiError('Telegram connection error') from None
        if not res.get('ok'):raise ApiError('Telegram rejected request')
        return res['result']
    def upload(self,chat,path,fmt,title):
        boundary='YTMedia'+secrets.token_hex(24)
        method,field={'mp3':('sendAudio','audio'),'mp4':('sendVideo','video'),'mkv':('sendDocument','document')}[fmt]
        fields={'chat_id':str(chat),'caption':title[:900]}
        if fmt=='mp3':fields['title']=title
        if fmt=='mp4':fields['supports_streaming']='true'
        body=[]
        for k,v in fields.items():body.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode())
        filename='YTMedia.'+fmt
        body.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+field+'"; filename="'+filename+'"\r\nContent-Type: '+(mimetypes.guess_type(filename)[0] or 'application/octet-stream')+'\r\n\r\n').encode()+path.read_bytes()+b'\r\n')
        body.append(('--'+boundary+'--\r\n').encode())
        req=urllib.request.Request(self.base+method,data=b''.join(body),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        return self.request(req,180)

QUALITY={'mp3':{'128':'128 кбит/с','192':'192 кбит/с','256':'256 кбит/с','320':'320 кбит/с'},'mp4':{'360':'360p','480':'480p','720':'720p','1080':'1080p'},'mkv':{'360':'360p','480':'480p','720':'720p','1080':'1080p','2160':'2160p · 4K'}}

def job_label(job):
    fmt=job['format'];q=job.get('quality','')
    if fmt=='mp3':return 'MP3 · '+q+' кбит/с'
    if fmt in ('mp4','mkv'):return fmt.upper()+' · до '+q+'p'+(' (4K)' if q=='2160' else '')
    return FORMATS[fmt]

from admin_tools import AdminTools

from yandex_tools import YandexTools,YandexInputError,is_yandex_link

class Bot(AdminTools,YandexTools):
    def __init__(self,api,owner,state):
        self.api=api;self.owner=int(owner);self.state=pathlib.Path(state);self.state.mkdir(parents=True,exist_ok=True)
        self.jobs=self.state/'jobs';self.jobs.mkdir(exist_ok=True);self.archive=self.state/'archive';self.public=pathlib.Path('/var/lib/yt-media-bot/public');self.max_archive=MAX_ARCHIVE
        self.queue=asyncio.Queue(maxsize=2);self.pending={};self.active=None;self.cancel=asyncio.Event();self.process=None;self.rate={}
        self.childenv=os.environ.copy()
        # Yandex connects directly; YouTube uses the configured Telegram/Xray proxy.
        for key in list(self.childenv):
            if key.lower() in ('http_proxy','https_proxy','all_proxy','no_proxy','ftp_proxy'):self.childenv.pop(key,None)
        self.youtube_env=self.childenv.copy()
        if getattr(api,'proxy_url',None):
            self.youtube_env.update({'http_proxy':api.proxy_url,'https_proxy':api.proxy_url,'HTTP_PROXY':api.proxy_url,'HTTPS_PROXY':api.proxy_url})
        try:self.offset=int((self.state/'offset').read_text())
        except (OSError,ValueError):self.offset=0
        try:self.access=json.loads((self.state/'access.json').read_text())
        except FileNotFoundError:self.access={'approved':{},'pending':{},'denied':{}}
        except Exception:raise SystemExit('Invalid access state; refusing to bypass approvals')
        for k in ['approved','pending','denied']:self.access.setdefault(k,{})
        self.init_admin()
        self.init_yandex()
    def save_access(self):
        tmp=self.state/'access.tmp';tmp.write_text(json.dumps(self.access,ensure_ascii=False));tmp.chmod(0o600);tmp.replace(self.state/'access.json')
    def allowed(self,uid):return uid==self.owner or str(uid) in self.access['approved']
    def actor(self,m):
        uid=m.get('from',{}).get('id');chat=m.get('chat',{})
        if not isinstance(uid,int) or uid<=0 or m.get('from',{}).get('is_bot') or chat.get('type')!='private' or chat.get('id')!=uid:return None
        return uid
    def authorized(self,m):
        uid=self.actor(m);return uid is not None and self.allowed(uid)
    async def call(self,method,data=None,timeout=35):return await asyncio.to_thread(self.api.call,method,data,timeout)
    async def send(self,text,markup=None,chat=None):
        d={'chat_id':self.owner if chat is None else chat,'text':text[:3900]}
        if markup:d['reply_markup']=markup
        try:
            result=await self.call('sendMessage',d)
            if isinstance(result,dict):self.record_message(d['chat_id'],result.get('message_id'))
            return result
        except ApiError:print('NOTIFICATION_FAILED',flush=True);return None
    async def request_access(self,uid,person):
        if self.allowed(uid):return
        k=str(uid);now=time.time();last=self.access['pending'].get(k)
        if last and now-last.get('created',0)<86400:
            await self.access_send(uid,'Запрос уже ждёт подтверждения владельца.',chat=uid);return
        if now-self.access['denied'].get(k,0)<7*86400:
            await self.temporary_send('Владелец отклонил запрос. Повторный запрос доступен через 7 дней.',chat=uid);return
        self.access['pending']={a:v for a,v in self.access['pending'].items() if now-v.get('created',0)<7*86400}
        if len(self.access['pending'])>=50:
            await self.send('Лимит ожидающих запросов достигнут. Попробуй позже.',chat=uid);return
        name=safe_title(' '.join(str(person.get(x,'')) for x in ['first_name','last_name']).strip())
        username=safe_title(person.get('username','')) if person.get('username') else ''
        nonce=secrets.token_hex(6);self.access['pending'][k]={'name':name,'username':username,'created':now,'nonce':nonce};self.save_access()
        markup={'inline_keyboard':[[{'text':'✅ Разрешить','callback_data':'usr:approve:'+k+':'+nonce},{'text':'❌ Отклонить','callback_data':'usr:deny:'+k+':'+nonce}]]}
        delivered=await self.access_send(uid,'Запрос доступа к видеоботу:\n'+name+('\n@'+username if username else '')+'\nTelegram ID: '+k,markup)
        await self.access_send(uid,'Запрос отправлен владельцу. До подтверждения обработка недоступна.' if delivered else 'Запрос сохранён. Владелец сможет посмотреть его в /requests.',chat=uid)
    async def closed(self,uid):
        await self.access_send(uid,'Доступ только с подтверждением владельца.',{'inline_keyboard':[[{'text':'Запросить доступ','callback_data':'access:request'}]]},chat=uid)
    async def access_callback(self,uid,parts,message):
        if uid!=self.owner:return
        if len(parts)<3 or not parts[2].isdigit():return
        target=int(parts[2]);k=str(target)
        if target==self.owner or target<=0:return
        action=parts[1]
        if action in ('approve','deny'):
            p=self.access['pending'].get(k)
            if len(parts)!=4 or not p or p.get('nonce')!=parts[3]:
                await self.temporary_send('Этот запрос уже обработан или устарел.');return
            self.access['pending'].pop(k,None)
            if action=='approve':
                self.access['approved'][k]={'name':p['name'],'username':p.get('username',''),'approved_at':time.time()};self.access['denied'].pop(k,None)
                await self.temporary_send('✅ Доступ подтверждён. Отправь /start или ссылку YouTube.',chat=target)
            else:
                self.access['denied'][k]=time.time();await self.temporary_send('Владелец отклонил запрос доступа.',chat=target)
            self.save_access();await self.temporary_send(('Разрешён' if action=='approve' else 'Отклонён')+' пользователь ID '+k+'.')
        elif action=='revoke':
            if k not in self.access['approved']:return
            self.access['approved'].pop(k,None);self.access['denied'][k]=time.time();self.save_access()
            await self.yandex_disconnect(target)
            self.pending={a:v for a,v in self.pending.items() if v.get('user')!=target}
            if self.active and self.active['user']==target:self.cancel.set()
            await self.temporary_send('Доступ отозван владельцем.',chat=target);await self.temporary_send('Доступ ID '+k+' отозван.')
        else:return
        await self.access_done(target,message)
    async def show_users(self):
        users=list(self.access['approved'].items())
        await self.send('Владелец всегда имеет доступ. Подтверждённых пользователей: '+str(len(users))+'.')
        for uid,p in users[:30]:
            await self.send(p.get('name','Пользователь')+' · ID '+uid,{'inline_keyboard':[[{'text':'Отозвать доступ','callback_data':'usr:revoke:'+uid}]]})
    async def show_requests(self):
        requests=list(self.access['pending'].items());await self.send('Ожидающих запросов: '+str(len(requests))+'.')
        for uid,p in requests[:30]:
            await self.access_send(int(uid),p.get('name','Пользователь')+' · ID '+uid,{'inline_keyboard':[[{'text':'Разрешить','callback_data':'usr:approve:'+uid+':'+p['nonce']},{'text':'Отклонить','callback_data':'usr:deny:'+uid+':'+p['nonce']}]]})
    async def edit_menu(self,uid,message,text,markup):
        try:await self.call('editMessageText',{'chat_id':uid,'message_id':message['message_id'],'text':text,'reply_markup':markup})
        except ApiError:await self.send(text,markup,chat=uid)
    def format_menu(self,key):
        return {'inline_keyboard':[[{'text':FORMATS[f],'callback_data':'fmt:'+key+':'+f} for f in pair] for pair in [('mp3','mp4'),('mkv',)]]}
    async def enqueue(self,uid,key,fmt,quality,message):
        task=self.pending.get(key)
        if not task or task.get('user')!=uid:return
        if task.get('source')=='yandex':return
        if self.queue.full():await self.send('Очередь заполнена: одна обработка и две ожидающие задачи.',chat=uid);return
        recent=[t for t in self.rate.get(uid,[]) if time.time()-t<3600]
        if uid!=self.owner and len(recent)>=3:
            await self.send('Лимит пользователя: 3 задачи в час. Попробуй позже.',chat=uid);return
        self.rate[uid]=recent+[time.time()];self.pending.pop(key,None)
        job={'url':task['url'],'format':fmt,'quality':quality,'user':uid}
        await self.queue.put(job)
        try:await self.call('editMessageReplyMarkup',{'chat_id':uid,'message_id':message['message_id'],'reply_markup':{'inline_keyboard':[]}})
        except ApiError:pass
        await self.send('Принято: '+job_label(job)+f'.\nКаждый результат сохраняется на {PUBLIC_BASE_URL}. До 50 МБ получишь файл и ссылку, больше — только ссылку. Файл виден всем посетителям публичной медиатеки.',chat=uid)
    async def handle(self,u):
        if 'callback_query' in u:
            q=u['callback_query'];message=q.get('message',{});uid=self.actor({'from':q.get('from',{}),'chat':message.get('chat',{})})
            if uid is None:return
            self.record_message(uid,message.get('message_id'),message.get('date'))
            try:await self.call('answerCallbackQuery',{'callback_query_id':q['id']})
            except ApiError:pass
            data=q.get('data','');parts=data.split(':')
            if data=='access:request':await self.request_access(uid,q.get('from',{}));return
            if parts[0]=='usr':await self.access_callback(uid,parts,message);return
            if parts[0]=='adm':await self.admin_callback(uid,parts,message);return
            if parts[0]=='ya':await self.yandex_account_callback(uid,parts,message);return
            if parts[0]=='ym':await self.yandex_callback(uid,parts,message);return
            if not self.allowed(uid):await self.closed(uid);return
            if len(parts)<3 or parts[0] not in ('fmt','q'):return
            task=self.pending.get(parts[1])
            if not task or task.get('user')!=uid or time.time()-task['created']>900:
                await self.send('Кнопки устарели или принадлежат другому запросу. Отправь свою ссылку ещё раз.',chat=uid);return
            key=parts[1];fmt=parts[2]
            if fmt=='back' and parts[0]=='fmt':await self.edit_menu(uid,message,'Выбери формат.',self.format_menu(key));return
            if fmt not in FORMATS:return
            if parts[0]=='fmt' and fmt in QUALITY:
                choices=list(QUALITY[fmt]);rows=[[{'text':QUALITY[fmt][qv],'callback_data':'q:'+key+':'+fmt+':'+qv} for qv in choices[i:i+2]] for i in range(0,len(choices),2)]
                rows.append([{'text':'← Назад к форматам','callback_data':'fmt:'+key+':back'}])
                await self.edit_menu(uid,message,'Выбери качество '+fmt.upper()+'. Качество ограничено исходным видео.',{'inline_keyboard':rows});return
            if parts[0]=='q':
                if len(parts)!=4 or fmt not in QUALITY or parts[3] not in QUALITY[fmt]:return
                quality=parts[3]
            else:return
            await self.enqueue(uid,key,fmt,quality,message);return
        message=u.get('message',{});uid=self.actor(message)
        if uid is None:return
        self.record_message(uid,message.get('message_id'),message.get('date'))
        text=message.get('text','').strip();cmd=text.split()[0].split('@')[0] if text else ''
        if not self.allowed(uid):
            if cmd=='/access':await self.request_access(uid,message.get('from',{}))
            else:await self.closed(uid)
            return
        if cmd in ('/start','/help'):
            text=f'🎬 Отправь ссылку YouTube → выбери формат → качество.\n\nMP3: 128 / 192 / 256 / 320 кбит/с.\nMP4: 360p / 480p / 720p / 1080p (доступное до выбранного разрешения).\nMKV: 360p / 480p / 720p / 1080p / 2160p (4K). Исходные потоки сохраняются без перекодирования; 4K только если доступно у источника.\n\nОграничения по длительности записи нет. Размер файлов, свободное место и время обработки ограничены для защиты сервера. Результаты YouTube сохраняются на {PUBLIC_BASE_URL}. До 50 МБ — файл сюда и ссылка; больше — только ссылка. Не отправляй конфиденциальные материалы: файлы доступны всем посетителям медиатеки. Исходные файлы и рабочие данные имеют защитные лимиты.\n\n/status — очередь и твоя задача\n/cancel — отменить свои задачи\n\nТолько материалы, которые имеешь право скачивать. Плейлисты, эфиры и другие сайты не поддерживаются.'
            text+='\n\n/yandex — подключить свой аккаунт Яндекс.Музыки или отключить его. Личные MP3 хранятся приватно, без ссылок.'
            if uid==self.owner:text+='\n\n/users — пользователи и отзыв доступа\n/requests — запросы подтверждения\nДля владельца /cancel отменяет все задачи.\n/admin — полная админ-панель и очистка сообщений.\n/yandex — личные MP3 из Яндекс.Музыки. Для них нет публичных ссылок, хранение в закрытой папке yamp.'
            await self.send(text,chat=uid);return
        if cmd=='/yandex':await self.yandex_status(uid);return
        if cmd=='/admin':
            if uid==self.owner:await self.show_admin()
            else:await self.send('Админ-панель доступна только владельцу.',chat=uid)
            return
        if cmd in ('/users','/requests'):
            if uid!=self.owner:await self.send('Эта команда доступна только владельцу.',chat=uid);return
            if cmd=='/users':await self.show_users()
            else:await self.show_requests()
            return
        if cmd=='/status':
            active=self.active and (uid==self.owner or self.active['user']==uid)
            count=sum(1 for j in list(self.queue._queue) if uid==self.owner or j['user']==uid)
            await self.send(('Обрабатывается: '+job_label(self.active) if active else 'Твоя задача сейчас не обрабатывается.')+'\nОжидающих задач: '+str(count),chat=uid);return
        if cmd=='/cancel':
            if self.active and (uid==self.owner or self.active['user']==uid):self.cancel.set()
            keep=[]
            while not self.queue.empty():
                j=self.queue.get_nowait();self.queue.task_done()
                if uid!=self.owner and j['user']!=uid:keep.append(j)
            for j in keep:self.queue.put_nowait(j)
            self.pending={k:v for k,v in self.pending.items() if uid!=self.owner and v.get('user')!=uid}
            await self.send('Отмена запрошена. Уже начатую отправку в Telegram отменить нельзя.',chat=uid);return
        if not text:return
        if is_yandex_link(text):await self.yandex_prepare(uid,text);return
        try:url=video_url(text)
        except UserError as e:await self.send(str(e),chat=uid);return
        self.pending={k:v for k,v in self.pending.items() if time.time()-v['created']<=900}
        if sum(1 for v in self.pending.values() if v['user']==uid)>=5 or len(self.pending)>=50:
            await self.send('Слишком много невыбранных ссылок. Выбери формат или отправь /cancel.',chat=uid);return
        key=secrets.token_hex(8);self.pending[key]={'url':url,'created':time.time(),'user':uid}
        await self.send('Выбери формат для одного видео. Кнопки действуют 15 минут.',self.format_menu(key),chat=uid)
    async def run_cmd(self,args,work,timeout):
        p=await asyncio.create_subprocess_exec(*args,cwd=work,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,env=self.youtube_env if args[0]==YTDLP else self.childenv)
        self.process=p;capture=asyncio.create_task(p.communicate());start=time.monotonic()
        try:
            while not capture.done():
                if self.cancel.is_set():raise UserError('Задача отменена.')
                if time.monotonic()-start>timeout:raise UserError('Превышено время обработки. Попробуй более короткое видео.')
                size=0
                for x in work.rglob('*'):
                    try:
                        if x.is_file() and not x.is_symlink():size+=x.stat().st_size
                    except FileNotFoundError:pass
                if size>MAX_WORK:raise UserError('Превышен лимит рабочих данных. Попробуй более короткое видео.')
                await asyncio.sleep(.5)
            out,err=await capture
            if p.returncode:raise UserError('Источник не удалось получить или преобразовать. Он может быть недоступен, требовать входа либо превышать защитный лимит загрузки. Ограничения доступа бот не обходит.')
            return out
        finally:
            if p.returncode is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:await asyncio.wait_for(asyncio.shield(capture),5)
                except asyncio.TimeoutError:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await capture
            self.process=None
    async def convert(self,job,work):
        if shutil.disk_usage(self.jobs).free<6*1024**3:raise UserError('Недостаточно свободного места: требуется резерв 6 ГиБ.')
        common=[YTDLP,'--ignore-config','--no-playlist','--no-cache-dir','--no-progress','--quiet','--no-warnings','--socket-timeout','15','--retries','2','--fragment-retries','2','--concurrent-fragments','4']
        meta_start=time.monotonic()
        raw=await self.run_cmd(common+['--skip-download','--dump-single-json',job['url']],work,90)
        try:info=json.loads(raw)
        except Exception:raise UserError('Не удалось прочитать данные видео.')
        print('STAGE_METADATA_SECONDS='+str(round(time.monotonic()-meta_start,2)),flush=True)
        duration=info.get('duration')
        if info.get('is_live') or isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:raise UserError('Поддерживаются законченные записи с известной длительностью, не прямые эфиры.')
        download_timeout=min(21600,max(1800,int(duration*1.5+600)))
        conversion_timeout=min(21600,max(1800,int(duration*2+600)))
        fmt=job['format'];q=job.get('quality','192' if fmt=='mp3' else '720')
        if fmt in QUALITY and q not in QUALITY[fmt]:raise UserError('Неподдерживаемое качество.')
        title=safe_title(info.get('title'))
        h=int(q) if fmt in ('mp4','mkv') else 0
        if fmt=='mkv':select=f'bv*[height<={h}]+ba/b[height<={h}]'
        elif fmt=='mp4':select=f'bv[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<={h}][ext=mp4]/bv*[height<={h}]+ba/b[height<={h}]'
        else:select='ba/b'
        metadata=work/'source-info.json';metadata.write_bytes(raw);metadata.chmod(0o600)
        download_start=time.monotonic()
        await self.run_cmd(common+['--max-filesize','1536M' if fmt=='mkv' else '1024M','--restrict-filenames','--no-mtime','-f',select,'--merge-output-format','mkv','-o',str(work/'input.%(ext)s'),'--load-info-json',str(metadata)],work,download_timeout)
        print('STAGE_DOWNLOAD_SECONDS='+str(round(time.monotonic()-download_start,2)),flush=True)
        candidates=[p for p in work.glob('input.*') if p.is_file() and p.suffix not in ('.part','.ytdl','.json')]
        if len(candidates)!=1:raise UserError('Загрузка не создала один исходный файл. Попробуй другое видео.')
        source=candidates[0];out=work/('result.'+fmt)
        args=[FFMPEG,'-hide_banner','-loglevel','error','-nostdin','-y','-filter_threads','2','-filter_complex_threads','2','-threads','2','-protocol_whitelist','file,pipe','-i',str(source)]
        if fmt=='mp3':args+=['-vn','-c:a','libmp3lame','-b:a',q+'k']
        elif fmt=='mkv':args+=['-map','0:v:0','-map','0:a:0?','-c','copy','-f','matroska']
        else:
            probe=await self.run_cmd(['/usr/bin/ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','stream=codec_type,codec_name,height','-of','json',str(source)],work,30)
            try:streams=json.loads(probe).get('streams',[])
            except Exception:streams=[]
            v=next((s for s in streams if s.get('codec_type')=='video'),{})
            a=next((s for s in streams if s.get('codec_type')=='audio'),{})
            copy=v.get('codec_name')=='h264' and v.get('height',h+1)<=h and a.get('codec_name') in (None,'aac')
            args+=['-map','0:v:0','-map','0:a:0?']
            if copy:args+=['-c:v','copy','-c:a','copy']
            else:
                width=h*16//9
                filt=f"scale=w='min({width},iw)':h='min({h},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
                args+=['-vf',filt,'-c:v','libx264','-preset','veryfast','-crf','23','-c:a','aac','-b:a','160k']
            args+=['-movflags','+faststart']
        conversion_start=time.monotonic()
        await self.run_cmd(args+['-threads','2',str(out)],work,conversion_timeout)
        print('STAGE_CONVERSION_SECONDS='+str(round(time.monotonic()-conversion_start,2))+' format='+fmt,flush=True)
        if self.cancel.is_set():raise UserError('Задача отменена.')
        if not out.exists() or not out.stat().st_size:raise UserError('Пустой результат конвертации.')
        if out.stat().st_size>MAX_SINGLE:raise UserError('Результат превысил защитный лимит одного файла 3 ГиБ.')
        return out,title
    def publish_result(self,out,job,title,keep_source=False):
        if not self.public.is_dir():raise UserError('Каталог публикации не подключён. Файл не опубликован.')
        size=out.stat().st_size
        used=self.storage_used()
        if used+size>MAX_ARCHIVE:raise UserError('Хранилище достигло лимита настроенного объёма. Владелец должен очистить старые файлы; автоматически они не удаляются.')
        if shutil.disk_usage(self.public).free<size+2*1024**3:raise UserError('Недостаточно места для безопасного сохранения результата.')
        if job['format'] not in ('mp3','mp4','mkv'):raise UserError('Недопустимый формат публикации.')
        slug=re.sub(r'[^A-Za-z0-9_-]+','-',str(title)).strip('-')[:55] or 'YouTube'
        name=slug+'_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+secrets.token_hex(16)+'.'+job['format']
        target=self.public/name;tmp=self.public/('.pending-'+name)
        try:
            shutil.copyfile(out,tmp);tmp.chmod(0o644);tmp.replace(target)
            if not keep_source:out.unlink()
        finally:tmp.unlink(missing_ok=True)
        return PUBLIC_BASE_URL+name,size
    def archive_result(self,out,job,title):
        if out.stat().st_size>MAX_RESULT:return self.publish_result(out,job,title)
        if not self.archive.is_dir():raise UserError('Закрытый архив сервера не подключён. Файл не опубликован.')
        used=sum(p.stat().st_size for p in self.archive.iterdir() if p.is_file() and not p.is_symlink())
        size=out.stat().st_size
        if used+size>MAX_ARCHIVE:raise UserError('Архив достиг лимита настроенного объёма. Владелец должен очистить старые файлы; автоматически они не удаляются.')
        if shutil.disk_usage(self.archive).free<size+2*1024**3:raise UserError('Недостаточно места для безопасного сохранения результата.')
        name=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_u'+str(job['user'])+'_'+secrets.token_hex(6)+'.'+job['format']
        target=self.archive/name;tmp=self.archive/('.pending-'+name)
        try:
            shutil.copyfile(out,tmp);tmp.chmod(0o600);tmp.replace(target);out.unlink()
            metadata={'created':time.time(),'user_id':job['user'],'format':job['format'],'quality':job['quality'],'title':title,'bytes':size}
            p=target.with_suffix(target.suffix+'.json');p.write_text(json.dumps(metadata,ensure_ascii=False));p.chmod(0o600)
        finally:tmp.unlink(missing_ok=True)
        return str(self.archive/name),size
    async def stored_message(self,path,size,job,title,reason):
        if path.startswith(PUBLIC_BASE_URL):
            text='🔗 '+reason+'\n'+title+'\n'+job_label(job)+' · '+str(round(size/1000**2,1))+' МБ\nСкачать:\n'+path+'\nФайл виден всем посетителям публичной медиатеки.'
            await self.send(text,chat=job['user'])
            if job['user']!=self.owner:await self.send('Опубликован результат пользователя ID '+str(job['user'])+'.\n'+text)
            return
        text='💾 '+reason+'\n'+title+'\n'+job_label(job)+' · '+str(round(size/1000**2,1))+' МБ\nСохранено на сервере:\n'+path+'\nОткрытая ссылка не создавалась.'
        await self.send(text,chat=job['user'])
        if job['user']!=self.owner:await self.send('Результат пользователя ID '+str(job['user'])+' сохранён в архив.\n'+text)
    async def worker(self):
        while True:
            job=await self.queue.get()
            if not self.allowed(job['user']):self.queue.task_done();continue
            self.active=job;self.cancel.clear();work=self.jobs/('job-'+secrets.token_hex(12));work.mkdir(mode=0o700)
            try:
                await self.send('⏳ Начинаю: '+job_label(job)+'.',chat=job['user'])
                if job.get('source')=='yandex':
                    await self.yandex_run_job(job,work)
                    continue
                out,title=await self.convert(job,work)
                if not self.allowed(job['user']):raise UserError('Доступ отозван владельцем; отправка остановлена.')
                storage_start=time.monotonic()
                path,size=await asyncio.to_thread(self.publish_result,out,job,title,keep_source=True)
                print('STAGE_STORAGE_SECONDS='+str(round(time.monotonic()-storage_start,2)),flush=True)
                if size>MAX_RESULT:
                    await self.stored_message(path,size,job,title,'Файл больше лимита Telegram 50 МБ.')
                    print('JOB_PUBLISHED format='+job['format'],flush=True)
                else:
                    await self.send('📤 Готово. Отправляю файл и ссылку…',chat=job['user'])
                    try:
                        upload_start=time.monotonic()
                        sent=await asyncio.to_thread(self.api.upload,job['user'],out,job['format'],title+' · '+job_label(job))
                        print('STAGE_TELEGRAM_UPLOAD_SECONDS='+str(round(time.monotonic()-upload_start,2)),flush=True)
                        if isinstance(sent,dict):self.record_message(job['user'],sent.get('message_id'))
                    except ApiError:
                        await self.stored_message(path,size,job,title,'Telegram не подтвердил отправку файла. Он сохранён и доступен по ссылке.')
                        print('UPLOAD_FAILED_LINK_AVAILABLE',flush=True)
                    else:
                        await self.stored_message(path,size,job,title,'Файл отправлен в Telegram и сохранён на сайте.')
                        print('JOB_DELIVERED_AND_PUBLISHED format='+job['format']+' quality='+job['quality'],flush=True)
            except (UserError,YandexInputError) as e:await self.send('⚠️ '+str(e),chat=job['user'])
            except Exception:await self.send('⚠️ Ошибка обработки. Рабочие файлы удалены; уже сохранённые результаты остаются на сервере.',chat=job['user']);print('JOB_FAILED',flush=True)
            finally:shutil.rmtree(work,ignore_errors=True);self.active=None;self.queue.task_done()
    async def poll(self):
        for p in self.jobs.iterdir():
            if p.name.startswith('job-') and p.is_dir() and not p.is_symlink():shutil.rmtree(p,ignore_errors=True)
        if self.archive.exists():
            for p in self.archive.glob('.pending-*'):
                if p.is_file() and not p.is_symlink():p.unlink()
        if self.public.exists():
            for p in self.public.glob('.pending-*'):
                if p.is_file() and not p.is_symlink():p.unlink()
        me=await self.call('getMe');print('BOT_READY @'+me['username']+' version=13',flush=True)
        await self.call('setMyName',{'name':'YT+YA-MP3'})
        await self.call('setMyCommands',{'commands':[{'command':'start','description':'Как пользоваться'},{'command':'help','description':'Форматы и качество'},{'command':'status','description':'Мои задачи'},{'command':'cancel','description':'Отменить мои задачи'},{'command':'access','description':'Запросить доступ'},{'command':'yandex','description':'Мой аккаунт Яндекс.Музыки'}]})
        await self.call('setMyCommands',{'scope':{'type':'chat','chat_id':self.owner},'commands':[{'command':'start','description':'Форматы и качество'},{'command':'status','description':'Все задачи'},{'command':'cancel','description':'Отменить задачи'},{'command':'users','description':'Пользователи и отзыв доступа'},{'command':'requests','description':'Подтвердить новых пользователей'},{'command':'admin','description':'Админ-панель и очистка сообщений'},{'command':'yandex','description':'Яндекс.Музыка — личные MP3'}]})
        asyncio.create_task(self.worker())
        asyncio.create_task(self.cleanup_loop())
        while True:
            try:
                updates=await self.call('getUpdates',{'offset':self.offset,'timeout':20,'allowed_updates':['message','callback_query']},35)
                for u in updates:
                    try:await self.handle(u)
                    except Exception:print('UPDATE_FAILED',flush=True)
                    self.offset=u['update_id']+1;tmp=self.state/'offset.tmp';tmp.write_text(str(self.offset));tmp.replace(self.state/'offset')
            except ApiError:print('POLL_RETRY',flush=True);await asyncio.sleep(5)

def main():
    global PUBLIC_BASE_URL, MAX_ARCHIVE
    os.umask(0o077)
    cfg=json.loads(pathlib.Path('/etc/yt-media-bot/config.json').read_text())
    token=(pathlib.Path(os.environ['CREDENTIALS_DIRECTORY'])/'telegram_token').read_text().strip()
    if not re.fullmatch(r'\d{5,16}:[A-Za-z0-9_-]{25,80}',token):raise SystemExit('Invalid credential')
    PUBLIC_BASE_URL=cfg['public_base_url'].rstrip('/')+'/'
    parsed=urllib.parse.urlsplit(PUBLIC_BASE_URL)
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise SystemExit('Invalid public_base_url')
    MAX_ARCHIVE=int(cfg.get('storage_limit_bytes',20*1024**3))
    if MAX_ARCHIVE<=0:raise SystemExit('Invalid storage limit')
    owner=int(cfg['owner_id'])
    if owner<=0:raise SystemExit('Private owner required')
    proxy_url=None
    if cfg.get('proxy_enabled'):
        proxy_url=(pathlib.Path(os.environ['CREDENTIALS_DIRECTORY'])/'proxy_url').read_text().strip()
        if not proxy_url.startswith('http://media:') or not proxy_url.endswith('@127.0.0.1:18189'):
            raise SystemExit('Invalid private proxy credential; direct fallback disabled')
    asyncio.run(Bot(API(token,proxy_url),owner,'/var/lib/yt-media-bot').poll())
if __name__=='__main__':main()
