# Word clock: "IT IS A QUARTER PAST"

This task adds the word A before QUARTER: "IT IS A QUARTER PAST SIX PM". It
records where the A can come from and the grid that the solver finds for each
option. The earlier task is `../2026-11-18-wordclock/PLAN.md`. Its
`layout-solver/README.md` gives the rules of the solver.

Files in this task (copies; do not update them):

- `wordclock.py`: the project file, with A before QUARTER in `phrase_for`.
- `cp_grid.py`: the CP-SAT solver of the earlier task, with the option
  `--a-from` and a line for each better layout that it finds.
- `runs/`: the logs, and the renders at 15:15.

## The source of the A

In `LAYOUT_20X9`, no A comes between IS and QUARTER: HALF comes after
QUARTER, and no filler cell is between them. So the grid must change. A lit
A needs an unlit cell or a line break before it (after IS) and after it
(before QUARTER).

- **bare**: a new word of one letter, A. It costs one cell, and maybe one
  filler cell on each side. The grid has 6 spare cells (5 fillers and 1 at the
  end of the last row). It must come before HALF, because the clock lights the
  first A after IS.
- **half**: the A of HALF. HALF is never lit with QUARTER, so its A is free.
  The H and the L are the unlit cells on each side. It costs no cell, but HALF
  must move before QUARTER, so the order of the words changes.

No other word can give the A. QUARTER, PAST and AM have an A, but each is lit
in the same phrase, after the A.

## Solver runs

Both runs use 20 × 9, the apostrophe in its own cell, and the priority shares,
then fillers, then inversions (the user prefers touching words to fillers, and
fillers to shared letters). Each run has 6 of the 12 cores and at most
5 hours.

In 30-second trial runs, each option found a layout with 1 shared letter. So
`--max-shares 1` does not remove the best layout, and it helps the solver to
prune.

## Results

CP-SAT proved each layout optimal. So, with the A, each 20 × 9 grid needs 1
shared letter. Both pass all 1440 minutes, and both keep the font at size 54
(cap height 36 px). The renders at 15:15 are `runs/a-from-*-1515.png`.

- **bare** (`runs/run-20x9-bare-a.txt`, 881 s): 1 share (SIXTEEN·NINETEEN),
  5 fillers, 31 inversions. The A starts row 2, below IT IS. The other rows
  are close to `LAYOUT_20X9`.
- **half** (`runs/run-20x9-half-a.txt`, 1229 s): 1 share (TWO·ONE), 6
  fillers, 19 inversions. HALF comes just before QUARTER in row 4.
- **20 × 10, bare** (`runs/run-20x10-bare-a.txt`, 1800 s, 12 cores): 0
  shares, 3 fillers, 12 inversions. Not proved optimal. The old
  `LAYOUT_20X10` had no A, so this layout replaces it.

## Choice

The user chose **bare** for `LAYOUT_20X9`. With the user's priorities, it
wins: its share ties with half, and it has 1 filler fewer. It also keeps most
of the old order, and the lit A stands alone at the start of a row. Half has
12 fewer inversions, but its shared letter (TWO·ONE at the end of row 1) and
the order TEN, TWO, ONE are harder to read.
