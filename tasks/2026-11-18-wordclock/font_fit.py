"""Largest cap height each font reaches in each grid shape on an 800x480 screen.
A letter fits if its ink is <= 85% of the cell width and <= 70% of the cell height."""
import string
from PIL import ImageFont
TEX = "/usr/local/texlive/2026/texmf-dist/fonts/truetype"
FONTS = {
    "DejaVu Sans (current)": "/Users/martin/Develop/weather/DejaVuSans.ttf",
    "DejaVu Sans Bold": f"{TEX}/public/dejavu/DejaVuSans-Bold.ttf",
    "DejaVu Sans Condensed Bold": f"{TEX}/public/dejavu/DejaVuSansCondensed-Bold.ttf",
    "Open Sans Condensed Bold": f"{TEX}/ascender/opensans/OpenSansCondensed-Bold.ttf",
}
SHAPES = [(18, 11), (17, 11), (20, 10), (16, 10)]
def cap_height(path, columns, rows):
    cell_width, cell_height = 800 / columns, 480 / rows
    best = 0
    for size in range(10, 120):
        font = ImageFont.truetype(path, size)
        widest = max(font.getbbox(letter)[2] - font.getbbox(letter)[0] for letter in string.ascii_uppercase)
        top, bottom = font.getbbox("H")[1], font.getbbox("H")[3]
        if widest > 0.85 * cell_width or bottom - top > 0.70 * cell_height:
            break
        best = bottom - top
    return best
print("font".ljust(30), *[f"{c}x{r}".rjust(7) for c, r in SHAPES])
for name, path in FONTS.items():
    print(name.ljust(30), *[f"{cap_height(path, c, r):5d}px" for c, r in SHAPES])
