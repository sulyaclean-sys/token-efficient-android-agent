# Token cost of images (and why the preset table looks like this)

## The model

A vision-capable model splits the image into patches and bills the patch count.
The consequence is simple and routinely forgotten:

> Cost is a function of **pixel dimensions**, not of file size.

A 1080x2408 PNG at 1.1 MB and the same image re-encoded to 27 KB JPEG at q40 cost
the same tokens. Lowering quality buys nothing except blur.

Two secondary rules that follow:

* Upstream encoders rescale when the long side exceeds ~1568 px, so pixels past
  that point are pure byte cost. `shrink.py` caps there by default (`--no-cap`
  disables it).
* Very small images hit a floor per image (a minimum patch/tile count), so
  "thumbnail" is not free either - it is just cheap.

## Measured reference points (author's phone: 1080x2408, 480 dpi, CJK UI text)

| Budget | Output size | Verdict for small CJK text |
|---|---|---|
| 1471 | 703x1568 | everything legible (upstream cap) |
| 900 (`detail`) | 550x1226 | legible, comfortable |
| 600 (`dense`) | 449x1001 | legible |
| **420 (`ui`, default)** | 375x837 | **legible - the sweet spot** |
| 300 (`scan`) | 317x707 | borderline, tiring to read |
| 236 | 286x620 | blurred: `BALANCE 12.34` was read as `B4L4NCE I2.34` |
| 130 (`thumb`) | 208x464 | identify the screen only |

Numbers, not gospel: patch size differs per model, legibility depends on your DPI
and font size, and CJK glyphs are the worst case. Latin text stays readable with
noticeably less.

## Re-calibrating for your device / model (5 minutes, once)

1. Take one screenshot with the smallest text you actually care about.
2. `python3 scripts/shrink.py shot.png --tokens 420 --format jpeg --print-path`
3. Look at the output and answer one question: can you read that smallest text?
4. Bisect: `--tokens 300`, `--tokens 600`, `--tokens 900`.
5. Keep the lowest budget that is comfortably readable - comfortable, not
   marginal. A blurred read costs a whole extra round-trip, which is 10-100x the
   price of the extra patches.
6. Write it into `scripts/shrink.conf` as `ui = <tokens>,90,120`. Do not touch the
   code.

## Reading tokens/screen without a tool

Billing is patch-based, so the same image read twice costs twice as much as once;
and an image that is 30% longer on each side costs ~70% more. Rule of thumb when
you only know the size: cost scales with **width x height**, everything else is
noise.

## Common mis-optimizations

| Tempting | Reality |
|---|---|
| `--quality 40` to hit a KB target | same tokens, blurrier text |
| `--target-kb 20` | only useful when the *transport* has a size limit, never for legibility |
| reading two screenshots "to be sure" | 2x tokens and 1 extra round-trip; merge instead |
| reading the full-resolution original "once" | 3-4x tokens of the default preset for the same answer |
| cropping and reading the crop separately | fine only when the crop *replaces* the full read, not in addition |

## Where the real money is

The image is often the cheap part. A single extra tool round-trip re-sends the
whole conversation - on a long session that is orders of magnitude more than the
image. If you must choose: read one good image, not three cheap ones and not one
image plus two probes.

See `docs/context-rules.md`.
