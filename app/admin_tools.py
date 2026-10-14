"""Private-chat admin and access-only auto-cleanup. Stores IDs/timestamps, never message text."""
import asyncio,time,secrets
class AdminTools:
    def init_admin(self):
        self.access.setdefault('access_ui',{})
        self.access.setdefault('cleanup',[])
        self.access.setdefault('message_log',{})
        self.admin_confirm={};self.admin_busy=False;self.cleanup_busy=False
    def record_message(self,chat,mid,created=None):
        if not isinstance(chat,int) or chat<=0 or not isinstance(mid,int) or mid<=0:return
        k=str(chat);now=time.time();log=self.access['message_log']
        rows=[x for x in log.get(k,[]) if now-x['time']<48*3600]
        if not any(x['id']==mid for x in rows):rows.append({'id':mid,'time':float(created or now)})
        log[k]=rows[-200:]
        if len(log)>100:
            oldest=min((a for a in log if a!=str(self.owner)),key=lambda a:max([x['time'] for x in log[a]] or [0]))
            log.pop(oldest,None)
        self.save_access()
    def remember_access(self,target,chat,message):
        if not isinstance(message,dict) or not isinstance(message.get('message_id'),int):return
        rows=self.access['access_ui'].setdefault(str(target),[])
        row={'chat':int(chat),'id':message['message_id']}
        if row not in rows:rows.append(row)
        self.access['access_ui'][str(target)]=rows[-60:];self.save_access()
    def queue_cleanup(self,chat,mid,delay=30):
        if not isinstance(mid,int) or mid<=0:return
        now=time.time();q=self.access['cleanup']
        existing=next((x for x in q if x['chat']==int(chat) and x['id']==mid),None)
        if existing:existing['due']=min(existing['due'],now+delay)
        else:q.append({'chat':int(chat),'id':mid,'due':now+delay,'tries':0})
        self.access['cleanup']=q[-1000:];self.save_access()
    async def access_send(self,target,text,markup=None,chat=None):
        chat=self.owner if chat is None else chat
        result=await self.send(text,markup,chat=chat);self.remember_access(target,chat,result);return result
    async def temporary_send(self,text,markup=None,chat=None,delay=30):
        chat=self.owner if chat is None else chat
        result=await self.send(text,markup,chat=chat)
        if isinstance(result,dict):self.queue_cleanup(chat,result.get('message_id'),delay)
        return result
    async def access_done(self,target,message):
        rows=self.access['access_ui'].pop(str(target),[])
        if message and isinstance(message.get('message_id'),int):rows.append({'chat':self.owner,'id':message['message_id']})
        for r in rows:self.queue_cleanup(r['chat'],r['id'],0)
        self.save_access();await self.pump_cleanup()
    def forget_messages(self,chat,ids):
        ids=set(ids);k=str(chat)
        self.access['message_log'][k]=[x for x in self.access['message_log'].get(k,[]) if x['id'] not in ids]
        for key,rows in self.access['access_ui'].items():self.access['access_ui'][key]=[x for x in rows if x['chat']!=chat or x['id'] not in ids]
        self.access['cleanup']=[x for x in self.access['cleanup'] if x['chat']!=chat or x['id'] not in ids]
        self.save_access()
    async def delete_rows(self,rows):
        groups={};removed=failed=0
        for row in rows:
            if row['chat']>0 and row['id']>0:groups.setdefault(row['chat'],set()).add(row['id'])
        for chat,values in groups.items():
            values=sorted(values)
            for i in range(0,len(values),100):
                batch=values[i:i+100]
                try:await self.call('deleteMessages',{'chat_id':chat,'message_ids':batch})
                except Exception:
                    for mid in batch:
                        try:await self.call('deleteMessage',{'chat_id':chat,'message_id':mid})
                        except Exception:failed+=1
                        else:removed+=1;self.forget_messages(chat,[mid])
                else:removed+=len(batch);self.forget_messages(chat,batch)
        return removed,failed
    async def pump_cleanup(self):
        if self.cleanup_busy:return
        now=time.time();due=[x.copy() for x in self.access['cleanup'] if x['due']<=now]
        if not due:return
        self.cleanup_busy=True
        try:
            await self.delete_rows(due)
            keys={(x['chat'],x['id']) for x in due};remaining=[]
            for row in self.access['cleanup']:
                if (row['chat'],row['id']) in keys:
                    row['tries']=row.get('tries',0)+1
                    if row['tries']>=3:continue
                    row['due']=time.time()+60
                remaining.append(row)
            self.access['cleanup']=remaining;self.save_access()
        finally:self.cleanup_busy=False
    async def cleanup_loop(self):
        while True:
            try:await self.pump_cleanup()
            except Exception:print('CLEANUP_FAILED',flush=True)
            await asyncio.sleep(2)
    async def show_admin(self):
        markup={'inline_keyboard':[[{'text':'Пользователи','callback_data':'adm:users'},{'text':'Запросы доступа','callback_data':'adm:requests'}],[{'text':'Очистить отдельный чат','callback_data':'adm:pick'}],[{'text':'Очистить все учтённые чаты','callback_data':'adm:all'}]]}
        await self.send('Администратор бота: владелец.\n\nУправление пользователями и очистка сообщений в личных диалогах с этим ботом. Удаление — только после подтверждения. Telegram обычно допускает удаление сообщений моложе 48 часов. Архив на сервере не удаляется.',markup)
    def deletion_rows(self,scope):
        now=time.time();rows=[]
        for chat,items in self.access['message_log'].items():
            if scope!='all' and str(scope)!=chat:continue
            for x in items:
                if now-x['time']<47*3600+55*60:rows.append({'chat':int(chat),'id':x['id']})
        return rows
    async def admin_preview(self,scope):
        rows=self.deletion_rows(scope)
        if not rows:await self.temporary_send('Учтённых сообщений для очистки нет. Старую историю бот получить не может.');return
        token=secrets.token_hex(8);self.admin_confirm={k:v for k,v in self.admin_confirm.items() if time.time()-v['created']<300}
        self.admin_confirm[token]={'rows':rows,'created':time.time()}
        text='Подтвердить очистку '+str(len(rows))+' учтённых сообщений '+('во всех диалогах' if scope=='all' else 'в чате ID '+str(scope))+'?\n\nБудут удалены сообщения в Telegram, включая ссылки, меню и отправленные файлы. Файлы в архиве на сервере и права пользователей НЕ удаляются. Для старых сообщений/особых типов Telegram может отказать.'
        await self.send(text,{'inline_keyboard':[[{'text':'Да, удалить','callback_data':'adm:confirm:'+token},{'text':'Отмена','callback_data':'adm:cancel:'+token}]]})
    async def execute_admin_cleanup(self,rows):
        try:
            n,bad=await self.delete_rows(rows)
            await self.temporary_send('Очистка завершена. Запрошено удаление: '+str(n)+'. Не удалось: '+str(bad)+'. Telegram пропускает уже отсутствующие сообщения.')
        except Exception:await self.temporary_send('Ошибка очистки. Остальные функции бота не остановлены.')
        finally:self.admin_busy=False
    async def admin_callback(self,uid,parts,message):
        if uid!=self.owner:return
        if len(parts)<2:return
        action=parts[1]
        if action=='users':await self.show_users()
        elif action=='requests':await self.show_requests()
        elif action=='pick':
            chats=[int(k) for k,v in self.access['message_log'].items() if v]
            markup={'inline_keyboard':[[{'text':('Мой чат' if c==self.owner else self.access['approved'].get(str(c),{}).get('name','ID '+str(c)))[:55],'callback_data':'adm:chat:'+str(c)}] for c in chats[:50]]}
            await self.send('Выбери диалог с ботом для очистки. Показываются последние учтённые диалоги.',markup)
        elif action=='all':await self.admin_preview('all')
        elif action=='chat' and len(parts)==3 and parts[2].isdigit():await self.admin_preview(int(parts[2]))
        elif action in ('confirm','cancel') and len(parts)==3:
            item=self.admin_confirm.get(parts[2])
            if not item or time.time()-item['created']>300:await self.temporary_send('Подтверждение устарело. Открой /admin ещё раз.');return
            if action=='confirm' and self.admin_busy:await self.temporary_send('Предыдущая очистка ещё выполняется.');return
            self.admin_confirm.pop(parts[2],None)
            self.queue_cleanup(self.owner,message.get('message_id'),0)
            if action=='cancel':await self.temporary_send('Очистка отменена.');return
            self.admin_busy=True;asyncio.create_task(self.execute_admin_cleanup(item['rows']))
            await self.temporary_send('Очистка запущена. Это не изменяет файлы на сервере.')
