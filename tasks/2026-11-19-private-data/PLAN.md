# Private data out of the public repository

This task removes what is specific to the owner from the public repository:
API keys, coordinates, place names and the names of people. It records what
was public, how the history was rewritten, and where the private settings
went.

Files in this task (copies; do not update them):

- `launch.py`: runs a `weather.py` with its HTTP requests recorded to, or
  replayed from, a fixture directory.
- `compare.py`: serves the old and the new `weather.py` on the same recorded
  responses, and compares each page.

## What was public

An audit of every version of every file in the history (27 commits, all text
files, 7 image versions, commit messages and authors) found one leak: commit
`4ca2e83` (2024-01-04) held a test URL with a tomorrow.io API key and the home
coordinates. The next commit removed it. The owner revoked the key.

Also public, and kept: the owner's name and email (deliberate), a thank-you to
Konstantin at Invisible Computers, the kids and the school bus in the README
(no names), the time zone (US Eastern), the LaCrosse sensor model and ID. The
photos have no GPS data.

The other three locations and their names, a person's name, and a Clear Sky
Chart link (which names a place) were only in uncommitted changes, so they
were never public.

## History rewrite

`git filter-repo --replace-text` cleans the line, but it also drops the GitHub
signatures of 6 older web commits, which changes 25 of the 27 hashes. The
history is linear, so we rebuilt only the commits from `4ca2e83` on, with
`git commit-tree`: the same author, committer, dates and message, and the
cleaned tree. The 22 older commits keep their hashes and signatures.

- `4ca2e83` → `1882cd3`; `8832d54` → `8cee956`; `887cbb2` → `6b6923f`;
  `459b105` → `0793f32`; `3adda85` → `eeb58d6`.
- GitHub also had `869738a` (a README edit made on the web, 2024-02-01, never
  pulled). The force-push lease caught it. It became `7709795`, without its
  signature.

The old commits stay visible by hash on GitHub until GitHub Support purges
them, and the fork dezren39/weather has them on its `main`.

## Where the private settings go

The private data: 2 API keys, 4 named locations, the Unsplash query, and notes
(other search terms).

- **A. The systemd service file** (`Environment=` lines and comments). No new
  file, but flat strings: 4 named locations need 12 variables or JSON. Local
  tests need the variables copied into the shell. The repository cannot show
  an example of it.
- **B. A private `config.toml`, in `.gitignore`, with a committed
  `config.example.toml`.** One private file. The locations are tables, the
  notes are comments. The same file works on the Mac and the Pi. Readers of
  the repository see the format. Needs Python 3.11 (`tomllib`) and a small
  refactor.
- **C. An `EnvironmentFile=` that systemd and the shell both read.** Easier
  local tests than A, but the same flat strings.
- **D. B, plus a private repository for `config.toml`.** History and a backup,
  but a second repository for one file.

Ranking: B, A, C, D. The owner chose B.

## Result

`weather.py` reads `config.toml` (or `--config PATH`). The home location is
required; a page whose location is left out returns 404. The location
constants, the positional latitude and longitude, the environment variables
and a function that nothing called (`format_epoch`) are gone.

`compare.py` served `/weather.bmp`, `/second.bmp`, `/third.bmp`,
`/stargazing.bmp`, `/wordclock.bmp`, `/pics.bmp` and a 404 from the old and the
new code: each page and the `/pics.bmp` redirect were byte-identical, and both
versions requested the same 5 URLs.

- 2026-11-19: The pages `/second.bmp` and `/third.bmp` are gone. Each location
  in `config.toml` other than `home` and `stargazing` is a page named after its
  key (`[locations.paris]` is `/paris.bmp`). On the recorded responses, the new
  pages for the two old locations were byte-identical to the old
  `/second.bmp` and `/third.bmp`.
- 2026-11-19: `[unsplash]` is optional; without it, `/pics.bmp` returns 404.
  With it, the redirect is the same as before.
