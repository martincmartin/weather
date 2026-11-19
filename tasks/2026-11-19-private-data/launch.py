"""Run a weather.py with urlopen recorded to, or replayed from, a fixture dir.

python3 launch.py record|replay FIXTURE_DIR SCRIPT CHDIR_AS [ARGS...]

CHDIR_AS is the path that the script sees as sys.argv[0], so that it changes
to the project directory. Each URL is logged as a hash, never as text, since
it holds an API key.
"""

import hashlib
import io
import sys
import urllib.request
from pathlib import Path

mode, fixtures, script, chdir_as, *arguments = sys.argv[1:]
fixtures = Path(fixtures)
fixtures.mkdir(exist_ok=True)
real_urlopen = urllib.request.urlopen


class Replayed(io.BytesIO):
    status = 200


def urlopen(url, timeout=None):
    name = hashlib.sha256(url.encode()).hexdigest()[:16]
    print(f"[fixture] {mode} {name}", flush=True)
    path = fixtures / name
    if mode == "record" and not path.exists():
        with real_urlopen(url, timeout=timeout) as response:
            path.write_bytes(response.read())
    return Replayed(path.read_bytes())


urllib.request.urlopen = urlopen
sys.argv = [chdir_as, *arguments]
sys.path.insert(0, str(Path(chdir_as).parent))
code = compile(Path(script).read_text(), script, "exec")
# Not runpy: it sets sys.argv[0] to the script, so weather.py would chdir there.
exec(code, {"__name__": "__main__", "__file__": script})  # noqa: S102 runs the script under test
