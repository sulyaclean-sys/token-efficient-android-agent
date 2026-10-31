---
name: android-agent-devkit
description: One-line tools for agent UI work on Android (and any screen you screenshot). shrink.py=screenshot to a token budget; zoom.py=crop the one known-wrong region (~30 tokens); tapcalc.py=bounds/image/XML to tap coordinates; uicheck.py=one-line OK/FAIL for layout symmetry and pixel visibility; linemap.py=file line map; shot.sh=screencap+dump+md5; screen.sh=cache screen size; selftest.py=self-check. Use before reading a screenshot, locating an element, or trusting a geometry check.
---

# android-agent-devkit

Every tool answers in **one line**: `OK key=value` or `FAIL code key=value`, exit 0/1.
Prose only in docs. `--json` only when a number is disputed.

| want | run | get |
|---|---|---|
| what is on screen | `sh shot.sh home` then `tapcalc.py find home.xml --list` | 1 line per item |
| tap an element | `tapcalc.py find home.xml --text "Save" --contains` | `input tap 540 1490` |
| see the whole screen | `shrink.py home.png --format jpeg` | `home_sm.jpg 419tok 375x837 kx=2.88 ky=2.88` |
| see ONE known-wrong spot | `zoom.py home.png --from-dump home.xml --text "12.34"` | `home_patch.jpg 320x60 27tok dev=90,1190 kx=1.00` |
| coords from an image | `shrink.py ... --grid 200` then `tapcalc.py img2dev X Y --img ...` | `input tap X Y` |
| is the layout balanced | `uicheck.py row home.xml --band 2200,2408 --expect 4` | `OK row n=4 gap=48..48 lp=24 rp=24` |
| is it actually visible | `uicheck.py px home.png --rect 100,1199,200,3` | `OK px cr=11.59` / `FAIL px uniform` |
| read a big file | `linemap.py big.md` then read only that range | 1 line per section |

## FAIL codes - what to do next

| code | means | move |
|---|---|---|
| `px uniform` | nothing drawn in the rect (rect = device px, pass the full screenshot) | covered / opacity 0 / clipped / same colour |
| `px faint` / `px partial` | contrast < 1.5 / only part of the row | change colour or box, then re-check |
| `asym lp= rp=` | content shifted; the culprit is the sibling that moved | re-place by unique id, never by index |
| `gap=..skew=` `overlap` `count` | spacing / width / item count | fix the width before the margins |
| `TOKEN-floor` | budget would break the min readable side | raise `--tokens` / use `--crop` |
| `MISS` / `no-match` | anchor not in the dump | `tapcalc.py find --list` for real names |
| `no screen size` | nothing cached | pass `--screen WxH` or run `sh screen.sh` |

## Four rules

1. **One image per task - and only the patch you need.** If you already know which
   spot is wrong, `zoom.py` reads ~30 tokens instead of ~420. Prefer the dump: it
   is text and cannot be misread.
2. **Exists is not visible.** A geometry check proves presence; `uicheck.py px`
   proves the pixels exist.
3. **Measure -> identify by unique anchor -> assert -> edit -> diff.** Editing by
   index or "the middle" moves the neighbour instead (see `docs/verification.md`).
4. **One round-trip beats smaller bytes.** Batch commands, print conclusions.

Docs: `README.md` (install, permissions), `docs/token-cost.md` (presets, calibration),
`docs/verification.md` (the two failure modes and their checks),
`docs/android-workflow.md`, `docs/context-rules.md`, `docs/porting-notes.md`.
