# android-agent-devkit

Small, dependency-light helpers that stop an LLM agent from burning context on
screenshots, logs and whole-file reads - plus the notes that explain *why* they
are shaped this way.

Two rules everything here is built around:

1. **Images are billed by pixel dimensions, not kilobytes.** Re-encoding a
   1080x2408 PNG down to 27 KB costs exactly the same tokens as the 1.1 MB
   original. Lowering JPEG quality therefore saves nothing and only blurs text.
   The only real lever is *size*.
2. **Every extra tool round-trip re-sends the whole conversation.** One call that
   prints 400 bytes beats two calls that print 100 bytes each. Optimize
   *round-trips* first, bytes second.

## What's inside

| Path | What it does | Runs on |
|---|---|---|
| `scripts/shrink.py` | downscale a screenshot to a token budget while keeping text legible; optional grid / crop / annotations | any host with Python 3 + Pillow |
| `scripts/tapcalc.py` | bounds, image pixels or a UI-dump XML -> real device tap coordinates | host |
| `scripts/zoom.py` | crop the one known-wrong region out of a screenshot, read only that (~30 tokens) | host |
| `scripts/uicheck.py` | one-line `OK`/`FAIL`: layout symmetry from the dump, pixel visibility from a screenshot | host |
| `scripts/linemap.py` | print a file's section map (headings / defs / docstrings) so the agent reads 40 lines instead of 4000 | host |
| `scripts/shot.sh` | one call: screencap + uiautomator dump + md5 + byte size | device shell |
| `scripts/screen.sh` | cache the device resolution into `scripts/.screen.txt` | device shell |
| `scripts/selftest.py` | run every tool on synthetic fixtures, print `OK selftest n/n` | host |
| `scripts/shrink.conf` | the token presets - edit this instead of the code | - |

## Quick start

```bash
git clone https://github.com/sulyaclean-sys/token-efficient-android-agent.git
cd token-efficient-android-agent
pip install -r requirements.txt
python3 scripts/selftest.py          # -> OK selftest 11/11

# 1) device side (adb shell / Shizuku shell / Termux), once per device or rotation
sh scripts/screen.sh
sh scripts/shot.sh home              # -> $SHOT_DIR/home.png + home.xml

# 2) no image at all: locate the element from the XML
SHOT=${SHOT_DIR:-/sdcard/AndroidAgentDevkit}
python3 scripts/tapcalc.py find $SHOT/home.xml --text "Save" --contains
# -> input tap 540 1490

# 3) assertions (rects are device pixels: pass the full screenshot)
python3 scripts/uicheck.py row $SHOT/home.xml --band 2200,2408 --expect 4
# -> OK row n=4 gap=48..48 lp=24 rp=24
python3 scripts/uicheck.py px $SHOT/home.png --rect 100,1199,200,3
# -> FAIL px uniform ... (the 1px border is not rendered)

# 4) only when you must look: one shrunk screen, or one patch
python3 scripts/shrink.py $SHOT/home.png --format jpeg
# -> $SHOT/home_sm.jpg  419tok 375x837  kx=2.88 ky=2.88
python3 scripts/zoom.py $SHOT/home.png --from-dump $SHOT/home.xml --text "12.34"
# -> home_patch.jpg 320x60 27tok dev=90,1190 kx=1.00 ky=1.00
```

Feeding the shrunk JPEG to the model is the *last* resort: dump-based lookups are
plain text, cost ~100 tokens, and cannot be misread.

## Use it from another project

Nothing is installed globally - every tool is a single file you can point at by
absolute path. Either clone the repo somewhere your agent can read, or copy just
the pieces you need into your own skill/tools directory:

```bash
git clone https://github.com/sulyaclean-sys/token-efficient-android-agent.git
cp -r token-efficient-android-agent/scripts ~/.claude/skills/android-agent-devkit/
```

`SKILL.md` is the agent-facing description (one line per tool); `docs/` explains
why the tools are shaped that way. `.gitignore` already keeps `.screen.txt`
(device-specific) and local captures out, so a fork is safe to publish as-is.

MIT licensed: use it, fork it, ship it in your own product. Issues and PRs are
welcome; the only ask is that you keep `LICENSE` with any copy.

## Verify your install (10 seconds)

```bash
pip install -r requirements.txt
python3 scripts/selftest.py      # -> OK selftest 11/11
```

It builds a synthetic screenshot + UI dump in a temp dir, runs every tool against
them (including the two *must-fail* cases), and prints one line. No device and no
network needed. If it says `FAIL`, that line names the case and the tool output.

## Requirements & permissions

* Python 3.8+ and Pillow (`pip install -r requirements.txt`) for the host scripts (`shrink`, `tapcalc`, `linemap`).
* Device-side scripts use `screencap`, `uiautomator`, `wm` - i.e. they need **a
  shell on the phone**: `adb shell`, a Shizuku-backed shell, a root shell, or
  Termux. User level is enough; **no root escalation is required**.
* No network access, no telemetry, nothing uploaded. Everything is local files.

| Capability | Needed for | Privilege |
|---|---|---|
| local python3 | `shrink.py`, `tapcalc.py`, `linemap.py` | none |
| device shell | `shot.sh`, `screen.sh` | adb/Shizuku/Termux user shell |
| `uiautomator dump` | `tapcalc.py find/list` | same as above |

If you have no shell on the phone, the package still works: take the screenshot
however you like, then pass `--screen WxH` and point `shrink.py` at the file.

## Configuration (nothing is hardcoded to one machine)

| Setting | How |
|---|---|
| device resolution | `--screen 1080x2408` > `$TOKEN_TOOLS_SCREEN` > `scripts/.screen.txt` (written by `screen.sh`) |
| screen cache path | `$SCREEN_CACHE` |
| screenshot output dir | `$SHOT_DIR` (default `/sdcard/AndroidAgentDevkit`) |
| presets / default preset | `scripts/shrink.conf` |

`tapcalc.py` deliberately **refuses to guess** when it has no resolution instead
of falling back to a constant: a wrong scale factor silently produces a tap a few
hundred pixels off, which is much worse than an error message.

## Does this only work on the author's phone?

* **Geometry: resolution independent.** Scale factors are derived from the actual
  image and screen size. No 1080x2408 assumptions anywhere in the math.
* **Token budgets: calibrated, not universal.** The 420-token default was tuned on
  a 1080x2408 / 480dpi phone showing Chinese UI text at default font size. Image
  cost depends on your model's vision encoder; legibility depends on your DPI and
  font size. Re-calibrate once (see `docs/token-cost.md`) and change **only**
  `scripts/shrink.conf`.
* **Language: any.** CJK small text is the hard case; Latin text stays legible at
  lower budgets, so the default is conservative rather than optimized for English.
* **Platform: portable host scripts.** Plain POSIX shell + Python; they do not care
  whether they run on Linux, macOS, WSL or inside proot/Termux.

## Limitations - read before trusting an automated check

These are the two failure modes that keep coming up in real use (details and the
resulting protocol in `docs/verification.md`):

1. **A geometry/static check proves *existence*, not *visibility*.** A 1px border
   can be reported as present by a DOM/box check while being invisible to the eye:
   covered by a later-painted layer, `opacity`/`alpha` near zero, `overflow:hidden`
   clipping, same colour as its background, or sub-pixel rounding at the given
   `devicePixelRatio`. When the human cannot see it, the pixels are the truth -
   sample the rendered screenshot instead of arguing with the checker.
2. **Measuring a gap tells you the gap, not which element is wrong.** If a nav bar
   loses a chunk on the right, the fix is not "put something back in the middle":
   the mismatched item is usually the *sibling* that was edited. Anchor edits to a
   unique id/text, assert the element you are editing is the one you measured, and
   diff the rendered result before/after.

`scripts/uicheck.py` turns both checks into one command with an exit code:
`row` asserts count / spacing / edge symmetry / overlap on a dump, `px` samples the
rendered pixels and fails on `uniform`, `faint`, `partial` - the exact cases where
a geometry check says "present" and the user says "I cannot see it".

Also: none of these scripts can tell you whether a UI *looks* right. They can only
answer "how many pixels" and "where is this element".

## Not included on purpose

Anything that was tied to one private project or one machine stayed out of this
repo: Android UI-dump analyzers for a specific app, a project build/packaging
pipeline, and an HTML design-proof checker. See `docs/porting-notes.md` for what
was removed, how the scripts were made relocatable, and how to plug your own
tools into the same workflow.

## Docs

* `docs/token-cost.md` - the billing model, the preset table, how to re-calibrate.
* `docs/context-rules.md` - round-trip economy rules for agents (what to batch, what never to `cat`).
* `docs/android-workflow.md` - the screen -> shrink -> find -> tap loop.
* `docs/verification.md` - two real incidents and the resulting check protocol.
* `docs/porting-notes.md` - what changed versus the original private setup.

## License

MIT - see `LICENSE`.
