import unittest,tempfile,pathlib,importlib.util,time,asyncio
p=pathlib.Path(__file__).resolve().parents[1]/'app'/'bot.py'
if not p.exists():p=p.with_name('bot.py')
spec=importlib.util.spec_from_file_location('media_bot',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class API:
 def __init__(self):self.calls=[];self.ids={}
 def call(self,name,data=None,timeout=35):
  self.calls.append((name,data))
  if name=='sendMessage':
   c=data['chat_id'];self.ids[c]=self.ids.get(c,0)+1;return {'message_id':self.ids[c]}
  return True
def cb(uid,data,mid):return {'callback_query':{'id':'test','from':{'id':uid},'message':{'message_id':mid,'chat':{'id':uid,'type':'private'}},'data':data}}
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_access_auto_cleanup_only_technical(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d)
   await b.closed(999);await b.request_access(999,{'first_name':'Test'})
   nonce=b.access['pending']['999']['nonce'];owner_request=a.ids[12345]
   await b.handle(cb(12345,'usr:approve:999:'+nonce,owner_request))
   deletes=[x[1] for x in a.calls if x[0]=='deleteMessages']
   self.assertTrue(any(x['chat_id']==999 for x in deletes));self.assertTrue(any(x['chat_id']==12345 for x in deletes))
   self.assertTrue(b.allowed(999));self.assertTrue(b.access['cleanup'])
   await b.send('Do not delete conversion/file message',chat=999);regular=a.ids[999]
   for x in b.access['cleanup']:x['due']=time.time()-1
   await b.pump_cleanup()
   deleted=[mid for name,data in a.calls if name=='deleteMessages' and data['chat_id']==999 for mid in data['message_ids']]
   self.assertNotIn(regular,deleted)
 async def test_admin_owner_only_requires_confirmation(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d);b.access['approved']['999']={'name':'Test'}
   b.record_message(999,77)
   await b.handle(cb(999,'adm:all',10));self.assertFalse(b.admin_confirm);self.assertFalse(any(n.startswith('delete') for n,_ in a.calls))
   await b.handle(cb(12345,'adm:all',20));self.assertTrue(b.admin_confirm);self.assertFalse(any(n.startswith('delete') for n,_ in a.calls))
   token=next(iter(b.admin_confirm));await b.handle(cb(999,'adm:confirm:'+token,21));self.assertIn(token,b.admin_confirm)
   await b.handle(cb(12345,'adm:confirm:'+token,21));await asyncio.sleep(.05)
   self.assertTrue(any(n=='deleteMessages' and q['chat_id']==999 and 77 in q['message_ids'] for n,q in a.calls))
 async def test_cleanup_survives_restart_and_skips_old_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   a=API();b=m.Bot(a,12345,d)
   b.record_message(999,5);b.queue_cleanup(999,5,30);b.record_message(999,6,time.time()-49*3600)
   c=m.Bot(a,12345,d);self.assertEqual(len(c.access['cleanup']),1)
   self.assertFalse(any(r['id']==6 for r in c.deletion_rows('all')))
   c.access['cleanup'][0]['due']=time.time()-1;await c.pump_cleanup();self.assertFalse(c.access['cleanup'])
if __name__=='__main__':unittest.main()
