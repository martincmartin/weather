"""Make the 30 moon phase images for /stargazing.bmp from NASA renders.

Run from the project directory: PYTHONPATH=. python3 moon-phase/make_moon_phases.py

The images come from NASA's Dial-A-Moon (Scientific Visualization Studio,
https://svs.gsfc.nasa.gov/gallery/moonphase/). NASA renders them from Lunar
Reconnaissance Orbiter data. NASA material is not under copyright; credit
"NASA's Scientific Visualization Studio".

phase-NN.png shows the moon at the hour nearest to phase NN/30 (moon.phase), in
the lunation from the new moon of 2026-01-18 19:51 UTC to that of 2026-02-17
12:01 UTC: phase-00 is new, phase-15 is full. Each image is the disc only, 120 x 120
pixels, grey with an alpha channel.
"""

import datetime
import io
import json
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

import moon

DIAL_A_MOON = "https://svs.gsfc.nasa.gov/api/dialamoon/{time:%Y-%m-%dT%H:%M}"
NEW_MOON = datetime.datetime(2026, 1, 18, 19, 51, tzinfo=datetime.UTC)
LUNATION = datetime.timedelta(days=29.673)  # to the new moon of 2026-02-17
PHASE_COUNT = 30
# The frames are 730 x 730 pixels, with the moon at the centre, 0.35 pixels
# for each arcsecond of its apparent diameter (measured on a full moon).
PIXELS_PER_ARCSECOND = 0.35
SIZE = 120  # twice MOON_PHASE_BOX in weather.py
MASK_OVERSAMPLE = 4  # for a smooth edge on the alpha mask


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def time_of_phase(target: float) -> datetime.datetime:
    """The time in the lunation after NEW_MOON when moon.phase() is target."""
    time = NEW_MOON + LUNATION * target
    for _ in range(5):  # Newton's method; the phase grows at about 1/LUNATION
        error = (moon.phase(time) - target + 0.5) % 1 - 0.5
        time -= LUNATION * error
    return time


def frame_at(time: datetime.datetime) -> tuple[Image.Image, float]:
    """The Dial-A-Moon frame for the hour nearest to time, and the moon's
    apparent diameter in arcseconds."""
    hour = (time + datetime.timedelta(minutes=30)).replace(minute=0, second=0)
    data = json.loads(fetch(DIAL_A_MOON.format(time=hour)))
    url = data["image"]["url"].replace("http://", "https://")
    return Image.open(io.BytesIO(fetch(url))).convert("L"), data["diameter"]


def disc(frame: Image.Image, diameter: float) -> Image.Image:
    """The moon's disc from frame, scaled to SIZE, with a round alpha mask."""
    radius = diameter * PIXELS_PER_ARCSECOND / 2
    centre_x, centre_y = frame.width / 2, frame.height / 2
    box = (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius)
    grey = frame.resize((SIZE, SIZE), Image.Resampling.LANCZOS, box=box)
    large = SIZE * MASK_OVERSAMPLE
    mask = Image.new("L", (large, large), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, large - 1, large - 1), fill=255)
    mask = mask.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return Image.merge("LA", (grey, mask))


def main() -> None:
    folder = Path(__file__).parent
    for index in range(PHASE_COUNT):
        frame, diameter = frame_at(time_of_phase(index / PHASE_COUNT))
        disc(frame, diameter).save(folder / f"phase-{index:02d}.png", optimize=True)
        print(f"phase-{index:02d}.png")


if __name__ == "__main__":
    main()
