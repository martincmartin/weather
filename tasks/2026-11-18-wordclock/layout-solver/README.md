# Layout solver

What this holds: the CP-SAT model that found `LAYOUT_20X9`, the copy of
`wordclock.py` that it imports, and the logs of its runs. Read it before you
change the word order of a layout. The task is `../PLAN.md`.

- `cp_grid.py`: the model. Its docstring gives the rules, the priorities and
  the command.
- `wordclock.py`: a copy of the project file when the layout was chosen.
- `runs/run-20x9.txt`, `runs/run-20x9-long.txt`: priority fillers, shares,
  inversions; 5 and 15 minutes. Best found: 4 fillers, 4 shares (all in the
  hour words), 23 inversions; not proved optimal.
- `runs/run-20x9-max3.txt`: priority shares, fillers, inversions, at most 3
  shares. OPTIMAL: 0 shares, 5 fillers, 32 inversions. This is
  `LAYOUT_20X9`.
- `runs/run-19x9.txt`, `runs/run-19x9-attached.txt`: INFEASIBLE, with the
  apostrophe in its own cell and in the cell of the O.
