"""Run from this directory: python3 font_compare.py. It imports the copy of
wordclock.py here, as it was for the comparison.

Compare fonts in each word clock layout, by ink (not advance) boxes:
cap height, the white space beside each letter in its cell, and stroke weight."""
import dataclasses
import statistics
import string
from pathlib import Path

from PIL import Image, ImageDraw

import wordclock

FONT_DIR = Path("/usr/local/texlive/2026/texmf-dist/fonts")
FONTS = {
    "Open Sans Condensed Bold": FONT_DIR / "truetype/ascender/opensans/OpenSansCondensed-Bold.ttf",
    "JetBrains Mono Bold": FONT_DIR / "opentype/SIL/jetbrainsmono-otf/JetBrainsMono-Bold.otf",
    "Roboto Mono Bold": FONT_DIR / "opentype/google/roboto/RobotoMono-Bold.otf",
    "IBM Plex Mono Bold": FONT_DIR / "opentype/ibm/plex/IBMPlexMono-Bold.otf",
    "Atkinson Hyperlegible Mono Bold": FONT_DIR / "opentype/public/atkinson/AtkinsonHyperlegibleMono-Bold.otf",
    "DejaVu Sans Mono Bold": FONT_DIR / "truetype/public/dejavu/DejaVuSansMono-Bold.ttf",
    "Source Code Pro Bold": FONT_DIR / "opentype/adobe/sourcecodepro/SourceCodePro-Bold.otf",
}

def ink_area(font, text):
    image = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(image).text((20, 150), text, font=font, fill=0, anchor="ls")
    return sum(1 for value in image.get_flattened_data() if value < 128)

def stem_width(font):
    """Width of the left stem of H, a quarter of the way down."""
    image = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(image).text((20, 150), "H", font=font, fill=0, anchor="ls")
    row = 150 + round(wordclock._ink_box(font, "H")[1] * 0.75)
    pixels = [image.getpixel((x, row)) < 128 for x in range(200)]
    first = pixels.index(True)
    return pixels[first:].index(False)

print(f"{'font':34}{'layout':>7}{'cap':>5}{'gap mean':>9}{'gap range':>10}{'stem':>6}{'ink px':>8}")
for name, path in FONTS.items():
    for layout in (wordclock.LAYOUT_18X11, wordclock.LAYOUT_20X10):
        settings = dataclasses.replace(wordclock.DEFAULT_SETTINGS, font_path=path, layout=layout)
        font = wordclock.fitted_font(settings)
        cell_width = settings.width / layout.column_count
        gaps = [cell_width - wordclock._ink_width(font, letter) for letter in string.ascii_uppercase]
        area = statistics.mean(ink_area(font, letter) for letter in string.ascii_uppercase)
        shape = f"{layout.column_count}x{layout.row_count}"
        print(f"{name:34}{shape:>7}{wordclock._cap_height(font):5.0f}{statistics.mean(gaps):9.1f}"
              f"{min(gaps):6.0f}-{max(gaps):<3.0f}{stem_width(font):6d}{area:8.0f}")
