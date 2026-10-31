#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tapcalc.py - coordinate math before you tap or swipe.

  1) bounds -> center (from uiautomator or get_page_info)
     tapcalc.py bounds "[540,2280][720,2400]"
  2) image pixels -> device pixels (coordinates read off a shrunk screenshot)
     tapcalc.py img2dev 320 700 --image 574x1280 --screen 1080x2408
     tapcalc.py img2dev 320 700 --img ./shot_sm.jpg --screen 1080x2408
  3) device pixels -> image pixels (locate an element on the shrunk image)
     tapcalc.py dev2img 540 2340 --image 574x1280
  4) element lookup in a UI dump, with a ready-to-paste tap
     tapcalc.py find ./window_dump.xml --text "Login"
     tapcalc.py find dump.xml --id com.example:id/btn --contains
     tapcalc.py find dump.xml --list

Screen size comes from --screen, $TOKEN_TOOLS_SCREEN, or scripts/.screen.txt
(written by scripts/screen.sh). There is no silent default: a wrong scale factor
taps a few hundred pixels off, which is worse than an error message.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JSON = "--json" in sys.argv
if JSON:
    sys.argv.remove("--json")
SCREEN_CACHE = os.path.join(HERE, ".screen.txt")


def get_screen(explicit=None):
    if explicit:
        t = explicit.lower().replace(" ", "").replace("*", "x")
        p = t.split("x") if "x" in t else t.split(",")
        return int(p[0]), int(p[1])
    env = os.environ.get("TOKEN_TOOLS_SCREEN", "").strip()
    if env:
        m = re.search(r"(\d+)\s*[x*,]\s*(\d+)", env.lower())
        if m:
            return int(m.group(1)), int(m.group(2))
    if os.path.exists(SCREEN_CACHE):
        try:
            txt = open(SCREEN_CACHE).read().strip()
            m = re.search(r"(\d+)\s*[x*,]\s*(\d+)", txt.lower())
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    sys.stderr.write("no screen size: pass --screen WxH, set $TOKEN_TOOLS_SCREEN, "
                       "or run `sh scripts/screen.sh` once to create .screen.txt\n")
    sys.exit(2)


def parse_bounds(s):
    m = re.findall(r"-?\d+", s)
    if len(m) < 4:
        raise ValueError("bounds must look like [l,t][r,b], got: " + s)
    l, t, r, b = [int(x) for x in m[:4]]
    return l, t, r, b


def img_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception as e:
        raise ValueError("cannot read image size from %s (%s); pass --image WxH" % (path, e))


def out(d):
    """One line by default: the tap command plus the numbers behind it."""
    if JSON:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return
    if d.get("ok") is False:
        print("FAIL error=%s" % d.get("error", "unknown"))
        return
    els = d.get("elements")
    if els is not None:
        sc = d.get("screen") or (0, 0)
        print("screen=%dx%d n=%d" % (sc[0], sc[1], d.get("count", len(els))))
        for e in els:
            b = e["bounds"]
            label = (e.get("label") or e.get("cls", "").split(".")[-1])[:40]
            print("%-40s [%d,%d][%d,%d]  %s%s" % (
                label, b[0], b[1], b[2], b[3], e["tap"],
                "" if e.get("clickable") else " via=parent"))
        return
    tap = d.get("tap")
    if tap:
        extra = []
        if "size" in d:
            extra.append("%dx%d" % (d["size"][0], d["size"][1]))
        if "as_image_px_center" in d:
            extra.append("img=%s" % (d["as_image_px_center"],))
        print(tap + ("  (" + " ".join(extra) + ")" if extra else ""))
        return
    bits = []
    for k, v in d.items():
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        bits.append("%s=%s" % (k, v))
    print(" ".join(bits)[:400])


def cmd_bounds(a):
    l, t, r, b = parse_bounds(a.value)
    cx, cy = (l + r) // 2, (t + b) // 2
    res = {"bounds": [l, t, r, b], "center": [cx, cy], "size": [r - l, b - t],
           "tap": "input tap %d %d" % (cx, cy),
           "note": "center is already device pixels; if the bounds came from a shrunk image, convert with kx/ky first"}
    if a.image:
        iw, ih = a.image
        res["as_image_px_center"] = [int(round(cx * iw / float(get_screen(a.screen)[0]))),
                                     int(round(cy * ih / float(get_screen(a.screen)[1])))]
    out(res)


def crop_map(a):
    """Return (offset_x, offset_y, crop_w, crop_h) in device pixels. --crop x,y,w,h"""
    c = getattr(a, "crop", None)
    if c:
        v = [int(x) for x in re.findall(r"-?\d+", c)]
        if len(v) >= 4:
            return v[0], v[1], v[2], v[3]
    ox, oy = getattr(a, "crop_offset", None) or (0, 0)
    return ox, oy, None, None


def cmd_img2dev(a):
    sw, sh = get_screen(a.screen)
    if a.img:
        iw, ih = img_size(a.img)
    elif a.image:
        iw, ih = a.image
    else:
        raise ValueError("need --image WxH or --img <file>")
    ox, oy, cw, ch = crop_map(a)
    if cw and ch:                       # cropped: scale against the crop region
        kx, ky = cw / float(iw), ch / float(ih)
    else:
        kx, ky = (sw - 0) / float(iw), (sh - 0) / float(ih)
    dx, dy = int(round(ox + a.xy[0] * kx)), int(round(oy + a.xy[1] * ky))
    dx = max(0, min(sw - 1, dx))
    dy = max(0, min(sh - 1, dy))
    res = {"image_px": [a.xy[0], a.xy[1]], "image": [iw, ih], "screen": [sw, sh],
           "kx": round(kx, 4), "ky": round(ky, 4), "device_px": [dx, dy],
           "tap": "input tap %d %d" % (dx, dy)}
    if ox or oy or cw:
        res["crop"] = {"origin": [ox, oy], "size": [cw, ch] if cw else None}
    out(res)


def cmd_dev2img(a):
    sw, sh = get_screen(a.screen)
    if a.img:
        iw, ih = img_size(a.img)
    elif a.image:
        iw, ih = a.image
    else:
        raise ValueError("need --image WxH or --img <file>")
    ox, oy, cw, ch = crop_map(a)
    if cw and ch:
        px = int(round((a.xy[0] - ox) * iw / float(cw)))
        py = int(round((a.xy[1] - oy) * ih / float(ch)))
    else:
        px = int(round(a.xy[0] * iw / float(sw)))
        py = int(round(a.xy[1] * ih / float(sh)))
    out({"device_px": [a.xy[0], a.xy[1]], "image": [iw, ih], "screen": [sw, sh],
         "image_px": [px, py], "crop_origin": [ox, oy]})


NODE_RE = re.compile(r"<node\b[^>]*>", re.S)
ATTR_RE = re.compile(r'([a-zA-Z-]+)="([^"]*)"')


def parse_nodes(xml_text):
    """Parse a uiautomator dump; return (nodes, parent_of). nodes[i] carries idx/parent."""
    import xml.etree.ElementTree as ET
    nodes, parent_of = [], {}
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        root = None
    if root is not None:
        def walk(el, parent_idx):
            at = el.attrib
            b = at.get("bounds", "")
            idx = None
            if b:
                try:
                    l, t, r, bb = parse_bounds(b)
                except Exception:
                    l = t = r = bb = None
                if l is not None:
                    idx = len(nodes)
                    nodes.append({
                        "idx": idx, "parent": parent_idx,
                        "text": at.get("text", ""), "desc": at.get("content-desc", ""),
                        "rid": at.get("resource-id", ""), "cls": at.get("class", ""),
                        "clickable": at.get("clickable") == "true",
                        "scrollable": at.get("scrollable") == "true",
                        "enabled": at.get("enabled") != "false",
                        "bounds": [l, t, r, bb], "center": [(l + r) // 2, (t + bb) // 2],
                    })
            for ch in el:
                walk(ch, idx if idx is not None else parent_idx)
        walk(root, None)
    else:  # regex fallback (incomplete XML)
        for m in NODE_RE.finditer(xml_text):
            at = dict(ATTR_RE.findall(m.group(0)))
            b = at.get("bounds", "")
            if not b:
                continue
            try:
                l, t, r, bb = parse_bounds(b)
            except Exception:
                continue
            nodes.append({
                "idx": len(nodes), "parent": None,
                "text": at.get("text", ""), "desc": at.get("content-desc", ""),
                "rid": at.get("resource-id", ""), "cls": at.get("class", ""),
                "clickable": at.get("clickable") == "true",
                "scrollable": at.get("scrollable") == "true",
                "enabled": True,
                "bounds": [l, t, r, bb], "center": [(l + r) // 2, (t + bb) // 2],
            })
    by_idx = {n["idx"]: n for n in nodes}
    for n in nodes:
        p = n.get("parent")
        chain = []
        while p is not None and p in by_idx and len(chain) < 12:
            chain.append(by_idx[p])
            p = by_idx[p].get("parent")
        n["_ancestors"] = chain
    return nodes


def clickable_target(n):
    """Return the node or its nearest clickable ancestor, plus a note."""
    if n["clickable"]:
        return n["center"], None
    for a in n.get("_ancestors") or []:
        if a["clickable"]:
            return a["center"], ("the clickable target is the parent %s%s; tap its center %s"
                                 % (a["cls"], ("/" + a["rid"].split("/")[-1]) if a["rid"] else "",
                                    a["center"]))
    return n["center"], "no clickable ancestor; tapping the text center usually works (self-drawn UIs report clickable=false everywhere)"


def cmd_find(a):
    path = a.xml
    if not os.path.exists(path):
        out({"ok": False, "error": "no such file: " + path})
        return
    xml = open(path, "rb").read().decode("utf-8", "ignore")
    nodes = parse_nodes(xml)
    sw, sh = get_screen(a.screen)

    if a.list:
        keep = [n for n in nodes if (n["clickable"] or n["text"] or n["desc"])
                and (not a.no_offscreen or (0 <= n["center"][0] < sw and 0 <= n["center"][1] < sh))]
        res = []
        for n in keep:
            tgt, _note = clickable_target(n)
            res.append({"label": n["text"] or n["desc"] or n["rid"].split("/")[-1],
                        "cls": n["cls"], "clickable": n["clickable"],
                        "bounds": n["bounds"], "center": n["center"],
                        "tap": "input tap %d %d" % tuple(tgt)})
        if a.limit:
            res = res[:a.limit]
        out({"screen": [sw, sh], "count": len(res), "elements": res})
        return

    key = (a.text or a.id or a.desc or "").strip()
    if not key:
        out({"ok": False, "error": "need --text / --id / --desc / --list"})
        return
    k = key.lower()
    hits = []
    for n in nodes:
        if a.id:
            hay = n["rid"].lower()
        elif a.desc:
            hay = n["desc"].lower()
        else:
            hay = (n["text"] + " " + n["desc"]).strip().lower()
        if (k in hay) if a.contains else (hay == k):
            tgt, note = clickable_target(n)
            hits.append({"label": n["text"] or n["desc"] or n["rid"].split("/")[-1],
                         "cls": n["cls"], "clickable": n["clickable"],
                         "bounds": n["bounds"], "center": n["center"],
                         "tap": "input tap %d %d" % tuple(tgt),
                         "tap_target": tgt, "note": note})
    out({"screen": [sw, sh], "query": key, "count": len(hits),
         "elements": hits[:a.limit or 20]})


def main():
    ap = argparse.ArgumentParser(description="coordinate math and UI-dump element lookup")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--screen", help="device resolution WxH, defaults to .screen.txt")
        p.add_argument("--limit", type=int, help="max rows to print")

    p = sp.add_parser("bounds", help="bounds string -> center")
    p.add_argument("value")
    p.add_argument("--image", help="bounds are image pixels: give the image size WxH")
    common(p)

    p = sp.add_parser("img2dev", help="image pixels -> device pixels")
    p.add_argument("xy", nargs=2, type=int, metavar=("X", "Y"))
    p.add_argument("--image", help="image size WxH")
    p.add_argument("--img", help="image path (size read automatically, e.g. the shrunk _sm.jpg)")
    p.add_argument("--crop-offset", help="crop origin x,y to add (device pixels)")
    p.add_argument("--crop", help="pass the shrink --crop x,y,w,h this image came from")
    common(p)

    p = sp.add_parser("dev2img", help="device pixels -> image pixels")
    p.add_argument("xy", nargs=2, type=int, metavar=("X", "Y"))
    p.add_argument("--image", help="image size WxH")
    p.add_argument("--img", help="image path")
    p.add_argument("--crop", help="same as img2dev")
    common(p)

    p = sp.add_parser("find", help="find an element in a UI dump, print its tappable center")
    p.add_argument("xml")
    p.add_argument("--text", help="match text/content-desc")
    p.add_argument("--desc", help="match content-desc")
    p.add_argument("--id", help="match resource-id")
    p.add_argument("--contains", action="store_true", help="substring match (default is exact)")
    p.add_argument("--list", action="store_true", help="list every clickable/labelled element")
    p.add_argument("--no-offscreen", action="store_true", help="drop elements outside the screen")
    common(p)

    a = ap.parse_args()
    if getattr(a, "image", None):
        t = a.image.lower().replace(" ", "").replace("*", "x")
        p2 = t.split("x") if "x" in t else t.split(",")
        a.image = (int(p2[0]), int(p2[1]))
    if getattr(a, "crop_offset", None):
        v = [int(x) for x in re.findall(r"-?\d+", a.crop_offset)]
        a.crop_offset = (v[0], v[1])

    {"bounds": cmd_bounds, "img2dev": cmd_img2dev,
     "dev2img": cmd_dev2img, "find": cmd_find}[a.cmd](a)


if __name__ == "__main__":
    main()