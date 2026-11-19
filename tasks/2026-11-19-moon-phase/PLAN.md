# Moon phase images and the phase at midnight

This task replaces the moon phase images of `/stargazing.bmp`, and changes the
time that each night's moon shows.

## Images

The old images had no known source, so they could not be published. The user
prefers images like photographs to icons.

- **NASA Dial-A-Moon renders** (chosen): photographic, with real shadows along
  the terminator; not under copyright; an API gives the frame for each hour.
- **Draw the phases with PIL** from one photograph of the full moon: no source
  question, but the terminator is a flat edge, like the old images.

`moon-phase/make_moon_phases.py` makes them: the frame at the hour nearest to
each phase NN/30, cropped to the disc, 120 x 120 pixels (twice the 60 pixels
that the page draws; 344 KB for all 30).

## The phase at midnight

Visual Crossing gives one `moonphase` a day, with 2 digits (±0.005 of a
lunation, ±3.5 hours). Compared with NASA's moon age for 2026-11-19 to 22, its
values fit both the phase near local midnight, rounded, and the phase near
noon UTC, truncated. So an interpolation would rest on a guess.

`moon.py` computes the phase for any time from the low-precision positions of
the Sun and the Moon (Meeus). Checks: within 0.2 hours of the new, quarter and
full moons of January and February 2026; the lit fraction within 0.002 of
NASA's over November 2026. The page shows the phase at each night's midnight,
centred on that night's midnight line.
