"""Lay out the whole word clock grid with the OR-Tools CP-SAT solver.

Run from this directory. It imports the copy of wordclock.py here (the
phrases, and Layout to check the result). OR-Tools has no wheels for Python
3.15, so uv runs it with Python 3.13:

    PYTHONPATH=. uv run --no-project --python 3.13 --with ortools --with pillow \
        python cp_grid.py --columns 20 --rows 9 [--attached-apostrophe]
        [--priority shares,fillers,inversions] [--max-shares N]
        [--seconds 300] [--workers 8] [--a-from bare|half]

Each word of a phrase is a word of the grid: the minute words (IT, IS, the
numbers, QUARTER, HALF, MINUTES, PAST, TO) and the hour words (ONE to
TWELVE, O'CLOCK, AM, PM) are different words, even with the same letters.
The hour words can start in the middle of a row.

Each row starts with a word. Between two words in a row:

- a filler cell, if some phrase lights them one right after the other (else
  the lit words would touch); a line break also separates them;
- else they can touch, or share a letter if the last letter of one is the
  first letter of the other and no phrase lights both.

A word comes after each word that some phrase lights before it. The solver
minimises, in the order of --priority:

- fillers: filler cells between two words in a row (spare cells at the end of
  a row do not count);
- shares: letters that two words share;
- inversions: pairs of number words (minute or hour) out of numerical order.

With --attached-apostrophe, the apostrophe of O'CLOCK is in the cell of the
O, so O'CLOCK is 6 cells, not 7.

The A of "IT IS A QUARTER PAST" comes from --a-from:

- bare: a word of one letter, A. It comes before HALF, so that the clock,
  which finds the first A after IS, does not find the A of HALF.
- half: the A of HALF, which then comes before QUARTER. HALF and QUARTER
  are never lit together.
"""

import argparse
import itertools
import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

import wordclock

# A minute unit lights as the first letters of its teen, MINUTE as MINUTES.
CARRIER = {
    "FOUR": "FOURTEEN",
    "SIX": "SIXTEEN",
    "SEVEN": "SEVENTEEN",
    "EIGHT": "EIGHTEEN",
    "NINE": "NINETEEN",
    "MINUTE": "MINUTES",
}
MINUTE_NUMBERS = [
    "TWENTY",  # before its units, so first in numerical order
    "ONE",
    "TWO",
    "THREE",
    "FIVE",
    "TEN",
    "ELEVEN",
    "TWELVE",
    "THIRTEEN",
    "FOURTEEN",
    "SIXTEEN",
    "SEVENTEEN",
    "EIGHTEEN",
    "NINETEEN",
]
MINUTE_OTHERS = ["IT", "IS", "A", "QUARTER", "HALF", "MINUTES", "PAST", "TO"]
HOUR_NUMBERS = list(wordclock.NUMBER_WORDS[1:13])
HOUR_OTHERS = ["O’CLOCK", "AM", "PM"]


@dataclass(frozen=True)
class Word:
    text: str
    is_hour: bool
    cells: int
    rank: int | None  # place in numerical order, if it is a number

    def __str__(self) -> str:
        return self.text


def make_words(
    attached_apostrophe: bool, a_from: str
) -> tuple[dict[str, Word], dict[str, Word]]:
    def cells(text: str) -> int:
        return len(text) - (1 if attached_apostrophe and "’" in text else 0)

    minute = {}
    for text in MINUTE_NUMBERS + MINUTE_OTHERS:
        if text == "A" and a_from != "bare":
            continue
        rank = MINUTE_NUMBERS.index(text) if text in MINUTE_NUMBERS else None
        minute[text] = Word(text, False, cells(text), rank)
    hour = {}
    for text in HOUR_NUMBERS + HOUR_OTHERS:
        rank = HOUR_NUMBERS.index(text) if text in HOUR_NUMBERS else None
        hour[text] = Word(text, True, cells(text), rank)
    return minute, hour


@dataclass(frozen=True)
class LitPart:
    """The cells of a grid word that a phrase word lights."""

    word: Word
    offset: int  # cells before the lit part
    cells: int

    @property
    def to_end(self) -> bool:
        return self.offset + self.cells == self.word.cells


def lit_parts(phrase, minute, hour) -> list[LitPart]:
    """The parts of grid words that the phrase lights, in order."""
    parts = []
    for text in phrase.lead:
        if text == "A" and "A" not in minute:
            parts.append(LitPart(minute["HALF"], 1, 1))
        elif text in CARRIER:
            parts.append(LitPart(minute[CARRIER[text]], 0, len(text)))
        else:
            parts.append(LitPart(minute[text], 0, minute[text].cells))
    return parts + [LitPart(hour[text], 0, hour[text].cells) for text in phrase.hour]


@dataclass(frozen=True)
class Rules:
    before: frozenset[tuple[Word, Word]]
    gap: frozenset[tuple[Word, Word]]
    together: frozenset[frozenset[Word]]


def rules_for(minute, hour) -> Rules:
    before, gap, together = set(), set(), set()
    for hour_of_day in range(24):
        for minute_of_hour in range(60):
            phrase = wordclock.phrase_for(hour_of_day, minute_of_hour)
            parts = lit_parts(phrase, minute, hour)
            for first, second in itertools.combinations(parts, 2):
                before.add((first.word, second.word))
                together.add(frozenset((first.word, second.word)))
            for first, second in itertools.pairwise(parts):
                # An unlit cell of a word, such as TEEN after SIX in SIXTEEN or
                # the H of HALF before its A, separates the lit parts.
                if first.to_end and second.offset == 0:
                    gap.add((first.word, second.word))
    if "A" in minute:
        before.add((minute["A"], minute["HALF"]))
    return Rules(frozenset(before), frozenset(gap), frozenset(together))


@dataclass(frozen=True)
class Weights:
    fillers: int
    shares: int
    inversions: int


def solve(
    words, rules, rows, columns, weights, seconds, fixed, workers, max_shares=None
):
    model = cp_model.CpModel()
    position, row, column = {}, {}, {}
    for word in words:
        row[word] = model.new_int_var(0, rows - 1, f"row {word}")
        column[word] = model.new_int_var(0, columns - word.cells, f"column {word}")
        position[word] = model.new_int_var(0, rows * columns - 1, f"position {word}")
        model.add(position[word] == row[word] * columns + column[word])
        if word in fixed:
            model.add(position[word] == fixed[word])
    first_before = {}
    shares, inversions = [], []
    for first, second in itertools.combinations(words, 2):
        flag = model.new_bool_var(f"{first} before {second}")
        first_before[first, second] = flag
        first_before[second, first] = flag.Not()
        if (first, second) in rules.before:
            model.add(flag == 1)
        if (second, first) in rules.before:
            model.add(flag == 0)
        for a, b in ((first, second), (second, first)):
            a_first = first_before[a, b]
            end_a = position[a] + a.cells
            if (a, b) in rules.gap:
                same_row = model.new_bool_var(f"{a} {b} same row")
                model.add(row[a] == row[b]).only_enforce_if(same_row)
                model.add(row[a] != row[b]).only_enforce_if(same_row.Not())
                model.add(end_a + 1 <= position[b]).only_enforce_if([a_first, same_row])
                model.add(end_a <= position[b]).only_enforce_if(a_first)
            elif a.text[-1] == b.text[0] and frozenset((a, b)) not in rules.together:
                share = model.new_bool_var(f"{a} shares with {b}")
                model.add_implication(share, a_first)
                model.add(position[b] == end_a - 1).only_enforce_if(share)
                model.add(end_a <= position[b]).only_enforce_if([a_first, share.Not()])
                shares.append(share)
            else:
                model.add(end_a <= position[b]).only_enforce_if(a_first)
        if (
            first.rank is not None
            and second.rank is not None
            and first.is_hour == second.is_hour
        ):
            inversions.append(flag if first.rank > second.rank else flag.Not())
    # The order is transitive; this helps the solver prune.
    for a, b, c in itertools.permutations(words, 3):
        model.add_bool_or(
            [first_before[a, b].Not(), first_before[b, c].Not(), first_before[a, c]]
        )
    row_end = []
    for index in range(rows):
        starts = []
        end = model.new_int_var(0, columns, f"end of row {index}")
        for word in words:
            in_row = model.new_bool_var(f"{word} in row {index}")
            model.add(row[word] == index).only_enforce_if(in_row)
            model.add(row[word] != index).only_enforce_if(in_row.Not())
            starts_row = model.new_bool_var(f"{word} starts row {index}")
            model.add_implication(starts_row, in_row)
            model.add(column[word] == 0).only_enforce_if(starts_row)
            starts.append(starts_row)
            model.add(end >= column[word] + word.cells).only_enforce_if(in_row)
        model.add(sum(starts) >= 1)
        row_end.append(end)
    letters = sum(word.cells for word in words)
    fillers = sum(row_end) - letters + sum(shares)
    if max_shares is not None:
        model.add(sum(shares) <= max_shares)
    model.minimize(
        weights.fillers * fillers
        + weights.shares * sum(shares)
        + weights.inversions * sum(inversions)
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = workers
    status = solver.solve(model, Progress(fillers, shares, inversions))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"no layout: {solver.status_name(status)}")
        return None
    print(
        f"{solver.status_name(status)}: fillers {solver.value(fillers)},"
        f" shares {sum(solver.value(share) for share in shares)},"
        f" inversions {sum(solver.value(flag) for flag in inversions)},"
        f" best bound {solver.best_objective_bound:.0f} of {solver.objective_value:.0f}"
    )
    return {
        word: (solver.value(row[word]), solver.value(column[word])) for word in words
    }


class Progress(cp_model.CpSolverSolutionCallback):
    """Prints each better layout that the solver finds, so a long run shows its
    progress."""

    def __init__(self, fillers, shares, inversions) -> None:
        super().__init__()
        self.fillers, self.shares, self.inversions = fillers, shares, inversions
        self.start = time.monotonic()

    def on_solution_callback(self) -> None:
        print(
            f"  {time.monotonic() - self.start:7.0f} s: fillers {self.value(self.fillers)},"
            f" shares {sum(self.value(share) for share in self.shares)},"
            f" inversions {sum(self.value(flag) for flag in self.inversions)},"
            f" bound {self.best_objective_bound:.0f}",
            flush=True,
        )


FILLERS = "kpzqjxvbmdgwrycfhlu"


def to_rows(placed, rows, columns, attached_apostrophe):
    grid = [[None] * columns for _ in range(rows)]
    for word, (row, column) in placed.items():
        text = word.text
        if attached_apostrophe:
            cells = []
            for letter in text:
                if letter == "’":
                    cells[-1] += letter
                else:
                    cells.append(letter)
        else:
            cells = list(text)
        for index, cell in enumerate(cells):
            existing = grid[row][column + index]
            if existing not in (None, cell):
                raise ValueError(
                    f"{word} overlaps {existing} at {row}, {column + index}"
                )
            grid[row][column + index] = cell
    fillers = itertools.cycle(FILLERS)
    return ["".join(cell or next(fillers) for cell in line) for line in grid]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--columns", type=int, default=20)
    parser.add_argument("--rows", type=int, default=9)
    parser.add_argument("--attached-apostrophe", action="store_true")
    parser.add_argument("--priority", default="fillers,shares,inversions")
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-shares", type=int)
    parser.add_argument("--a-from", choices=["bare", "half"], default="bare")
    arguments = parser.parse_args()
    names = arguments.priority.split(",")
    weights = Weights(**{name: 1000 ** (2 - index) for index, name in enumerate(names)})
    minute, hour = make_words(arguments.attached_apostrophe, arguments.a_from)
    words = list(minute.values()) + list(hour.values())
    rules = rules_for(minute, hour)
    print(
        f"{arguments.columns} x {arguments.rows},"
        f" apostrophe {'attached' if arguments.attached_apostrophe else 'own cell'},"
        f" priority {arguments.priority}, A from {arguments.a_from}",
        flush=True,
    )
    start = time.monotonic()
    placed = solve(
        words,
        rules,
        arguments.rows,
        arguments.columns,
        weights,
        arguments.seconds,
        fixed={minute["IT"]: 0, minute["IS"]: 3},
        workers=arguments.workers,
        max_shares=arguments.max_shares,
    )
    print(f"{time.monotonic() - start:.0f} s")
    if placed is None:
        return
    rows = to_rows(
        placed, arguments.rows, arguments.columns, arguments.attached_apostrophe
    )
    hour_start = min(place for word, place in placed.items() if word.is_hour)
    for line in rows:
        print(f'    "{line}",')
    print(f"    hour_start={hour_start}")
    if arguments.attached_apostrophe:
        return  # wordclock.py needs the apostrophe in its own cell
    layout = wordclock.Layout(rows=tuple(rows), hour_start=hour_start)
    for hour_of_day in range(24):
        for minute_of_hour in range(60):
            phrase = wordclock.phrase_for(hour_of_day, minute_of_hour)
            expected = set()
            for part in lit_parts(phrase, minute, hour):
                word_row, word_column = placed[part.word]
                start_column = word_column + part.offset
                expected.update(
                    (word_row, start_column + index) for index in range(part.cells)
                )
            if layout.lit_cells(phrase) != expected:
                raise ValueError(f"{phrase} lights other cells than intended")
    print("All 1440 minutes light the intended cells.")


if __name__ == "__main__":
    main()
