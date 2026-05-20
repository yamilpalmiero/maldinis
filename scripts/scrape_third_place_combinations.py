#!/usr/bin/env python3
"""
Scrapes the 495-row "Combinations of matches in the round of 32" table from
the Wikipedia article on the 2026 FIFA World Cup knockout stage, then writes
the static dataset to app/predictions/data/third_place_combinations.py.

Run once from the repo root:
    python3 scripts/scrape_third_place_combinations.py

Requires: requests, beautifulsoup4 (pip3 install requests beautifulsoup4)

Table structure (after inspection of the live page):
  - Row 1: 22 cells — row# | 12 group cols | rowspan-th separator | 8 assignment cols
  - Rows 2–495: 21 cells — row# | 12 group cols | 8 assignment cols
  The rowspan=495 th (separator) only appears in row 1; cells[-8:] always
  gives the assignment columns regardless of row length.

  Group columns (cells[1:13]) → one per group A…L in alphabetical order.
    A qualifying group shows its letter; a non-qualifying group is empty.
  Assignment columns (cells[-8:]) → one per match, in header order:
    1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L  (note: not consecutive A–L, see below)
"""

import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKIPEDIA_URL = (
    "https://en.wikipedia.org/wiki/"
    "2026_FIFA_World_Cup_knockout_stage"
)

# Wikipedia assignment columns (cells[-8:]) are ordered by group winner:
# 1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L — these map to R32 match numbers.
# Groups C, F, H, J only appear in "1X vs 2Y" slots (not vs-third slots).
COLUMN_ORDER = ["A", "B", "D", "E", "G", "I", "K", "L"]
WINNER_GROUP_TO_MATCH = {
    "A": "79",
    "B": "85",
    "D": "81",
    "E": "74",
    "G": "82",
    "I": "77",
    "K": "87",
    "L": "80",
}
MATCH_NUMBERS = [WINNER_GROUP_TO_MATCH[g] for g in COLUMN_ORDER]

# All 12 groups in alphabetical order — matches cells[1:13]
GROUPS_IN_ORDER = list("ABCDEFGHIJKL")
VALID_GROUPS = set(GROUPS_IN_ORDER)

EXPECTED_ROWS = 495
OUTPUT_PATH = (
    Path(__file__).parent.parent
    / "app" / "predictions" / "data" / "third_place_combinations.py"
)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> BeautifulSoup:
    print(f"Fetching {url} …")
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    print(f"  → {resp.status_code}, {len(resp.content):,} bytes")
    return BeautifulSoup(resp.content, "html.parser")


def find_combinations_table(soup: BeautifulSoup):
    """Return the table that has 495 data rows and the "1Xvs" headers."""
    for table in soup.find_all("table", class_="wikitable"):
        header_texts = [th.get_text(strip=True) for th in table.find_all("th")]
        if sum(1 for h in header_texts if re.match(r"^1[A-L]vs$", h)) == 8:
            data_rows = [r for r in table.find_all("tr") if r.find("td")]
            if len(data_rows) >= EXPECTED_ROWS:
                print(f"  → Found table with {len(data_rows)} data rows")
                return table, data_rows
    return None, None


def clean(text: str) -> str:
    """Strip whitespace and zero-width / non-breaking space characters."""
    return re.sub(r"[ ​‌‍﻿\s]", "", text)


def parse_row(row) -> tuple | None:
    """
    Parse one <tr> into (frozenset[qualifying_groups], {match_num: src_group}).

    Returns None on any validation failure so the caller can report it.
    """
    cells = row.find_all(["td", "th"])

    # Minimum length check (rows can be 21 or 22 cells)
    if len(cells) < 21:
        return None

    # Group columns: always cells[1:13]
    group_cells = [clean(c.get_text()) for c in cells[1:13]]
    # Assignment columns: always the last 8 cells
    assign_cells = [clean(c.get_text()) for c in cells[-8:]]

    # Build frozenset of qualifying groups
    qualifying: set[str] = set()
    for expected_letter, text in zip(GROUPS_IN_ORDER, group_cells):
        if text == expected_letter:
            qualifying.add(expected_letter)
        elif text != "":
            return None  # unexpected value in a group cell

    if len(qualifying) != 8:
        return None

    groups = frozenset(qualifying)

    # Build match → source-group assignment
    assignment: dict[str, str] = {}
    for match_num, raw in zip(MATCH_NUMBERS, assign_cells):
        m = re.match(r"^3([A-L])$", raw)
        if not m:
            return None
        src_group = m.group(1)
        if src_group not in groups:
            return None  # assigned group not in the qualifying set
        assignment[match_num] = src_group

    # Each of the 8 qualifying groups must appear exactly once
    if set(assignment.values()) != groups:
        return None

    return groups, assignment


def scrape() -> dict:
    soup = fetch_page(WIKIPEDIA_URL)
    table, data_rows = find_combinations_table(soup)
    if table is None:
        print("ERROR: Could not find the combinations table.")
        sys.exit(1)

    combinations: dict[frozenset, dict] = {}
    errors: list[int] = []

    for i, row in enumerate(data_rows[:EXPECTED_ROWS], start=1):
        result = parse_row(row)
        if result is None:
            cells = row.find_all(["td", "th"])
            print(f"  WARNING row {i}: parse failed — {[c.get_text(strip=True) for c in cells]}")
            errors.append(i)
            continue
        groups, assignment = result
        if groups in combinations:
            print(f"  WARNING row {i}: duplicate key {sorted(groups)}")
        combinations[groups] = assignment

    print(f"\nParsed {len(combinations)} combinations, {len(errors)} errors.")
    if len(combinations) != EXPECTED_ROWS:
        print(f"ERROR: Expected {EXPECTED_ROWS}, got {len(combinations)}. Aborting.")
        sys.exit(1)

    return combinations


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def fmt_frozenset(fs: frozenset) -> str:
    return "frozenset({" + ", ".join(f'"{x}"' for x in sorted(fs)) + "})"


def fmt_dict(d: dict) -> str:
    keys = sorted(d, key=int)
    return "{" + ", ".join(f'"{k}": "{d[k]}"' for k in keys) + "}"


def generate_file(combinations: dict, path: Path) -> None:
    today = date.today().isoformat()

    header = f'''\
"""
Third-place slot assignment table for the 2026 FIFA World Cup Round of 32.

Source : Wikipedia — "2026 FIFA World Cup knockout stage",
          section "Combinations of matches in the round of 32".
          Corresponds to Annex C of the official FIFA 2026 tournament regulations.
Scraped: {today}

Structure
---------
THIRD_PLACE_COMBINATIONS: dict[frozenset[str], dict[str, str]]

  Key   — frozenset of the 8 group letters whose third-place teams qualified
           for the knockout stage (one of C(12,8) = 495 possible subsets).

  Value — dict mapping match_number (str) to the source group letter (str)
           of the third-place team assigned to that R32 slot.
           Match numbers: "74", "77", "79", "80", "81", "82", "85", "87".

  Example:
      frozenset({{"E","F","G","H","I","J","K","L"}}): {{
          "74": "F",   # Match 74: winner E  vs 3rd-place F
          "77": "G",   # Match 77: winner I  vs 3rd-place G
          "79": "E",   # Match 79: winner A  vs 3rd-place E
          "80": "K",   # Match 80: winner L  vs 3rd-place K
          "81": "I",   # Match 81: winner D  vs 3rd-place I
          "82": "H",   # Match 82: winner G  vs 3rd-place H
          "85": "J",   # Match 85: winner B  vs 3rd-place J
          "87": "L",   # Match 87: winner K  vs 3rd-place L
      }}

DO NOT edit this file manually.  Regenerate with:
    python3 scripts/scrape_third_place_combinations.py
"""

# fmt: off
THIRD_PLACE_COMBINATIONS: dict[frozenset, dict[str, str]] = {{
'''

    body_lines = []
    for fs, assignment in sorted(combinations.items(), key=lambda kv: tuple(sorted(kv[0]))):
        body_lines.append(f"    {fmt_frozenset(fs)}: {fmt_dict(assignment)},")

    footer = """}
# fmt: on
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(body_lines) + "\n" + footer, encoding="utf-8")
    print(f"Written {len(combinations)} entries → {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    combinations = scrape()
    generate_file(combinations, OUTPUT_PATH)
    print("Done.")
