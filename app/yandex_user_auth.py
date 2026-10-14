#!/usr/bin/python3
"""Unprivileged device auth; only public verification data on stdout."""
import argparse,json,logging,os,pathlib,time,urllib.parse
logging.disable(logging.CRITICAL)
def emit(d):print(json.dumps(d,ensure_ascii=False),flush=True)
def main():
 os.umask(0o077);p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output)
 try:
  from yandex_music import Client
  if out.exists() or out.is_symlink() or out.parent.is_symlink():raise ValueError('unsafe output')
  def on_code(code):
   url=str(code.verification_url);u=urllib.parse.urlsplit(url)
   if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.query or u.fragment or not (u.hostname in ('oauth.yandex.ru','oauth.yandex.com') or (u.hostname=='ya.ru' and u.path=='/device')):raise ValueError('unexpected OAuth host')
   emit({'state':'awaiting_user','verification_url':url,'user_code':str(code.user_code),'expires_in':min(300,int(code.expires_in))})
  client=Client();token=client.device_auth(on_code=on_code,timeout=300,device_name='YT Media personal music');client.init(timeout=20)
  if not token.access_token or int(token.expires_in)<=0:raise ValueError('invalid token')
  fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:json.dump({'access_token':token.access_token,'refresh_token':getattr(token,'refresh_token',None),'expires_at':time.time()+int(token.expires_in),'created':time.time()},f)
  emit({'state':'authorized'})
 except Exception:emit({'state':'failed'});return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
