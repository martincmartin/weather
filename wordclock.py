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
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


@dataclass(frozen=True)
class Phrase:
    """The words to light. The hour words are searched for from Layout.hour_start on."""

    lead: tuple[str, ...]
    hour: tuple[str, ...]

    def __str__(self) -> str:
        return " ".join(self.lead + self.hour)


def phrase_for(hour: int, minute: int) -> Phrase:
    """The phrase for a time. hour is 0 to 23, minute is 0 to 59."""
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"no such time: {hour}:{minute}")
    # After half past, the phrase names the next hour: 11:45 is "A QUARTER TO
    # TWELVE PM", and 23:45 is "A QUARTER TO TWELVE AM".
    shown_hour = (hour if minute <= 30 else hour + 1) % 24
    hour_word = NUMBER_WORDS[shown_hour % 12 or 12]
    meridiem = "AM" if shown_hour < 12 else "PM"
    lead = ["IT", "IS"]
    if minute == 0:
        return Phrase(tuple(lead), (hour_word, "O’CLOCK", meridiem))
    offset = minute if minute <= 30 else 60 - minute
    if offset == 15:
        lead += ["A", "QUARTER"]
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
    return Phrase(tuple(lead), (hour_word, meridiem))


@dataclass(frozen=True)
class Layout:
    """A letter grid, and the cell where its hour words start.

    Each character of rows is one cell. Upper case letters and the apostrophe
    make the words. Lower case letters are filler, which is never lit, so a
    word cannot match it. Two words that never light together can share a
    letter. The cells before hour_start also hold the words ONE to TWELVE,
    for the minutes.
    """

    rows: tuple[str, ...]
    hour_start: Cell

    def __post_init__(self) -> None:
        if any(len(row) != self.column_count for row in self.rows):
            raise ValueError("each row must have the same number of cells")
        row, column = self.hour_start
        if not (0 < row < self.row_count and 0 <= column < self.column_count):
            raise ValueError(f"hour_start {self.hour_start} is not in the grid")

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.rows[0])

    def lit_cells(self, phrase: Phrase) -> set[Cell]:
        """The cells to light. Raise ValueError if the grid cannot show the phrase."""
        lit: set[Cell] = set()
        cursor = (0, 0)
        for word in phrase.lead:
            cursor = self._place_word(word, cursor, lit)
        cursor = max(cursor, self.hour_start)
        for word in phrase.hour:
            cursor = self._place_word(word, cursor, lit)
        return lit

    def _place_word(self, word: str, start: Cell, lit: set[Cell]) -> Cell:
        """Add the cells of the first match of word at or after start to lit.

        Return where the next word can start: one cell after the end of this
        word, so that two lit words never touch.
        """
        start_row, start_column = start
        for row in range(start_row, self.row_count):
            first_column = start_column if row == start_row else 0
            column = self.rows[row].find(word, first_column)
            if column >= 0:
                lit.update((row, column + index) for index in range(len(word)))
                return (row, column + len(word) + 1)
        raise ValueError(f"the grid cannot show {word!r} after cell {start}")

    def check(self) -> None:
        """Raise ValueError if the grid cannot show some minute of the day."""
        for hour in range(24):
            for minute in range(60):
                self.lit_cells(phrase_for(hour, minute))


# 20 x 10: cells narrower than they are tall, so little space between the
# letters of a row. The fewest columns for 10 rows:
# see tasks/2026-11-18-wordclock/PLAN.md. The CP-SAT model in
# tasks/2026-11-19-wordclock-a-quarter/ found this order, by the same rules as
# LAYOUT_20X9: no shared letters, 3 filler letters between words (not proved
# the fewest), and then the closest to numerical order.
LAYOUT_20X10 = Layout(
    rows=(
        "ITkISpTWENTYAONETWOz",
        "QUARTERTHREETHIRTEEN",
        "ELEVENTWELVEFOURTEEN",
        "FIVESIXTEENSEVENTEEN",
        "TENEIGHTEENNINETEENq",
        "MINUTESHALFTOPASTjxv",
        "ONETWOTHREEFOURFIVEb",
        "SIXSEVENEIGHTNINETEN",
        "ELEVENTWELVEmO’CLOCK",
        "PMAMdgwrycfhlukpzqjx",
    ),
    hour_start=(6, 0),
)

# 20 x 9 (the default): letters 9% taller than in 20 x 10 (36 px, not 33 px).
# 19 x 9 cannot show these phrases, so 20 x 9 is the smallest grid of 9 rows.
# The CP-SAT model in tasks/2026-11-19-wordclock-a-quarter/ found this order,
# and proved it the best by these rules, in this order: the fewest shared
# letters (1: SIXTEEN and NINETEEN), the fewest filler letters between words
# (5, each one between two words that light one after the other), and then
# the closest to numerical order. The other words touch. An unlit word can
# stand between two lit words: QUARTER between TWELVE and MINUTES, HALF and
# TO between FIVE and PAST. The A of "A QUARTER" is a word of its own, before
# HALF, so that the clock does not light the A of HALF. The hour words start
# in row 5, after PAST.
LAYOUT_20X9 = Layout(
    rows=(
        "ITkISpTWENTYTHIRTEEN",
        "AONETWOTHREEFOURTEEN",
        "TENSEVENTEENEIGHTEEN",
        "ELEVENSIXTEENINETEEN",
        "TWELVEQUARTERMINUTES",
        "FIVEHALFTOPASTzTHREE",
        "ONETWOFOURFIVESIXTEN",
        "SEVENEIGHTNINEELEVEN",
        "TWELVEqO’CLOCKjAMPMx",
    ),
    hour_start=(5, 15),
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
    # The darkness of an unlit letter (or its outline): 0 is white, 1 is
    # black. The dither makes about this part of its pixels black.
    grey_level: float = 0.33

    def __post_init__(self) -> None:
        if not 0 <= self.grey_level <= 1:
            raise ValueError(f"grey_level must be 0 to 1, not {self.grey_level}")


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
    letters = {character.upper() for row in layout.rows for character in row}
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
        raise ValueError(f"{text!r} has no ink in {font.path!r}")
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
    lit = layout.lit_cells(phrase_for(time.hour, time.minute))
    font = fitted_font(settings)
    # Draw in antialiased grey levels (white 255, black 0), then make the image
    # 1-bit with Floyd–Steinberg dithering. An ordered (Bayer) dither of the
    # unlit letters, with the text thresholded, looked the same at a viewing
    # distance and needed more code.
    image = Image.new("L", (settings.width, settings.height), 255)
    draw = ImageDraw.Draw(image)
    unlit_ink = round(255 * (1 - settings.grey_level))
    cell_width = settings.width / layout.column_count
    cell_height = settings.height / layout.row_count
    baseline_offset = _cap_height(font) / 2
    for row, characters in enumerate(layout.rows):
        for column, character in enumerate(characters):
            letter = character.upper()
            left, _, right, _ = _ink_box(font, letter)
            x = (column + 0.5) * cell_width - (left + right) / 2
            y = (row + 0.5) * cell_height + baseline_offset
            if (row, column) in lit:
                draw.text((x, y), letter, fill=0, font=font, anchor="ls")
            elif settings.unlit_outline:
                draw.text(
                    (x, y),
                    letter,
                    fill=255,
                    font=font,
                    anchor="ls",
                    stroke_width=settings.outline_width,
                    stroke_fill=unlit_ink,
                )
            else:
                draw.text((x, y), letter, fill=unlit_ink, font=font, anchor="ls")
    return image.convert("1", dither=Image.Dither.FLOYDSTEINBERG)


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
    for layout in (LAYOUT_20X10, LAYOUT_20X9):
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
