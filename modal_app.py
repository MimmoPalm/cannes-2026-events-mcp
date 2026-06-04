"""Cannes Lions 2026 -- StreamableHTTP MCP server on Modal."""

import modal

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "mcp>=1.9.0",
    "httpx>=0.27.0",
    "uvicorn>=0.34.0",
)

app = modal.App("cannes-lions-mcp", image=image)


@app.function(scaledown_window=300)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    import csv
    import io

    import httpx
    from mcp.server.fastmcp import FastMCP

    # ── Sheet config ─────────────────────────────────────────────────────
    SCHEDULE_SHEET_ID = "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"
    SCHEDULE_GID = "1111568312"
    REGISTRATION_SHEET_ID = "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"
    REGISTRATION_GID = "835495045"
    CSV_TEMPLATE = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"
    SCHEDULE_COLS = {"event": 0, "host": 1, "time": 2, "location": 3, "link": 4, "details": 5}

    # ── Helpers ───────────────────────────────────────────────────────────
    def _fetch_csv(sheet_id: str, gid: str) -> list[dict[str, str]]:
        url = CSV_TEMPLATE.format(id=sheet_id, gid=gid)
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

    def _fetch_schedule_raw() -> list[list[str]]:
        url = CSV_TEMPLATE.format(id=SCHEDULE_SHEET_ID, gid=SCHEDULE_GID)
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        return list(reader)

    def _col(row: list[str], key: str) -> str:
        idx = SCHEDULE_COLS[key]
        return row[idx].strip() if idx < len(row) else ""

    def _format_row(row: list[str]) -> str:
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

    # ── MCP server ───────────────────────────────────────────────────────
    from mcp.server.streamable_http import TransportSecuritySettings
    mcp = FastMCP(
        "cannes-lions",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def search_schedule(query: str) -> str:
        """Search the Cannes Lions 2026 event schedule by keyword. Matches across event name, host, location, and details."""
        rows = _fetch_schedule_raw()
        q = query.lower()
        matches = [
            row for row in rows[1:]
            if any(cell.strip() for cell in row) and q in " ".join(c.lower() for c in row)
        ]
        if not matches:
            return f"No events matching '{query}'."
        result = "\n".join(_format_row(m) for m in matches[:15])
        return f"Found {len(matches)} events matching '{query}':\n\n{result}"

    @mcp.tool()
    def list_schedule_by_day(day: str) -> str:
        """List all Cannes events for a specific day (sunday, monday, tuesday, wednesday, thursday)."""
        rows = _fetch_schedule_raw()
        d = day.lower()
        day_keywords = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        matches = []
        in_section = False
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            first = row[0].lower() if row else ""
            is_day_header = any(dk in first for dk in day_keywords)
            if is_day_header:
                in_section = d in first
                continue
            if in_section:
                matches.append(row)
        if not matches:
            return f"No events found for '{day}'."
        result = "\n".join(_format_row(m) for m in matches[:25])
        return f"Events for {day.title()}:\n\n{result}"

    @mcp.tool()
    def list_schedule_by_host(host: str) -> str:
        """Find all events hosted by a specific company at Cannes Lions 2026."""
        rows = _fetch_schedule_raw()
        h = host.lower()
        matches = [
            row for row in rows[1:]
            if any(cell.strip() for cell in row) and h in _col(row, "host").lower()
        ]
        if not matches:
            return f"No events found hosted by '{host}'."
        result = "\n".join(_format_row(m) for m in matches[:15])
        return f"Events hosted by {host}:\n\n{result}"

    @mcp.tool()
    def search_registrations(company: str) -> str:
        """Search the Cannes registration links sheet by company name."""
        data = _fetch_csv(REGISTRATION_SHEET_ID, REGISTRATION_GID)
        q = company.lower()
        matches = [e for e in data if q in list(e.values())[0].lower()]
        if not matches:
            return f"No registration links found for '{company}'."
        lines = []
        for m in matches[:10]:
            vals = list(m.values())
            name = vals[0] if len(vals) > 0 else "?"
            url = vals[1] if len(vals) > 1 else "N/A"
            notes = vals[2] if len(vals) > 2 else ""
            lines.append(f"**{name}**\n  Registration: {url}\n  Notes: {notes}\n")
        return "\n".join(lines)

    @mcp.tool()
    def list_registrations() -> str:
        """List all known Cannes event registration links."""
        data = _fetch_csv(REGISTRATION_SHEET_ID, REGISTRATION_GID)
        lines = []
        for e in data:
            vals = list(e.values())
            name = vals[0] if len(vals) > 0 else ""
            url = vals[1] if len(vals) > 1 else ""
            if name and "company or event" not in name.lower():
                lines.append(f"- **{name}**: {url}")
        return "\n".join(lines)

    return mcp.streamable_http_app()
