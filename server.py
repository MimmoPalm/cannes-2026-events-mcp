"""Cannes Lions 2026 MCP Server.

Exposes two datasources:
1. Event schedule (The Digital Voice) — full timetable
2. Registration links (community-sourced) — company + URL

Both sheets are published to web (no auth needed).
"""

import csv
import io
import re
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── Sheet config ──────────────────────────────────────────────────────────

SCHEDULE_SHEET_ID = "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"
SCHEDULE_GID = "1111568312"

REGISTRATION_SHEET_ID = "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"
REGISTRATION_GID = "835495045"

CSV_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"
)

# ── Data loading ───────────────────────────────────────────────────────────


def _fetch_csv(sheet_id: str, gid: str) -> list[dict[str, str]]:
    """Fetch a published Google Sheet as CSV and parse into list of dicts."""
    url = CSV_TEMPLATE.format(id=sheet_id, gid=gid)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()

    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)

    if not rows:
        return []

    headers = [h.strip() for h in rows[0]]
    data: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        record: dict[str, str] = {}
        for i, h in enumerate(headers):
            record[h] = row[i].strip() if i < len(row) else ""
        data.append(record)

    return data


def _fetch_schedule_raw() -> list[list[str]]:
    """Fetch schedule sheet and return rows as list of lists (header + data).

    Returns rows where index-based access is used (column names are unwieldy).
    Indices:
      0 = Event name
      1 = Host
      2 = Local Time (CEST)
      3 = Location
      4 = Link
      5 = Details
    """
    url = CSV_TEMPLATE.format(id=SCHEDULE_SHEET_ID, gid=SCHEDULE_GID)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()

    reader = csv.reader(io.StringIO(resp.text))
    return list(reader)


# ── MCP server ─────────────────────────────────────────────────────────────

server = Server("cannes-lions")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_schedule",
            description="Search the Cannes Lions 2026 event schedule by keyword. Matches across event name, host, location, and details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term (e.g. 'Equativ', 'Microsoft', 'Tennis')",
                    }
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_schedule_by_day",
            description="List all Cannes events for a specific day.",
            inputSchema={
                "type": "object",
                "properties": {
                    "day": {
                        "type": "string",
                        "description": "Day keyword: 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday'",
                    }
                },
                "required": ["day"],
            },
        ),
        Tool(
            name="list_schedule_by_host",
            description="Find all events hosted by a specific company.",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Company name (e.g. 'Microsoft', 'TikTok', 'Equativ')",
                    }
                },
                "required": ["host"],
            },
        ),
        Tool(
            name="search_registrations",
            description="Search the Cannes registration links sheet by company name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company or event name to search for",
                    }
                },
                "required": ["company"],
            },
        ),
        Tool(
            name="list_registrations",
            description="List all known Cannes event registration links.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_schedule":
        return _search_schedule(arguments["query"])
    elif name == "list_schedule_by_day":
        return _list_by_day(arguments["day"])
    elif name == "list_schedule_by_host":
        return _list_by_host(arguments["host"])
    elif name == "search_registrations":
        return _search_registrations(arguments["company"])
    elif name == "list_registrations":
        return _list_registrations()
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Schedule helpers ───────────────────────────────────────────────────────

# Column indices for the schedule sheet (row 0 = header)
SCHEDULE_COLS = {
    "event": 0,
    "host": 1,
    "time": 2,
    "location": 3,
    "link": 4,
    "details": 5,
}


def _format_schedule_row(row: list[str]) -> str:
    """Format a schedule row (list by index) for output."""
    parts = [
        f"**{_col(row, 'event')}**",
        f"Host: {_col(row, 'host')}",
        f"Time: {_col(row, 'time')}",
        f"Location: {_col(row, 'location')}",
    ]
    link = _col(row, "link")
    if link and link != "Coming soon":
        parts.append(f"Link: {link}")
    details = _col(row, "details")
    if details:
        parts.append(f"Details: {details[:300]}")
    parts.append("---")
    return "\n".join(parts)


def _col(row: list[str], key: str) -> str:
    """Safe column access by name, returns empty string if missing."""
    idx = SCHEDULE_COLS[key]
    if idx < len(row):
        return row[idx].strip()
    return ""


def _match_day(row: list[str], day: str) -> bool:
    """Check if a row belongs to a given day by looking for day markers.

    Rows that are day headers (like 'SUNDAY 21ST') set the current day context.
    Event rows under that header match if the day matches.
    """
    text = " ".join(row).lower()
    return day.lower() in text


# ── Schedule tools ─────────────────────────────────────────────────────────


def _search_schedule(query: str) -> list[TextContent]:
    rows = _fetch_schedule_raw()
    q = query.lower()
    matches = []

    for row in rows[1:]:  # skip header
        if not any(cell.strip() for cell in row):
            continue
        text = " ".join(cell.lower() for cell in row)
        if q in text:
            matches.append(row)

    if not matches:
        return [TextContent(type="text", text=f"No events matching '{query}'.")]

    result = "\n".join(_format_schedule_row(m) for m in matches[:15])
    header = f"Found {len(matches)} events matching '{query}':\n\n"
    return [TextContent(type="text", text=header + result)]


def _list_by_day(day: str) -> list[TextContent]:
    rows = _fetch_schedule_raw()
    d = day.lower()

    # Find the day marker and collect all subsequent rows until next day marker
    day_keywords = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    matches = []
    in_section = False

    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue

        first = row[0].lower() if row else ""

        # Check if this row starts a new day section
        is_day_header = any(dk in first for dk in day_keywords)
        if is_day_header:
            in_section = d in first
            continue

        if in_section:
            matches.append(row)

    if not matches:
        return [TextContent(type="text", text=f"No events found for '{day}'.")]

    result = "\n".join(_format_schedule_row(m) for m in matches[:25])
    header = f"Events for {day.title()}:\n\n"
    return [TextContent(type="text", text=header + result)]


def _list_by_host(host: str) -> list[TextContent]:
    rows = _fetch_schedule_raw()
    h = host.lower()
    matches = []

    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        host_val = _col(row, "host").lower()
        if h in host_val:
            matches.append(row)

    if not matches:
        return [TextContent(type="text", text=f"No events found hosted by '{host}'.")]

    result = "\n".join(_format_schedule_row(m) for m in matches[:15])
    header = f"Events hosted by {host}:\n\n"
    return [TextContent(type="text", text=header + result)]


# ── Registration tools ─────────────────────────────────────────────────────


def _search_registrations(company: str) -> list[TextContent]:
    data = _fetch_csv(REGISTRATION_SHEET_ID, REGISTRATION_GID)
    q = company.lower()
    matches = []

    for e in data:
        vals = list(e.values())
        name = vals[0].lower() if vals else ""
        if q in name:
            matches.append(e)

    if not matches:
        return [TextContent(type="text", text=f"No registration links found for '{company}'.")]

    lines = []
    for m in matches[:10]:
        vals = list(m.values())
        name = vals[0] if len(vals) > 0 else "?"
        url = vals[1] if len(vals) > 1 else "N/A"
        notes = vals[2] if len(vals) > 2 else ""
        lines.append(f"**{name}**\n  Registration: {url}\n  Notes: {notes}\n")

    return [TextContent(type="text", text="\n".join(lines))]


def _list_registrations() -> list[TextContent]:
    data = _fetch_csv(REGISTRATION_SHEET_ID, REGISTRATION_GID)
    lines = []
    for e in data:
        vals = list(e.values())
        name = vals[0] if len(vals) > 0 else ""
        url = vals[1] if len(vals) > 1 else ""
        if name and "company or event" not in name.lower():
            lines.append(f"- **{name}**: {url}")
    return [TextContent(type="text", text="\n".join(lines))]


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    import asyncio

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(run())


if __name__ == "__main__":
    main()
