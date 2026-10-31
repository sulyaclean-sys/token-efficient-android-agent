# Screen -> shrink -> find -> tap

The loop that keeps phone automation cheap. Works with adb, a Shizuku-backed
shell, a root shell or Termux; only `screencap`, `uiautomator` and `wm` are used.

## 1. Observe (device shell, one call)

```bash
sh scripts/screen.sh            # once per device / rotation
sh scripts/shot.sh home         # -> $SHOT_DIR/home.png / home.xml + md5 + size
```

Two artifacts, and the XML is the important one: it is plain text, costs tens of
tokens, and cannot be misread by OCR.

## 2. Locate (host, no image)

```bash
python3 scripts/tapcalc.py find home.xml --text "Save" --contains --no-offscreen
python3 scripts/tapcalc.py find home.xml --list
```

`find` skips text nodes with `clickable=false` and reports the centre of the
nearest clickable ancestor - the thing you actually meant to press. It prints a
ready-to-paste `input tap X Y`.

For long presses / swipes reuse the same numbers: `input swipe X1 Y1 X2 Y2 400`
(a swipe from a lower y to a higher y scrolls up; reverse for back).

## 3. Only if the dump is useless: read one image

```bash
python3 scripts/shrink.py home.png --format jpeg --print-path   # ~420 tokens
```

Read that file, answer **all** questions you have about that screen from it, then
stop reading. If you need a second look later, reuse the file - do not re-read at a
higher budget. If the thing you need is tiny, `--crop x,y,w,h` (device pixels)
beats raising the budget for the whole screen.

**When a human points at a spot** ("this row is wrong"), do not read the screen at
all - read the patch:

```bash
python3 scripts/zoom.py $SHOT_DIR/home.png --from-dump $SHOT_DIR/home.xml --text "12.34" --pad 12
# -> home_patch.jpg 344x84 78tok dev=78,1178 kx=1.00 ky=1.00
python3 scripts/zoom.py $SHOT_DIR/home.png --rect 80,1170,440,160 --zoom 2 --grid 50
```

`dev=` is the crop origin in device pixels, so a coordinate you see inside the patch
maps back with `dev_x = dev.x + img_x * kx`. `--grid 50` labels the ruler in device
pixels, so you can tap straight from the patch without arithmetic.

## 4. Coordinates

Three coordinate spaces exist and confusing them is the classic mis-tap:

| Space | Where it comes from |
|---|---|
| dump bounds | `[l,t][r,b]`, already device pixels |
| image pixels | what you see in the shrunk JPEG |
| device pixels | what `input tap` takes |

```bash
python3 scripts/tapcalc.py bounds "[60,1420][1020,1560]"          # dump -> tap
python3 scripts/tapcalc.py img2dev 188 418 --img home_sm.jpg      # image -> tap
python3 scripts/tapcalc.py img2dev 188 418 --img c.png --crop 60,1180,960,140
python3 scripts/tapcalc.py dev2img 540 1200 --image 375x837       # tap -> image
```

`kx = screen_w / image_w`, `ky = screen_h / image_h`, applied to the cropped
region when `--crop` was used. If you do not want to convert at all, re-render
with `--grid 200`: the ruler drawn on the image is already in device pixels.

Avoid: reading dp or `%` values from a design file and tapping them. Convert once,
to device pixels, in one place.

## 5. Verify

```bash
md5sum $SHOT_DIR/home.png            # before
# ... act ...
sh scripts/shot.sh after
md5sum $SHOT_DIR/after.png           # changed? that is all this proves
```

Then assert, do not eyeball:

```bash
python3 scripts/uicheck.py row after.xml --band 2200,2408 --expect 4   # layout still balanced
python3 scripts/uicheck.py px after.png --rect 100,1199,200,3          # the 1px line is drawn
```

A changed hash proves *something* changed; it does not prove the right thing
changed. For anything structural, assert the invariant instead - element present
with expected bounds, first/last item edges symmetric (see
`docs/verification.md`).

## Gotchas

* **Self-drawn UI** (Flutter, games, some WebViews): dump is nearly empty. One
  image + `img2dev`, and nothing else will work.
* **Non-ASCII input**: `input text` cannot type non-ASCII text on many ROMs. Focus the field, then
  inject text with your automation layer.
* **Low-RAM devices**: decoding a full-resolution PNG can kill the agent app
  itself. Shrink on the host before the image ever reaches the model; keep one
  image in flight.
* **Rotation / split screen**: re-run `screen.sh`; cached dimensions go stale.
* **Scrollable lists**: an element can exist in the dump while being off-screen -
  `--no-offscreen` filters those; scroll first, then look again.
