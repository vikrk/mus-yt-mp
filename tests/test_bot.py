import asyncio,importlib.util,json,pathlib,tempfile,time,unittest,os
p=pathlib.Path(__file__).resolve().parents[1]/'app'/'bot.py'
if not p.exists():p=p.with_name('bot.py')
spec=importlib.util.spec_from_file_location('media_bot',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class FakeAPI:
 def __init__(self):self.calls=[]
 def call(self,method,data=None,timeout=35):self.calls.append((method,data));return {'message_id':1}
def msg(uid,text,kind='private'):
 return {'message':{'chat':{'id':uid,'type':kind},'from':{'id':uid,'first_name':'Test'},'text':text}}
def callback(uid,data):
 return {'callback_query':{'id':'test','from':{'id':uid,'first_name':'Test'},'message':{'message_id':1,'chat':{'id':uid,'type':'private'}},'data':data}}
class Tests(unittest.IsolatedAsyncioTestCase):
 def test_urls(self):
  self.assertEqual(m.video_url('https://youtu.be/BaW_jenozKc?t=1'),'https://www.youtube.com/watch?v=BaW_jenozKc')
  for u in ['file:///etc/passwd','http://127.0.0.1','https://youtube.com@127.0.0.1/watch?v=BaW_jenozKc','https://youtube.com.evil/watch?v=BaW_jenozKc','https://youtube.com/playlist?list=x','https://youtu.be/BaW_jenozKc ;id']:
   with self.assertRaises(m.UserError):m.video_url(u)
 async def test_request_owner_approval_and_persistence(self):
  with tempfile.TemporaryDirectory() as d:
   a=FakeAPI();b=m.Bot(a,12345,d)
   await b.handle(msg(999,'https://youtu.be/BaW_jenozKc'));self.assertEqual(b.queue.qsize(),0);self.assertFalse(b.allowed(999))
   await b.handle(callback(999,'access:request'));nonce=b.access['pending']['999']['nonce']
   await b.handle(callback(999,'usr:approve:999:'+nonce));self.assertFalse(b.allowed(999))
   await b.handle(callback(12345,'usr:approve:999:'+nonce));self.assertTrue(b.allowed(999))
   c=m.Bot(a,12345,d);self.assertTrue(c.allowed(999))
   await c.handle(callback(12345,'usr:revoke:999'));self.assertFalse(c.allowed(999))
 async def test_quality_and_no_cross_user_buttons(self):
  with tempfile.TemporaryDirectory() as d:
   a=FakeAPI();b=m.Bot(a,12345,d);b.access['approved']['999']={'name':'Test'}
   await b.handle(msg(12345,'https://youtu.be/BaW_jenozKc'));key=next(iter(b.pending))
   await b.handle(callback(12345,'fmt:'+key+':mp3'));self.assertEqual(b.queue.qsize(),0)
   await b.handle(callback(12345,'fmt:'+key+':mkv'))
   menu=a.calls[-1][1]['reply_markup']['inline_keyboard']
   self.assertTrue(any(btn.get('callback_data')=='q:'+key+':mkv:2160' for row in menu for btn in row))
   self.assertEqual(set(m.FORMATS),{'mp3','mp4','mkv'})
   await b.handle(callback(999,'q:'+key+':mp3:320'));self.assertEqual(b.queue.qsize(),0)
   await b.handle(callback(12345,'q:'+key+':mp3:999'));self.assertEqual(b.queue.qsize(),0)
   await b.handle(callback(12345,'q:'+key+':mp3:320'));self.assertEqual(b.queue.qsize(),1)
   job=await b.queue.get();self.assertEqual(job['quality'],'320');self.assertEqual(job['user'],12345)
 async def test_groups_cannot_use_bot_or_owner_controls(self):
  with tempfile.TemporaryDirectory() as d:
   a=FakeAPI();b=m.Bot(a,12345,d)
   await b.handle(msg(12345,'https://youtu.be/BaW_jenozKc','group'))
   self.assertEqual(a.calls,[]);self.assertEqual(b.pending,{})
 async def test_user_cancel_preserves_others(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(FakeAPI(),12345,d);b.access['approved']['999']={'name':'Test'}
   await b.queue.put({'user':12345});await b.queue.put({'user':999})
   b.active={'user':12345,'format':'mp3','quality':'192'}
   await b.handle(msg(999,'/cancel'));self.assertFalse(b.cancel.is_set());self.assertEqual(b.queue.qsize(),1);self.assertEqual((await b.queue.get())['user'],12345)
 async def test_private_upload_failure_archive_and_quota(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(FakeAPI(),12345,d);b.archive.mkdir();out=pathlib.Path(d)/'large.mp4'
   with out.open('wb') as f:f.truncate(m.MAX_RESULT)
   job={'user':12345,'format':'mp4','quality':'1080'}
   path,size=b.archive_result(out,job,'Test');self.assertTrue(path.startswith(str(b.archive)));self.assertEqual(size,50_000_000);self.assertFalse(out.exists())
   target=b.archive/pathlib.Path(path).name;self.assertTrue(target.exists())
   if os.name=='posix':self.assertEqual(target.stat().st_mode&0o777,0o600)
   out.write_bytes(b'x');old=m.MAX_ARCHIVE;m.MAX_ARCHIVE=1
   try:
    with self.assertRaises(m.UserError):b.archive_result(out,job,'Test')
    self.assertTrue(out.exists())
   finally:m.MAX_ARCHIVE=old
 async def test_quality_conversion_arguments_and_mkv4k(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(FakeAPI(),12345,d);w=pathlib.Path(d)/'test';w.mkdir();calls=[];duration=635
   async def cmd(args,work,timeout):
    calls.append(args)
    if '--dump-single-json' in args:return json.dumps({'duration':duration,'title':'Test'}).encode()
    if args[0]==m.YTDLP:(work/'input.webm').write_bytes(b'test')
    elif args[0]=='/usr/bin/ffprobe':return json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','height':720},{'codec_type':'audio','codec_name':'aac'}]}).encode()
    else:pathlib.Path(args[-1]).write_bytes(b'output')
    return b''
   b.run_cmd=cmd
   await b.convert({'url':'https://youtu.be/BaW_jenozKc','format':'mp3','quality':'320','user':12345},w)
   self.assertIn('320k',calls[-1])
   await b.convert({'url':'https://youtu.be/BaW_jenozKc','format':'mp4','quality':'1080','user':12345},w)
   self.assertIn('copy',calls[-1]);self.assertTrue(any('height<=1080' in x for x in calls[-2] if isinstance(x,str)) or any('height<=1080' in x for call in calls for x in call if isinstance(x,str)))
   await b.convert({'url':'https://youtu.be/BaW_jenozKc','format':'mkv','quality':'2160','user':12345},w)
   self.assertIn('matroska',calls[-1]);self.assertIn('copy',calls[-1]);self.assertTrue(any('height<=2160' in x for call in calls for x in call if isinstance(x,str)))
if __name__=='__main__':unittest.main()
