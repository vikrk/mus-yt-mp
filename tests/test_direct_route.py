import unittest,tempfile,pathlib,json,unittest.mock as mock
import bot as m
class API:
 proxy_url='http://example-private-proxy.invalid:18189'
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_youtube_proxy_yandex_direct(self):
  with tempfile.TemporaryDirectory() as d:
   with mock.patch.dict(m.os.environ,{'http_proxy':'http://bad.invalid','HTTPS_PROXY':'http://bad.invalid','ALL_PROXY':'socks5://bad.invalid'}):
    api=API();b=m.Bot(api,12345,d)
   self.assertFalse(any(k.lower() in ('http_proxy','https_proxy','all_proxy','no_proxy','ftp_proxy') for k in b.childenv));self.assertEqual(b.api.proxy_url,API.proxy_url)
   self.assertEqual(b.youtube_env['https_proxy'],API.proxy_url);self.assertNotIn('ALL_PROXY',b.youtube_env)
   work=pathlib.Path(d)/'test';work.mkdir();calls=[]
   async def cmd(args,work,timeout):
    calls.append(args)
    if args[0]==m.YTDLP:self.assertNotIn('--proxy',args)
    if '--dump-single-json' in args:return json.dumps({'duration':3600,'title':'Direct test'}).encode()
    if args[0]==m.YTDLP:(work/'input.webm').write_bytes(b'test')
    else:pathlib.Path(args[-1]).write_bytes(b'test-output')
    return b''
   b.run_cmd=cmd;await b.convert({'url':'https://youtu.be/BaW_jenozKc','format':'mp3','quality':'192','user':12345},work)
   self.assertEqual(len([c for c in calls if c[0]==m.YTDLP]),2)
 async def test_subprocess_receives_source_specific_environment(self):
  with tempfile.TemporaryDirectory() as d:
   b=m.Bot(API(),12345,d)
   class Process:
    returncode=0
    async def communicate(self):return b'ok',b''
   with mock.patch('asyncio.create_subprocess_exec',new_callable=mock.AsyncMock,return_value=Process()) as spawn:
    await b.run_cmd([m.YTDLP,'--version'],pathlib.Path(d),5)
    self.assertEqual(spawn.call_args.kwargs['env']['https_proxy'],API.proxy_url)
    await b.run_cmd(['/opt/yt-media-bot/yandex-venv/bin/python','yandex_download.py'],pathlib.Path(d),5)
    self.assertFalse(any(k.lower() in ('http_proxy','https_proxy','all_proxy') for k in spawn.call_args.kwargs['env']))
if __name__=='__main__':unittest.main()
