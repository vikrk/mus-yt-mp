#!/usr/bin/env python3
"""Download official release assets and verify GitHub's SHA256 digest."""
import hashlib, io, json, os, pathlib, urllib.request, zipfile

def request(url):
    req=urllib.request.Request(url,headers={'User-Agent':'yt-media-installer','Accept':'application/vnd.github+json'})
    return urllib.request.urlopen(req,timeout=120)

def install(repo,version,asset_name,destination,member=None):
    endpoint='latest' if version=='latest' else 'tags/'+version
    with request('https://api.github.com/repos/'+repo+'/releases/'+endpoint) as response:
        release=json.load(response)
    asset=next(a for a in release['assets'] if a['name']==asset_name)
    digest=asset.get('digest') or ''
    if not digest.startswith('sha256:'):raise SystemExit('No SHA256 digest for '+asset_name+'; select a release with GitHub asset digests.')
    with request(asset['browser_download_url']) as response: raw=response.read()
    if hashlib.sha256(raw).hexdigest()!=digest.split(':',1)[1]:raise SystemExit('Checksum mismatch: '+asset_name)
    data=zipfile.ZipFile(io.BytesIO(raw)).read(member) if member else raw
    path=pathlib.Path(destination);tmp=path.with_name(path.name+'.download')
    tmp.write_bytes(data);tmp.chmod(0o755);tmp.replace(path)
    print(repo,release['tag_name'],asset_name,digest,flush=True)

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run as root')
    install('yt-dlp/yt-dlp',os.environ.get('YTDLP_VERSION','latest'),'yt-dlp_linux','/usr/local/bin/yt-dlp')
    install('denoland/deno',os.environ.get('DENO_VERSION','latest'),'deno-x86_64-unknown-linux-gnu.zip','/usr/local/bin/deno','deno')
    install('XTLS/Xray-core',os.environ.get('XRAY_VERSION','latest'),'Xray-linux-64.zip','/opt/yt-media-bot/xray','xray')
