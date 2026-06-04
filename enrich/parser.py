"""Parse and normalize the raw schedule sheet data."""

import re
from dataclasses import dataclass


DAY_MAP = {
    "sunday": "2026-06-21",
    "monday": "2026-06-22",
    "tuesday": "2026-06-23",
    "wednesday": "2026-06-24",
    "thursday": "2026-06-25",
    "friday": "2026-06-26",
}

DAY_KEYWORDS = list(DAY_MAP.keys())

DAY_HEADER_RE = re.compile(
    r"^(sunday|monday|tuesday|wednesday|thursday|friday)\s+\d+",
    re.IGNORECASE,
)

TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2})\s*[-\u2013\u2014]\s*(\d{1,2}:?\d{0,2})"
)


@dataclass
class Event:
    event_name: str = ""
    host: str = ""
    day: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    event_url: str = ""
    details: str = ""
    crawled_summary: str = ""
    company_type: str = ""
    event_type: str = ""
    target_audience: str = ""
    registration_url: str = ""
    registration_notes: str = ""
    status: str = "confirmed"


def parse_time(raw: str) -> tuple[str, str]:
    if not raw or not raw.strip():
        return ("", "")
    text = raw.strip()
    lower = text.lower()
    if lower in ("all week", "all day"):
        return ("all_day", "")
    if lower in ("coming soon", "tbc", "tba"):
        return ("", "")
    match = TIME_RANGE_RE.search(text)
    if match:
        start = match.group(1)
        end_raw = match.group(2)
        if ":" not in end_raw and len(end_raw) == 4:
            end_raw = end_raw[:2] + ":" + end_raw[2:]
        elif ":" not in end_raw and len(end_raw) <= 2:
            end_raw = end_raw + ":00"
        return (start, end_raw)
    return ("", "")


def _detect_day(first_cell: str) -> str | None:
    if DAY_HEADER_RE.match(first_cell.strip()):
        for day in DAY_KEYWORDS:
            if day in first_cell.lower():
                return day
    return None


def _split_mega_row(rows: list[list[str]]) -> tuple[list[list[str]], dict[int, list[int]]]:
    if len(rows) < 2:
        return rows, {i: [i] for i in range(len(rows))}
    first_data = rows[1]
    has_newlines = any("\n" in cell for cell in first_data)
    if not has_newlines:
        return rows, {i: [i] for i in range(len(rows))}
    split_cols = [cell.split("\n") for cell in first_data]
    col_lengths = [len(col) for col in split_cols]
    max_items = max(col_lengths)
    if len(set(col_lengths)) > 1:
        print(f"  Warning: mega-row column lengths differ: {col_lengths}. Padding shorter columns.")
    for col in split_cols:
        while len(col) < max_items:
            col.append("")
    new_rows = [rows[0]]
    index_map: dict[int, list[int]] = {0: [0]}
    mega_new_indices = []
    for i in range(max_items):
        new_row = [col[i].strip() for col in split_cols]
        if any(cell for cell in new_row):
            mega_new_indices.append(len(new_rows))
            new_rows.append(new_row)
    index_map[1] = mega_new_indices
    for old_idx in range(2, len(rows)):
        new_idx = len(new_rows)
        index_map[old_idx] = [new_idx]
        new_rows.append(rows[old_idx])
    return new_rows, index_map


def _remap_hyperlinks(
    hyperlinks: dict[int, str],
    index_map: dict[int, list[int]],
) -> dict[int, str]:
    remapped = {}
    for raw_idx, url in hyperlinks.items():
        new_indices = index_map.get(raw_idx, [])
        if new_indices:
            remapped[new_indices[0]] = url
    return remapped


def _derive_status(time_str: str, location: str) -> str:
    combined = (time_str + " " + location).lower()
    if "coming soon" in combined:
        return "coming_soon"
    if "tbc" in combined or "tba" in combined:
        return "tbc"
    return "confirmed"


def parse_schedule_rows(
    rows: list[list[str]],
    hyperlinks: dict[int, str],
) -> list[Event]:
    rows, index_map = _split_mega_row(rows)
    remapped_links = _remap_hyperlinks(hyperlinks, index_map)
    events = []
    current_day = ""
    current_date = ""
    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue
        if not any(cell.strip() for cell in row):
            continue
        first_cell = row[0].strip() if row else ""
        detected_day = _detect_day(first_cell)
        if detected_day:
            current_day = detected_day
            current_date = DAY_MAP.get(detected_day, "")
            continue
        def col(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""
        time_raw = col(2)
        start, end = parse_time(time_raw)
        location = col(3)
        link_text = col(4)
        event_url = remapped_links.get(row_idx, "")
        if not event_url and link_text.startswith("http"):
            event_url = link_text
        event = Event(
            event_name=col(0),
            host=col(1),
            day=current_day,
            date=current_date,
            start_time=start,
            end_time=end,
            location=location,
            event_url=event_url,
            details=col(5),
            status=_derive_status(time_raw, location),
        )
        events.append(event)
    return events
