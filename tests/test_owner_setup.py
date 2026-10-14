import importlib.util,pathlib,unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('owner_setup',pathlib.Path(__file__).resolve().parents[1]/'scripts'/'token_setup.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def update(uid=101,text='/start',date=100,kind='private',bot=False,chat_id=None):
 return {'update_id':7,'message':{'date':date,'text':text,'from':{'id':uid,'is_bot':bot,'username':'example_user'},'chat':{'type':kind,'id':uid if chat_id is None else chat_id}}}

class OwnerSetupTests(unittest.TestCase):
 def test_fresh_private_start_returns_telegram_id(self):
  self.assertEqual(m.owner_from_update(update(),100)['id'],101)
 def test_old_group_bot_and_unrelated_messages_rejected(self):
  for item in [update(date=99),update(kind='group'),update(bot=True),update(text='/help'),update(uid=True),update(uid=-1),update(chat_id=999),{'callback_query':{}},update(text=123)]:
   with self.subTest(item=item):self.assertIsNone(m.owner_from_update(item,100))
 def test_confirmation_required_and_old_queue_skipped(self):
  calls=[];responses=[[dict(update(),update_id=4)],[update(uid=202),dict(update(uid=303),update_id=8)]]
  def api(method,data):calls.append((method,data));return responses.pop(0)
  with patch.object(m.time,'time',return_value=100),patch('builtins.input',side_effect=['NO','YES']):
   self.assertEqual(m.discover_owner(api,'example_bot'),303)
  self.assertEqual(calls[0][1]['offset'],-1);self.assertEqual(calls[1][1]['offset'],5)
 def test_no_start_times_out_without_assigning_owner(self):
  with patch.object(m.time,'monotonic',side_effect=[0,301]):
   with self.assertRaises(SystemExit):m.discover_owner(lambda *args:[],'example_bot')
