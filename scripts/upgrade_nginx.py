#!/usr/bin/python3
"""Replace the legacy media location while preserving certbot's TLS settings."""
import pathlib,re,sys
INCLUDE='    include /etc/nginx/snippets/yt-media-locations.conf;\n'

def upgrade(source):
    if INCLUDE.strip() in source:return source
    pattern=r'(?m)^    location /mp/ \{\n(?:[^\n]*\n)*?    \}\n'
    matches=list(re.finditer(pattern,source))
    if len(matches)!=1:raise ValueError('Unrecognized media nginx configuration; migrate the /mp/ locations manually')
    block=matches[0].group()
    if 'alias /var/lib/yt-media-bot/public/;' not in block or 'autoindex off;' not in block:raise ValueError('Custom media location; manual migration required')
    return source[:matches[0].start()]+INCLUDE+source[matches[0].end():]

if __name__=='__main__':
    original=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2]);target.write_text(upgrade(original.read_text()));target.chmod(0o644)
