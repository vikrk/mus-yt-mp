#!/usr/bin/python3
"""Private credential in, permitted MP3 only out. No public URL or token logging."""
import argparse,json,logging,os,pathlib,time
logging.disable(logging.CRITICAL)
def main():
 p=argparse.ArgumentParser();p.add_argument('--credential',required=True);p.add_argument('--track',required=True);p.add_argument('--album');p.add_argument('--quality',choices=['192','320'],required=True);a=p.parse_args()
 if not a.track.isdigit() or (a.album and not a.album.isdigit()):return {'ok':False,'reason':'invalid'}
 try:
  from yandex_music import Client
  credential=pathlib.Path(a.credential)
  if credential.is_symlink() or not credential.is_file() or credential.stat().st_mode&0o077:return {'ok':False,'reason':'auth'}
  secret=json.loads(credential.read_text())
  if secret.get('expires_at',0)<=time.time()+30:return {'ok':False,'reason':'auth'}
  client=Client(secret['access_token']).init(timeout=20)
  tracks=client.tracks([a.track+(':'+a.album if a.album else '')],timeout=20)
  if not tracks:return {'ok':False,'reason':'unavailable'}
  track=tracks[0];variants=track.get_download_info(timeout=20)
  variants=[v for v in variants if v.codec=='mp3' and isinstance(v.bitrate_in_kbps,int) and v.bitrate_in_kbps>0]
  if not variants:return {'ok':False,'reason':'unavailable'}
  requested=int(a.quality);chosen=next((v for v in variants if v.bitrate_in_kbps==requested),max(variants,key=lambda v:v.bitrate_in_kbps))
  track.download('source.mp3',codec='mp3',bitrate_in_kbps=chosen.bitrate_in_kbps,timeout=20)
  artists=', '.join(x.name for x in (track.artists or []) if x.name);title=(artists+' — ' if artists else '')+(track.title or 'Яндекс.Музыка')
  return {'ok':True,'bitrate':chosen.bitrate_in_kbps,'title':title}
 except Exception as e:return {'ok':False,'reason':'auth' if type(e).__name__ in ('UnauthorizedError','Unauthorized') else 'unavailable'}
if __name__=='__main__':print(json.dumps(main(),ensure_ascii=False))
