# Cannes Lions MCP Data Layer v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an enrichment pipeline that reads two messy Google Sheets, parses/normalizes/crawls/classifies events, writes clean data to a master sheet, and update the MCP server to expose 8 richer tools.

**Architecture:** Python enrichment script (`enrich.py`) orchestrates 6 modules: sheets reader, parser, crawler, classifier, matcher, writer. Each module is a single file in `enrich/` with one clear responsibility. The MCP server (`modal_app.py`) reads the master sheet via CSV export and exposes 8 tools. The master sheet ID and tab GIDs are stored in `config.json` locally and passed to Modal as secrets for the deployed server.

**Tech Stack:** Python 3.12, httpx (crawling), anthropic SDK (classification), thefuzz (fuzzy matching), Google Sheets API v4 (hyperlinks), `gws` CLI (sheet read/write), Modal (deployment), FastMCP (MCP server).

---

## File Structure

| File | Responsibility |
|------|---------------|
| `enrich/__init__.py` | Package init |
| `enrich/sheets_reader.py` | Read source sheets via Sheets API, extract hyperlinks |
| `enrich/parser.py` | Parse mega-row, extract days/times, normalize fields |
| `enrich/crawler.py` | Crawl event URLs with httpx, cache results |
| `enrich/classifier.py` | Batch classify events via Claude API |
| `enrich/matcher.py` | Fuzzy-match registrations to events |
| `enrich/writer.py` | Write enriched data to master Google Sheet, return sheet ID + tab GIDs |
| `enrich.py` | CLI entry point wiring all modules |
| `config.json` | Stores master sheet ID and tab GIDs after first creation (gitignored) |
| `modal_app.py` | Updated MCP server with 8 tools, reads sheet IDs from Modal secrets |
| `tests/__init__.py` | Test package init |
| `tests/test_parser.py` | Tests for parsing logic (including mega-row + hyperlink alignment) |
| `tests/test_matcher.py` | Tests for fuzzy matching |
| `tests/test_classifier.py` | Tests for classification validation |

---

## Chunk 1: Foundation and Parsing

### Task 1: Project setup and dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `enrich/__init__.py`
- Create: `tests/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Update pyproject.toml with new dependencies**

```toml
[project]
name = "cannes-lions-mcp"
version = "0.2.0"
description = "MCP server for querying Cannes Lions 2026 event schedules and registration links"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0.0",
    "httpx>=0.27.0",
    "anthropic>=0.49.0",
    "thefuzz[speedup]>=0.22.0",
    "google-api-python-client>=2.0.0",
]

[project.scripts]
cannes-lions-mcp = "server:main"

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Create package inits**

`enrich/__init__.py`:
```python
"""Cannes Lions 2026 enrichment pipeline."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Update .gitignore**

Append to `.gitignore`:
```
.cache/
config.json
```

- [ ] **Step 4: Install dependencies**

Run: `cd /tmp/cannes-lions-mcp && pip install -e ".[dev]"`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml enrich/__init__.py tests/__init__.py .gitignore
git commit -m "feat: add v2 dependencies and enrich package skeleton"
```

---

### Task 2: Sheets reader module

**Files:**
- Create: `enrich/sheets_reader.py`

This module reads both source sheets. For the schedule sheet, it uses the Google Sheets API v4 to extract hyperlinks (the "HERE" text hides actual URLs). For the registration sheet, it reads plain CSV since URLs are in text.

**Key design note:** `extract_hyperlinks()` returns a dict mapping the original raw row index (0-based, pre-mega-row-splitting) to the URL. The parser is responsible for re-indexing these after mega-row splitting.

- [ ] **Step 1: Create sheets_reader.py**

```python
"""Read source Google Sheets and extract hyperlinks."""

import csv
import io
import pickle
from pathlib import Path

import httpx


SCHEDULE_SHEET_ID = "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"
SCHEDULE_GID = "1111568312"
REGISTRATION_SHEET_ID = "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"
REGISTRATION_GID = "835495045"

CSV_TEMPLATE = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"


def read_schedule_csv() -> list[list[str]]:
    """Fetch schedule sheet as CSV, return list of rows (each row is list of strings)."""
    url = CSV_TEMPLATE.format(id=SCHEDULE_SHEET_ID, gid=SCHEDULE_GID)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    return list(reader)


def read_registration_csv() -> list[dict[str, str]]:
    """Fetch registration sheet as CSV, return list of dicts."""
    url = CSV_TEMPLATE.format(id=REGISTRATION_SHEET_ID, gid=REGISTRATION_GID)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    data = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        record = {}
        for i, h in enumerate(headers):
            record[h] = row[i].strip() if i < len(row) else ""
        data.append(record)
    return data


def _get_sheets_credentials():
    """Load bot account credentials from pickle file."""
    token_path = Path.home() / ".config" / "gdrive_token.pickle"
    if not token_path.exists():
        raise FileNotFoundError(
            f"Bot account token not found at {token_path}. "
            "Run the auth flow first."
        )
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    return creds


def extract_hyperlinks() -> dict[int, str]:
    """Extract hyperlinks from the schedule sheet's Link column (col index 4).

    Returns a dict mapping raw row index (0-based, including header) to URL.
    These indices correspond to the original sheet rows BEFORE any mega-row
    splitting. The parser must re-index after splitting.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = _get_sheets_credentials()
    service = build("sheets", "v4", credentials=creds)

    result = service.spreadsheets().get(
        spreadsheetId=SCHEDULE_SHEET_ID,
        ranges=["A:F"],
        fields="sheets.data.rowData.values.hyperlink",
    ).execute()

    hyperlinks = {}
    sheets_data = result.get("sheets", [])
    if not sheets_data:
        return hyperlinks

    row_data = sheets_data[0].get("data", [{}])[0].get("rowData", [])
    for row_idx, row in enumerate(row_data):
        values = row.get("values", [])
        # Column E (index 4) is the Link column
        if len(values) > 4:
            link_cell = values[4]
            url = link_cell.get("hyperlink", "")
            if url:
                hyperlinks[row_idx] = url

    return hyperlinks
```

- [ ] **Step 2: Test manually that CSV fetch works**

Run: `cd /tmp/cannes-lions-mcp && python -c "from enrich.sheets_reader import read_schedule_csv; rows = read_schedule_csv(); print(f'{len(rows)} rows'); print(rows[0][:3]); print(rows[1][:3])"`
Expected: prints row count and first couple of cells

- [ ] **Step 3: Commit**

```bash
git add enrich/sheets_reader.py
git commit -m "feat: add sheets reader with CSV fetch and hyperlink extraction"
```

---

### Task 3: Parser module

**Files:**
- Create: `enrich/parser.py`
- Create: `tests/test_parser.py`

The parser handles the messy schedule format: splitting the mega first row, extracting day headers, parsing inconsistent time strings, and normalizing all fields.

**Critical design note:** Hyperlinks from the Sheets API are indexed against raw (pre-split) rows. The parser splits the mega-row first, then re-indexes hyperlinks to align with the post-split row indices. The `_split_mega_row` function returns both the new rows and an index mapping (old raw index -> list of new indices) so hyperlinks can be remapped.

- [ ] **Step 1: Write failing tests for time parsing and mega-row hyperlink alignment**

`tests/test_parser.py`:
```python
"""Tests for the schedule parser."""

import pytest
from enrich.parser import parse_time, parse_schedule_rows, Event


class TestParseTime:
    def test_standard_range(self):
        start, end = parse_time("09:00-17:00")
        assert start == "09:00"
        assert end == "17:00"

    def test_range_with_spaces(self):
        start, end = parse_time("09:00 - 17:00")
        assert start == "09:00"
        assert end == "17:00"

    def test_range_no_colon_end(self):
        start, end = parse_time("09:00 - 1800")
        assert start == "09:00"
        assert end == "18:00"

    def test_all_week(self):
        start, end = parse_time("All week")
        assert start == "all_day"
        assert end == ""

    def test_all_day(self):
        start, end = parse_time("All day")
        assert start == "all_day"
        assert end == ""

    def test_coming_soon(self):
        start, end = parse_time("Coming soon")
        assert start == ""
        assert end == ""

    def test_tbc(self):
        start, end = parse_time("TBC")
        assert start == ""
        assert end == ""

    def test_en_dash(self):
        start, end = parse_time("10:00\u201312:00")
        assert start == "10:00"
        assert end == "12:00"

    def test_em_dash(self):
        start, end = parse_time("10:00\u201412:00")
        assert start == "10:00"
        assert end == "12:00"

    def test_empty(self):
        start, end = parse_time("")
        assert start == ""
        assert end == ""


class TestParseScheduleRows:
    def test_day_extraction(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],  # header
            ["SUNDAY 21ST", "", "", "", "", ""],  # day header
            ["Beach Party", "Acme Corp", "10:00-12:00", "Beach", "HERE", "Fun"],
            ["MONDAY 22ND", "", "", "", "", ""],  # day header
            ["Panel Talk", "BigCo", "14:00-15:00", "Stage", "HERE", "Talk"],
        ]
        events = parse_schedule_rows(rows, {})
        assert len(events) == 2
        assert events[0].day == "sunday"
        assert events[0].date == "2026-06-21"
        assert events[0].event_name == "Beach Party"
        assert events[1].day == "monday"
        assert events[1].date == "2026-06-22"

    def test_time_parsing_in_events(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Party", "Host", "09:00-17:00", "Loc", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        assert events[0].start_time == "09:00"
        assert events[0].end_time == "17:00"

    def test_status_derivation(self):
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Event A", "Host", "Coming soon", "TBC", "", ""],
            ["Event B", "Host", "10:00-11:00", "Beach", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        assert events[0].status == "coming_soon"
        assert events[1].status == "confirmed"

    def test_hyperlink_injection_simple(self):
        """Hyperlinks on non-mega-row data align by raw row index."""
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Event A", "Host", "10:00-11:00", "Beach", "HERE", ""],
        ]
        hyperlinks = {2: "https://example.com/event"}
        events = parse_schedule_rows(rows, hyperlinks)
        assert events[0].event_url == "https://example.com/event"

    def test_hyperlink_alignment_after_mega_row_split(self):
        """Hyperlinks indexed against raw rows must re-align after mega-row split.

        Raw row 1 is the mega-row (contains newlines, splits into 2 sub-rows).
        Raw row 2 is a day header.
        Raw row 3 is an event with a hyperlink at raw index 3.
        After split, row 3 shifts to a higher index. The hyperlink must follow.
        """
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            # Mega-row: two venues packed with newlines
            ["Venue A\nVenue B", "Host A\nHost B", "All week\nAll week", "Loc A\nLoc B", "HERE\nHERE", ""],
            ["SUNDAY 21ST", "", "", "", "", ""],
            ["Panel Talk", "BigCo", "14:00-15:00", "Stage", "HERE", ""],
        ]
        # Hyperlink on raw row 1 (mega-row link col) and raw row 3 (Panel Talk)
        hyperlinks = {1: "https://venuea.com", 3: "https://panel.com"}
        events = parse_schedule_rows(rows, hyperlinks)

        # After split: mega-row becomes 2 rows. Venue A gets the hyperlink from raw row 1.
        venue_a = [e for e in events if e.event_name == "Venue A"]
        assert len(venue_a) == 1
        assert venue_a[0].event_url == "https://venuea.com"

        # Panel Talk was raw row 3, should still get its hyperlink
        panel = [e for e in events if e.event_name == "Panel Talk"]
        assert len(panel) == 1
        assert panel[0].event_url == "https://panel.com"

    def test_mega_row_mismatched_columns_warns(self, capsys):
        """When mega-row columns have different line counts, log a warning."""
        rows = [
            ["Event", "Host", "Time", "Location", "Link", "Details"],
            # 3 events but only 2 hosts
            ["A\nB\nC", "H1\nH2", "All week\nAll week\nAll week", "L1\nL2\nL3", "", ""],
        ]
        events = parse_schedule_rows(rows, {})
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "warning" in captured.out
        # Should still produce 3 events with padding
        assert len(events) == 3
        assert events[2].host == ""  # padded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_parser.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement parser.py**

```python
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

# Matches day headers like "SUNDAY 21ST", "MONDAY 22ND"
DAY_HEADER_RE = re.compile(
    r"^(sunday|monday|tuesday|wednesday|thursday|friday)\s+\d+",
    re.IGNORECASE,
)

# Matches time ranges with various separators (hyphen, en-dash, em-dash)
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
    """Parse a time string into (start_time, end_time).

    Handles: "09:00-17:00", "09:00 - 1800", "All week", "Coming soon", "TBC", etc.
    """
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
        # Handle missing colon: "1800" -> "18:00"
        if ":" not in end_raw and len(end_raw) == 4:
            end_raw = end_raw[:2] + ":" + end_raw[2:]
        elif ":" not in end_raw and len(end_raw) <= 2:
            end_raw = end_raw + ":00"
        return (start, end_raw)

    return ("", "")


def _detect_day(first_cell: str) -> str | None:
    """If this row is a day header, return the day name (lowercase). Else None."""
    if DAY_HEADER_RE.match(first_cell.strip()):
        for day in DAY_KEYWORDS:
            if day in first_cell.lower():
                return day
    return None


def _split_mega_row(rows: list[list[str]]) -> tuple[list[list[str]], dict[int, list[int]]]:
    """Split the first data row if it contains newline-delimited values.

    The schedule sheet packs all 'all week' venues into row 1 with newlines
    inside each cell. We split by newlines and zip across columns.

    Returns:
        A tuple of (new_rows, index_map) where index_map maps each original
        raw row index to a list of new row indices in the output. This is
        needed to re-align hyperlinks after splitting.
    """
    if len(rows) < 2:
        return rows, {i: [i] for i in range(len(rows))}

    first_data = rows[1]
    has_newlines = any("\n" in cell for cell in first_data)
    if not has_newlines:
        # No split needed, identity mapping
        return rows, {i: [i] for i in range(len(rows))}

    # Split each column by newlines
    split_cols = [cell.split("\n") for cell in first_data]
    col_lengths = [len(col) for col in split_cols]
    max_items = max(col_lengths)

    # Warn if column lengths differ (spec requirement)
    if len(set(col_lengths)) > 1:
        print(f"  Warning: mega-row column lengths differ: {col_lengths}. Padding shorter columns.")

    # Pad shorter columns
    for col in split_cols:
        while len(col) < max_items:
            col.append("")

    # Build new rows and index mapping
    new_rows = [rows[0]]  # keep header, index 0 -> [0]
    index_map: dict[int, list[int]] = {0: [0]}

    # Mega-row (raw index 1) splits into multiple new rows
    mega_new_indices = []
    for i in range(max_items):
        new_row = [col[i].strip() for col in split_cols]
        if any(cell for cell in new_row):
            mega_new_indices.append(len(new_rows))
            new_rows.append(new_row)
    index_map[1] = mega_new_indices

    # Remaining rows shift by (number of new rows inserted - 1)
    for old_idx in range(2, len(rows)):
        new_idx = len(new_rows)
        index_map[old_idx] = [new_idx]
        new_rows.append(rows[old_idx])

    return new_rows, index_map


def _remap_hyperlinks(
    hyperlinks: dict[int, str],
    index_map: dict[int, list[int]],
) -> dict[int, str]:
    """Re-index hyperlinks from raw row indices to post-split row indices.

    For the mega-row (raw index 1), the hyperlink is assigned to the first
    sub-row only (since the raw cell had one hyperlink covering all venues).
    For all other rows, the mapping is 1:1.
    """
    remapped = {}
    for raw_idx, url in hyperlinks.items():
        new_indices = index_map.get(raw_idx, [])
        if new_indices:
            # Assign hyperlink to first new index (for mega-row, that's the first venue)
            remapped[new_indices[0]] = url
    return remapped


def _derive_status(time_str: str, location: str) -> str:
    """Derive event status from time and location fields."""
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
    """Parse raw schedule rows into structured Event objects.

    Args:
        rows: Raw CSV rows (header + data). May contain mega-row and day headers.
        hyperlinks: Map of raw row_index -> URL from Sheets API hyperlink extraction.
            These indices are pre-split; this function re-indexes them after mega-row
            splitting.
    """
    rows, index_map = _split_mega_row(rows)
    remapped_links = _remap_hyperlinks(hyperlinks, index_map)

    events = []
    current_day = ""
    current_date = ""

    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue  # skip header

        if not any(cell.strip() for cell in row):
            continue

        first_cell = row[0].strip() if row else ""

        # Check for day header
        detected_day = _detect_day(first_cell)
        if detected_day:
            current_day = detected_day
            current_date = DAY_MAP.get(detected_day, "")
            continue

        # Regular event row
        def col(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        time_raw = col(2)
        start, end = parse_time(time_raw)
        location = col(3)
        link_text = col(4)

        # Prefer hyperlink from Sheets API, fall back to cell text if it looks like a URL
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_parser.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add enrich/parser.py tests/test_parser.py
git commit -m "feat: add schedule parser with day extraction, time normalization, and mega-row hyperlink re-indexing"
```

---

### Task 4: Crawler module

**Files:**
- Create: `enrich/crawler.py`

Crawls event URLs with httpx. Rate-limited: max 10 concurrent total, max 2 per domain (using per-domain semaphore), 0.5s delay between requests to same host. Caches results in `.cache/crawled/` with 24h TTL.

- [ ] **Step 1: Create crawler.py**

```python
"""Crawl event pages to extract text content."""

import asyncio
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

CACHE_DIR = Path(".cache/crawled")
CACHE_TTL = 86400  # 24 hours
MAX_CONCURRENT = 10
MAX_PER_DOMAIN = 2
DOMAIN_DELAY = 0.5
TIMEOUT = 15
MAX_TEXT_LENGTH = 3000


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _read_cache(url: str) -> str | None:
    path = CACHE_DIR / f"{_cache_key(url)}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if time.time() - data.get("ts", 0) > CACHE_TTL:
        return None
    return data.get("text", "")


def _write_cache(url: str, text: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(url)}.json"
    path.write_text(json.dumps({"url": url, "text": text, "ts": time.time()}))


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_LENGTH]


def _get_domain(url: str) -> str:
    return urlparse(url).netloc


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    global_semaphore: asyncio.Semaphore,
    domain_semaphores: dict[str, asyncio.Semaphore],
    domain_last: dict[str, float],
    domain_lock: dict[str, asyncio.Lock],
) -> tuple[str, str]:
    """Fetch a single URL, respecting rate limits. Returns (url, text)."""
    domain = _get_domain(url)

    # Check cache first (no semaphore needed)
    cached = _read_cache(url)
    if cached is not None:
        return (url, cached)

    # Acquire both global and per-domain semaphores
    async with global_semaphore:
        async with domain_semaphores[domain]:
            # Per-domain delay
            async with domain_lock[domain]:
                elapsed = time.time() - domain_last.get(domain, 0)
                if elapsed < DOMAIN_DELAY:
                    await asyncio.sleep(DOMAIN_DELAY - elapsed)
                domain_last[domain] = time.time()

            for attempt in range(2):
                try:
                    resp = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
                    resp.raise_for_status()
                    text = _strip_html(resp.text)
                    _write_cache(url, text)
                    return (url, text)
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(1)
                    else:
                        print(f"  Warning: failed to crawl {url}: {e}")
                        _write_cache(url, "")
                        return (url, "")


async def crawl_urls(urls: list[str]) -> dict[str, str]:
    """Crawl multiple URLs concurrently with rate limiting.

    Args:
        urls: List of URLs to crawl.

    Returns:
        Dict mapping URL to extracted text content.
    """
    # Filter out empty/coming-soon URLs
    valid_urls = [u for u in urls if u and "coming soon" not in u.lower() and u.startswith("http")]

    if not valid_urls:
        return {}

    global_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    domain_semaphores: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(MAX_PER_DOMAIN))
    domain_last: dict[str, float] = {}
    domain_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    results = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "CannesLionsMCP/1.0 (event-enrichment)"},
    ) as client:
        tasks = [
            _fetch_one(client, url, global_semaphore, domain_semaphores, domain_last, domain_lock)
            for url in valid_urls
        ]
        for coro in asyncio.as_completed(tasks):
            url, text = await coro
            results[url] = text

    return results


def crawl_urls_sync(urls: list[str]) -> dict[str, str]:
    """Synchronous wrapper for crawl_urls."""
    return asyncio.run(crawl_urls(urls))
```

- [ ] **Step 2: Quick smoke test**

Run: `cd /tmp/cannes-lions-mcp && python -c "from enrich.crawler import crawl_urls_sync; r = crawl_urls_sync(['https://httpbin.org/html']); print(list(r.keys())[0], len(list(r.values())[0]), 'chars')"`
Expected: prints URL and character count

- [ ] **Step 3: Commit**

```bash
git add enrich/crawler.py
git commit -m "feat: add async URL crawler with rate limiting, per-domain semaphores, and cache"
```

---

## Chunk 2: Classification, Matching, and Writer

### Task 5: Classifier module

**Files:**
- Create: `enrich/classifier.py`
- Create: `tests/test_classifier.py`

Batch-classifies events using Claude API. Validates output against allowed enum values. Retries with exponential backoff (2s, 8s) per spec.

- [ ] **Step 1: Write failing tests for validation logic**

`tests/test_classifier.py`:
```python
"""Tests for the classifier validation logic."""

from enrich.classifier import validate_classification, COMPANY_TYPES, EVENT_TYPES


class TestValidateClassification:
    def test_valid_classification(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "party",
            "target_audience": "publishers, brands",
            "crawled_summary": "A great event.",
        })
        assert result["company_type"] == "adtech"
        assert result["event_type"] == "party"
        assert result["target_audience"] == "publishers, brands"

    def test_invalid_company_type_falls_back(self):
        result = validate_classification({
            "company_type": "startup",
            "event_type": "party",
            "target_audience": "everyone",
            "crawled_summary": "",
        })
        assert result["company_type"] == "other"

    def test_invalid_event_type_falls_back(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "gala_dinner",
            "target_audience": "everyone",
            "crawled_summary": "",
        })
        assert result["event_type"] == "other"

    def test_missing_fields_get_defaults(self):
        result = validate_classification({})
        assert result["company_type"] == "other"
        assert result["event_type"] == "other"
        assert result["target_audience"] == "everyone"
        assert result["crawled_summary"] == ""

    def test_invalid_audience_values_filtered(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "panel",
            "target_audience": "publishers, ceos, brands",
            "crawled_summary": "",
        })
        assert result["target_audience"] == "publishers, brands"

    def test_all_invalid_audience_falls_back_to_everyone(self):
        result = validate_classification({
            "company_type": "adtech",
            "event_type": "panel",
            "target_audience": "executives, vips",
            "crawled_summary": "",
        })
        assert result["target_audience"] == "everyone"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_classifier.py -v`
Expected: FAIL

- [ ] **Step 3: Implement classifier.py**

```python
"""Classify events using Claude API."""

import json
import os
import time

COMPANY_TYPES = {"adtech", "publisher", "agency", "brand", "platform", "media", "industry_body", "other"}
EVENT_TYPES = {"party", "panel", "breakfast", "happy_hour", "networking", "workshop", "all_week_venue", "session", "other"}
AUDIENCE_VALUES = {"publishers", "brands", "agencies", "adtech", "everyone", "senior_leaders", "women_in_media", "creators"}

BATCH_SIZE = 20
MAX_RETRIES = 2
RETRY_DELAYS = [2, 8]  # seconds, per spec

PROMPT_TEMPLATE = """You are classifying Cannes Lions 2026 events. For each event, return JSON.

Allowed values:
- company_type: adtech | publisher | agency | brand | platform | media | industry_body | other
- event_type: party | panel | breakfast | happy_hour | networking | workshop | all_week_venue | session | other
- target_audience: comma-separated from: publishers, brands, agencies, adtech, everyone, senior_leaders, women_in_media, creators

Rules:
- Use ONLY the allowed values above. Do not invent new categories.
- target_audience can combine values: "publishers, adtech" is valid.
- crawled_summary: 2-3 sentences. If no crawled text available, summarize from event name and details only.
- If the crawled text does not describe a specific Cannes event, note this in the summary.

Events:
{events_json}

Return a JSON array of objects, one per event, in the same order:
[{{"company_type": "...", "event_type": "...", "target_audience": "...", "crawled_summary": "..."}}]
"""


def validate_classification(raw: dict) -> dict:
    """Validate and normalize a single classification result."""
    company_type = raw.get("company_type", "other")
    if company_type not in COMPANY_TYPES:
        company_type = "other"

    event_type = raw.get("event_type", "other")
    if event_type not in EVENT_TYPES:
        event_type = "other"

    target_audience = raw.get("target_audience", "everyone")
    if target_audience:
        parts = [p.strip() for p in target_audience.split(",")]
        valid_parts = [p for p in parts if p in AUDIENCE_VALUES]
        target_audience = ", ".join(valid_parts) if valid_parts else "everyone"

    return {
        "company_type": company_type,
        "event_type": event_type,
        "target_audience": target_audience,
        "crawled_summary": raw.get("crawled_summary", ""),
    }


def _default_classification() -> dict:
    return {
        "company_type": "other",
        "event_type": "other",
        "target_audience": "everyone",
        "crawled_summary": "",
    }


def classify_batch(events: list[dict]) -> list[dict]:
    """Classify a batch of events using Claude API.

    Args:
        events: List of dicts with keys: event_name, host, details, crawled_text

    Returns:
        List of dicts with keys: company_type, event_type, target_audience, crawled_summary
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set, returning defaults")
        return [_default_classification() for _ in events]

    client = anthropic.Anthropic(api_key=api_key)
    events_json = json.dumps(events, indent=2)
    prompt = PROMPT_TEMPLATE.format(events_json=events_json)

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON array found in response")

            results = json.loads(text[start:end])

            validated = []
            for r in results:
                validated.append(validate_classification(r))

            # Pad if response has fewer results than input
            while len(validated) < len(events):
                validated.append(_default_classification())

            return validated[:len(events)]

        except Exception as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt]
                print(f"  Retry {attempt + 1}/{MAX_RETRIES} after error: {e} (waiting {delay}s)")
                time.sleep(delay)
            else:
                print(f"  Warning: classification failed after {MAX_RETRIES + 1} attempts: {e}")
                return [_default_classification() for _ in events]


def classify_events(events: list[dict]) -> list[dict]:
    """Classify all events in batches.

    Args:
        events: List of dicts with keys: event_name, host, details, crawled_text

    Returns:
        List of classification dicts in same order as input.
    """
    all_results = []
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i:i + BATCH_SIZE]
        print(f"  Classifying batch {i // BATCH_SIZE + 1} ({len(batch)} events)...")
        results = classify_batch(batch)
        all_results.extend(results)
    return all_results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_classifier.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add enrich/classifier.py tests/test_classifier.py
git commit -m "feat: add Claude API classifier with batch processing and validation"
```

---

### Task 6: Registration matcher module

**Files:**
- Create: `enrich/matcher.py`
- Create: `tests/test_matcher.py`

Fuzzy-matches registration sheet entries to schedule events using `thefuzz`. Logs match confidence per spec.

- [ ] **Step 1: Write failing tests**

`tests/test_matcher.py`:
```python
"""Tests for the registration fuzzy matcher."""

from enrich.matcher import normalize_name, match_registrations
from enrich.parser import Event


class TestNormalizeName:
    def test_basic(self):
        assert normalize_name("  Microsoft  ") == "microsoft"

    def test_strip_at_cannes(self):
        assert normalize_name("Microsoft @ Cannes") == "microsoft"

    def test_strip_at_cannes_lowercase(self):
        assert normalize_name("google at cannes") == "google"

    def test_strip_at_cannes_lions(self):
        assert normalize_name("Meta at Cannes Lions") == "meta"


class TestMatchRegistrations:
    def test_exact_match(self):
        events = [
            Event(event_name="Party", host="Microsoft"),
            Event(event_name="Talk", host="Google"),
        ]
        registrations = [
            {"company": "Microsoft", "url": "https://ms.com/reg", "notes": "Free"},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ms.com/reg"
        assert events[0].registration_notes == "Free"
        assert events[1].registration_url == ""
        assert len(unmatched) == 0

    def test_fuzzy_match(self):
        events = [Event(event_name="Party", host="The Trade Desk")]
        registrations = [
            {"company": "Trade Desk @ Cannes", "url": "https://ttd.com", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ttd.com"
        assert len(unmatched) == 0

    def test_one_reg_multiple_events(self):
        events = [
            Event(event_name="Talk 1", host="Microsoft"),
            Event(event_name="Talk 2", host="Microsoft"),
        ]
        registrations = [
            {"company": "Microsoft", "url": "https://ms.com/reg", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert events[0].registration_url == "https://ms.com/reg"
        assert events[1].registration_url == "https://ms.com/reg"

    def test_unmatched_returned(self):
        events = [Event(event_name="Party", host="Microsoft")]
        registrations = [
            {"company": "Obscure Corp XYZ", "url": "https://obscure.com", "notes": ""},
        ]
        unmatched = match_registrations(events, registrations)
        assert len(unmatched) == 1
        assert unmatched[0]["company"] == "Obscure Corp XYZ"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_matcher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement matcher.py**

```python
"""Fuzzy-match registrations to schedule events."""

import re

from thefuzz import fuzz

from enrich.parser import Event

MATCH_THRESHOLD = 80


def normalize_name(name: str) -> str:
    """Normalize a company name for matching."""
    s = name.strip().lower()
    s = re.sub(r"\s*@\s*cannes\s*(lions)?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+at\s+cannes\s*(lions)?\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def match_registrations(
    events: list[Event],
    registrations: list[dict],
) -> list[dict]:
    """Match registration entries to events by fuzzy company name matching.

    Modifies events in-place (sets registration_url and registration_notes).
    Logs match confidence for each match per spec.

    Args:
        events: List of Event objects with host field populated.
        registrations: List of dicts with keys: company, url, notes.

    Returns:
        List of unmatched registration dicts.
    """
    unmatched = []

    for reg in registrations:
        company = reg.get("company", "")
        url = reg.get("url", "")
        notes = reg.get("notes", "")

        if not company:
            continue

        norm_company = normalize_name(company)
        matched_any = False

        for event in events:
            norm_host = normalize_name(event.host)
            score = fuzz.token_set_ratio(norm_company, norm_host)

            if score >= MATCH_THRESHOLD:
                event.registration_url = url
                event.registration_notes = notes
                matched_any = True
                print(f"    Matched '{company}' -> '{event.host}' (confidence: {score})")

        if not matched_any:
            unmatched.append(reg)

    return unmatched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /tmp/cannes-lions-mcp && python -m pytest tests/test_matcher.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add enrich/matcher.py tests/test_matcher.py
git commit -m "feat: add fuzzy registration matcher with confidence logging"
```

---

### Task 7: Sheet writer module

**Files:**
- Create: `enrich/writer.py`

Writes enriched data to the MIMMS master Google Sheet using `gws` CLI. Creates the sheet on first run and stores the sheet ID **and tab GIDs** in `config.json`. Returns the config dict so the caller can use it.

- [ ] **Step 1: Create writer.py**

```python
"""Write enriched data to the MIMMS master Google Sheet."""

import csv
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from enrich.parser import Event

CONFIG_PATH = Path("config.json")

EVENT_HEADERS = [
    "event_name", "host", "day", "date", "start_time", "end_time",
    "location", "event_url", "details", "crawled_summary",
    "company_type", "event_type", "target_audience",
    "registration_url", "registration_notes", "status",
]

UNREG_HEADERS = ["company", "registration_url", "notes", "crawled_summary", "company_type"]


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"master_sheet_id": "", "events_gid": "", "unreg_gid": ""}


def _save_config(config: dict):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def _run_gws(args: list[str]) -> str:
    """Run a gws CLI command and return stdout."""
    result = subprocess.run(
        ["gws"] + args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gws command failed: {result.stderr}")
    return result.stdout.strip()


def _create_master_sheet() -> str:
    """Create a new Google Sheet and return its ID."""
    title = "Cannes Lions 2026 - Master (MIMMS)"
    output = _run_gws(["sheets", "create", title])
    sheet_id = output.strip()
    if "spreadsheets/d/" in sheet_id:
        sheet_id = sheet_id.split("spreadsheets/d/")[1].split("/")[0]
    return sheet_id


def _make_sheet_public(sheet_id: str):
    """Make the sheet viewable by anyone with the link."""
    try:
        _run_gws(["drive", "share", sheet_id, "--type", "anyone", "--role", "reader"])
    except Exception as e:
        print(f"  Warning: could not make sheet public: {e}")


def _get_tab_gids(sheet_id: str) -> dict[str, str]:
    """Retrieve GIDs for all tabs in a sheet using gws CLI.

    Returns dict mapping tab name (lowercase) to GID string.
    """
    try:
        output = _run_gws(["sheets", "info", sheet_id])
        # Parse tab info from gws output. Format varies by gws version.
        # Try to extract tab name -> GID mappings.
        gids = {}
        for line in output.splitlines():
            # Look for patterns like "Events (gid: 0)" or "tab_name: gid"
            line = line.strip()
            if "gid" in line.lower():
                # Try to parse "TabName (gid: 12345)" or similar
                import re
                match = re.search(r"(.+?)\s*\(?gid[:\s]*(\d+)", line, re.IGNORECASE)
                if match:
                    tab_name = match.group(1).strip().lower()
                    gid = match.group(2)
                    gids[tab_name] = gid
        return gids
    except Exception as e:
        print(f"  Warning: could not retrieve tab GIDs: {e}")
        return {}


def _event_to_row(event: Event) -> list[str]:
    """Convert an Event to a list of strings matching EVENT_HEADERS."""
    return [
        event.event_name,
        event.host,
        event.day,
        event.date,
        event.start_time,
        event.end_time,
        event.location,
        event.event_url,
        event.details,
        event.crawled_summary,
        event.company_type,
        event.event_type,
        event.target_audience,
        event.registration_url,
        event.registration_notes,
        event.status,
    ]


def _to_csv_string(headers: list[str], rows: list[list[str]]) -> str:
    """Convert headers and rows to a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def write_master_sheet(
    events: list[Event],
    unmatched_regs: list[dict],
    warnings: list[str],
) -> dict:
    """Write enriched data to the master Google Sheet.

    Creates the sheet on first run, overwrites on subsequent runs.
    Stores sheet ID and tab GIDs in config.json.

    Returns:
        Config dict with keys: master_sheet_id, events_gid, unreg_gid.
    """
    config = _load_config()
    sheet_id = config.get("master_sheet_id", "")

    if not sheet_id:
        print("Creating master sheet...")
        sheet_id = _create_master_sheet()
        config["master_sheet_id"] = sheet_id
        _save_config(config)
        _make_sheet_public(sheet_id)
        print(f"  Created: https://docs.google.com/spreadsheets/d/{sheet_id}")

    # Write Events tab
    print("Writing Events tab...")
    event_rows = [_event_to_row(e) for e in events]
    events_csv = _to_csv_string(EVENT_HEADERS, event_rows)
    csv_path = Path("/tmp/cannes_events.csv")
    csv_path.write_text(events_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path), "--sheet", "Events", "--replace"])

    # Write Unmatched Registrations tab
    print("Writing Unmatched Registrations tab...")
    unreg_rows = [
        [
            r.get("company", ""),
            r.get("url", ""),
            r.get("notes", ""),
            r.get("crawled_summary", ""),
            r.get("company_type", ""),
        ]
        for r in unmatched_regs
    ]
    unreg_csv = _to_csv_string(UNREG_HEADERS, unreg_rows)
    csv_path2 = Path("/tmp/cannes_unreg.csv")
    csv_path2.write_text(unreg_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path2), "--sheet", "Unmatched Registrations", "--replace"])

    # Write _metadata tab
    print("Writing _metadata tab...")
    now = datetime.now(timezone.utc).isoformat()
    meta_csv = _to_csv_string(
        ["key", "value"],
        [
            ["last_updated", now],
            ["schedule_sheet_id", "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"],
            ["registration_sheet_id", "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"],
            ["event_count", str(len(events))],
            ["unmatched_reg_count", str(len(unmatched_regs))],
            *[["warning", w] for w in warnings],
        ],
    )
    csv_path3 = Path("/tmp/cannes_meta.csv")
    csv_path3.write_text(meta_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path3), "--sheet", "_metadata", "--replace"])

    # Retrieve tab GIDs after writing (Google assigns them on tab creation)
    print("Retrieving tab GIDs...")
    tab_gids = _get_tab_gids(sheet_id)
    config["events_gid"] = tab_gids.get("events", "0")
    config["unreg_gid"] = tab_gids.get("unmatched registrations", "")
    _save_config(config)

    if config["unreg_gid"]:
        print(f"  Events GID: {config['events_gid']}")
        print(f"  Unmatched Registrations GID: {config['unreg_gid']}")
    else:
        print("  Warning: could not auto-detect tab GIDs. Check config.json manually.")
        print(f"  Open https://docs.google.com/spreadsheets/d/{sheet_id} and note the gid= parameter for each tab.")
        warnings.append("Tab GIDs not auto-detected. Set events_gid and unreg_gid in config.json manually.")

    # Clean up temp files
    for p in [csv_path, csv_path2, csv_path3]:
        p.unlink(missing_ok=True)

    return config
```

- [ ] **Step 2: Commit**

```bash
git add enrich/writer.py
git commit -m "feat: add master sheet writer with tab GID retrieval"
```

---

## Chunk 3: CLI Entry Point and MCP Server Update

### Task 8: Enrichment CLI entry point

**Files:**
- Create: `enrich.py`

Wires all modules together. Supports `--dry-run`, `--no-crawl`, `--no-classify` flags. Prints config with sheet IDs and GIDs at the end for use in Modal secrets.

- [ ] **Step 1: Create enrich.py**

```python
#!/usr/bin/env python3
"""Cannes Lions 2026 enrichment pipeline.

Reads two source Google Sheets, parses/normalizes/crawls/classifies events,
and writes clean structured data to a MIMMS master Google Sheet.

Usage:
    python enrich.py                # Full run
    python enrich.py --dry-run      # Parse + normalize only, no crawl/classify/write
    python enrich.py --no-crawl     # Skip crawling, use cache or empty
    python enrich.py --no-classify  # Skip Claude API, leave classification empty
"""

import argparse

from enrich.sheets_reader import read_schedule_csv, read_registration_csv, extract_hyperlinks
from enrich.parser import parse_schedule_rows
from enrich.crawler import crawl_urls_sync
from enrich.classifier import classify_events
from enrich.matcher import match_registrations
from enrich.writer import write_master_sheet


def main():
    parser = argparse.ArgumentParser(description="Cannes Lions 2026 enrichment pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Parse + normalize only, no crawl/classify/write")
    parser.add_argument("--no-crawl", action="store_true", help="Skip crawling, use cache or empty")
    parser.add_argument("--no-classify", action="store_true", help="Skip Claude API classification")
    args = parser.parse_args()

    warnings = []

    # Step 1: Read source sheets
    print("Step 1: Reading source sheets...")
    schedule_rows = read_schedule_csv()
    print(f"  Schedule: {len(schedule_rows)} raw rows")

    registrations_raw = read_registration_csv()
    print(f"  Registrations: {len(registrations_raw)} entries")

    # Extract hyperlinks (requires Sheets API auth)
    hyperlinks = {}
    try:
        print("  Extracting hyperlinks from schedule sheet...")
        hyperlinks = extract_hyperlinks()
        print(f"  Found {len(hyperlinks)} hyperlinks")
    except Exception as e:
        msg = f"Hyperlink extraction failed: {e}. Using CSV link values."
        print(f"  Warning: {msg}")
        warnings.append(msg)

    # Step 2: Parse and normalize
    print("\nStep 2: Parsing and normalizing...")
    events = parse_schedule_rows(schedule_rows, hyperlinks)
    print(f"  Parsed {len(events)} events")

    days = {}
    for e in events:
        days[e.day] = days.get(e.day, 0) + 1
    for day, count in sorted(days.items()):
        print(f"    {day}: {count} events")

    if args.dry_run:
        print("\n--- DRY RUN: stopping before crawl/classify/write ---")
        for e in events[:5]:
            print(f"  {e.day} | {e.start_time}-{e.end_time} | {e.host}: {e.event_name}")
        print(f"  ... and {len(events) - 5} more")
        return

    # Step 3: Crawl event pages
    crawled = {}
    if not args.no_crawl:
        print("\nStep 3: Crawling event pages...")
        urls = [e.event_url for e in events if e.event_url]
        unique_urls = list(set(urls))
        print(f"  {len(unique_urls)} unique URLs to crawl")
        crawled = crawl_urls_sync(unique_urls)
        print(f"  Crawled {len(crawled)} pages")
    else:
        print("\nStep 3: Skipping crawl (--no-crawl)")

    # Step 4: Classify with Claude API
    if not args.no_classify:
        print("\nStep 4: Classifying events with Claude API...")
        classify_input = [
            {
                "event_name": e.event_name,
                "host": e.host,
                "details": e.details,
                "crawled_text": crawled.get(e.event_url, ""),
            }
            for e in events
        ]
        classifications = classify_events(classify_input)

        for i, c in enumerate(classifications):
            events[i].crawled_summary = c["crawled_summary"]
            events[i].company_type = c["company_type"]
            events[i].event_type = c["event_type"]
            events[i].target_audience = c["target_audience"]

        classified_count = sum(1 for c in classifications if c["company_type"] != "other")
        print(f"  Classified {classified_count}/{len(events)} events with specific types")
    else:
        print("\nStep 4: Skipping classification (--no-classify)")

    # Step 5: Match registrations
    print("\nStep 5: Matching registrations...")
    reg_data = []
    for r in registrations_raw:
        vals = list(r.values())
        company = vals[0] if len(vals) > 0 else ""
        url = vals[1] if len(vals) > 1 else ""
        notes = vals[2] if len(vals) > 2 else ""
        if company and "company or event" not in company.lower():
            reg_data.append({"company": company, "url": url, "notes": notes})

    unmatched = match_registrations(events, reg_data)
    matched_count = len(reg_data) - len(unmatched)
    print(f"  Matched {matched_count}/{len(reg_data)} registrations")
    print(f"  Unmatched: {len(unmatched)}")

    # Step 6: Write to master sheet
    print("\nStep 6: Writing to master sheet...")
    config = write_master_sheet(events, unmatched, warnings)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"ENRICHMENT COMPLETE")
    print(f"{'=' * 50}")
    print(f"  Events written: {len(events)}")
    print(f"  Registrations matched: {matched_count}")
    print(f"  Unmatched registrations: {len(unmatched)}")
    print(f"  Warnings: {len(warnings)}")
    print(f"  Master sheet: https://docs.google.com/spreadsheets/d/{config['master_sheet_id']}")
    print()
    print("  Modal secrets to set (for MCP server deployment):")
    print(f"    MASTER_SHEET_ID={config['master_sheet_id']}")
    print(f"    EVENTS_GID={config.get('events_gid', '0')}")
    print(f"    UNREG_GID={config.get('unreg_gid', '')}")
    print()
    print("  Run: modal secret create cannes-lions-config \\")
    print(f"    MASTER_SHEET_ID={config['master_sheet_id']} \\")
    print(f"    EVENTS_GID={config.get('events_gid', '0')} \\")
    print(f"    UNREG_GID={config.get('unreg_gid', '')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test dry-run mode**

Run: `cd /tmp/cannes-lions-mcp && python enrich.py --dry-run`
Expected: reads sheets, parses events, prints summary, stops before crawl/classify/write

- [ ] **Step 3: Commit**

```bash
git add enrich.py
git commit -m "feat: add enrichment CLI with Modal secret output"
```

---

### Task 9: Update MCP server with 8 tools

**Files:**
- Modify: `modal_app.py`

Replace the current 5 tools with 8 tools reading from the master sheet. Sheet IDs come from Modal secrets (not hardcoded), solving the deploy-time configuration problem.

- [ ] **Step 1: Rewrite modal_app.py**

```python
"""Cannes Lions 2026 -- StreamableHTTP MCP server on Modal (v2: enriched data)."""

import modal

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "mcp>=1.9.0",
    "httpx>=0.27.0",
    "uvicorn>=0.34.0",
    "thefuzz[speedup]>=0.22.0",
)

app = modal.App("cannes-lions-mcp", image=image)


@app.function(
    scaledown_window=300,
    secrets=[modal.Secret.from_name("cannes-lions-config")],
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    import csv
    import io
    import os

    import httpx
    from thefuzz import fuzz
    from mcp.server.fastmcp import FastMCP
    from mcp.server.streamable_http import TransportSecuritySettings

    # ── Master sheet config from Modal secrets ─────────────────────────
    MASTER_SHEET_ID = os.environ.get("MASTER_SHEET_ID", "")
    EVENTS_GID = os.environ.get("EVENTS_GID", "0")
    UNREG_GID = os.environ.get("UNREG_GID", "")
    CSV_TEMPLATE = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"

    # ── Data loading ────────────────────────────────────────────────────

    def _fetch_csv(sheet_id: str, gid: str) -> list[dict[str, str]]:
        url = CSV_TEMPLATE.format(id=sheet_id, gid=gid)
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        if not rows:
            return []
        headers = [h.strip().lower() for h in rows[0]]
        data = []
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            record = {}
            for i, h in enumerate(headers):
                record[h] = row[i].strip() if i < len(row) else ""
            data.append(record)
        return data

    def _load_events() -> list[dict[str, str]]:
        if not MASTER_SHEET_ID:
            return []
        return _fetch_csv(MASTER_SHEET_ID, EVENTS_GID)

    def _load_unmatched_regs() -> list[dict[str, str]]:
        if not MASTER_SHEET_ID or not UNREG_GID:
            return []
        return _fetch_csv(MASTER_SHEET_ID, UNREG_GID)

    # ── Formatting ──────────────────────────────────────────────────────

    def _format_event(e: dict) -> str:
        parts = [f"**{e.get('event_name', '')}**"]
        host = e.get("host", "")
        ctype = e.get("company_type", "")
        if host:
            parts.append(f"Host: {host}" + (f" ({ctype})" if ctype and ctype != "other" else ""))
        day = e.get("day", "").title()
        date = e.get("date", "")
        start = e.get("start_time", "")
        end = e.get("end_time", "")
        time_str = f"{start}-{end}" if start and end else start or ""
        if day:
            parts.append(f"Day: {day} {date}" + (f" | {time_str}" if time_str else ""))
        loc = e.get("location", "")
        if loc:
            parts.append(f"Location: {loc}")
        audience = e.get("target_audience", "")
        if audience:
            parts.append(f"Audience: {audience}")
        etype = e.get("event_type", "")
        if etype and etype != "other":
            parts.append(f"Type: {etype}")
        summary = e.get("crawled_summary", "")
        if summary:
            parts.append(f"Summary: {summary}")
        reg = e.get("registration_url", "")
        if reg:
            parts.append(f"Registration: {reg}")
        status = e.get("status", "")
        if status and status != "confirmed":
            parts.append(f"Status: {status}")
        parts.append("---")
        return "\n".join(parts)

    # ── MCP server ──────────────────────────────────────────────────────

    mcp = FastMCP(
        "cannes-lions",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def search_schedule(query: str, limit: int = 15) -> str:
        """Search the Cannes Lions 2026 event schedule by keyword. Matches across event_name, host, location, details, crawled_summary."""
        events = _load_events()
        q = query.lower()
        matches = []
        for e in events:
            searchable = " ".join([
                e.get("event_name", ""), e.get("host", ""),
                e.get("location", ""), e.get("details", ""),
                e.get("crawled_summary", ""),
            ]).lower()
            if q in searchable:
                matches.append(e)
        if not matches:
            return f"No events matching '{query}'."
        capped = matches[:limit]
        result = "\n\n".join(_format_event(m) for m in capped)
        return f"Found {len(matches)} events matching '{query}':\n\n{result}"

    @mcp.tool()
    def list_schedule_by_day(day: str) -> str:
        """List all Cannes events for a specific day (sunday/monday/tuesday/wednesday/thursday/friday). Returns events sorted by start time."""
        events = _load_events()
        d = day.lower().strip()
        matches = [e for e in events if e.get("day", "").lower() == d]
        matches.sort(key=lambda e: e.get("start_time", "zz"))
        if not matches:
            return f"No events found for '{day}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Events for {day.title()} ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def list_schedule_by_host(host: str) -> str:
        """Find all events hosted by a specific company at Cannes Lions 2026."""
        events = _load_events()
        h = host.lower()
        matches = [e for e in events if h in e.get("host", "").lower()]
        if not matches:
            return f"No events found hosted by '{host}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Events hosted by {host} ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def recommend_events(role: str, day: str = "", limit: int = 20) -> str:
        """Recommend Cannes Lions 2026 events based on your role (publisher, brand, agency, adtech, creator, senior_leader). Optionally filter by day."""
        events = _load_events()
        role_stem = role.lower().strip().rstrip("s")
        matches = []
        for e in events:
            audience = e.get("target_audience", "").lower()
            audience_parts = [a.strip() for a in audience.split(",")]
            if any(a.startswith(role_stem) or a == "everyone" for a in audience_parts):
                if day and e.get("day", "").lower() != day.lower().strip():
                    continue
                matches.append(e)
        matches.sort(key=lambda e: (e.get("day", ""), e.get("start_time", "zz")))
        if not matches:
            return f"No events found for role '{role}'" + (f" on {day}" if day else "") + "."
        capped = matches[:limit]
        result = "\n\n".join(_format_event(m) for m in capped)
        header = f"Recommended events for {role}" + (f" on {day.title()}" if day else "")
        return f"{header} ({len(matches)} total, showing {len(capped)}):\n\n{result}"

    @mcp.tool()
    def filter_events(audience: str = "", company_type: str = "", event_type: str = "", day: str = "") -> str:
        """Filter Cannes Lions 2026 events by multiple criteria. All parameters optional, combine any. Example: audience=publishers, event_type=happy_hour, day=wednesday."""
        events = _load_events()
        matches = events
        if day:
            matches = [e for e in matches if e.get("day", "").lower() == day.lower().strip()]
        if audience:
            a = audience.lower().strip()
            matches = [e for e in matches if a in e.get("target_audience", "").lower()]
        if company_type:
            ct = company_type.lower().strip()
            matches = [e for e in matches if e.get("company_type", "").lower() == ct]
        if event_type:
            et = event_type.lower().strip()
            matches = [e for e in matches if e.get("event_type", "").lower() == et]
        matches.sort(key=lambda e: (e.get("day", ""), e.get("start_time", "zz")))
        if not matches:
            filters = []
            if day: filters.append(f"day={day}")
            if audience: filters.append(f"audience={audience}")
            if company_type: filters.append(f"company_type={company_type}")
            if event_type: filters.append(f"event_type={event_type}")
            return f"No events matching filters: {', '.join(filters)}."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Filtered events ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def get_event_details(event_name: str) -> str:
        """Get full details for a specific Cannes Lions 2026 event. Uses fuzzy matching on event name."""
        events = _load_events()
        if not events:
            return "No events data available."
        best_match = None
        best_score = 0
        for e in events:
            score = fuzz.token_set_ratio(event_name.lower(), e.get("event_name", "").lower())
            if score > best_score:
                best_score = score
                best_match = e
        if not best_match or best_score < 50:
            return f"No event found matching '{event_name}'."
        return _format_event(best_match)

    @mcp.tool()
    def find_registration(company: str) -> str:
        """Find registration info for a company at Cannes Lions 2026. Searches both matched events and unmatched registrations."""
        events = _load_events()
        c = company.lower()
        event_matches = []
        for e in events:
            if e.get("registration_url") and c in e.get("host", "").lower():
                event_matches.append(e)
        unreg = _load_unmatched_regs()
        unreg_matches = [r for r in unreg if c in r.get("company", "").lower()]
        if not event_matches and not unreg_matches:
            return f"No registration info found for '{company}'."
        parts = []
        if event_matches:
            parts.append(f"**Events with registration ({len(event_matches)}):**\n")
            for e in event_matches:
                parts.append(f"- {e.get('event_name', '')}: {e.get('registration_url', '')}")
                if e.get("registration_notes"):
                    parts.append(f"  Notes: {e.get('registration_notes')}")
        if unreg_matches:
            parts.append(f"\n**Other registrations ({len(unreg_matches)}):**\n")
            for r in unreg_matches:
                parts.append(f"- {r.get('company', '')}: {r.get('registration_url', '')}")
                if r.get("notes"):
                    parts.append(f"  Notes: {r.get('notes')}")
        return "\n".join(parts)

    @mcp.tool()
    def list_registrations() -> str:
        """List all known Cannes Lions 2026 event registration links."""
        events = _load_events()
        seen = set()
        lines = []
        for e in events:
            url = e.get("registration_url", "")
            host = e.get("host", "")
            if url and url not in seen:
                seen.add(url)
                lines.append(f"- **{host}**: {url}")
        unreg = _load_unmatched_regs()
        for r in unreg:
            url = r.get("registration_url", "")
            company = r.get("company", "")
            if url and url not in seen:
                seen.add(url)
                lines.append(f"- **{company}**: {url}")
        if not lines:
            return "No registration links available."
        return f"Registration links ({len(lines)} total):\n\n" + "\n".join(lines)

    return mcp.streamable_http_app()
```

- [ ] **Step 2: Verify the file is syntactically valid**

Run: `cd /tmp/cannes-lions-mcp && python -c "import ast; ast.parse(open('modal_app.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 3: Commit**

```bash
git add modal_app.py
git commit -m "feat: update MCP server with 8 enriched tools, sheet IDs from Modal secrets"
```

---

### Task 10: Run the enrichment pipeline and configure Modal

**Files:** None (execution + configuration)

- [ ] **Step 1: Dry run to validate parsing**

Run: `cd /tmp/cannes-lions-mcp && python enrich.py --dry-run`
Expected: prints event count, day breakdown, sample events. No writes.

- [ ] **Step 2: Run with --no-classify to test crawling + matching + sheet creation**

Run: `cd /tmp/cannes-lions-mcp && python enrich.py --no-classify`
Expected: creates master sheet, crawls URLs, matches registrations, writes data. Prints sheet ID and GIDs.

- [ ] **Step 3: Verify config.json has sheet ID and GIDs**

Run: `cd /tmp/cannes-lions-mcp && cat config.json`
Expected: JSON with `master_sheet_id`, `events_gid`, `unreg_gid` all populated.

If `unreg_gid` is empty, open the master sheet URL in the browser, navigate to the "Unmatched Registrations" tab, and note the `gid=` parameter from the URL. Manually update `config.json`.

- [ ] **Step 4: Full run with classification**

Run: `cd /tmp/cannes-lions-mcp && python enrich.py`
Expected: full pipeline completes. Classification columns populated. Summary printed.

- [ ] **Step 5: Create Modal secret with sheet IDs**

Run the command printed by `enrich.py` at the end:

```bash
modal secret create cannes-lions-config \
    MASTER_SHEET_ID=<value from config.json> \
    EVENTS_GID=<value from config.json> \
    UNREG_GID=<value from config.json>
```

Expected: secret created successfully.

- [ ] **Step 6: Commit**

```bash
cd /tmp/cannes-lions-mcp && git add -A && git commit -m "feat: enrichment pipeline complete, config populated"
```

---

### Task 11: Deploy and test

**Files:** None (deployment only)

- [ ] **Step 1: Deploy to Modal**

Run: `cd /tmp/cannes-lions-mcp && modal deploy modal_app.py`
Expected: deploys successfully, prints URL.

- [ ] **Step 2: Test tools/list returns 8 tools**

Run:
```bash
curl -s -X POST https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -m json.tool
```
Expected: JSON response listing 8 tools: search_schedule, list_schedule_by_day, list_schedule_by_host, recommend_events, filter_events, get_event_details, find_registration, list_registrations.

- [ ] **Step 3: Test recommend_events tool**

Run:
```bash
curl -s -X POST https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"recommend_events","arguments":{"role":"publisher","day":"tuesday"}}}'
```
Expected: returns publisher-relevant events for Tuesday with enriched metadata.

- [ ] **Step 4: Test filter_events tool**

Run:
```bash
curl -s -X POST https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"filter_events","arguments":{"event_type":"happy_hour","day":"wednesday"}}}'
```
Expected: returns happy hour events on Wednesday.

- [ ] **Step 5: Commit any final fixes**

```bash
cd /tmp/cannes-lions-mcp && git add -A && git commit -m "fix: post-deployment adjustments"
```

---

### Task 12: Update landing page and push

**Files:**
- Modify: `/tmp/mimms-tech/app/cannes/page.tsx`

Update the tools section from 5 to 8 tools, and update example queries to show the new capabilities.

- [ ] **Step 1: Update the tools list in the landing page**

In `/tmp/mimms-tech/app/cannes/page.tsx`, replace the tools section (around line 140-156) with:

```tsx
<p className="section-label mb-5">8 tools exposed</p>
<div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
  {[
    ['search_schedule', 'Keyword search across all events'],
    ['list_schedule_by_day', 'Filter by day of the week'],
    ['list_schedule_by_host', 'Find events by host company'],
    ['recommend_events', 'Get recommendations by role (publisher, brand, agency)'],
    ['filter_events', 'Multi-criteria filter (audience, type, day)'],
    ['get_event_details', 'Deep dive into a specific event'],
    ['find_registration', 'Find registration links by company'],
    ['list_registrations', 'All registration links'],
  ].map(([name, desc]) => (
    <div key={name} className="bg-surface border border-border px-4 py-3">
      <code className="text-accent font-mono text-small">{name}</code>
      <p className="text-small text-text-muted mt-1">{desc}</p>
    </div>
  ))}
</div>
```

- [ ] **Step 2: Update example queries to show new capabilities**

Replace the example queries (around line 119-132) with:

```tsx
{[
  "What should a publisher do on Tuesday?",
  "Find all happy hours on Wednesday",
  "What's Equativ doing at Cannes?",
].map((q) => (
```

- [ ] **Step 3: Commit and deploy landing page**

```bash
cd /tmp/mimms-tech && git add app/cannes/page.tsx && git commit -m "feat: update cannes page to show 8 MCP tools and new example queries"
```

- [ ] **Step 4: Push both repos**

```bash
cd /tmp/cannes-lions-mcp && git push origin main
cd /tmp/mimms-tech && git push origin main
```
