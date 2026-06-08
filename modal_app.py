"""Cannes Lions 2026 -- StreamableHTTP MCP server on Modal (v3: explicit schemas + cache)."""

from __future__ import annotations

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
    import time

    import httpx
    from thefuzz import fuzz
    from mcp.server.fastmcp import FastMCP
    from mcp.server.streamable_http import TransportSecuritySettings

    # ── Master sheet config from Modal secrets ─────────────────────────
    MASTER_SHEET_ID = os.environ.get("MASTER_SHEET_ID", "")
    EVENTS_GID = os.environ.get("EVENTS_GID", "0")
    UNREG_GID = os.environ.get("UNREG_GID", "")
    CSV_TEMPLATE = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"

    # ── TTL cache (5 min) to avoid hammering Google Sheets ─────────────
    _cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
    CACHE_TTL = 300  # seconds

    def _fetch_csv(sheet_id: str, gid: str) -> list[dict[str, str]]:
        cache_key = f"{sheet_id}:{gid}"
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now - cached[0]) < CACHE_TTL:
            return cached[1]

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
        _cache[cache_key] = (now, data)
        return data

    def _load_events() -> list[dict[str, str]]:
        if not MASTER_SHEET_ID:
            return []
        return _fetch_csv(MASTER_SHEET_ID, EVENTS_GID)

    def _load_unmatched_regs() -> list[dict[str, str]]:
        if not MASTER_SHEET_ID or not UNREG_GID:
            return []
        return _fetch_csv(MASTER_SHEET_ID, UNREG_GID)

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

    mcp = FastMCP(
        "cannes-lions",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def search_schedule(query: str, limit: int = 15) -> str:
        """Search the Cannes Lions 2026 event schedule by keyword. Matches across event_name, host, location, details, crawled_summary.

        Args:
            query: Search term, e.g. 'Microsoft', 'Tennis', 'AI', 'happy hour', 'retail media'
            limit: Max results to return (default 15)
        """
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
        """List all Cannes events for a specific day. Returns events sorted by start time.

        Args:
            day: Day of the week. One of: 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday'
        """
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
        """Find all events hosted by a specific company at Cannes Lions 2026.

        Args:
            host: Company name, e.g. 'Microsoft', 'TikTok', 'Equativ', 'Financial Times'
        """
        events = _load_events()
        h = host.lower()
        matches = [e for e in events if h in e.get("host", "").lower()]
        if not matches:
            return f"No events found hosted by '{host}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Events hosted by {host} ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def recommend_events(role: str, day: str = "", limit: int = 20) -> str:
        """Recommend Cannes Lions 2026 events based on your role. Optionally filter by day.

        Args:
            role: Your industry role. One of: 'publisher', 'brand', 'agency', 'adtech', 'creator', 'senior_leader'
            day: Optional day filter. One of: 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday'
            limit: Max results to return (default 20)
        """
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
        """Filter Cannes Lions 2026 events by multiple criteria. All parameters are optional -- combine any.

        Args:
            audience: Target audience. One of: 'publishers', 'brands', 'agencies', 'senior_leaders', 'women_in_media', 'everyone'
            company_type: Host company type. One of: 'adtech', 'publisher', 'agency', 'brand', 'platform', 'media', 'industry_body'
            event_type: Event format. One of: 'party', 'panel', 'breakfast', 'happy_hour', 'networking', 'workshop', 'session', 'all_week_venue'
            day: Day of the week. One of: 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday'
        """
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
        """Get full details for a specific Cannes Lions 2026 event. Uses fuzzy matching on event name.

        Args:
            event_name: Event name or partial name to look up, e.g. 'Microsoft Beach House', 'Diaspora Dinner'
        """
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
        """Find registration info for a company at Cannes Lions 2026. Searches both matched events and unmatched registrations.

        Args:
            company: Company or host name, e.g. 'Microsoft', 'Seedtag', 'Adobe'
        """
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
