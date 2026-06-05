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


SKIP_ROWS = {"event", "the a - z of beaches / apartments / week long activations"}


def _is_skip_row(first_cell: str) -> bool:
    """Check if row is a section header or attribution to skip."""
    stripped = first_cell.strip().lower()
    return stripped in SKIP_ROWS or stripped.startswith("produced by")


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
    """Parse schedule rows from the Sheets API.

    Row indices in `rows` and `hyperlinks` are aligned (both from the API).
    No mega-row splitting needed since the API returns one row per event.
    """
    events = []
    current_day = ""
    current_date = ""
    for row_idx, row in enumerate(rows):
        if not any(cell.strip() for cell in row):
            continue
        first_cell = row[0].strip() if row else ""
        if _is_skip_row(first_cell):
            continue
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
        event_url = hyperlinks.get(row_idx, "")
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
