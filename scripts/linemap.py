#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""linemap.py - print a compact line map of files so an agent can jump by line number
instead of reading whole files.
linemap.py - print where headings/defs are, so an agent reads a line range instead of the file.

usage:
  linemap.py FILE...              # auto: headings for .md, defs for .py, usage lines for .sh
  linemap.py --mode md docs/*.md  # md | code | sh
  linemap.py --docstring a.py     # docstring line ranges

output: one line per section ->  <path>  <start>-<end>  <title>
"""
import argparse
import os
import re

MD = re.compile(r'^(#{1,6})[ ]+(.*)$')
CODE = re.compile(r'^([ 	]*)(?:async[ ]+)?(?:def|class|func|function|fn)[ ]+([A-Za-z_][A-Za-z0-9_]*)')
USAGE = re.compile(r'^#[ ]*[Uu]sage')
Q3 = chr(34) * 3


def md_map(lines):
    hits = [(i + 1, len(m.group(1)), m.group(2).strip()) for i, l in enumerate(lines)
            for m in [MD.match(l)] if m]
    out = []
    for k, (ln, depth, title) in enumerate(hits):
        end = hits[k + 1][0] - 1 if k + 1 < len(hits) else len(lines)
        out.append((ln, end, '  ' * (depth - 1) + title))
    return out


def code_map(lines):
    hits = [(i + 1, m.group(1), m.group(2)) for i, l in enumerate(lines)
            for m in [CODE.match(l)] if m]
    out = []
    for k, (ln, indent, name) in enumerate(hits):
        end = hits[k + 1][0] - 1 if k + 1 < len(hits) else len(lines)
        out.append((ln, end, indent + name))
    return out


def sh_map(lines):
    return [(i + 1, i + 1, l.strip()[:100]) for i, l in enumerate(lines) if USAGE.match(l)]


def docstring_map(lines):
    pos = [i + 1 for i, l in enumerate(lines) if Q3 in l]
    return [(pos[i], pos[i + 1], 'docstring') for i in range(0, len(pos) - 1, 2)]


def pick(path):
    ext = os.path.splitext(path)[1].lower()
    return {'.md': 'md', '.py': 'code', '.sh': 'sh'}.get(ext, 'md')


def main():
    ap = argparse.ArgumentParser(description='print a line map instead of the file')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--mode', choices=['auto', 'md', 'code', 'sh'], default='auto')
    ap.add_argument('--docstring', action='store_true')
    ap.add_argument('--max', type=int, default=400, help='max output lines (default 400)')
    a = ap.parse_args()
    n = 0
    for p in a.files:
        if not os.path.exists(p):
            print('MISS ' + p)
            continue
        lines = open(p, encoding='utf-8', errors='replace').read().split(chr(10))
        mode = pick(p) if a.mode == 'auto' else a.mode
        if a.docstring:
            rows = docstring_map(lines)
        elif mode == 'md':
            rows = md_map(lines)
        elif mode == 'code':
            rows = code_map(lines)
        else:
            rows = sh_map(lines)
        for s, e, t in rows:
            name = p if len(p) <= 42 else os.path.basename(p)
            print('%-42s %5d-%-5d %s' % (name, s, e, t))
            n += 1
            if n >= a.max:
                print('... truncated at --max %d' % a.max)
                return


if __name__ == '__main__':
    main()
