# Word clock: letter grid, phrases and font

This task designs the word clock that `wordclock.py` draws for the 800 × 480,
1-bit e-ink display. It records the options for the grid shape, the phrases,
the font and the style of the unlit letters, and why we chose each one.

Files in this task (copies; do not update them):

- `grid_check.py`: the first checker. It finds each of the 720 phrases of a
  12-hour day in the grid. `wordclock.check_grid()` now does this job.
- `font_fit.py`: measures the largest cap height for each font and grid shape.
- `previews/`: the first renders, at 17:33 and 12:00, in the two unlit styles.

## Requirements

- The clock shows the time to the minute, for example "IT IS TWENTY SEVEN
  MINUTES TO SIX".
- Each phrase starts with "IT IS". 15 is QUARTER and 30 is HALF. Minutes 31 to
  59 count down with TO, so the largest number is TWENTY NINE.
- O'CLOCK lights only on the hour. The apostrophe is in the cell of the O.
- The unlit letters stay visible.
- The grid can go to the edge of the image, because the display has a frame.

## Phrases

- Minutes that are a multiple of 5 have no MINUTES: "IT IS TWENTY PAST SIX".
  Other minutes have it: "IT IS TWENTY THREE MINUTES PAST SIX". This is how
  people say the time. The user chose this.
- 1 minute uses MINUTE: the S of MINUTES stays unlit.

## Grid rules

1. Words read left to right, then top to bottom.
2. Two words do not share a letter.
3. Two words that light together have a filler cell or a line break between
   them, so lit words never run together.
4. The units FOUR, SIX, SEVEN, EIGHT and NINE light as the first letters of
   FOURTEEN, SIXTEEN, SEVENTEEN, EIGHTEEN and NINETEEN. The units row then
   needs only ONE, TWO, THREE and FIVE. This saves 21 cells.

The minutes need 8 teens (11 to 14 and 16 to 19). With rule 4, the grid holds
169 letters.

## Font

The widest letters (W and M) set the font size in a narrow cell. The cap
height sets it in a short cell. `font_fit.py` gives the largest cap height
that fits in 85% of the cell width and 70% of the cell height:

- DejaVu Sans (the font of `weather.py`): 18 × 11: 27 px, 17 × 11: 29 px,
  20 × 10: 25 px, 16 × 10: 31 px.
- DejaVu Sans Bold: 24, 26, 23, 28 px.
- DejaVu Sans Condensed Bold: 27, 30, 25, 31 px.
- Open Sans Condensed Bold: 30, 30, 31, 33 px.

We chose Open Sans Condensed Bold (Apache License 2.0). It gives the largest
letters in the grids that are possible. Its bold strokes also stay legible
when the unlit letters are dithered to grey.

## Grid shape

The cell count must hold 169 letters plus the gaps of rule 3.

1. **18 × 11, 44 × 44 px cells (chosen).** 198 cells. There is a gap after
   each word, and the words are in numeric order where the space permits.
   30 px cap height.
2. **20 × 10.** 200 cells, but each row is full, so the words must go in a
   mixed order. 31 px: only 1 px more.
3. **17 × 11.** 187 cells: 18 spare cells for 23 gaps, so some hour words run
   together, as on the QLOCKTWO ("ONESIXTHREE"). 30 px: no gain.
4. **16 × 10.** 160 cells: too few.

## Unlit letters

Two styles, `UnlitStyle.GREY` (a 50% checkerboard dither) and
`UnlitStyle.OUTLINE`. See `previews/`. The default is grey: on screen the lit
words stand out more than they do against outlines. The user will choose on
the real display.

## Open: AM and PM

AM or PM lights at every minute, after the hour word. It fits in the 18 × 11
grid with the same 30 px letters, if the last row is
`TWELVE·O'CLOCK·AMPM` and two hour rows run their words together:

```
PAST·ONE·TWO·THREE
FOUR·FIVE·SIXSEVEN
EIGHTNINETENELEVEN
TWELVE·O'CLOCK·AMPM
```

The checker passes for all 1440 minutes of a day. The cost: the grey text of
these hours is harder to read. A 12th row would give each word a gap, but the
cap height goes down to 28 px (70% of a 40 px row).

## Changes after this plan

- 2026-11-18: The user chose AM and PM in the 18 × 11 grid, with the hour rows
  above (some hour words without gaps), not a 12th row. `wordclock.py` holds
  the current grid.
- 2026-11-18: `UnlitStyle` is now two settings: `unlit_outline` (outline or
  filled) and `grey_level` (the dither). So an outline can also be grey.
- 2026-11-18: The user asked for less space between the letters of a row,
  with one row fewer. `wordclock.py` now has two layouts, `LAYOUT_18X11` (the
  default) and `LAYOUT_20X10`, chosen by `Settings.layout`. 20 is the fewest
  columns for 10 rows if each minute word keeps a gap, as in 18 × 11. The
  proof: the minute words (IT, IS, the numbers, HALF, QUARTER and MINUTES)
  are 19 words with 106 letters. In $m$ rows they need at least
  $106 + (19 - m)$ cells, so with 19 columns $125 - m \le 19m$ and $m \ge 7$.
  The other 3 rows have 57 cells, but the hour part (PAST, TO, the hours,
  O'CLOCK, AM and PM) has 67 letters. With 20 columns, $m = 6$ fits, and the
  hour rows need only 2 hour words without a gap (TWOTHREE, EIGHTNINE). The
  cost: the minute words are not in numeric order. The cap height is 31 px, 1
  px more than 18 × 11, because the width of W limits it.
- 2026-11-18: The user chose filled grey letters, not outlines: at a distance,
  outlines look jumbled and busy. The outline code stays, but it is not a
  criterion for later choices (for example the font).
- 2026-11-18: `font_fit.py` above measured letter widths with
  `font.getbbox()`, which gives the advance width, not the ink. In a
  monospaced font the two differ a lot. `wordclock.py` now uses ink boxes.
  `font_compare.py` measures again by ink, for the current font and six
  monospaced fonts: cap height, the white space beside each letter, and
  stroke weight. A monospaced font makes that white space more even. The
  font is not chosen yet.
- 2026-11-18: The user chose Atkinson Hyperlegible Mono Bold and the 20 × 10
  layout, now the defaults in `wordclock.py`. The font has heavy strokes
  (7 px stems, 44% more ink than Open Sans Condensed Bold), and it is made to
  be legible at a distance. In 20 × 10 its letters are 33 px tall, not 31 px.
  Open Sans Condensed Bold is no longer in the project. This task now also
  holds `wordclock.py`, a copy of the code that `font_compare.py` imports, as
  it was at the comparison.
- 2026-11-18: The user allowed two words that never light together to share
  a letter. In 20 × 10 the row height limits the letters (33 px is 70% of a
  48 px row). `LAYOUT_20X9` in `wordclock.py` uses shared letters (11 of
  them, the most there can be) to fit 9 rows, for 36 px letters. 19 × 9 would
  give 37 px but cannot fit: the hour rows need 58 cells, and 3 rows of 19
  have 57. 8 rows need 21 or more columns, where the width of W limits the
  letters to 34 px or less. The default is still 20 × 10.
- 2026-11-18: Without AM and PM, the hour rows need 53 cells, so 19 × 9 fits:
  `LAYOUT_19X9` (`has_am_pm=False`), 37 px letters. That is the most for 9
  rows (70% of a 53 px row). 8 rows still do not help: 20 × 8 has 160 cells,
  but even without AM and PM the grid needs at least 162 (158 letters and 4
  gaps between lit words). 21 or more columns make W limit the letters to
  34 px or less. The default is still 20 × 10 with AM and PM.
- 2026-11-18: Rule (the user agreed): words share a letter or touch only where
  the grid needs it to fit. In `LAYOUT_20X9`, PAST and TO, and HALF and
  FOURTEEN, now have a gap. The minute rows now fill every cell but one. In
  `LAYOUT_19X9`, a gap between PAST and TO would need two more words to
  touch, so PASTO stays.
- 2026-11-18: The user made `LAYOUT_20X9` the default: 36 px letters, with AM
  and PM.
- 2026-11-18: In 20 × 9 the apostrophe touched the C: the space between the
  ink of O and C is 9.5 px, and the apostrophe is 12 px wide. The apostrophe
  now has its own cell (O’CLOCK is 7 cells), which the spare cell of the last
  row of 20 × 9 and 20 × 10 permits, with no loss of size. 18 × 11 and 19 × 9
  had no spare cell there, so `wordclock.py` no longer has them, nor the
  `has_am_pm` flag that only 19 × 9 used. `wordclock-four-layouts.py` in this
  task is a copy of `wordclock.py` from before this change.
- 2026-11-18: Rule refined (the user's idea): touching is better than sharing
  a letter, because each word keeps its own letters. In 20 × 9, EIGHTEEN and
  NINETEEN now touch and do not share the N; the spare cell at the end of
  their row permits it.
- 2026-11-18: The user prefers words that touch to a filler letter between
  them: the display draws a filler as an upper case letter (as on the
  QLOCKTWO), so between two words it looks like part of a word. A filler is
  now only where two words that light one after the other would touch. The
  hour words can start in the middle of a row (`Layout.hour_start`, a cell,
  not a row). A CP-SAT model (`layout-solver/`) finds the word order:
  - 19 × 9 is infeasible, with the apostrophe in its own cell or in the cell
    of the O. So no grid of 9 rows or fewer gives larger letters than 20 × 9.
  - In 20 × 9, the user chose the layout with no shared letters (proved
    optimal: 5 fillers, all needed, and 32 pairs of numbers out of order,
    most of them in the minute words). The other candidate had 4 shared
    letters and 23 pairs out of order.
- 2026-11-19: 15 minutes is now "A QUARTER", and `LAYOUT_20X9` has a word A
  and 1 shared letter. See `../2026-11-19-wordclock-a-quarter/PLAN.md`.
- 2026-11-19: The image is now drawn in antialiased grey (unlit letters at
  `grey_level`) and made 1-bit by Floyd–Steinberg, not thresholded text with
  a 4 × 4 Bayer dither of the unlit letters. On the display, half of each,
  the user could not tell them apart at a viewing distance, and close up each
  looked odd in its own way. Floyd–Steinberg needs less code.
