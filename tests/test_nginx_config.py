import importlib.util,json,os,pathlib,shutil,socket,subprocess,tempfile,time,unittest,urllib.request,urllib.error

ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
renderer=module('render_nginx');migration=module('upgrade_nginx')

class ConfigTests(unittest.TestCase):
 def test_domain_validation_and_preserved_nginx_variables(self):
  template=(ROOT/'config/nginx.conf.template').read_text()
  self.assertIn('server_name media.example.com;',renderer.render('MEDIA.EXAMPLE.COM',template))
  for domain in ['example.com; return 200;','-bad.example.com','a..com','a/b.com','x\n.example.com']:
   with self.assertRaises(ValueError):renderer.render(domain,template)
 def test_migration_preserves_tls(self):
  legacy='server {\n    listen 443 ssl;\n    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;\n    location /mp/ {\n        alias /var/lib/yt-media-bot/public/;\n        autoindex off;\n    }\n}\n'
  updated=migration.upgrade(legacy)
  self.assertIn('listen 443 ssl;',updated);self.assertIn('ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;',updated)
  self.assertIn(migration.INCLUDE,updated);self.assertEqual(migration.upgrade(updated),updated)
  with self.assertRaises(ValueError):migration.upgrade('server { location /mp/ { proxy_pass http://custom; } }')

@unittest.skipUnless(shutil.which('nginx'),'nginx binary required for HTTP integration')
class HTTPTests(unittest.TestCase):
 def test_catalog_playback_ranges_and_private_files(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);public=root/'public';public.mkdir();web=root/'web';web.mkdir()
   (web/'index.html').write_text('<title>Media Library</title>');(public/'track.mp3').write_bytes(b'0123456789')
   (public/'.hidden.mp3').write_bytes(b'secret');(public/'token.json').write_text('{}')
   (root/'private.mp3').write_bytes(b'private');(public/'linked.mp3').symlink_to(root/'private.mp3')
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   routes=(ROOT/'config/nginx-media.locations').read_text().replace('/var/lib/yt-media-bot/public/',str(public)+'/').replace('/opt/yt-media-bot/web/index.html',str(web/'index.html'))
   temp_paths=' '.join(f'{kind}_temp_path {root}/{kind};' for kind in ['client_body','proxy','fastcgi','uwsgi','scgi'])
   worker_user='user root;\n' if getattr(os,'geteuid',lambda:1)()==0 else ''
   conf=root/'nginx.conf';conf.write_text(worker_user+f'pid {root}/nginx.pid;\nerror_log {root}/error.log;\nevents {{}}\nhttp {{ access_log off; {temp_paths} server {{ listen 127.0.0.1:{port}; disable_symlinks on; {routes} location / {{ return 404; }} }} }}')
   subprocess.run(['nginx','-t','-p',str(root),'-c',str(conf)],check=True,capture_output=True)
   process=subprocess.Popen(['nginx','-p',str(root),'-c',str(conf),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   base=f'http://127.0.0.1:{port}'
   try:
    for _ in range(50):
     try:
      with urllib.request.urlopen(base+'/mp/',timeout=1) as response:self.assertIn(b'Media Library',response.read())
      break
     except urllib.error.URLError:time.sleep(.1)
    else:self.fail('nginx did not become ready: '+(root/'error.log').read_text())
    with urllib.request.urlopen(base+'/mp/_catalog/') as response:catalog=json.load(response)
    self.assertIn('track.mp3',[row['name'] for row in catalog]);self.assertNotIn('.hidden.mp3',[row['name'] for row in catalog])
    request=urllib.request.Request(base+'/mp/track.mp3',headers={'Range':'bytes=2-5'})
    with urllib.request.urlopen(request) as response:
     self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345');self.assertEqual(response.headers['Content-Type'],'audio/mpeg');self.assertEqual(response.headers['Content-Disposition'],'inline')
    for path in ['/mp/.hidden.mp3','/mp/token.json','/mp/linked.mp3','/yandex-accounts/token.json','/yamp/123/track.mp3']:
     with self.subTest(path=path),self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+path)
     self.assertIn(error.exception.code,(403,404))
   finally:
    process.terminate();process.wait(timeout=5)
