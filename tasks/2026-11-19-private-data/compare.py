"""Serve the old and new weather.py in turn on the same fixtures; compare.

The old code is weather-before.py next to this file: the project file before
the change. This task does not keep that copy, since it held the private
locations. It reads its API keys and home location from the private service
file, as the old code did. The first run records the API responses in
fixtures/; then both versions replay them, and each page must be the same.
"""

import hashlib
import http.client
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PROJECT = Path(__file__).resolve().parents[2]
FIXTURES = HERE / "fixtures"
PATHS = [
    "/weather.bmp",
    "/second.bmp",
    "/third.bmp",
    "/stargazing.bmp",
    "/wordclock.bmp",
    "/pics.bmp",
    "/nope",
]

service = (
    PROJECT / "weather.service.martin-specific-dont-upload-to-github"
).read_text()
keys = dict(re.findall(r'^Environment="(\w+)=([^"]+)"', service, re.MULTILINE))
home = re.search(
    r"^ExecStart=\S+ \S+weather\.py (\S+) (\S+)$", service, re.MULTILINE
).groups()


def serve(mode, script, arguments, environment):
    with open(HERE / f"log-{script.stem}-{mode}.txt", "w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(HERE / "launch.py"),
                mode,
                str(FIXTURES),
                str(script),
                str(PROJECT / "weather.py"),
                *arguments,
            ],
            env={**os.environ, **environment},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            return fetch_pages()
        finally:
            process.terminate()
            process.wait()


def fetch_pages():
    for _ in range(100):
        try:
            http.client.HTTPConnection("localhost", 8998, timeout=1).connect()
            break
        except OSError:
            time.sleep(0.2)
    results = {}
    for path in PATHS:
        connection = http.client.HTTPConnection("localhost", 8998, timeout=60)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        results[path] = (
            response.status,
            response.getheader("Location"),
            hashlib.sha256(body).hexdigest()[:16],
            len(body),
        )
    return results


old = HERE / "weather-before.py"
new = PROJECT / "weather.py"
serve("record", old, list(home), keys)
for attempt in range(3):
    before = serve("replay", old, list(home), keys)
    after = serve("replay", new, [], {})
    if before == after:
        break
for path in PATHS:
    mark = "same" if before[path] == after[path] else "DIFFERENT"
    status, location, digest, size = after[path]
    print(
        f"{path:16} {mark:9} status {status}, {size} bytes, sha {digest},"
        f" redirect {'yes' if location else 'no'}"
    )
