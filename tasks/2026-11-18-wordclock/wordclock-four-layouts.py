"""A word clock for the 800x480 1-bit e-ink display, to the minute.

It lights words in a letter grid, for example "IT IS TWENTY SEVEN MINUTES TO
SIX PM". The unlit letters stay visible, in grey (dithered) or as outlines.
weather.py serves the image at /wordclock.bmp.

Run this file to check that each layout can show every minute, and to write
preview images of each layout:

    python3 wordclock.py OUTPUT_DIR [HH:MM]

The grid design and the options that were compared are in
tasks/2026-11-18-wordclock/PLAN.md.
"""

import dataclasses
import datetime
import re
import sys
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

NUMBER_WORDS = (
    "",
    "ONE",
    "TWO",
    "THREE",
    "FOUR",
    "FIVE",
    "SIX",
    "SEVEN",
    "EIGHT",
    "NINE",
    "TEN",
    "ELEVEN",
    "TWELVE",
    "THIRTEEN",
    "FOURTEEN",
    "FIFTEEN",
    "SIXTEEN",
    "SEVENTEEN",
    "EIGHTEEN",
    "NINETEEN",
)

Cell = tuple[int, int]  # (row, column)


def split_cells(text: str) -> list[str]:
    """Split text into grid cells: one letter each, with its apostrophe."""
    return re.findall(r".’?", text)


@dataclass(frozen=True)
class Phrase:
    """The words to light. The hour words are searched for from Layout.hour_row on."""

    lead: tuple[str, ...]
    hour: tuple[str, ...]

    def __str__(self) -> str:
        return " ".join(self.lead + self.hour)


def phrase_for(hour: int, minute: int, has_am_pm: bool = True) -> Phrase:
    """The phrase for a time. hour is 0 to 23, minute is 0 to 59. If has_am_pm,
    the phrase ends with AM or PM."""
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"no such time: {hour}:{minute}")
    # After half past, the phrase names the next hour: 11:45 is "QUARTER TO
    # TWELVE PM", and 23:45 is "QUARTER TO TWELVE AM".
    shown_hour = (hour if minute <= 30 else hour + 1) % 24
    hour_word = NUMBER_WORDS[shown_hour % 12 or 12]
    meridiem = ("AM" if shown_hour < 12 else "PM",) if has_am_pm else ()
    lead = ["IT", "IS"]
    if minute == 0:
        return Phrase(tuple(lead), (hour_word, "O’CLOCK", *meridiem))
    offset = minute if minute <= 30 else 60 - minute
    if offset == 15:
        lead.append("QUARTER")
    elif offset == 30:
        lead.append("HALF")
    else:
        if offset < 20:
            lead.append(NUMBER_WORDS[offset])
        else:
            lead += ["TWENTY", NUMBER_WORDS[offset - 20]] if offset > 20 else ["TWENTY"]
        # People say "twenty past six" but "twenty three minutes past six".
        if offset % 5 != 0:
            lead.append("MINUTE" if offset == 1 else "MINUTES")
    lead.append("PAST" if minute <= 30 else "TO")
    return Phrase(tuple(lead), (hour_word, *meridiem))


@dataclass(frozen=True)
class Layout:
    """A letter grid, the row where its hour words start, and whether it
    shows AM and PM.

    In rows, upper case letters make the words. Lower case letters are
    filler, which is never lit, so a word cannot match it. Two words that
    never light together can share a letter. An apostrophe
    belongs to the cell of the letter before it. The rows above hour_row also
    hold the words ONE to TWELVE, for the minutes.
    """

    rows: tuple[str, ...]
    hour_row: int
    has_am_pm: bool = True

    def __post_init__(self) -> None:
        if any(len(row) != self.column_count for row in self.cells):
            raise ValueError("each row must have the same number of cells")
        if not 0 < self.hour_row < self.row_count:
            raise ValueError(f"hour_row {self.hour_row} is not in the grid")

    @cached_property
    def cells(self) -> tuple[list[str], ...]:
        return tuple(split_cells(row) for row in self.rows)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.cells[0])

    def lit_cells(self, phrase: Phrase) -> set[Cell]:
        """The cells to light. Raise ValueError if the grid cannot show the phrase."""
        lit: set[Cell] = set()
        cursor = (0, 0)
        for word in phrase.lead:
            cursor = self._place_word(word, cursor, lit)
        cursor = max(cursor, (self.hour_row, 0))
        for word in phrase.hour:
            cursor = self._place_word(word, cursor, lit)
        return lit

    def _place_word(self, word: str, start: Cell, lit: set[Cell]) -> Cell:
        """Add the cells of the first match of word at or after start to lit.

        Return where the next word can start: one cell after the end of this
        word, so that two lit words never touch.
        """
        target = split_cells(word)
        start_row, start_column = start
        for row in range(start_row, self.row_count):
            row_cells = self.cells[row]
            first_column = start_column if row == start_row else 0
            for column in range(first_column, self.column_count - len(target) + 1):
                if row_cells[column : column + len(target)] == target:
                    lit.update((row, column + index) for index in range(len(target)))
                    return (row, column + len(target) + 1)
        raise ValueError(f"the grid cannot show {word!r} after cell {start}")

    def check(self) -> None:
        """Raise ValueError if the grid cannot show some minute of the day."""
        for hour in range(24):
            for minute in range(60):
                self.lit_cells(phrase_for(hour, minute, self.has_am_pm))


# 18 x 11: square cells, but more space between the letters of a row than in
# 20 x 10, and smaller letters. To make room for AM and PM, some hour words
# have no gap between them: they never light together.
LAYOUT_18X11 = Layout(
    rows=(
        "ITkISpTENzELEVENqj",
        "TWELVExTWENTYvHALF",
        "ONEbTWOmTHREEdFIVE",
        "THIRTEENwFOURTEENg",
        "SIXTEENrSEVENTEENy",
        "EIGHTEENcNINETEENf",
        "MINUTESjQUARTERzTO",
        "PASTvONEhTWOxTHREE",
        "FOURlFIVEkSIXSEVEN",
        "EIGHTNINETENELEVEN",
        "TWELVEbO’CLOCKcAMPM",
    ),
    hour_row=7,
)
# 20 x 10: narrower cells, so less space between the letters of a row, and
# 10% taller letters with a monospaced font. The fewest columns for 10 rows:
# see tasks/2026-11-18-wordclock/PLAN.md. To fit, the minute words are not in
# numeric order.
LAYOUT_20X10 = Layout(
    rows=(
        "ITaISpQUARTERzTWENTY",
        "ONEkELEVENxSEVENTEEN",
        "TWOvFOURTEENrSIXTEEN",
        "THREEdFIVEgNINETEENb",
        "HALFmTWELVEcTHIRTEEN",
        "TENjEIGHTEENwMINUTES",
        "PASTqTOzONEhTWOTHREE",
        "FOURlFIVEkSIXwSEVENy",
        "EIGHTNINEfTENpELEVEN",
        "TWELVEvO’CLOCKcAMxPMj",
    ),
    hour_row=6,
)

# 20 x 9 (the default): letters 9% taller than in 20 x 10 (36 px, not 33 px).
# To fit, words that never light together share a letter (TWONE is TWO and
# ONE), and the hour words have no gaps. Words share a letter or touch only
# where the grid needs it to fit. The fewest columns for 9 rows: in 19
# columns, the hour words, O'CLOCK, AM and PM do not fit in 3 rows.
LAYOUT_20X9 = Layout(
    rows=(
        "ITaISpQUARTERzTWENTY",
        "TWONEIGHTEENINETEENx",
        "THREELEVENkSEVENTEEN",
        "TENyFOURTEENvSIXTEEN",
        "HALFbTWELVEcTHIRTEEN",
        "FIVEjMINUTESwPASTkTO",
        "TENFIVESIXTHREELEVEN",
        "FOURSEVENINEIGHTWONE",
        "TWELVEvO’CLOCKcAMxPMj",
    ),
    hour_row=6,
)

# 19 x 9, without AM and PM: letters 37 px, the most that 9 rows permit. As
# in 20 x 9, words that never light together share a letter.
LAYOUT_19X9 = Layout(
    rows=(
        "ITaISpQUARTERTWENTY",
        "TWONEIGHTEENINETEEN",
        "HALFOURTEENySIXTEEN",
        "THIRTEENkTHREELEVEN",
        "TENTWELVEbSEVENTEEN",
        "FIVEjMINUTESwPASTOg",
        "SIXrFOURkTWONELEVEN",
        "FIVEmSEVENINEIGHTEN",
        "THREEvTWELVEcO’CLOCK",
    ),
    hour_row=6,
    has_am_pm=False,
)


@dataclass(frozen=True)
class Settings:
    font_path: Path
    layout: Layout = LAYOUT_20X9
    # Draw an unlit letter as its outline (True) or filled (False). Outlines
    # look busy at a distance, so filled is the choice.
    unlit_outline: bool = False
    width: int = 800
    height: int = 480
    # The largest part of a cell that the ink of a letter can fill.
    max_width_fill: float = 0.85
    max_height_fill: float = 0.70
    outline_width: int = 3
    # The part of the pixels of an unlit letter (or its outline) that are
    # black, by an ordered dither: 0 is white, 1 is black. The steps are 1/16.
    grey_level: float = 0.33

    def __post_init__(self) -> None:
        if not 0 <= self.grey_level <= 1:
            raise ValueError(f"grey_level must be 0 to 1, not {self.grey_level}")

    # The gap between the O and its apostrophe, as a part of the font size.
    apostrophe_gap: float = 0.03


DEFAULT_SETTINGS = Settings(
    # Monospaced, so the space beside each letter is about the same. Heavy
    # strokes keep the dithered unlit letters legible at a distance.
    font_path=Path(__file__).parent / "AtkinsonHyperlegibleMono-Bold.otf",
)


@cache
def fitted_font(settings: Settings) -> ImageFont.FreeTypeFont:
    """The largest font in which each letter of the grid fits in its cell."""
    layout = settings.layout
    cell_width = settings.width / layout.column_count
    cell_height = settings.height / layout.row_count
    letters = {cell[0].upper() for row in layout.cells for cell in row}
    best: ImageFont.FreeTypeFont | None = None
    for size in range(8, 200):
        font = ImageFont.truetype(settings.font_path, size)
        widest = max(_ink_width(font, letter) for letter in letters)
        if (
            widest > settings.max_width_fill * cell_width
            or _cap_height(font) > settings.max_height_fill * cell_height
        ):
            break
        best = font
    if best is None:
        raise ValueError(f"no size of {settings.font_path} fits the cells")
    return best


def _ink_box(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    """The box (left, top, right, bottom) of the ink of text drawn at (0, 0)
    with its baseline at y = 0.

    Not font.getbbox(): horizontally, that box is the advance width, which in
    a monospaced font is much wider than a narrow glyph such as I or ’.
    """
    mask, (offset_x, offset_y) = font.getmask2(text, anchor="ls")
    box = mask.getbbox()
    if box is None:
        raise ValueError(f"{text!r} has no ink in {font.path}")
    left, top, right, bottom = box
    return (offset_x + left, offset_y + top, offset_x + right, offset_y + bottom)


def _ink_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    left, _, right, _ = _ink_box(font, text)
    return right - left


def _cap_height(font: ImageFont.FreeTypeFont) -> float:
    _, top, _, _ = _ink_box(font, "H")
    return -top


def render(
    time: datetime.time | datetime.datetime, settings: Settings = DEFAULT_SETTINGS
) -> Image.Image:
    """A 1-bit image of the clock at the given time."""
    layout = settings.layout
    lit = layout.lit_cells(phrase_for(time.hour, time.minute, layout.has_am_pm))
    font = fitted_font(settings)
    size = (settings.width, settings.height)
    # Draw in grey levels (white 255, ink 0), then make it 1-bit at the end.
    lit_layer = Image.new("L", size, 255)
    unlit_layer = Image.new("L", size, 255)
    cell_width = settings.width / layout.column_count
    cell_height = settings.height / layout.row_count
    baseline_offset = _cap_height(font) / 2
    for row, row_cells in enumerate(layout.cells):
        for column, cell in enumerate(row_cells):
            letter, mark = cell[0].upper(), cell[1:]
            left, _, right, _ = _ink_box(font, letter)
            x = (column + 0.5) * cell_width - (left + right) / 2
            y = (row + 0.5) * cell_height + baseline_offset
            is_lit = (row, column) in lit
            layer = lit_layer if is_lit else unlit_layer
            _draw_text(layer, (x, y), letter, font, settings, is_lit)
            if mark:
                mark_left = _ink_box(font, mark)[0]
                gap = settings.apostrophe_gap * font.size
                mark_x = x + right + gap - mark_left
                _draw_text(layer, (mark_x, y), mark, font, settings, is_lit)
    # Keep the unlit ink only where the dither pattern is black.
    unlit_layer = ImageChops.lighter(
        unlit_layer.point(_threshold), _dither_pattern(settings)
    )
    image = ImageChops.darker(lit_layer, unlit_layer)
    return image.point(_threshold).convert("1")


# An ordered dither: a pixel is black if its value is less than the number of
# black pixels in each 4 x 4 tile. At 8 of 16, this gives a checkerboard.
BAYER_4X4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def _dither_pattern(settings: Settings) -> Image.Image:
    """A black (0) and white (255) image, black in grey_level of its pixels."""
    black_per_tile = round(settings.grey_level * 16)
    tile_rows = [
        bytes(0 if row[x % 4] < black_per_tile else 255 for x in range(settings.width))
        for row in BAYER_4X4
    ]
    rows = [tile_rows[y % 4] for y in range(settings.height)]
    return Image.frombytes("L", (settings.width, settings.height), b"".join(rows))


def _threshold(value: int) -> int:
    return 255 if value >= 128 else 0


def _draw_text(
    layer: Image.Image,
    position: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    settings: Settings,
    is_lit: bool,
) -> None:
    draw = ImageDraw.Draw(layer)
    if is_lit or not settings.unlit_outline:
        draw.text(position, text, fill=0, font=font, anchor="ls")
    else:
        draw.text(
            position,
            text,
            fill=0,
            font=font,
            anchor="ls",
            stroke_width=settings.outline_width,
            stroke_fill=0,
        )
        draw.text(position, text, fill=255, font=font, anchor="ls")


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    output_dir = Path(sys.argv[1])
    time = (
        datetime.time.fromisoformat(sys.argv[2])
        if len(sys.argv) == 3
        else datetime.datetime.now().time()
    )
    print(phrase_for(time.hour, time.minute))
    output_dir.mkdir(parents=True, exist_ok=True)
    for layout in (LAYOUT_18X11, LAYOUT_20X10, LAYOUT_20X9, LAYOUT_19X9):
        layout.check()
        shape = f"{layout.column_count}x{layout.row_count}"
        font = fitted_font(dataclasses.replace(DEFAULT_SETTINGS, layout=layout))
        print(
            f"{shape}: can show every minute. Font size {font.size},"
            f" cap height {_cap_height(font):.0f} px."
        )
        for unlit_outline in (False, True):
            settings = dataclasses.replace(
                DEFAULT_SETTINGS, layout=layout, unlit_outline=unlit_outline
            )
            style = "outline" if unlit_outline else "filled"
            path = output_dir / f"wordclock-{shape}-{style}.png"
            render(time, settings).save(path)
            print(f"Wrote {path}")


if __name__ == "__main__":
    main()
