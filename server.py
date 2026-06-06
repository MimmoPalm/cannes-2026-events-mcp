"""Cannes Lions 2026 MCP Server — Enriched Edition.

Reads from the enriched MIMMS Cannes schedule sheet with company types,
event types, target audiences, speaker details, and registration URLs.
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

SCHEDULE_SHEET_ID = "1f1zyz9m-AL6f_JUlE606sV2UbuRsrijfMxNwfpOMRoo"
SCHEDULE_GID = "1460350760"

REGISTRATION_SHEET_ID = "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"
REGISTRATION_GID = "835495045"

CSV_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"
)

# ── Data loading ───────────────────────────────────────────────────────────

def _fetch_csv(sheet_id: str, gid: str) -> list[dict[str, str]]:
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


def _fetch_schedule() -> list[dict[str, str]]:
    """Fetch the enriched schedule sheet and return list of event dicts."""
    return _fetch_csv(SCHEDULE_SHEET_ID, SCHEDULE_GID)


# ── Column access helpers ─────────────────────────────────────────────────

def _s(e: dict[str, str], key: str) -> str:
    """Safe dict access."""
    return e.get(key, "").strip()


# ── MCP server ─────────────────────────────────────────────────────────────

server = Server("cannes-lions")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_schedule",
            description="Search the Cannes Lions 2026 event schedule by keyword. Matches across event name, host, location, details, and crawled summaries.",
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
                        "description": "Day keyword: 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday'",
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
            name="recommend_events",
            description="Get personalised event recommendations by role. Filters by target audience and returns the most relevant events.",
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Your role: 'publisher', 'brand', 'agency', 'adtech', 'senior_leader'",
                    },
                    "day": {
                        "type": "string",
                        "description": "Optional: filter to a specific day (e.g. 'tuesday')",
                    },
                },
                "required": ["role"],
            },
        ),
        Tool(
            name="filter_events",
            description="Multi-criteria filter across the Cannes schedule. Combine audience, company type, event type, and day.",
            inputSchema={
                "type": "object",
                "properties": {
                    "company_type": {
                        "type": "string",
                        "description": "Filter by company type: 'adtech', 'publisher', 'agency', 'brand', 'platform', 'media', 'industry_body'",
                    },
                    "event_type": {
                        "type": "string",
                        "description": "Filter by event type: 'party', 'panel', 'breakfast', 'happy_hour', 'networking', 'workshop', 'all_week_venue', 'session'",
                    },
                    "target_audience": {
                        "type": "string",
                        "description": "Filter by target audience keyword (e.g. 'publishers', 'brands', 'agencies', 'senior_leaders', 'women_in_media')",
                    },
                    "day": {
                        "type": "string",
                        "description": "Optional: filter to a specific day",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_event_details",
            description="Get full details for a specific event by name (fuzzy match). Includes summary, speakers, registration info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Event name or partial name to look up",
                    }
                },
                "required": ["name"],
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
    elif name == "recommend_events":
        return _recommend_events(arguments["role"], arguments.get("day", ""))
    elif name == "filter_events":
        return _filter_events(arguments)
    elif name == "get_event_details":
        return _get_event_details(arguments["name"])
    elif name == "search_registrations":
        return _search_registrations(arguments["company"])
    elif name == "list_registrations":
        return _list_registrations()
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Output formatting ─────────────────────────────────────────────────────

def _format_event(e: dict[str, str], include_details: bool = False) -> str:
    """Format an event for display."""
    parts = [
        f"**{_s(e, 'event_name')}**",
        f"Host: {_s(e, 'host')}",
    ]
    day = _s(e, "day")
    date = _s(e, "date")
    if day or date:
        when = f"{day} {date}".strip()
        parts.append(f"When: {when}")
    
    start = _s(e, "start_time")
    end = _s(e, "end_time")
    if start:
        time_str = f"{start} - {end}" if end else start
        parts.append(f"Time: {time_str}")

    location = _s(e, "location")
    if location:
        parts.append(f"Location: {location}")

    ct = _s(e, "company_type")
    et = _s(e, "event_type")
    if ct or et:
        badges = " · ".join(b for b in [ct, et] if b)
        parts.append(f"Type: {badges}")

    audience = _s(e, "target_audience")
    if audience:
        parts.append(f"Audience: {audience}")

    if include_details:
        summary = _s(e, "crawled_summary")
        if summary:
            parts.append(f"Summary: {summary[:500]}")
        
        speakers = _s(e, "speakers")
        if speakers:
            parts.append(f"Speakers: {speakers}")

    reg_url = _s(e, "registration_url")
    if reg_url:
        parts.append(f"Register: {reg_url}")

    reg_notes = _s(e, "registration_notes")
    if reg_notes:
        parts.append(f"Registration notes: {reg_notes}")

    parts.append("---")
    return "\n".join(parts)


# ── Schedule tools ─────────────────────────────────────────────────────────

def _search_schedule(query: str) -> list[TextContent]:
    events = _fetch_schedule()
    q = query.lower()
    matches = []

    for e in events:
        text = " ".join(str(v).lower() for v in e.values())
        if q in text:
            matches.append(e)

    if not matches:
        return [TextContent(type="text", text=f"No events matching '{query}'.")]

    result = "\n".join(_format_event(m) for m in matches[:15])
    header = f"Found {len(matches)} events matching '{query}':\n\n"
    return [TextContent(type="text", text=header + result)]


def _list_by_day(day: str) -> list[TextContent]:
    events = _fetch_schedule()
    d = day.lower()
    
    matches = []
    for e in events:
        eday = _s(e, "day").lower()
        if d in eday or (d == "all week" and "all week" in eday):
            matches.append(e)
    
    matches.sort(key=lambda e: _s(e, "start_time"))

    if not matches:
        return [TextContent(type="text", text=f"No events found for '{day}'.")]

    result = "\n".join(_format_event(m) for m in matches[:30])
    header = f"Events for {day.title()}: ({len(matches)} total, showing up to 30)\n\n"
    return [TextContent(type="text", text=header + result)]


def _list_by_host(host: str) -> list[TextContent]:
    events = _fetch_schedule()
    h = host.lower()
    matches = [e for e in events if h in _s(e, "host").lower()]

    if not matches:
        return [TextContent(type="text", text=f"No events found hosted by '{host}'.")]

    result = "\n".join(_format_event(m) for m in matches[:15])
    header = f"Events hosted by {host}: ({len(matches)} total)\n\n"
    return [TextContent(type="text", text=header + result)]


def _recommend_events(role: str, day: str = "") -> list[TextContent]:
    events = _fetch_schedule()
    r = role.lower()

    role_map = {
        "publisher": "publishers",
        "brand": "brands",
        "agency": "agencies",
        "adtech": "adtech",
        "senior_leader": "senior_leaders",
    }
    keyword = role_map.get(r, r)

    matches = []
    for e in events:
        audience = _s(e, "target_audience").lower()
        if keyword in audience:
            if day and day.lower() not in _s(e, "day").lower():
                continue
            matches.append(e)

    matches.sort(key=lambda e: (
        0 if _s(e, "day").lower() and "all week" not in _s(e, "day").lower() else 1,
        _s(e, "start_time"),
    ))

    if not matches:
        msg = f"No events found for role '{role}'"
        if day:
            msg += f" on {day}"
        return [TextContent(type="text", text=msg + ".")]

    result = "\n".join(_format_event(m) for m in matches[:20])
    header = f"Recommended for {role}s"
    if day:
        header += f" on {day.title()}"
    header += f": ({len(matches)} events, showing top 20)\n\n"
    return [TextContent(type="text", text=header + result)]


def _filter_events(args: dict) -> list[TextContent]:
    events = _fetch_schedule()
    matches = events

    ct = args.get("company_type", "").lower()
    if ct:
        matches = [e for e in matches if ct in _s(e, "company_type").lower()]

    et = args.get("event_type", "").lower()
    if et:
        matches = [e for e in matches if et in _s(e, "event_type").lower()]

    audience = args.get("target_audience", "").lower()
    if audience:
        matches = [e for e in matches if audience in _s(e, "target_audience").lower()]

    day = args.get("day", "").lower()
    if day:
        matches = [e for e in matches if day in _s(e, "day").lower()]

    if not matches:
        filters = ", ".join(f"{k}={v}" for k, v in args.items() if v)
        return [TextContent(type="text", text=f"No events match filters: {filters}.")]

    result = "\n".join(_format_event(m) for m in matches[:25])
    header = f"Filtered events ({len(matches)} total, showing up to 25):\n\n"
    return [TextContent(type="text", text=header + result)]


def _get_event_details(name: str) -> list[TextContent]:
    events = _fetch_schedule()
    n = name.lower()

    matches = [e for e in events if n == _s(e, "event_name").lower()]
    if not matches:
        matches = [e for e in events if n in _s(e, "event_name").lower()]

    if not matches:
        return [TextContent(type="text", text=f"No event found matching '{name}'.")]

    result = "\n".join(_format_event(m, include_details=True) for m in matches[:5])
    header = f"Found {len(matches)} matching events:\n\n"
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