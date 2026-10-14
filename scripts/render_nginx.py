#!/usr/bin/python3
"""Render the media virtual host without shell expansion of nginx variables."""
import argparse,pathlib,re

def render(domain,template):
    if not isinstance(domain,str) or len(domain)>253 or '.' not in domain or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in domain.split('.')):
        raise ValueError('Invalid domain')
    if '@DOMAIN@' not in template:raise ValueError('Missing domain placeholder')
    return template.replace('@DOMAIN@',domain.lower())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('domain');parser.add_argument('template');parser.add_argument('output');args=parser.parse_args()
    text=render(args.domain,pathlib.Path(args.template).read_text())
    target=pathlib.Path(args.output);target.write_text(text);target.chmod(0o644)
