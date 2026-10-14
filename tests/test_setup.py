import importlib.util,json,pathlib,tempfile,unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('setup_wizard',pathlib.Path(__file__).resolve().parents[1]/'scripts'/'setup.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SetupTests(unittest.TestCase):
 def test_failed_subscription_never_reaches_token(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'config.json').write_text('{}')
   with patch.object(m,'ROOT',root),patch.object(m.os,'geteuid',return_value=0,create=True),patch('builtins.input',return_value='1'),patch.object(m.subprocess,'run',side_effect=m.subprocess.CalledProcessError(1,'network check')) as run:
    with self.assertRaises(m.subprocess.CalledProcessError):m.main()
    self.assertEqual(run.call_count,1)
 def test_subscription_checks_finish_before_token(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'config.json').write_text('{}');calls=[]
   with patch.object(m,'ROOT',root),patch.object(m,'DROPIN',root/'dropin'/'media-proxy.conf'),patch.object(m.os,'geteuid',return_value=0,create=True),patch('builtins.input',return_value='1'),patch.object(m.subprocess,'run',side_effect=lambda args,**kw:calls.append(args)):
    m.main()
   self.assertEqual(calls[0],['/usr/local/sbin/yt-media-vpn-setup','--configure-only'])
   self.assertEqual(calls[-1],['/usr/local/sbin/yt-media-token-setup'])
 def test_direct_api_failure_never_configures_bot(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'config.json').write_text('{}')
   with patch.object(m,'ROOT',root),patch.object(m.os,'geteuid',return_value=0,create=True),patch('builtins.input',return_value='2'),patch.object(m,'direct_api_check',side_effect=SystemExit('unreachable')),patch.object(m.subprocess,'run') as run:
    with self.assertRaises(SystemExit):m.main()
    run.assert_not_called()
 def test_direct_mode_skips_subscription(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'config.json').write_text('{"proxy_enabled":true}');calls=[]
   with patch.object(m,'ROOT',root),patch.object(m,'DROPIN',root/'dropin.conf'),patch.object(m.os,'geteuid',return_value=0,create=True),patch('builtins.input',return_value='2'),patch.object(m,'direct_api_check',side_effect=lambda:calls.append(['api-check'])),patch.object(m.subprocess,'run',side_effect=lambda args,**kw:calls.append(args)):
    m.main()
   self.assertEqual(calls[0],['api-check']);self.assertFalse(any('vpn-setup' in ' '.join(x) for x in calls))
   self.assertFalse(json.loads((root/'config.json').read_text())['proxy_enabled'])
   self.assertEqual(calls[-1],['/usr/local/sbin/yt-media-token-setup'])
