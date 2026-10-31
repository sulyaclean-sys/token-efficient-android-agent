#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zoom.py - look at ONE problem region instead of the whole screen.

Fallback of last resort: when a human says "this bit is wrong" and you already
know where that bit is, do not read the full screenshot. Read the patch.

usage:
  zoom.py IMG --rect X,Y,W,H [--pad 8] [--zoom 2] [--grid 50]
  zoom.py IMG --from-dump dump.xml --text "Save" [--contains] [--all]
  zoom.py IMG --from-dump dump.xml --cls Button --all

Output (one line):
  /path/bug_patch.jpg 412x136 108tok dev=88,1180 412x136 kx=1.00 ky=1.00
  dev=... is where this patch starts in device pixels; kx/ky map a pixel inside
the patch back to the device: dev_x = 88 + img_x * kx.
Add --json for the full report. Exit 0 ok, 1 failed.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shrink as S  # bill_tokens / solve_for_tokens / encode_with_alpha / CAP
import uicheck as U  # load_nodes


def fail(msg, **kv):
    print('FAIL ' + msg + ''.join(' %s=%s' % (k, v) for k, v in kv.items()))
    return 1


def nums(s):
    return [int(x) for x in re.findall(r'-?\d+', s)]


def rect_from_dump(path, a):
    nodes = U.load_nodes(path)
    hits = []
    for n in nodes:
        if a.text:
            t = n.text or ''
            if (a.text in t) if a.contains else (t == a.text):
                hits.append(n)
        elif a.cls:
            if a.cls.lower() in (n.cls or '').lower():
                hits.append(n)
    if not hits:
        return None
    if a.all:
        return (min(n.b[0] for n in hits), min(n.b[1] for n in hits),
                max(n.b[2] for n in hits), max(n.b[3] for n in hits))
    n = min(hits, key=lambda x: x.area)  # smallest match = the actual text/leaf
    return n.b


def main():
    ap = argparse.ArgumentParser(prog='zoom.py', description='crop the one region that is wrong')
    ap.add_argument('img')
    ap.add_argument('--rect', help='X,Y,W,H in device pixels')
    ap.add_argument('--from-dump', help='uiautomator XML: take the rect from a matched node')
    ap.add_argument('--text', help='match node text (exact unless --contains)')
    ap.add_argument('--contains', action='store_true')
    ap.add_argument('--cls', help='match node class substring')
    ap.add_argument('--all', action='store_true', help='union of all matches')
    ap.add_argument('--pad', type=int, default=8, help='padding in device px (default 8)')
    ap.add_argument('--zoom', type=float, default=1.0, help='magnify the patch (default 1.0)')
    ap.add_argument('--tokens', type=int, default=420, help='token budget for the patch (default 420)')
    ap.add_argument('--min-side', type=int, default=0, help='min output side in px')
    ap.add_argument('--grid', type=int, default=0, help='draw device-pixel grid every N px')
    ap.add_argument('--format', default='jpeg', choices=['jpeg', 'webp', 'png'])
    ap.add_argument('--quality', type=int, default=90)
    ap.add_argument('--out', help='output path (default <img>_patch.<ext>)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    try:
        from PIL import Image, ImageDraw
    except Exception:
        return fail('no-pillow', hint='pip install pillow')

    if not os.path.exists(a.img):
        return fail('no-image', img=a.img)
    with Image.open(a.img) as im:
        im = im.convert('RGB')
        IW, IH = im.size
        if a.rect:
            v = nums(a.rect)
            if len(v) < 4:
                return fail('bad-rect', need='X,Y,W,H')
            x, y, w, h = v[:4]
        elif a.from_dump:
            b = rect_from_dump(a.from_dump, a)
            if not b:
                return fail('no-match', dump=os.path.basename(a.from_dump),
                            hint='tapcalc.py find --list')
            x, y, w, h = b[0], b[1], b[2] - b[0], b[3] - b[1]
        else:
            return fail('need-rect', hint='--rect X,Y,W,H or --from-dump dump.xml --text ...')
        p = max(0, a.pad)
        x, y = max(0, x - p), max(0, y - p)
        w, h = min(IW - x, w + 2 * p), min(IH - y, h + 2 * p)
        if w <= 0 or h <= 0:
            return fail('bad-rect', rect='%d,%d,%d,%d' % (x, y, w, h), img='%dx%d' % (IW, IH))
        work = im.crop((x, y, x + w, y + h)).copy()

    warns = []
    if a.zoom and a.zoom != 1.0:
        nw, nh = max(1, int(round(w * a.zoom))), max(1, int(round(h * a.zoom)))
        work = work.resize((nw, nh), Image.LANCZOS)
        warns.append('UPSCALE x%.2f' % a.zoom) if a.zoom > 1 else None
    mside = a.min_side or S.MIN_OUT_SIDE
    if max(work.size) > S.CAP:
        k = S.CAP / float(max(work.size))
        work = work.resize((max(1, int(work.size[0] * k)), max(1, int(work.size[1] * k))), Image.LANCZOS)
        warns.append('CAP %d' % S.CAP)
    if S.bill_tokens(*work.size) > a.tokens:
        tw, th, k, over = S.solve_for_tokens(work.size[0], work.size[1], a.tokens, min_side=mside)
        work = work.resize((tw, th), Image.LANCZOS)
        if over:
            warns.append('TOKEN-floor')

    if a.grid:
        d = ImageDraw.Draw(work, 'RGBA')
        kx, ky = w / float(work.size[0]), h / float(work.size[1])
        g = a.grid
        dx = (g - (x % g)) % g
        while dx < w:
            ix = int(dx / kx)
            d.line([(ix, 0), (ix, work.size[1])], fill=(255, 0, 0, 110))
            d.text((ix + 2, 2), str(x + dx), fill=(255, 0, 0, 220))
            dx += g
        dy = (g - (y % g)) % g
        while dy < h:
            iy = int(dy / ky)
            d.line([(0, iy), (work.size[0], iy)], fill=(0, 128, 255, 110))
            d.text((2, iy + 1), str(y + dy), fill=(0, 128, 255, 220))
            dy += g

    fmt = {'jpeg': 'JPEG', 'webp': 'WEBP', 'png': 'PNG'}[a.format]
    ext = {'JPEG': '.jpg', 'WEBP': '.webp', 'PNG': '.png'}[fmt]
    outp = a.out or (os.path.splitext(a.img)[0] + '_patch' + ext)
    blob = S.encode_with_alpha(work, fmt, a.quality)
    with open(outp, 'wb') as f:
        f.write(blob)

    tok = S.bill_tokens(*work.size)
    kx, ky = w / float(work.size[0]), h / float(work.size[1])
    if a.json:
        print(json.dumps({'ok': True, 'out': outp, 'size': list(work.size), 'tokens': tok,
                          'dev': [x, y, w, h], 'kx': round(kx, 4), 'ky': round(ky, 4),
                          'bytes': len(blob), 'warn': warns}, indent=2))
        return 0
    line = '%s %dx%d %dtok dev=%d,%d %dx%d kx=%.2f ky=%.2f' % (
        outp, work.size[0], work.size[1], tok, x, y, w, h, kx, ky)
    if warns:
        line += '  WARN ' + ','.join(warns)
    print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
