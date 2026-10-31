#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shrink.py - shrink a screenshot to a token budget (saves image tokens)

Image input is billed by PIXEL DIMENSIONS, not by KB: a 27 KB JPEG and a 110 KB JPEG of
the same size cost the same tokens. Compressing bytes optimises something that is not
billed and pays for it with blurrier text, so the objective is the smallest size that
still keeps UI detail legible -- expressed as --tokens / --preset.

Design:
  1) presets are token budgets; ui (default, ~419 tok) stays legible for small CJK text
  2) long side capped at 1568 (upstream rescales anyway; extra pixels only cost bytes)
  3) short side has a 200 px floor, reported as TOKEN-floor instead of shipping mush
  4) image pixels -> device pixels, ready for input tap / swipe
  5) --crop zooms one region, far cheaper than raising the budget for the whole screen
  6) --grid/--mark/--box annotate in device pixels: read and measure in one round-trip

Runs on Linux / macOS / proot with Python 3 + Pillow. Device resolution comes from
--screen, $TOKEN_TOOLS_SCREEN, or scripts/.screen.txt (written by scripts/screen.sh).
"""

import argparse
import io
import json
import math
import os
import re
import sys

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception:  # pragma: no cover
    sys.stderr.write('{"ok": false, "error": "Pillow missing: pip install pillow"}\n')
    sys.exit(2)

# ---------------------------------------------------------------- presets
# max_side=0 means "do not resize" (format/quality only)
# Values can be edited right here, or overridden in scripts/shrink.conf ("ui=820,75"),
# or from the command line --max-side/--quality (precedence: CLI > conf > here).
# Billing is per IMAGE DIMENSION, not KB -- so presets are token budgets, not sides/quality.
# "tokens" is already cap-adjusted (long side >1568 is pre-scaled to 1568): the real billed number.
# Calibrated on one 1080x2408 / 480dpi phone with CJK UI text, checked preset by preset:
#   tok 414 (379x820) all small CJK legible / tok 301 (323x700) borderline / tok 236 (286x620) blurred.
# Re-calibrate once per device/font size: edit this table or scripts/shrink.conf only (docs/token-cost.md).
PRESETS = {
    # default: smallest size that still keeps app-UI detail legible (1080x2408 -> ~378x820, tok~410)
    "ui":     {"tokens": 420,  "quality": 90, "sharpen": 120},
    # dense small text / tables / logs (-> ~450x980, tok~590)
    "dense":  {"tokens": 600,  "quality": 90, "sharpen": 110},
    # pixel-peeping small text (-> ~570x1240, tok~890)
    "detail": {"tokens": 900,  "quality": 90, "sharpen": 90},
    # layout and positions only, small text not guaranteed (-> ~320x700, tok~290)
    "scan":   {"tokens": 300,  "quality": 92, "sharpen": 135},
    # "which screen is this" only (-> ~210x460, tok~125)
    "thumb":  {"tokens": 130,  "quality": 92, "sharpen": 150},
    # ceiling: bigger is not billed more (upstream caps at 1568); not for daily use
    "max":    {"tokens": 1631, "quality": 92, "sharpen": 0},
    # legacy aliases for the same presets
    "large":  {"tokens": 900,  "quality": 90, "sharpen": 90},
    "tiny":   {"tokens": 300,  "quality": 92, "sharpen": 135},
    "orig":   {"tokens": 1631, "quality": 92, "sharpen": 0},
}
# short-side floor: below this, more tokens do not buy legibility
CAP = 1568            # upstream long-side cap; pixels beyond it are pure byte cost
MIN_OUT_SIDE = 200
# Bytes are not billed, so KB is not managed by default (no --target-kb = no quality drop).
# Need a soft ceiling anyway: --target-kb 180 lowers quality only, never the size.
DEFAULT_PRESET = "ui"          # change this to change the permanent default
CONF_NAME = "shrink.conf"      # same directory as this script; overrides default/presets
ENV_PRESET = "SHRINK_PRESET"   # temporary override via environment variable

CJK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

SCREEN_CACHE = os.environ.get("SCREEN_CACHE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".screen.txt")


def get_cached_screen():
    """Device resolution sources: $TOKEN_TOOLS_SCREEN > scripts/.screen.txt (or $SCREEN_CACHE).

    .screen.txt is written by scripts/screen.sh (wm size); re-run it after a rotation.
    """
    env = os.environ.get("TOKEN_TOOLS_SCREEN", "").strip()
    m = re.search(r"(\d+)\s*[x*,]\s*(\d+)", env.lower())
    if m:
        return int(m.group(1)), int(m.group(2))
    try:
        if os.path.exists(SCREEN_CACHE):
            m = re.search(r"(\d+)\s*[x*,]\s*(\d+)", open(SCREEN_CACHE).read().lower())
            if m:
                return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def load_conf():
    """Read scripts/shrink.conf:
         default = ui            # default preset
         ui      = 820,75        # max_side,quality
         large   = 1280,82
       Returns the default preset name. Missing file / bad lines are ignored."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONF_NAME)
    default = DEFAULT_PRESET
    if not os.path.exists(p):
        return default
    try:
        for line in open(p, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if not line or "=" not in line:
                continue
            k, v = [x.strip() for x in line.split("=", 1)]
            if k.lower() == "default":
                default = v or default
                continue
            nums = [int(x) for x in re.findall(r"\d+", v)]
            if k not in PRESETS or not nums:
                continue
            e = dict(PRESETS[k])
            # conf: 1st number = token budget, 2nd = quality, 3rd = sharpen
            if v.lstrip().startswith("max_side=") or "max_side" in v:
                e.pop("tokens", None)          # legacy form: a stale token value would win
                e["max_side"] = nums[0]
                if len(nums) > 1: e["quality"] = nums[1]
                e.setdefault("sharpen", 110)
            else:
                e["tokens"] = nums[0]
                if len(nums) > 1: e["quality"] = nums[1]
                if len(nums) > 2: e["sharpen"] = nums[2]
            PRESETS[k] = e
    except Exception:
        pass
    return default


def load_font(size):
    for p in CJK_FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def parse_wh(s):
    """'1080x2408' / '1080,2408' -> (1080, 2408)"""
    if not s:
        return None
    t = s.lower().replace(" ", "").replace("*", "x")
    parts = t.split("x") if "x" in t else t.split(",")
    if len(parts) != 2:
        raise ValueError("size must be WxH, e.g. 1080x2408")
    return int(parts[0]), int(parts[1])


def parse_nums(s, n):
    v = [int(round(float(x))) for x in s.replace("\uff0c", ",").split(",") if x != ""]
    if len(v) != n:
        raise ValueError("need %d numbers: %s" % (n, s))
    return v


def split_nums_label(s, n):
    """'540,2340,home' -> ([540,2340], 'home'); '60,200,400,280' -> ([...], None)
    also accepts space separation: '540 2340 home'"""
    parts = [p for p in s.replace("\uff0c", ",").replace(" ", ",").split(",") if p != ""]
    nums, label = [], None
    for i, p in enumerate(parts):
        try:
            nums.append(int(round(float(p))))
        except ValueError:
            label = ",".join(parts[i:])
            break
    if len(nums) < n:
        raise ValueError("need %d numbers: %s" % (n, s))
    return nums[:n], label


def bill_tokens(w, h):
    """The number actually billed: a long side above the upstream cap (1568) is pre-scaled."""
    s = 1.0
    L = max(w, h)
    if L > 1568:
        s = 1568.0 / L
    return int(round(w * s * h * s / 750.0)) + 1


def solve_for_tokens(w0, h0, target, min_side=MIN_OUT_SIDE, cap=CAP):
    """Largest output size that stays within `target` billed tokens without breaking min_side.
    tokens ~ area, so solve along the input aspect ratio; a fixed max_side is far off for tall images.
    If hitting the target would break min_side (mushy text), keep min_side and report over budget."""
    if bill_tokens(w0, h0) <= target:
        if cap and max(w0, h0) > cap:             # billing unchanged, but saves wasted pixels
            k = cap / float(max(w0, h0))
            return max(1, int(round(w0 * k))), max(1, int(round(h0 * k))), k, False
        return w0, h0, 1.0, False
    L0 = float(max(w0, h0))
    ratio = min(w0, h0) / L0                 # <= 1
    L_floor = min_side / ratio               # long side when the short side is exactly min_side
    if L_floor > L0:
        L_floor = L0
    # Upstream rescales anything above 1568; extra pixels cost bytes and add an uncontrolled resample
    hi = int(min(L0, cap if cap else L0))
    lo = int(math.ceil(L_floor))
    if lo > hi:
        lo = hi
    while lo <= hi:
        mid = (lo + hi) // 2
        k = mid / L0
        w, h = max(1, int(round(w0 * k))), max(1, int(round(h0 * k)))
        if bill_tokens(w, h) <= target:
            best = (w, h, k)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:                          # hitting the target would blur -> keep the readable floor
        k = L_floor / L0
        best = (max(1, int(round(w0 * k))), max(1, int(round(h0 * k))), k)
        return best[0], best[1], best[2], True
    return best[0], best[1], best[2], False


def est_tokens(w, h):
    """Rough token estimate (model-dependent; only for comparing relative gains).
    claude: scale the long side to <=1568 first, then tokens ~= w*h/750
    qwen/gpt(28px patch): tokens ~= ceil(w/28)*ceil(h/28)
    """
    s = 1.0
    long_side = max(w, h)
    if long_side > 1568:
        s = 1568.0 / long_side
    tw, th = w * s, h * s
    return {
        "claude_like": int(round(tw * th / 750.0)) + 1,
        "patch28_like": int(math.ceil(tw / 28) * math.ceil(th / 28)),
    }


def flatten_alpha(im, bg=(255, 255, 255)):
    if im.mode == "RGB":
        return im
    has_alpha = ("A" in im.mode) or (im.mode == "P" and "transparency" in im.info)
    rgba = im.convert("RGBA")
    out = Image.new("RGB", rgba.size, bg)
    if has_alpha:
        out.paste(rgba, (0, 0), rgba)
    else:
        out.paste(rgba.convert("RGB"), (0, 0))
    return out


def draw_overlay(im, screen, grid_step, marks, boxes, opacity=55):
    """Overlay a device-pixel grid/markers. screen=(w,h) is the real device resolution.
    Composited on a translucent layer so the grid does not cover UI text (OCR/vision).
    opacity: grid line alpha 0-255, lower = fainter."""
    sw, sh = screen
    iw, ih = im.size
    sx, sy = iw / float(sw), ih / float(sh)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fsize = max(11, int(min(iw, ih) / 42))
    font = load_font(fsize)
    line = (255, 0, 128, max(20, min(255, opacity)))
    txtbg = (255, 255, 255, 200)

    if grid_step:
        step = grid_step
        x = 0
        while x <= sw:
            px = x * sx
            d.line([(px, 0), (px, ih)], fill=line, width=1)
            lab = str(int(x))
            w0 = d.textlength(lab, font=font)
            d.rectangle([min(px + 1, iw - w0 - 4), 0, min(px + w0 + 4, iw), fsize + 4], fill=txtbg)
            d.text((min(px + 2, iw - w0 - 3), 1), lab, fill=(180, 0, 90), font=font)
            x += step
        y = 0
        while y <= sh:
            py = y * sy
            d.line([(0, py), (iw, py)], fill=line, width=1)
            lab = str(int(y))
            w0 = d.textlength(lab, font=font)
            d.rectangle([0, min(py + 1, ih - fsize - 4), w0 + 4, min(py + fsize + 4, ih)], fill=txtbg)
            d.text((2, min(py + 2, ih - fsize - 2)), lab, fill=(180, 0, 90), font=font)
            y += step

    for b in boxes:
        x1, y1, x2, y2 = b["x"] * sx, b["y"] * sy, b["x2"] * sx, b["y2"] * sy
        d.rectangle([x1, y1, x2, y2], outline=(0, 160, 255), width=3)
        if b.get("label"):
            w0 = d.textlength(b["label"], font=font)
            d.rectangle([x1, max(0, y1 - fsize - 4), x1 + w0 + 4, y1], fill=(0, 160, 255))
            d.text((x1 + 2, max(0, y1 - fsize - 3)), b["label"], fill=(255, 255, 255), font=font)

    for m in marks:
        px, py = m["x"] * sx, m["y"] * sy
        r = max(10, int(min(iw, ih) / 40))
        d.ellipse([px - r, py - r, px + r, py + r], outline=(255, 40, 40), width=3)
        d.line([(px - r * 2, py), (px + r * 2, py)], fill=(255, 40, 40), width=2)
        d.line([(px, py - r * 2), (px, py + r * 2)], fill=(255, 40, 40), width=2)
        lab = m.get("label") or ("%d,%d" % (m["x"], m["y"]))
        w0 = d.textlength(lab, font=font)
        d.rectangle([px + r + 2, py - fsize, px + r + 6 + w0, py + 3], fill=(255, 255, 255, 230))
        d.text((px + r + 4, py - fsize + 1), lab, fill=(200, 0, 0, 255), font=font)
    # translucent composite: faint grid, crisp label text
    return Image.alpha_composite(im.convert("RGBA"), layer)


def has_real_alpha(im):
    """Only genuinely translucent pixels count as alpha (RGBA after the grid overlay is opaque)."""
    if im.mode == "P":
        return "transparency" in im.info
    if "A" not in im.mode:
        return False
    try:
        a = im.getchannel("A")
        lo, hi = a.getextrema()
        return lo < 250
    except Exception:
        return True


def encode(im, fmt, quality, method=None, ss=None):
    """ss=0 -> JPEG 4:4:4. The default 4:2:0 smears coloured glyph edges, and bytes are not billed."""
    buf = io.BytesIO()
    if fmt == "JPEG":
        kw = dict(quality=quality, optimize=True, progressive=True)
        if ss is not None:      # some Pillow builds accept int only; skip entirely when None
            kw["subsampling"] = ss
        im.save(buf, "JPEG", **kw)
    elif fmt == "WEBP":
        im.save(buf, "WEBP", quality=quality, method=6)
    elif fmt == "PNG8":
        tmp = im.convert("RGB")
        q = tmp.quantize(colors=256)
        q.save(buf, "PNG", optimize=True)
    elif fmt == "PNG":
        im.save(buf, "PNG", optimize=True)
    else:
        raise ValueError("unknown format " + fmt)
    return buf.getvalue()


def encode_with_alpha(im, fmt, quality, ss=None):
    """webp/png keep alpha; jpeg needs a flattened background."""
    if fmt == "JPEG":
        return encode(flatten_alpha(im), "JPEG", quality, ss=ss)
    return encode(im, fmt, quality)


def process_one(path, args):
    if not os.path.exists(path):
        return {"ok": False, "input": path, "error": "no such file"}

    with Image.open(path) as im:
        im.load()
        src_fmt = (im.format or "?").upper()
        src_mode = im.mode
        src_size = im.size
        src_bytes = os.path.getsize(path)
        est_before = est_tokens(*src_size)

        work = im

        # 1) crop (device-pixel coordinates; without --screen they are source pixels)
        if args.crop:
            cx, cy, cw, ch = args.crop
            sc = args.screen or get_cached_screen()
            if sc:
                scx, scy = sc
                kx, ky = src_size[0] / float(scx), src_size[1] / float(scy)
                box = (int(cx * kx), int(cy * ky), int((cx + cw) * kx), int((cy + ch) * ky))
            else:
                box = (cx, cy, cx + cw, cy + ch)
            box = (max(0, box[0]), max(0, box[1]),
                   min(src_size[0], box[2]), min(src_size[1], box[3]))
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                return {"ok": False, "input": path, "error": "invalid crop box: %s" % (box,)}
            work = work.crop(box)

        # 2) resize: the target is BILLED TOKENS, not bytes
        ow, oh = work.size
        scale = 1.0
        reduced = False
        if args.eff_tokens:
            tw, th, k, over = solve_for_tokens(work.size[0], work.size[1], args.eff_tokens,
                                              min_side=args.min_side or MIN_OUT_SIDE,
                                              cap=0 if args.no_cap else CAP)
            tok_over = bool(over)
            if (tw, th) != work.size:
                work = work.resize((tw, th), Image.LANCZOS)
                ow, oh = work.size
                reduced = True
            scale = 1.0          # size already decided; the block below must not resize again
        elif args.eff_max_side:
            cur = max(work.size)
            if cur > args.eff_max_side:
                scale = args.eff_max_side / float(cur)
            elif args.allow_grow and cur < args.eff_max_side:
                scale = args.eff_max_side / float(cur)
        if args.scale:
            scale = float(args.scale)
        if args.width:
            scale = args.width / float(work.size[0])
        if scale != 1.0 and not reduced:
            ow = max(1, int(round(work.size[0] * scale)))
            oh = max(1, int(round(work.size[1] * scale)))
            work = work.resize((ow, oh), Image.LANCZOS)
            reduced = True
        # downscaling loses high frequencies; size is fixed and bytes are unbilled, so pull strokes back
        if args.sharpen and reduced:
            if work.mode not in ("RGB", "L"):
                work = flatten_alpha(work)
            work = work.filter(ImageFilter.UnsharpMask(
                radius=args.sharpen_radius, percent=int(args.sharpen), threshold=2))

        if not args.no_cap and max(work.size) > CAP:
            k = CAP / float(max(work.size))
            work = work.resize((max(1, int(round(work.size[0] * k))),
                                max(1, int(round(work.size[1] * k)))), Image.LANCZOS)
            ow, oh = work.size
            reduced = True

        # 3) coordinate overlay (drawn on the resized image, labelled in device pixels)
        screen = args.screen or get_cached_screen() or src_size
        if args.grid or args.marks or args.boxes:
            work = work.convert("RGBA")
            work = draw_overlay(work, screen, args.grid, args.marks, args.boxes,
                                opacity=args.grid_opacity)

        # 4) format
        fmt = args.format
        if fmt == "auto":
            fmt = "WEBP" if has_real_alpha(work) else "JPEG"
        fmt = {"jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "png": "PNG", "png8": "PNG8"}[fmt.lower()]

        # 5) bytes are only a ceiling, never a legibility decision
        #    billing looks at dimensions; the old code bisected to q=20 chasing KB and only got blur
        q = args.quality
        out_bytes = None
        floor = args.quality_floor
        if args.target_kb:
            limit = args.target_kb * 1024
            lo, hi, best = floor, q, None
            while lo <= hi:
                mid = (lo + hi) // 2
                blob = encode_with_alpha(work, fmt, mid, ss=args.ss)
                if len(blob) <= limit:
                    best = (mid, blob)
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is None:
                # even the quality floor does not fit -> emit at the floor and report OVER
                # never shrink dimensions for KB: it breaks legibility and saves nothing
                q, out_bytes = floor, encode_with_alpha(work, fmt, floor, ss=args.ss)
                kb_over = True
            else:
                q, out_bytes = best
                kb_over = False

        # output path
        if args.out:
            outp = args.out
        else:
            base, _ = os.path.splitext(path)
            ext = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png", "PNG8": ".png"}[fmt]
            dirname = args.outdir or os.path.dirname(path)
            outp = os.path.join(dirname, os.path.basename(base) + args.suffix + ext)
        if not os.path.isdir(os.path.dirname(os.path.abspath(outp))):
            os.makedirs(os.path.dirname(os.path.abspath(outp)), exist_ok=True)

        if out_bytes is None:
            out_bytes = encode_with_alpha(work, fmt, q, ss=args.ss)
        with open(outp, "wb") as f:
            f.write(out_bytes)

        out_w, out_h = work.size
        rep_out_tok = [bill_tokens(out_w, out_h)]
        est_after = est_tokens(out_w, out_h)
        kb_over = locals().get("kb_over", False)
        tok_over = locals().get("tok_over", False)
        rep = {
            "ok": True,
            "input": path,
            "preset": getattr(args, "preset_used", None),
            "src": {"path_bytes": src_bytes, "w": src_size[0], "h": src_size[1],
                    "format": src_fmt, "mode": src_mode, "est_tokens": est_before},
            "out": {"path": outp, "bytes": len(out_bytes), "w": out_w, "h": out_h,
                    "format": fmt, "quality": q, "est_tokens": est_after},
            "billed": {"tokens": bill_tokens(out_w, out_h),
                       "src_tokens": bill_tokens(src_size[0], src_size[1]),
                       "pct": round(100.0 * bill_tokens(out_w, out_h) / max(1, bill_tokens(src_size[0], src_size[1])), 1),
                       "note": "this is what gets billed, not KB"},
            "saved": {"bytes_pct": round(100.0 * len(out_bytes) / src_bytes, 1),
                      "area_pct": round(100.0 * (out_w * out_h) / float(src_size[0] * src_size[1]), 1),
                      "token_pct": round(100.0 * est_after["claude_like"] / max(1, est_before["claude_like"]), 1)},
            "coord": {
                "screen": [screen[0], screen[1]],
                "image": [out_w, out_h],
                "kx": round(screen[0] / float(out_w), 4),
                "ky": round(screen[1] / float(out_h), 4),
                "how": "device_x = img_x * kx ; device_y = img_y * ky",
                "note": "--grid/--mark labels are already device pixels; use them as-is",
            },
        }
        warns = []
        if kb_over:
            warns.append("KB-over: byte budget exceeded, size kept for legibility (bytes are not billed)")
        if tok_over:
            warns.append("TOKEN-floor: hitting the target would push the short side below %d; kept at the readable floor, billed %d > target (raise --tokens or --crop)" % (MIN_OUT_SIDE, rep_out_tok[0]))
        if warns:
            rep["warn"] = " | ".join(warns)
        if args.crop:
            rep["crop_device"] = args.crop
        return rep


def main():
    ap = argparse.ArgumentParser(description="shrink a screenshot to a token budget instead of a KB target")
    ap.add_argument("--json", action="store_true", help="full report instead of one line")
    ap.add_argument("inputs", nargs="+", help="input image path(s)")
    ap.add_argument("--preset", choices=list(PRESETS.keys()),
                    help="token presets: ui (default ~420tok) dense (~600) detail (~900) scan (~300) thumb (~130) max")
    ap.add_argument("--tokens", type=int, default=None, help="billed-token budget (overrides --preset)")
    ap.add_argument("--min-side", type=int, default=0, help="min short side in px, default %d (a blurred read is worse than none)" % MIN_OUT_SIDE)
    ap.add_argument("--max-side", type=int, default=None, help="max long side in px (legacy; do not mix with token budgets)")
    ap.add_argument("--sharpen", type=int, default=None, help="unsharp strength 0-200 after downscale (default per preset)")
    ap.add_argument("--sharpen-radius", type=float, default=1.2, help="unsharp radius, default 1.2")
    ap.add_argument("--quality-floor", type=int, default=80, help="never drop quality below this while chasing bytes, default 80")
    ap.add_argument("--no-444", action="store_true", help="let JPEG use 4:2:0 (smaller bytes, softer colour text)")
    ap.add_argument("--quality", type=int, default=None, help="JPEG/WEBP quality, default from the preset (90)")
    ap.add_argument("--width", type=int, help="output width in px (height follows)")
    ap.add_argument("--scale", type=float, help="scale factor (overrides --max-side)")
    ap.add_argument("--target-kb", type=int, help="byte ceiling in KB (lowers quality only, never the size; billing is --tokens)")
    ap.add_argument("--crop", help="crop x,y,w,h in device pixels (converted using --screen)")
    ap.add_argument("--format", default="auto", help="auto/jpeg/webp/png/png8")
    ap.add_argument("--screen", help="device resolution WxH, for the ruler and crop conversion")
    ap.add_argument("--grid", type=int, help="draw a device-pixel grid every N px (e.g. 100/200)")
    ap.add_argument("--grid-opacity", type=int, default=55, help="grid opacity 0-255, default 55 (faint, keeps text readable)")
    ap.add_argument("--mark", action="append", default=[], help="cross marker x,y[,label]; repeatable")
    ap.add_argument("--box", action="append", default=[], help="box x1,y1,x2,y2[,label]; repeatable")
    ap.add_argument("--out", help="output path (single input)")
    ap.add_argument("--outdir", help="output directory (multiple inputs)")
    ap.add_argument("--suffix", default="_sm", help="auto-name suffix, default _sm")
    ap.add_argument("--allow-grow", action="store_true", help="allow upscaling small images")
    ap.add_argument("--no-cap", action="store_true", help="do not cap the long side at 1568 (upstream rescales anyway; use for pixel measuring)")
    ap.add_argument("--quiet", action="store_true", help="print nothing")
    ap.add_argument("--print-path", action="store_true", help="print only the output path (for shell pipelines)")
    a = ap.parse_args()

    default_preset = load_conf()
    preset_name = a.preset or os.environ.get(ENV_PRESET) or default_preset
    if preset_name not in PRESETS:
        preset_name = default_preset
    p = PRESETS[preset_name]
    # precedence: --tokens > --width/--scale (manual) > --max-side (legacy) > preset
    if a.tokens:
        a.eff_tokens = a.tokens
        a.eff_max_side = 0
    elif a.width or a.scale:
        a.eff_tokens = 0
        a.eff_max_side = 0
    elif a.max_side is not None:
        a.eff_tokens = 0
        a.eff_max_side = a.max_side
    else:
        a.eff_tokens = p.get("tokens", 0)
        a.eff_max_side = 0 if a.eff_tokens else p.get("max_side", 0)
    a.quality = a.quality if a.quality is not None else p.get("quality", 90)
    if a.sharpen is None:
        a.sharpen = p.get("sharpen", 120)
    a.ss = 0 if not a.no_444 else None
    a.preset_used = preset_name
    a.screen = parse_wh(a.screen)
    a.crop = parse_nums(a.crop, 4) if a.crop else None
    a.marks = []
    for m in a.mark:
        nums, label = split_nums_label(m, 2)
        a.marks.append({"x": nums[0], "y": nums[1], "label": label})
    a.boxes = []
    for b in a.box:
        nums, label = split_nums_label(b, 4)
        a.boxes.append({"x": nums[0], "y": nums[1], "x2": nums[2], "y2": nums[3],
                        "label": label})

    reports = []
    for path in a.inputs:
        try:
            reports.append(process_one(path, a))
        except Exception as e:  # pragma: no cover
            reports.append({"ok": False, "input": path, "error": "%s: %s" % (type(e).__name__, e)})

    if a.print_path:
        for r in reports:
            if r.get("ok"):
                print(r["out"]["path"])
    elif not a.quiet:
        if a.json:
            print(json.dumps(reports if len(reports) > 1 else reports[0],
                             ensure_ascii=False, indent=2))
        else:
            for r in reports:
                if not r.get("ok"):
                    print("FAIL %s %s" % (r.get("input"), r.get("error")))
                    continue
                o, b, c = r["out"], r["billed"], r["coord"]
                line = "%s  %dtok %dx%d  kx=%.2f ky=%.2f" % (
                    o["path"], b["tokens"], o["w"], o["h"], c["kx"], c["ky"])
                if r.get("warn"):
                    line += "  WARN " + r["warn"].split(":")[0]
                print(line)
    sys.exit(0 if all(r.get("ok") for r in reports) else 1)


if __name__ == "__main__":
    main()
