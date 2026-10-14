import os
import unittest,asyncio,pathlib,tempfile,json
import bot as m
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_reuse_metadata_and_four_fragments(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(None,12345,d);work=pathlib.Path(d)/'test';work.mkdir();calls=[];url='https://youtu.be/BaW_jenozKc'
   async def cmd(args,work,timeout):
    calls.append(args)
    if '--dump-single-json' in args:return json.dumps({'duration':3600,'title':'Test','id':'BaW_jenozKc'}).encode()
    if args[0]==m.YTDLP:
     self.assertIn('--load-info-json',args);self.assertNotIn(url,args)
     p=pathlib.Path(args[args.index('--load-info-json')+1]);self.assertEqual(json.loads(p.read_text())['id'],'BaW_jenozKc');self.assertEqual(p.stat().st_mode&0o777,0o600 if os.name=='posix' else 0o666)
     self.assertEqual(args[args.index('--concurrent-fragments')+1],'4');(work/'input.webm').write_bytes(b'test')
    else:pathlib.Path(args[-1]).write_bytes(b'test-output')
    return b''
   b.run_cmd=cmd;await b.convert({'url':url,'format':'mp3','quality':'320','user':12345},work)
   self.assertEqual(sum('--dump-single-json' in c for c in calls),1);self.assertIn('320k',calls[-1])
if __name__=='__main__':unittest.main()
