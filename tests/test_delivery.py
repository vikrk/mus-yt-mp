import asyncio,unittest,tempfile,pathlib,importlib.util
p=pathlib.Path(__file__).resolve().parents[1]/'app'/'bot.py'
if not p.exists():p=p.with_name('bot.py')
spec=importlib.util.spec_from_file_location('b',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class API:
 def __init__(self,fail=False):self.messages=[];self.uploads=[];self.fail=fail
 def call(self,method,data=None,timeout=35):
  if method=='sendMessage':self.messages.append(data);return {'message_id':len(self.messages)}
  return True
 def upload(self,chat,path,fmt,title):
  self.uploads.append((chat,path.read_bytes(),fmt))
  if self.fail:raise m.ApiError('Test upload failure')
  return {'message_id':100}
class Tests(unittest.IsolatedAsyncioTestCase):
 async def check(self,fmt,fail):
  with tempfile.TemporaryDirectory() as d:
   a=API(fail);b=m.Bot(a,12345,d);b.public=pathlib.Path(d)/'public';b.public.mkdir()
   async def convert(job,work):
    out=work/('out.'+fmt);out.write_bytes(b'test-media');return out,'Test title'
   b.convert=convert;job={'user':12345,'format':fmt,'quality':'192' if fmt=='mp3' else '720'}
   task=asyncio.create_task(b.worker());await b.queue.put(job)
   await asyncio.wait_for(b.queue.join(),10);task.cancel()
   try:await task
   except asyncio.CancelledError:pass
   self.assertEqual(len(a.uploads),1);self.assertEqual(a.uploads[0][1],b'test-media');self.assertEqual(len(list(b.public.iterdir())),1)
   file=next(b.public.iterdir());self.assertEqual(file.suffix,'.'+fmt);self.assertEqual(file.read_bytes(),b'test-media');self.assertFalse(list(b.jobs.iterdir()))
   links=[x['text'] for x in a.messages if 'https://media.example.com/mp/' in x['text']];self.assertEqual(len(links),1);self.assertIn(file.name,links[0]);self.assertIn('публичной медиатеки',links[0])
 async def test_small_file_and_link_all_formats(self):
  for fmt in ['mp3','mp4','mkv']:await self.check(fmt,False)
 async def test_upload_failure_keeps_single_public_file(self):await self.check('mp3',True)
if __name__=='__main__':unittest.main()
