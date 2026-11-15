"""Fingerprint the effective layout written by the standard brain service before startup."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

from board.layout import overlay


def fingerprint(repo, check_written=False):
    repo = Path(repo).resolve()
    selectors = [os.environ['RADIO_SIGHT_NODES']] if 'RADIO_SIGHT_NODES' in os.environ else []
    env = repo / '.env'
    if env.exists():
        chosen = None
        for line in env.read_text().splitlines():
            match = re.match(r'\s*(?:export\s+)?RADIO_SIGHT_NODES\s*=\s*(.*)',line)
            if match:
                values = shlex.split(match[1],comments=True)
                if len(values)>1: raise ValueError('cannot resolve RADIO_SIGHT_NODES in .env')
                chosen = values[0] if values else ''
        if chosen is not None: selectors.append(chosen)
    expected = (repo/'data/nodes.local.json').resolve()
    for selector in selectors:
        if not selector or (repo/selector).resolve()!=expected:
            raise ValueError('nonstandard RADIO_SIGHT_NODES is not verified; use the standard brain service layout')
    nodes = json.loads((repo/'radio/nodes.json').read_text())
    saved = repo/'data/layout.local.json'
    placement = json.loads(saved.read_text()) if saved.exists() else {}
    if not isinstance(nodes,dict) or not isinstance(placement,dict): raise ValueError('invalid layout configuration')
    effective = overlay(nodes,placement)
    canonical = json.dumps(effective,sort_keys=True,separators=(',',':'),allow_nan=False)
    if check_written and expected.exists():
        written = json.dumps(json.loads(expected.read_text()),sort_keys=True,separators=(',',':'),allow_nan=False)
        if written!=canonical: raise ValueError('generated layout disagrees; restart and take a fresh baseline before saving')
    return hashlib.sha256(canonical.encode()).hexdigest()


if __name__=='__main__':
    try:
        print(fingerprint(sys.argv[1], '--save' in sys.argv[2:]))
    except (OSError,ValueError,TypeError,AttributeError) as error:
        raise SystemExit(f'keep: cannot fingerprint effective layout: {error}') from None
