# Verification: what automated checks can and cannot prove

Two failures from real sessions. Both were "the tool was right and the human was
wrong", except the tool was answering a different question than the one asked.

## Run the checks instead of arguing

```bash
python3 scripts/uicheck.py px  shot.png  --rect X,Y,W,H   # is it drawn? (incident 1)
python3 scripts/uicheck.py row dump.xml  --band T,B --expect N   # is it balanced? (incident 2)
```

One line each, exit 0/1: `OK px row=1 fg=#333333 bg=#f5f5f5 cr=11.59 cover=1.00`,
`FAIL px uniform why=nothing drawn`, `FAIL asym lp=24 rp=100 delta=76 (right side
short of content)`, `FAIL overlap item3.right=928 > item4.left=852`.

| FAIL | Means |
|---|---|
| `px uniform` | nothing rendered in that rect: covered, `opacity` 0, clipped, or same colour |
| `px faint` | rendered but contrast < 1.5 - effectively invisible |
| `px partial` | dashed / clipped / only part of the row drawn |
| `asym lp=/rp=` | content sits off-centre: the gap is on the side named, the culprit is the sibling that moved |
| `gap=..skew=` | spacing uneven beyond `--tol` |
| `overlap` | one item overruns its neighbour: width grew, not a spacing problem |
| `count` | wrong number of items in the band |

## Incident 1 - "the checker says the 1px border is there"

An agent edited an HTML mock-up, then ran a geometry check which reported the 1px
border as present. On screen the border was invisible. The agent repeated the check
and insisted. Only after a screenshot was pushed through the loop did it concede
and fix the styling.

What the check could see: a box exists with `border: 1px`. What it could not see:

| Cause | Why a geometry/DOM check misses it |
|---|---|
| overlapping layer painted later | the box exists, something opaque sits on top |
| `opacity` / `rgba(...,0)` | the box exists, nothing is emitted |
| `overflow: hidden` / clip-path | box geometry is not clipped geometry |
| same colour as parent | contrast, not presence, is what fails |
| sub-pixel rounding at the real `devicePixelRatio` | 0.5px of a 1px line disappears |
| `transform: scale()` on an ancestor | reported width is pre-transform |

**Rule.** Presence and visibility are different assertions, and only the second
one is the user's question. When they disagree, the rendered pixels win:

1. Sample the rendered result, not the model: screenshot, then check the actual
   pixels along the border (`getComputedStyle` is not evidence).
2. If you must stay static, prove the *stack*: computed `opacity`, `visibility`,
   `z-index` of ancestors, `overflow` of every ancestor, effective
   `devicePixelRatio`. Any of these can be the whole answer.
3. A 1px line at 1x is a rendering coin-flip. If it must be visible, make it a
   hairline the renderer cannot round away (>= 1 CSS px at DPR >= 1, or a solid
   background instead of a border) and confirm with a pixel diff.

## Incident 2 - "the nav bar lost its right end"

A bottom nav bar lost a chunk on its right side. The agent measured the spacing,
then edited "the middle" - and produced a gap on the right with an extra button on
the left. It had modified the *neighbour* of the element it had measured: the
measurement pointed at a gap, the edit landed on the wrong sibling.

Root causes, all generalisable:

* **A gap is a symptom, not a target.** "Item 2 is 80px from item 1" does not say
  whether item 1 moved right, item 2 moved left, or a third node is overlapping.
* **Editing by position/index in a list is unsafe.** Reordering, hidden nodes and
  RTL layouts all break it.
* **Symmetry was never asserted.** The intent was "four items evenly spaced";
  nothing in the workflow compared left padding to right padding.
* **No before/after diff.** One screenshot after the edit would have shown the
  extra button on the left immediately.

**Rule.** Measure -> identify -> assert -> edit -> diff:

1. **Identify by unique anchor** (text, `id`, resource name), never by index or by
   "the one near x=540".
2. **Assert before writing**: print the matched element's own bounds and compare
   them with the numbers you measured. If they differ, stop - you are about to edit
   the wrong node.
3. **Edit the smallest ownership scope**: change the property of the element whose
   position is wrong, rather than compensating with margins on a neighbour.
4. **Diff after writing**: screenshot (or dump) again and confirm the intended
   change appeared *and* nothing else moved. A container-level assertion is cheap:
   first item left edge, last item right edge, spacing variance.
5. **State intent as an invariant** ("left edge == right edge", "4 items, spacing
   variance < 2px") so a passing check actually answers the question.

## The general protocol

| Claim | Cheap way to prove it |
|---|---|
| "the element exists" | dump / geometry |
| "the element is visible" | rendered pixels (one shrunk screenshot) |
| "the element is at X,Y" | dump bounds -> `tapcalc.py bounds` |
| "my edit changed the intended thing" | before/after md5 + targeted region diff |
| "the layout is correct" | assert the invariant, not the individual numbers |
| "the text is legible" | read one image at the calibrated preset, once |

If the cheapest proof of a claim is an image, read the image - but read exactly
one, at the calibrated preset, and reuse it for every question about that screen.
