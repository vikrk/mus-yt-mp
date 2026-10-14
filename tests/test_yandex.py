from unittest.mock import patch
import os
import unittest,tempfile,pathlib,importlib.util,sys,time,json,asyncio
p=pathlib.Path(__file__).resolve().parents[1]/'app'/'bot.py';spec=importlib.util.spec_from_file_location('media_bot_ym',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.modules['bot']=m
from yandex_tools import parse_yandex,YandexInputError
class API:
 def __init__(self):self.calls=[];self.uploads=[];self.ids=0
 def call(self,n,d=None,timeout=35):self.calls.append((n,d));self.ids+=1;return {'message_id':self.ids}
 def upload(self,chat,path,fmt,title):self.uploads.append((chat,path,fmt,title));return {'message_id':100}
def message(uid,text):return {'message':{'chat':{'id':uid,'type':'private'},'from':{'id':uid},'text':text}}
def callback(uid,data):return {'callback_query':{'id':'x','message':{'message_id':1,'chat':{'id':uid,'type':'private'}},'from':{'id':uid},'data':data}}
def account(b,uid,tag):
 p=b.yandex_credential(uid);p.write_text(json.dumps({'access_token':'test-not-a-real-secret-'+tag,'expires_at':time.time()+3600,'account_id':tag}));p.chmod(0o600)
def job(uid,tag):return {'source':'yandex','track':'456','album':None,'format':'mp3','quality':'192','user':uid,'account_id':tag}
class Tests(unittest.IsolatedAsyncioTestCase):
 def test_strict_urls(self):
  self.assertEqual(parse_yandex('https://music.yandex.ru/album/123/track/456?utm=x')['track'],'456')
  for url in ['http://music.yandex.ru/track/456','https://music.yandex.ru@evil.test/track/456','https://music.yandex.ru.evil.test/track/456','https://music.yandex.ru/album/123','https://music.yandex.ru/track/../../etc/passwd','https://music.yandex.ru:444/track/456']:
   with self.assertRaises(YandexInputError):parse_yandex(url)
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_individual_accounts_no_fallback_or_cross_user_buttons(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner')
   await b.handle(message(999,'https://music.yandex.ru/track/456'));self.assertFalse(b.pending);self.assertFalse(b.yandex_ready(999))
   account(b,999,'peer');await b.handle(message(999,'https://music.yandex.ru/track/456'));key=next(iter(b.pending))
   await b.yandex_callback(12345,['ym',key,'192'],{'message_id':1});self.assertEqual(b.queue.qsize(),0)
   await b.enqueue(999,key,'mp3','192',{'message_id':1});self.assertEqual(b.queue.qsize(),0)
   await b.yandex_callback(999,['ym',key,'192'],{'message_id':1});self.assertEqual(b.queue.qsize(),1);self.assertEqual((await b.queue.get())['account_id'],'peer')
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_worker_per_user_files_and_credential_no_public(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner');account(b,999,'peer');b.public=pathlib.Path(d)/'public';b.public.mkdir();b.publish_result=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('public forbidden'));seen=[]
   async def cmd(args,work,timeout):
    seen.append(args[args.index('--credential')+1]);(work/'source.mp3').write_bytes(b'MP3-private');return json.dumps({'ok':True,'bitrate':192,'title':'Track'}).encode()
   b.run_cmd=cmd;t=asyncio.create_task(b.worker())
   for uid,tag in [(12345,'owner'),(999,'peer')]:await b.queue.put(job(uid,tag));await asyncio.wait_for(b.queue.join(),10)
   t.cancel()
   try:await t
   except asyncio.CancelledError:pass
   self.assertEqual([x[0] for x in a.uploads],[12345,999]);self.assertEqual(seen,[str(b.yandex_credential(12345)),str(b.yandex_credential(999))]);self.assertFalse(list(b.public.iterdir()))
   for uid in (12345,999):
    folder=b.yamp/str(uid);saved=list(folder.glob('*.mp3'));self.assertEqual(len(saved),1);self.assertEqual(saved[0].stat().st_mode&0o777,0o600);self.assertEqual(folder.stat().st_mode&0o777,0o700)
   self.assertEqual(b.storage_used(),22);self.assertTrue(all('https://' not in x.get('text','') for n,x in a.calls if isinstance(x,dict)))
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_disconnect_cancels_only_own_yandex_and_keeps_others(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner');account(b,999,'peer')
   await b.queue.put(job(999,'peer'));await b.queue.put(job(12345,'owner'));b.active=job(999,'peer')
   await b.yandex_disconnect(999);self.assertFalse(b.yandex_ready(999));self.assertTrue(b.yandex_ready(12345));self.assertTrue(b.cancel.is_set());self.assertEqual(b.queue.qsize(),1);self.assertEqual((await b.queue.get())['user'],12345)
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_revoke_removes_credentials(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d);b.access['approved']['999']={'name':'Peer'};account(b,999,'peer');await b.handle(callback(12345,'usr:revoke:999'));self.assertFalse(b.allowed(999));self.assertFalse(b.yandex_credential(999).exists())
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_forged_stale_job_fails_without_download(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner');account(b,999,'peer')
   for j in [job(999,'owner'),job(999,'old-peer'),job(111,'owner')]:
    with self.assertRaises(YandexInputError):await b.yandex_run_job(j,pathlib.Path(d))
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_over_limit_private_only_and_rate_limit(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d);account(b,12345,'owner');b.public=pathlib.Path(d)/'public';b.public.mkdir()
   async def cmd(args,work,timeout):
    with (work/'source.mp3').open('wb') as f:f.truncate(m.MAX_RESULT+1)
    return json.dumps({'ok':True,'bitrate':192,'title':'Long'}).encode()
   b.run_cmd=cmd;work=b.jobs/'test';work.mkdir();await b.yandex_run_job(job(12345,'owner'),work);self.assertFalse(a.uploads);self.assertEqual(len(list((b.yamp/'12345').glob('*.mp3'))),1);self.assertFalse(list(b.public.iterdir()))
   b.access['approved']['999']={'name':'Peer'};account(b,999,'peer');b.rate[999]=[time.time()]*3;await b.yandex_prepare(999,'https://music.yandex.ru/track/456');key=next(iter(b.pending));await b.yandex_callback(999,['ym',key,'192'],{'message_id':1});self.assertEqual(b.queue.qsize(),0)
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_confirmation_is_bound_to_user(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner');account(b,999,'peer');await b.handle(callback(12345,'ya:disconnect'));nonce=b.yandex_confirm[12345][0]
   await b.handle(callback(999,'ya:confirm:'+nonce));self.assertTrue(b.yandex_ready(12345));self.assertTrue(b.yandex_ready(999))
   await b.handle(callback(12345,'ya:confirm:'+nonce));self.assertFalse(b.yandex_ready(12345));self.assertTrue(b.yandex_ready(999))
 @unittest.skipUnless(os.name=='posix','Requires POSIX credential permissions')
 async def test_device_flow_delivers_only_to_initiator_and_stores_secret_privately(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d);b.access['approved']['999']={'name':'Peer'};account(b,12345,'owner')
   class Proc:
    returncode=0
    def __init__(self):
     self.stdout=asyncio.StreamReader();self.stdout.feed_data(b'{"state":"awaiting_user","verification_url":"https://ya.ru/device","user_code":"testCODE","expires_in":300}\n{"state":"authorized"}\n');self.stdout.feed_eof()
    async def wait(self):return 0
   async def spawn(*args,**kw):
    out=pathlib.Path(args[args.index('--output')+1]);out.write_text(json.dumps({'access_token':'FAKE_SECRET_NEVER_DISPLAY','expires_at':time.time()+3600}));out.chmod(0o600);return Proc()
   with patch('asyncio.create_subprocess_exec',spawn):await b.yandex_authorize(999)
   self.assertTrue(b.yandex_ready(999));self.assertEqual(b.yandex_account(12345),'owner');self.assertEqual(b.yandex_credential(999).stat().st_mode&0o777,0o600)
   visible=json.dumps(a.calls);self.assertNotIn('FAKE_SECRET_NEVER_DISPLAY',visible)
   codes=[x for name,x in a.calls if name=='sendMessage' and 'testCODE' in x.get('text','')];self.assertEqual(len(codes),1);self.assertEqual(codes[0]['chat_id'],999);self.assertFalse(list(b.yandex_accounts.rglob('auth-*')))
if __name__=='__main__':unittest.main()
