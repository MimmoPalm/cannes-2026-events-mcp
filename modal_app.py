"""Cannes Lions 2026 -- StreamableHTTP MCP server on Modal (v3: Supabase backend)."""

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
    import os
    from urllib.parse import quote

    import httpx
    from thefuzz import fuzz
    from mcp.server.fastmcp import FastMCP
    from mcp.server.streamable_http import TransportSecuritySettings

    # -- Supabase config from Modal secrets --
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

    HEADERS = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # -- Data loading via Supabase REST API --

    def _query(table: str, params: str = "") -> list[dict]:
        url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
        resp = httpx.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _load_events() -> list[dict]:
        return _query("events", "select=*&order=day,start_time")

    def _search_events(query: str, limit: int = 15) -> list[dict]:
        # Use Postgres full-text search (plainto_tsquery handles multi-word naturally)
        params = f"select=*&fts=plfts.{quote(query)}&limit={limit}"
        results = _query("events", params)
        if results:
            return results
        # Fallback: ILIKE search for partial/compound words the FTS tokenizer misses
        q = quote(query)
        params = f"select=*&or=(event_name.ilike.*{q}*,host.ilike.*{q}*,location.ilike.*{q}*,details.ilike.*{q}*,crawled_summary.ilike.*{q}*)&limit={limit}"
        return _query("events", params)

    # -- Formatting --

    def _format_event(e: dict) -> str:
        parts = [f"**{e.get('event_name', '')}**"]
        host = e.get("host", "")
        ctype = e.get("company_type", "")
        if host:
            parts.append(f"Host: {host}" + (f" ({ctype})" if ctype and ctype != "other" else ""))
        day = (e.get("day") or "").title()
        date = e.get("date") or ""
        start = e.get("start_time") or ""
        end = e.get("end_time") or ""
        time_str = f"{start}-{end}" if start and end else start or ""
        if day:
            parts.append(f"Day: {day} {date}" + (f" | {time_str}" if time_str else ""))
        loc = e.get("location") or ""
        if loc:
            parts.append(f"Location: {loc}")
        audience = e.get("target_audience") or ""
        if audience:
            parts.append(f"Audience: {audience}")
        etype = e.get("event_type") or ""
        if etype and etype != "other":
            parts.append(f"Type: {etype}")
        summary = e.get("crawled_summary") or ""
        if summary:
            parts.append(f"Summary: {summary}")
        reg = e.get("registration_url") or ""
        if reg:
            parts.append(f"Registration: {reg}")
        status = e.get("status") or ""
        if status and status != "confirmed":
            parts.append(f"Status: {status}")
        parts.append("---")
        return "\n".join(parts)

    # -- MCP server --

    mcp = FastMCP(
        "cannes-lions",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def search_schedule(query: str, limit: int = 15) -> str:
        """Search the Cannes Lions 2026 event schedule by keyword. Matches across event name, host, location, details, and crawled summary."""
        matches = _search_events(query, limit)
        if not matches:
            return f"No events matching '{query}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Found {len(matches)} events matching '{query}':\n\n{result}"

    @mcp.tool()
    def list_schedule_by_day(day: str) -> str:
        """List all Cannes events for a specific day (sunday/monday/tuesday/wednesday/thursday/friday). Returns events sorted by start time."""
        d = day.lower().strip()
        matches = _query("events", f"select=*&day=eq.{quote(d)}&order=start_time")
        if not matches:
            return f"No events found for '{day}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Events for {day.title()} ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def list_schedule_by_host(host: str) -> str:
        """Find all events hosted by a specific company at Cannes Lions 2026."""
        matches = _query("events", f"select=*&host=ilike.*{quote(host)}*&order=day,start_time")
        if not matches:
            return f"No events found hosted by '{host}'."
        result = "\n\n".join(_format_event(m) for m in matches)
        return f"Events hosted by {host} ({len(matches)} total):\n\n{result}"

    @mcp.tool()
    def recommend_events(role: str, day: str = "", limit: int = 20) -> str:
        """Recommend Cannes Lions 2026 events based on your role (publisher, brand, agency, adtech, creator, senior_leader). Optionally filter by day."""
        role_stem = role.lower().strip().rstrip("s")
        params = f"select=*&or=(target_audience.ilike.*{quote(role_stem)}*,target_audience.eq.everyone)&order=day,start_time&limit={limit}"
        if day:
            params += f"&day=eq.{quote(day.lower().strip())}"
        matches = _query("events", params)
        if not matches:
            return f"No events found for role '{role}'" + (f" on {day}" if day else "") + "."
        result = "\n\n".join(_format_event(m) for m in matches)
        header = f"Recommended events for {role}" + (f" on {day.title()}" if day else "")
        return f"{header} ({len(matches)} total, showing {len(matches)}):\n\n{result}"

    @mcp.tool()
    def filter_events(audience: str = "", company_type: str = "", event_type: str = "", day: str = "") -> str:
        """Filter Cannes Lions 2026 events by multiple criteria. All parameters are optional -- combine any."""
        params = "select=*"
        if day:
            params += f"&day=eq.{quote(day.lower().strip())}"
        if audience:
            params += f"&target_audience=ilike.*{quote(audience.lower().strip())}*"
        if company_type:
            params += f"&company_type=eq.{quote(company_type.lower().strip())}"
        if event_type:
            params += f"&event_type=eq.{quote(event_type.lower().strip())}"
        params += "&order=day,start_time"
        matches = _query("events", params)
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
            score = fuzz.token_set_ratio(event_name.lower(), (e.get("event_name") or "").lower())
            if score > best_score:
                best_score = score
                best_match = e
        if not best_match or best_score < 50:
            return f"No event found matching '{event_name}'."
        return _format_event(best_match)

    @mcp.tool()
    def find_registration(company: str) -> str:
        """Find registration info for a company at Cannes Lions 2026."""
        matches = _query("events", f"select=event_name,host,registration_url,registration_notes&host=ilike.*{quote(company)}*&registration_url=neq.&order=day,start_time")
        if not matches:
            return f"No registration info found for '{company}'."
        parts = [f"**Events with registration ({len(matches)}):**\n"]
        for e in matches:
            parts.append(f"- {e.get('event_name', '')}: {e.get('registration_url', '')}")
            if e.get("registration_notes"):
                parts.append(f"  Notes: {e.get('registration_notes')}")
        return "\n".join(parts)

    @mcp.tool()
    def list_registrations() -> str:
        """List all known Cannes Lions 2026 event registration links."""
        events = _query("events", "select=host,registration_url&registration_url=neq.&order=host")
        seen = set()
        lines = []
        for e in events:
            url = e.get("registration_url", "")
            host = e.get("host", "")
            if url and url not in seen:
                seen.add(url)
                lines.append(f"- **{host}**: {url}")
        if not lines:
            return "No registration links available."
        return f"Registration links ({len(lines)} total):\n\n" + "\n".join(lines)

    return mcp.streamable_http_app()
