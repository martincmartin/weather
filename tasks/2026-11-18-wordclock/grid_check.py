"""Check a word-clock letter grid: every minute of 12 hours must light in reading order,
with a gap (unlit cell or line break) between any two lit words that touch."""
import sys
from PIL import ImageFont

GRID = [
    "IT.IS.TEN.ELEVEN..",
    "TWELVE.TWENTY.HALF",
    "ONE.TWO.THREE.FIVE",
    "THIRTEEN.FOURTEEN.",
    "SIXTEEN.SEVENTEEN.",
    "EIGHTEEN.NINETEEN.",
    "MINUTES.QUARTER.TO",
    "PAST.ONE.TWO.THREE",
    "FOUR.FIVE.SIX.NINE",
    "SEVEN.EIGHT.ELEVEN",
    "TEN.TWELVE.OCLOCK.",
]
NUMBERS = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
           "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN",
           "EIGHTEEN", "NINETEEN"]

def minute_words(count):
    if count < 20:
        return [NUMBERS[count]]
    return ["TWENTY"] + ([NUMBERS[count - 20]] if count > 20 else [])

def phrase(hour, minute):
    """Words to light for hour 1..12 and minute 0..59."""
    shown_hour = hour if minute <= 30 else hour % 12 + 1
    words = ["IT", "IS"]
    if minute == 0:
        return words + [NUMBERS[shown_hour], "OCLOCK"]
    offset = minute if minute <= 30 else 60 - minute
    if offset == 15:
        words.append("QUARTER")
    elif offset == 30:
        words.append("HALF")
    else:
        words += minute_words(offset) + ["MINUTE" if offset == 1 else "MINUTES"]
    return words + ["PAST" if minute <= 30 else "TO", NUMBERS[shown_hour]]

def place(words, grid):
    """Return (row, start, end) for each word, greedily earliest, or raise."""
    spans, row, col = [], 0, 0
    for word in words:
        while row < len(grid):
            found = grid[row].find(word, col)
            if found >= 0:
                spans.append((row, found, found + len(word)))
                row, col = row, found + len(word) + 1  # +1: the next lit word needs a gap
                break
            row, col = row + 1, 0
        else:
            raise ValueError(f"cannot place {word!r} in {words}")
    return spans

def main():
    width = {len(line) for line in GRID}
    assert len(width) == 1, width
    failures = 0
    for hour in range(1, 13):
        for minute in range(60):
            try:
                place(phrase(hour, minute), GRID)
            except ValueError as error:
                failures += 1
                print(error)
    print(f"grid {width.pop()} x {len(GRID)}: {720 - failures}/720 times OK")
    for sample in [(5, 33), (6, 27), (12, 45), (12, 31), (3, 1), (11, 59)]:
        print(sample, " ".join(phrase(*sample)))

if __name__ == "__main__":
    main()
