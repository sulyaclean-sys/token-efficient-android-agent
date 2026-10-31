#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uicheck.py - turn "it looks wrong" into one line of OK/FAIL.

row  UI-dump XML  -> items in a band: spacing, symmetry, overlap, count, min touch width
px   rendered img -> is the thing you declared actually drawn? (pixel truth)

Both print ONE line:  OK key=v ...   or   FAIL reason key=v ...
Exit code 0 = pass, 1 = fail. Add --json for the raw numbers.

Why: a geometry/DOM check proves an element EXISTS; the user's question is almost
always whether it is VISIBLE. And measuring a gap never tells you which of the two
neighbours moved. These are the two checks that closed those gaps in practice;
see docs/verification.md.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BOUNDS = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')


JOUT = {'on': False}  # --json: same verdict, machine-readable


def fail(msg, **kv):
    if JOUT['on']:
        d = {'ok': False, 'fail': msg}
        d.update(kv)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 1
    print('FAIL ' + msg + ''.join(' %s=%s' % (k, v) for k, v in kv.items()))
    return 1


def ok(msg, **kv):
    if JOUT['on']:
        d = {'ok': True, 'result': msg}
        d.update(kv)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    print('OK ' + msg + ''.join(' %s=%s' % (k, v) for k, v in kv.items()))
    return 0


# ---------------------------------------------------------------- xml
class Node(object):
    __slots__ = ('b', 'text', 'clickable', 'cls', 'depth')

    def __init__(self, b, text, clickable, cls, depth):
        self.b, self.text, self.clickable, self.cls, self.depth = b, text, clickable, cls, depth

    @property
    def area(self):
        return max(0, self.b[2] - self.b[0]) * max(0, self.b[3] - self.b[1])

    def contains(self, o):
        return (self.b[0] <= o.b[0] and self.b[1] <= o.b[1]
                and self.b[2] >= o.b[2] and self.b[3] >= o.b[3])


def load_nodes(path):
    root = ET.parse(path).getroot()
    out = []

    def walk(el, depth):
        for ch in el:
            if ch.tag != 'node':
                walk(ch, depth)
                continue
            m = BOUNDS.search(ch.get('bounds', ''))
            if m:
                out.append(Node(tuple(int(x) for x in m.groups()), ch.get('text', ''),
                                ch.get('clickable') == 'true',
                                (ch.get('class') or '').split('.')[-1], depth))
            walk(ch, depth + 1)

    walk(root, 0)
    return out


def screen_from_nodes(nodes):
    """Width of the window: first node in document order is the root."""
    if not nodes:
        return None
    return max(nodes[0].b[2], 1)


def row_items(nodes, band):
    t0, t1 = band
    cands = [n for n in nodes if n.area > 0 and t0 <= (n.b[1] + n.b[3]) // 2 <= t1]
    keep = []
    for n in cands:
        if any(o is not n and n.contains(o) and o.area < n.area for o in cands):
            continue  # ancestor of another candidate
        keep.append(n)
    keep.sort(key=lambda n: n.b[0])
    return keep


def cmd_row(a):
    nodes = load_nodes(a.dump)
    items = row_items(nodes, a.band)
    if not items:
        return fail('row empty', band='%d,%d' % a.band,
                    hint='wrong band? try tapcalc.py find --list')
    lefts = [n.b[0] for n in items]
    rights = [n.b[2] for n in items]
    widths = [max(1, n.b[2] - n.b[0]) for n in items]
    gaps = [lefts[i + 1] - rights[i] for i in range(len(items) - 1)]
    sw = a.screen or screen_from_nodes(nodes) or rights[-1]
    lp, rp = lefts[0], sw - rights[-1]
    issues = []
    if a.expect and len(items) != a.expect:
        issues.append(('count', 'n=%d want=%d' % (len(items), a.expect)))
    for i, g in enumerate(gaps):
        if g < 0:
            issues.append(('overlap', 'item%d.right=%d > item%d.left=%d'
                          % (i + 1, rights[i], i + 2, lefts[i + 1])))
            break
    if gaps and min(gaps) >= 0:
        skew = max(gaps) - min(gaps)
        if skew > a.tol:
            issues.append(('gap', '%s skew=%d' % (','.join(str(g) for g in gaps), skew)))
    if abs(lp - rp) > a.tol:
        issues.append(('asym', 'lp=%d rp=%d delta=%d (%s side short of content)'
                       % (lp, rp, abs(lp - rp), 'right' if rp > lp else 'left')))
    for i, w in enumerate(widths):
        if w < a.min_w:
            issues.append(('narrow', 'item%d w=%d < %d' % (i + 1, w, a.min_w)))
            break
    kv = dict(n=len(items), gap=('%d..%d' % (min(gaps), max(gaps)) if gaps else '-'),
              lp=lp, rp=rp, w='%d..%d' % (min(widths), max(widths)))
    if a.json:
        print(json.dumps({'ok': not issues, 'issues': issues, 'metrics': kv,
                          'items': [{'b': n.b, 'text': n.text, 'cls': n.cls} for n in items]},
                         ensure_ascii=False, indent=2))
        return 0 if not issues else 1
    if not issues:
        return ok('row', **kv)
    for k, v in issues[:3]:
        fail('%s %s' % (k, v), n=kv['n'])
    return 1


# ---------------------------------------------------------------- pixels
def rel_lum(c):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(c1, c2):
    l1, l2 = rel_lum(c1), rel_lum(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def hexc(c):
    return '#%02x%02x%02x' % c


def modal(pixels):
    counts = {}
    for p in pixels:
        counts[p] = counts.get(p, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])


def cmd_px(a):
    try:
        from PIL import Image
    except Exception:
        return fail('no-pillow', hint='pip install pillow')
    x, y, w, h = a.rect
    with Image.open(a.img) as im:
        im = im.convert('RGB')
        if x + w > im.size[0] or y + h > im.size[1]:
            return fail('rect-outside', img='%dx%d' % im.size, rect='%d,%d,%d,%d' % (x, y, w, h))
        px = [[im.getpixel((x + i, y + j)) for i in range(w)] for j in range(h)]
    bg, _ = modal([p for row in px for p in row])
    rows = []
    for j, row in enumerate(px):
        c, cnt = modal(row)
        rows.append((j, c, contrast(c, bg), cnt / float(w)))
    best = max(rows, key=lambda r: r[2])
    if best[2] < a.min_cr and best[1] == bg:
        return fail('px uniform', rect='%dx%d' % (w, h), all=hexc(bg),
                    why='nothing drawn: covered / opacity 0 / clipped / same color')
    j, c, cr, cover = best
    if cr < a.min_cr:
        return fail('px faint', row=j, fg=hexc(c), bg=hexc(bg), cr='%.2f' % cr,
                    why='contrast below %s, invisible in practice' % a.min_cr)
    if cover < a.min_cover:
        return fail('px partial', row=j, fg=hexc(c), cr='%.2f' % cr,
                    cover='%.2f' % cover, why='dashed or clipped')
    if cr < 3:
        print('WARN px low-contrast row=%d %s/%s cr=%.2f cover=%.2f'
              % (j, hexc(c), hexc(bg), cr, cover))
        return 0
    return ok('px', row=j, fg=hexc(c), bg=hexc(bg), cr='%.2f' % cr, cover='%.2f' % cover)


def main():
    ap = argparse.ArgumentParser(prog='uicheck.py', description='one-line OK/FAIL for layout and visibility')
    sp = ap.add_subparsers(dest='cmd', required=True)

    r = sp.add_parser('row', help='items in a horizontal band: spacing / symmetry / overlap')
    r.add_argument('dump')
    r.add_argument('--band', required=True, help='T,B device pixels (vertical band to scan)')
    r.add_argument('--expect', type=int, help='expected item count')
    r.add_argument('--tol', type=int, default=2, help='allowed px skew (default 2)')
    r.add_argument('--min-w', type=int, default=0, help='min item width in px')
    r.add_argument('--screen', type=int, help='screen width in px (default: from dump)')
    r.add_argument('--json', action='store_true')
    r.set_defaults(func=cmd_row)

    p = sp.add_parser('px', help='is it actually drawn? sample the rendered pixels')
    p.add_argument('img')
    p.add_argument('--rect', required=True, help='X,Y,W,H device pixels')
    p.add_argument('--min-cr', type=float, default=1.5, help='min contrast ratio (default 1.5)')
    p.add_argument('--min-cover', type=float, default=0.6, help='min row coverage (default 0.6)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_px)

    a = ap.parse_args()
    JOUT['on'] = bool(getattr(a, 'json', False))
    if getattr(a, 'band', None):
        v = [int(t) for t in re.findall(r'-?\d+', a.band)]
        a.band = (v[0], v[1]) if len(v) >= 2 else (v[0], v[0] + 1)
    if getattr(a, 'rect', None):
        v = [int(t) for t in re.findall(r'-?\d+', a.rect)]
        if len(v) < 4:
            print('FAIL bad-rect need X,Y,W,H'); return 2
        a.rect = (v[0], v[1], v[2], v[3])
    try:
        return a.func(a)
    except Exception as e:
        return fail('error', what='%s: %s' % (type(e).__name__, e))


if __name__ == '__main__':
    sys.exit(main())
