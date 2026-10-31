# Porting notes - what changed from the original private setup

This repo was extracted from a working private toolchain. Everything that was
machine-, project- or account-specific was either generalised or removed. If you
are adapting it further, this is the map.

## Removed (was private, is not here)

| Removed | Why |
|---|---|
| Absolute paths into a personal agent-skill tree | meaningless and unusable elsewhere; every script now resolves relative to itself or an env var |
| Android UI-dump analyzers written against one specific app | they encode one app's screen names and node ids; keeping them would be dead weight and a privacy leak |
| A project build/packaging pipeline (build, backup, restore, version bump) | tied to one Gradle project layout |
| An HTML mock-up checker | tied to one design system and one set of thresholds |
| Device-specific cache files (`.screen.txt` with a vendor/dpi note) | replaced by `scripts/screen.sh`, which regenerates it on any device; the file itself is gitignored |
| Personal identifiers: device model, serials, package names, project names, file paths, dates of measurement | no functional value, and exactly the sort of thing that should not go public |

## Changed in the shipped code

| Change | Detail |
|---|---|
| No silent resolution fallback | `tapcalc.py` used to fall back to a hardcoded `1080x2408`. A wrong scale factor mis-taps silently, so it now exits with a message telling you the three ways to supply the size. |
| Resolution sources | `--screen` > `$TOKEN_TOOLS_SCREEN` > `scripts/.screen.txt` (or `$SCREEN_CACHE`) |
| Output directory | `$SHOT_DIR`, default `/sdcard/AndroidAgentDevkit` - no longer a personal folder |
| Relocatable config | `shrink.conf` is loaded from the script's own directory, so the repo can live anywhere |
| `zoom.py` added | new: crop the one known-wrong region out of a screenshot and report the device-pixel mapping (`dev=`, `kx/ky`); ~30 tokens instead of ~420 |
| `uicheck.py` added | new: turns the two documented failure modes into one-line assertions (`row` = layout invariant from the dump, `px` = rendered visibility from pixels) |
| Every tool now prints one line | `shrink.py` and `tapcalc.py` used to dump multi-line JSON; JSON is still available behind `--json` |
| `linemap.py` rewritten | was a hardcoded list of one machine's files; now takes paths and modes and works on any tree |
| `screen.sh`, `shot.sh` added | replace private one-off scripts; POSIX `sh` only |
| Docs | English only: README, SKILL, docs, `--help` text, runtime messages and code comments |
| Licence | MIT added |

## What was deliberately *not* generalised

* **The 420-token default.** It is a measurement, not a constant of nature. Kept as
  the default because it is conservative for CJK text; re-calibrate for your device
  (see `docs/token-cost.md`).
* **The 1568 long-side cap.** A property of common vision encoders; override with
  `--no-cap` if your model differs.
* **Chinese CLI output in the image tools.** These strings are read by agents as
  terse signals (`TOKEN-floor`, `n!=want`, `MISS`); translating them would break
  existing prompts without adding clarity.

## Plugging your own tools in

The workflow is deliberately three narrow interfaces, so replacements only need
to match the shape:

| Interface | Contract |
|---|---|
| observe | produce `PNG + XML + md5` under one directory; print one line per artifact |
| shrink | input image + token budget -> output image <= budget; print the path |
| locate | XML (or bounds) -> `input tap X Y` in device pixels |

Anything that satisfies those can replace `shot.sh`, `shrink.py`, `tapcalc.py`
respectively, and the docs still apply.

## Publish checklist (used for this release)

* [x] no absolute personal paths; every path is relative-to-script or env-provided
* [x] no device model / vendor / serial / package-name strings
* [x] no credentials, tokens, endpoints; no network calls at all
* [x] device cache and generated images gitignored
* [x] behaviour-identical scripts verified after patching (`py_compile`, smoke run)
* [x] permissions documented: host python vs. on-device shell, no root escalation
* [x] limitations documented, including two real mis-verification incidents
* [x] licence and bilingual README present
