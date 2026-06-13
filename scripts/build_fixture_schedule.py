#!/usr/bin/env python3
"""Build the 2026 fixture context table used by the web predictor."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "fixtures.csv"

VENUE_TIMEZONES = {
    "Atlanta": "America/New_York",
    "Boston": "America/New_York",
    "Dallas": "America/Chicago",
    "Guadalajara": "America/Mexico_City",
    "Houston": "America/Chicago",
    "Kansas City": "America/Chicago",
    "Los Angeles": "America/Los_Angeles",
    "Mexico City": "America/Mexico_City",
    "Miami": "America/New_York",
    "Monterrey": "America/Monterrey",
    "New York New Jersey": "America/New_York",
    "Philadelphia": "America/New_York",
    "San Francisco Bay Area": "America/Los_Angeles",
    "Seattle": "America/Los_Angeles",
    "Toronto": "America/Toronto",
    "Vancouver": "America/Vancouver",
}

PUBLISHED_FIXTURE_CONTEXT = {
    1: ("2026-06-11", "13:00", "Mexico City"),
    2: ("2026-06-11", "20:00", "Guadalajara"),
    3: ("2026-06-12", "15:00", "Toronto"),
    4: ("2026-06-12", "18:00", "Los Angeles"),
    5: ("2026-06-13", "21:00", "Boston"),
    6: ("2026-06-13", "21:00", "Vancouver"),
    7: ("2026-06-13", "18:00", "New York New Jersey"),
    8: ("2026-06-13", "12:00", "San Francisco Bay Area"),
    9: ("2026-06-14", "19:00", "Philadelphia"),
    10: ("2026-06-14", "12:00", "Houston"),
    11: ("2026-06-14", "15:00", "Dallas"),
    12: ("2026-06-14", "20:00", "Monterrey"),
    13: ("2026-06-15", "18:00", "Miami"),
    14: ("2026-06-15", "12:00", "Atlanta"),
    15: ("2026-06-15", "18:00", "Los Angeles"),
    16: ("2026-06-15", "12:00", "Seattle"),
    17: ("2026-06-16", "15:00", "New York New Jersey"),
    18: ("2026-06-16", "18:00", "Boston"),
    19: ("2026-06-16", "20:00", "Kansas City"),
    20: ("2026-06-16", "21:00", "San Francisco Bay Area"),
    21: ("2026-06-17", "19:00", "Toronto"),
    22: ("2026-06-17", "15:00", "Dallas"),
    23: ("2026-06-17", "12:00", "Houston"),
    24: ("2026-06-17", "20:00", "Mexico City"),
    25: ("2026-06-18", "12:00", "Atlanta"),
    26: ("2026-06-18", "12:00", "Los Angeles"),
    27: ("2026-06-18", "15:00", "Vancouver"),
    28: ("2026-06-18", "19:00", "Guadalajara"),
    29: ("2026-06-19", "21:00", "Philadelphia"),
    30: ("2026-06-19", "18:00", "Boston"),
    31: ("2026-06-19", "20:00", "San Francisco Bay Area"),
    32: ("2026-06-19", "12:00", "Seattle"),
    33: ("2026-06-20", "16:00", "Toronto"),
    34: ("2026-06-20", "19:00", "Kansas City"),
    35: ("2026-06-20", "12:00", "Houston"),
    36: ("2026-06-20", "22:00", "Monterrey"),
    37: ("2026-06-21", "18:00", "Miami"),
    38: ("2026-06-21", "12:00", "Atlanta"),
    39: ("2026-06-21", "12:00", "Los Angeles"),
    40: ("2026-06-21", "18:00", "Vancouver"),
    41: ("2026-06-22", "20:00", "New York New Jersey"),
    42: ("2026-06-22", "17:00", "Philadelphia"),
    43: ("2026-06-22", "12:00", "Dallas"),
    44: ("2026-06-22", "20:00", "San Francisco Bay Area"),
    45: ("2026-06-23", "16:00", "Boston"),
    46: ("2026-06-23", "19:00", "Toronto"),
    47: ("2026-06-23", "12:00", "Houston"),
    48: ("2026-06-23", "20:00", "Guadalajara"),
    49: ("2026-06-24", "18:00", "Miami"),
    50: ("2026-06-24", "18:00", "Atlanta"),
    51: ("2026-06-24", "12:00", "Vancouver"),
    52: ("2026-06-24", "12:00", "Seattle"),
    53: ("2026-06-24", "19:00", "Mexico City"),
    54: ("2026-06-24", "19:00", "Monterrey"),
    55: ("2026-06-25", "16:00", "Philadelphia"),
    56: ("2026-06-25", "16:00", "New York New Jersey"),
    57: ("2026-06-25", "18:00", "Dallas"),
    58: ("2026-06-25", "18:00", "Kansas City"),
    59: ("2026-06-25", "19:00", "Los Angeles"),
    60: ("2026-06-25", "19:00", "San Francisco Bay Area"),
    61: ("2026-06-26", "15:00", "Boston"),
    62: ("2026-06-26", "15:00", "Toronto"),
    63: ("2026-06-26", "20:00", "Seattle"),
    64: ("2026-06-26", "20:00", "Vancouver"),
    65: ("2026-06-26", "19:00", "Houston"),
    66: ("2026-06-26", "18:00", "Guadalajara"),
    67: ("2026-06-27", "17:00", "New York New Jersey"),
    68: ("2026-06-27", "17:00", "Philadelphia"),
    69: ("2026-06-27", "21:00", "Kansas City"),
    70: ("2026-06-27", "21:00", "Dallas"),
    71: ("2026-06-27", "19:30", "Miami"),
    72: ("2026-06-27", "19:30", "Atlanta"),
    73: ("2026-06-28", "12:00", "Los Angeles"),
    74: ("2026-06-29", "16:30", "Boston"),
    75: ("2026-06-29", "19:00", "Monterrey"),
    76: ("2026-06-29", "12:00", "Houston"),
    77: ("2026-06-30", "17:00", "New York New Jersey"),
    78: ("2026-06-30", "12:00", "Dallas"),
    79: ("2026-06-30", "19:00", "Mexico City"),
    80: ("2026-07-01", "12:00", "Atlanta"),
    81: ("2026-07-01", "17:00", "San Francisco Bay Area"),
    82: ("2026-07-01", "13:00", "Seattle"),
    83: ("2026-07-02", "19:00", "Toronto"),
    84: ("2026-07-02", "12:00", "Los Angeles"),
    85: ("2026-07-02", "20:00", "Vancouver"),
    86: ("2026-07-03", "18:00", "Miami"),
    87: ("2026-07-03", "20:30", "Kansas City"),
    88: ("2026-07-03", "13:00", "Dallas"),
    89: ("2026-07-04", "17:00", "Philadelphia"),
    90: ("2026-07-04", "12:00", "Houston"),
    91: ("2026-07-05", "16:00", "New York New Jersey"),
    92: ("2026-07-05", "18:00", "Mexico City"),
    93: ("2026-07-06", "14:00", "Dallas"),
    94: ("2026-07-06", "17:00", "Seattle"),
    95: ("2026-07-07", "12:00", "Atlanta"),
    96: ("2026-07-07", "13:00", "Vancouver"),
    97: ("2026-07-09", "16:00", "Boston"),
    98: ("2026-07-10", "12:00", "Los Angeles"),
    99: ("2026-07-11", "17:00", "Miami"),
    100: ("2026-07-11", "20:00", "Kansas City"),
    101: ("2026-07-14", "14:00", "Dallas"),
    102: ("2026-07-15", "15:00", "Atlanta"),
    103: ("2026-07-18", "17:00", "Miami"),
    104: ("2026-07-19", "15:00", "New York New Jersey"),
}

GROUP_FIXTURES = [
    (1, "A", "Mexico", "South Africa"),
    (2, "A", "Korea Republic", "Czechia"),
    (3, "B", "Canada", "Bosnia and Herzegovina"),
    (4, "D", "USA", "Paraguay"),
    (5, "C", "Haiti", "Scotland"),
    (6, "D", "Australia", "Turkiye"),
    (7, "C", "Brazil", "Morocco"),
    (8, "B", "Qatar", "Switzerland"),
    (9, "E", "Cote d'Ivoire", "Ecuador"),
    (10, "E", "Germany", "Curacao"),
    (11, "F", "Netherlands", "Japan"),
    (12, "F", "Sweden", "Tunisia"),
    (13, "H", "Saudi Arabia", "Uruguay"),
    (14, "H", "Spain", "Cabo Verde"),
    (15, "G", "IR Iran", "New Zealand"),
    (16, "G", "Belgium", "Egypt"),
    (17, "I", "France", "Senegal"),
    (18, "I", "Iraq", "Norway"),
    (19, "J", "Argentina", "Algeria"),
    (20, "J", "Austria", "Jordan"),
    (21, "L", "Ghana", "Panama"),
    (22, "L", "England", "Croatia"),
    (23, "K", "Portugal", "Congo DR"),
    (24, "K", "Uzbekistan", "Colombia"),
    (25, "A", "Czechia", "South Africa"),
    (26, "B", "Switzerland", "Bosnia and Herzegovina"),
    (27, "B", "Canada", "Qatar"),
    (28, "A", "Mexico", "Korea Republic"),
    (29, "C", "Brazil", "Haiti"),
    (30, "C", "Scotland", "Morocco"),
    (31, "D", "Turkiye", "Paraguay"),
    (32, "D", "USA", "Australia"),
    (33, "E", "Germany", "Cote d'Ivoire"),
    (34, "E", "Ecuador", "Curacao"),
    (35, "F", "Netherlands", "Sweden"),
    (36, "F", "Tunisia", "Japan"),
    (37, "H", "Uruguay", "Cabo Verde"),
    (38, "H", "Spain", "Saudi Arabia"),
    (39, "G", "Belgium", "IR Iran"),
    (40, "G", "New Zealand", "Egypt"),
    (41, "I", "Norway", "Senegal"),
    (42, "I", "France", "Iraq"),
    (43, "J", "Argentina", "Austria"),
    (44, "J", "Jordan", "Algeria"),
    (45, "L", "England", "Ghana"),
    (46, "L", "Panama", "Croatia"),
    (47, "K", "Portugal", "Uzbekistan"),
    (48, "K", "Colombia", "Congo DR"),
    (49, "C", "Scotland", "Brazil"),
    (50, "C", "Morocco", "Haiti"),
    (51, "B", "Switzerland", "Canada"),
    (52, "B", "Bosnia and Herzegovina", "Qatar"),
    (53, "A", "Czechia", "Mexico"),
    (54, "A", "South Africa", "Korea Republic"),
    (55, "E", "Curacao", "Cote d'Ivoire"),
    (56, "E", "Ecuador", "Germany"),
    (57, "F", "Japan", "Sweden"),
    (58, "F", "Tunisia", "Netherlands"),
    (59, "D", "Turkiye", "USA"),
    (60, "D", "Paraguay", "Australia"),
    (61, "I", "Norway", "France"),
    (62, "I", "Senegal", "Iraq"),
    (63, "G", "Egypt", "IR Iran"),
    (64, "G", "New Zealand", "Belgium"),
    (65, "H", "Cabo Verde", "Saudi Arabia"),
    (66, "H", "Uruguay", "Spain"),
    (67, "L", "Panama", "England"),
    (68, "L", "Croatia", "Ghana"),
    (69, "J", "Algeria", "Austria"),
    (70, "J", "Jordan", "Argentina"),
    (71, "K", "Colombia", "Portugal"),
    (72, "K", "Congo DR", "Uzbekistan"),
]

KNOCKOUT_FIXTURES = [
    (73, "Round of 32", "2A", "2B"),
    (74, "Round of 32", "1E", "3ABCDF"),
    (75, "Round of 32", "1F", "2C"),
    (76, "Round of 32", "1C", "2F"),
    (77, "Round of 32", "1I", "3CDFGH"),
    (78, "Round of 32", "2E", "2I"),
    (79, "Round of 32", "1A", "3CEFHI"),
    (80, "Round of 32", "1L", "3EHIJK"),
    (81, "Round of 32", "1D", "3BEFIJ"),
    (82, "Round of 32", "1G", "3AEHIJ"),
    (83, "Round of 32", "2K", "2L"),
    (84, "Round of 32", "1H", "2J"),
    (85, "Round of 32", "1B", "3EFGIJ"),
    (86, "Round of 32", "1J", "2H"),
    (87, "Round of 32", "1K", "3DEIJL"),
    (88, "Round of 32", "2D", "2G"),
    (89, "Round of 16", "W74", "W77"),
    (90, "Round of 16", "W73", "W75"),
    (91, "Round of 16", "W76", "W78"),
    (92, "Round of 16", "W79", "W80"),
    (93, "Round of 16", "W83", "W84"),
    (94, "Round of 16", "W81", "W82"),
    (95, "Round of 16", "W86", "W88"),
    (96, "Round of 16", "W85", "W87"),
    (97, "Quarterfinals", "W89", "W90"),
    (98, "Quarterfinals", "W93", "W94"),
    (99, "Quarterfinals", "W91", "W92"),
    (100, "Quarterfinals", "W95", "W96"),
    (101, "Semifinals", "W97", "W98"),
    (102, "Semifinals", "W99", "W100"),
    (103, "Bronze Final", "L101", "L102"),
    (104, "Final", "W101", "W102"),
]

def venue_for_match(match_id: int) -> tuple[str, str]:
    return PUBLISHED_FIXTURE_CONTEXT[match_id][2], "published-schedule"


def timestamp_payload(match_id: int, venue: str) -> tuple[str, str, str, str]:
    date, local_time, _ = PUBLISHED_FIXTURE_CONTEXT[match_id]
    local = datetime.fromisoformat(f"{date}T{local_time}:00").replace(tzinfo=ZoneInfo(VENUE_TIMEZONES[venue]))
    return date, local_time, local.isoformat(), local.astimezone(ZoneInfo("UTC")).isoformat()


def row_for_match(match_id: int, stage: str, group: str, team_a: str, team_b: str, source_a: str, source_b: str) -> dict[str, str]:
    venue, venue_source = venue_for_match(match_id)
    date, kickoff_time_local, kickoff_local, kickoff_utc = timestamp_payload(match_id, venue)
    return {
        "match_id": str(match_id),
        "stage": stage,
        "round": stage,
        "group": group,
        "team_a": team_a,
        "team_b": team_b,
        "source_a": source_a,
        "source_b": source_b,
        "date": date,
        "kickoff_time_local": kickoff_time_local,
        "kickoff_local": kickoff_local,
        "kickoff_utc": kickoff_utc,
        "venue": venue,
        "venue_source": venue_source,
    }


def main() -> None:
    rows = []
    for match_id, group, team_a, team_b in GROUP_FIXTURES:
        rows.append(row_for_match(match_id, "Group", group, team_a, team_b, team_a, team_b))
    for match_id, stage, source_a, source_b in KNOCKOUT_FIXTURES:
        rows.append(row_for_match(match_id, stage, "", "", "", source_a, source_b))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: int(row["match_id"])))
    print(f"Wrote {len(rows)} fixture rows to {OUTPUT}")


if __name__ == "__main__":
    main()
