import asyncio,unittest,tempfile,pathlib,importlib.util,json
p=pathlib.Path(__file__).resolve().parents[1]/'app'/'bot.py'
if not p.exists():p=p.with_name('bot.py')
spec=importlib.util.spec_from_file_location('b',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.IsolatedAsyncioTestCase):
 async def trial(self,duration,live=False):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(None,12345,d);work=pathlib.Path(d)/'test';work.mkdir();calls=[]
   async def cmd(args,work,timeout):
    calls.append((args,timeout))
    if '--dump-single-json' in args:return json.dumps({'duration':duration,'is_live':live,'title':'Long test'}).encode()
    if args[0]==m.YTDLP:(work/'input.webm').write_bytes(b'test')
    else:pathlib.Path(args[-1]).write_bytes(b'test-output')
    return b''
   b.run_cmd=cmd
   out,title=await b.convert({'url':'https://youtu.be/BaW_jenozKc','format':'mp3','quality':'192','user':12345},work)
   self.assertTrue(out.is_file());self.assertTrue(all(x[1]<=21600 for x in calls));return calls
 async def test_no_recording_duration_cap(self):
  for seconds in (1801,3600,14400,86400):
   calls=await self.trial(seconds);self.assertGreaterEqual(calls[1][1],1800)
 async def test_live_unknown_invalid_rejected(self):
  for duration,live in [(3600,True),(None,False),(0,False),(float('nan'),False),(float('inf'),False)]:
   with self.assertRaises(m.UserError):await self.trial(duration,live)
if __name__=='__main__':unittest.main()
