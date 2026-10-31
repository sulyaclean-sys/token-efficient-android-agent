#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py - prove the toolchain works on THIS machine, in one line.

  python3 scripts/selftest.py       ->  OK selftest 10/10

No device, no network. Everything happens on synthetic fixtures in a temp dir.
If a case fails it prints the case name and the tool's first output line.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

def run(args, expect_rc=0):
    env = dict(os.environ, TOKEN_TOOLS_SCREEN='1080x2408')
    p = subprocess.run([PY] + args, cwd=HERE, env=env, capture_output=True, text=True)
    out = (p.stdout or p.stderr or '').strip()
    return p.returncode, out

def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print('FAIL pillow-missing: pip install -r requirements.txt')
        return 1

    d = tempfile.mkdtemp(prefix='tokentools-')
    png = os.path.join(d, 'full.png')
    xml = os.path.join(d, 'full.xml')
    md = os.path.join(d, 'doc.md')

    im = Image.new('RGB', (1080, 2408), '#ffffff')
    g = ImageDraw.Draw(im)
    g.rectangle([80, 1170, 520, 1330], fill='#eef4ff', outline='#3366cc')
    g.text((100, 1240), 'BILL 12.34', fill='#223344')
    im.save(png)
    Image.new('RGB', (400, 3), '#f5f5f5').save(os.path.join(d, 'uniform.png'))
    line = Image.new('RGB', (400, 3), '#f5f5f5')
    for x in range(400):
        line.putpixel((x, 1), (0x33, 0x33, 0x33))
    line.save(os.path.join(d, 'line.png'))

    def node(cls, b, text='', clickable='true'):
        return '<node class="%s" bounds="[%d,%d][%d,%d]" text="%s" clickable="%s"/>' % (
            cls, b[0], b[1], b[2], b[3], text, clickable)

    nav = ''.join(node('Button', b, 'i%d' % i) for i, b in enumerate([
        (24, 2210, 252, 2400), (300, 2210, 528, 2400),
        (576, 2210, 804, 2400), (852, 2210, 1056, 2400)]))
    open(xml, 'w').write(
        '<?xml version="1.0"?><hierarchy rotation="0">'
        '<node class="Root" bounds="[0,0][1080,2408]">'
        '<node class="Card" bounds="[80,1170][520,1330]">'
        '<node class="TextView" bounds="[100,1200][400,1240]" text="BILL 12.34" clickable="false"/>'
        '</node><node class="Nav" bounds="[24,2200][1056,2408]">%s</node>'
        '</node></hierarchy>' % nav)
    open(md, 'w').write(chr(10).join(['# Title', '', 'text', '', '## Section', '', 'body', '']))

    cases = [
        ('shrink',      ['shrink.py', png, '--format', 'jpeg'], 0, r'_sm\.jpg\s+\d+tok'),
        ('shrink-json', ['shrink.py', png, '--json'], 0, '"billed"'),
        ('bounds',      ['tapcalc.py', 'bounds', '[60,1420][1020,1560]'], 0, r'^input tap 540 1490'),
        ('find-text',   ['tapcalc.py', 'find', xml, '--text', 'BILL 12.34'], 0, 'input tap'),
        ('find-list',   ['tapcalc.py', 'find', xml, '--list'], 0, r'^screen=1080x2408 n=\d+'),
        ('uchecks-row', ['uicheck.py', 'row', xml, '--band', '2200,2408', '--expect', '4'], 0, r'^OK row'),
        ('uicheck-px',  ['uicheck.py', 'px', os.path.join(d, 'line.png'), '--rect', '0,0,400,3'], 0, r'^OK px'),
        ('zoom',        ['zoom.py', png, '--from-dump', xml, '--text', 'BILL 12.34'], 0, 'dev='),
        ('linemap',     ['linemap.py', md], 0, 'Section'),
    ]
    # negative cases: must fail loudly, not silently pass
    negatives = [
        ('px-uniform', ['uicheck.py', 'px', os.path.join(d, 'uniform.png'), '--rect', '0,0,400,3'], 'FAIL px'),
        ('zoom-miss',  ['zoom.py', png, '--from-dump', xml, '--text', 'no-such-text'], 'FAIL no-match'),
    ]

    n = ok = 0
    for name, args, rc, pat in cases:
        n += 1
        code, out = run(args)
        if code == rc and re.search(pat, out, re.M):
            ok += 1
        else:
            print('FAIL %s :: rc=%d out=%s' % (name, code, out.splitlines()[0] if out else ''))
    for name, args, pat in negatives:
        n += 1
        code, out = run(args)
        if code != 0 and pat in out:
            ok += 1
        else:
            print('FAIL %s :: rc=%d out=%s' % (name, code, out.splitlines()[0] if out else ''))

    print('%s selftest %d/%d' % ('OK' if ok == n else 'FAIL', ok, n))
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
