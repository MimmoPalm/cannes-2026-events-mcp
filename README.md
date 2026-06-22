# Cannes Lions 2026 MCP

Add the full Cannes Lions 2026 event schedule to ChatGPT, Claude, or any MCP-compatible AI agent. 311 events, enriched with classifications, speaker details, registration links, crawled summaries, and venue coordinates with Google Maps links.

**MCP endpoint:** `https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp`

Built by [MIMMS](https://mimms.tech).

## What you can do

Ask your AI agent natural questions about Cannes Lions 2026:

- "What should a publisher do on Tuesday?"
- "Find all happy hours on Wednesday"
- "What's Equativ doing at Cannes?"
- "Who's speaking at the Adelaide event?"
- "Is anyone from Google speaking at Cannes?"
- "Show me all adtech networking events"
- "What panels are relevant for agencies this week?"
- "Get me the registration link for the Microsoft Beach House"
- "What invite-only events are happening on Thursday?"
- "Where is the Equativ party?"
- "How long to walk from the Google Beach to the Microsoft Beach House?"

## Setup

### ChatGPT

**Prerequisite:** ChatGPT Plus or Pro subscription. Developer Mode is a beta feature.

1. Copy the MCP endpoint URL above.
2. Open ChatGPT and go to **Settings → Apps → Advanced settings**.
3. Enable **Developer Mode**.
4. Click **Add connector** and paste the endpoint URL.
5. Complete the OAuth flow if prompted.
6. The connector's tools will appear in your available tools. Open a new chat to verify.

### Claude Desktop

**Option 1: Add through the UI (recommended)**

1. Open Claude Desktop.
2. Click the **+** button in the chat box.
3. Go to **Connectors → Manage Connectors**.
4. Paste the endpoint URL.
5. Complete authentication if prompted.

**Option 2: Configure manually**

1. Open Claude Desktop and go to **Settings → Developer → Edit Config**.
2. Add the server to your `claude_desktop_config.json` under `mcpServers` using `mcp-remote`:

```json
{
  "mcpServers": {
    "cannes-lions": {
      "command": "npx",
      "args": ["mcp-remote", "https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp"]
    }
  }
}
```

3. Restart Claude Desktop.

### Claude Code (CLI)

```bash
claude mcp add cannes-lions --transport http https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp
```

### Cursor / Windsurf

Add to your `.cursor/mcp.json` or project MCP settings:

```json
{ "cannes-lions": { "url": "https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp" } }
```

### Any MCP client

Point your client at the endpoint URL using StreamableHTTP transport. The server is stateless, no session persistence required.

## 11 tools

| Tool | What it does |
|---|---|
| `search_schedule` | Keyword search across event names, hosts, locations, details, and summaries |
| `list_schedule_by_day` | All events for a specific day (Sunday through Friday), sorted by time |
| `list_schedule_by_host` | Every event from a specific company |
| `recommend_events` | Personalized recommendations by role: publisher, brand, agency, adtech, senior leader |
| `filter_events` | Multi-criteria filter combining audience, company type, event type, and day |
| `search_speakers` | Find speakers by name or company, see who's speaking where |
| `get_event_details` | Full details for a specific event with fuzzy name matching |
| `find_registration` | Registration links and notes for a specific company |
| `list_registrations` | All known registration links across events |
| `get_event_location` | Venue location with Google Maps pin link for a specific event |
| `get_directions_between_events` | Walking distance, estimated time, and Google Maps directions link between two events |

## Architecture

The MCP server runs on [Modal](https://modal.com) as a stateless ASGI app with StreamableHTTP transport.

**Data backend:** [Supabase](https://supabase.com) (PostgreSQL). Events are stored in a single `events` table with a generated `tsvector` column and GIN index for full-text search. The server queries Supabase via the PostgREST API on each request -- no caching layer, no stale data.

**Search strategy:** `search_schedule` first tries PostgreSQL full-text search (`plainto_tsquery`). If that returns no results, it falls back to `ILIKE` pattern matching across five text columns. Other tools use PostgREST filtering (`eq`, `ilike`, ordering) for structured queries.

**Fuzzy matching:** `get_event_details` loads all events and uses `thefuzz` (token set ratio) to find the closest match by event name, with a minimum score threshold of 50.

**Secrets:** `SUPABASE_URL` and `SUPABASE_KEY` are stored in a Modal secret (`cannes-lions-config`) and injected at runtime.

## Data

264 events across 6 days (Sunday 22 June -- Friday 27 June) plus all-week venues.

Each event includes:
- **Event name, host, day, date, time, location**
- **Company type** -- adtech, publisher, agency, brand, platform, media, industry body
- **Event type** -- party, panel, breakfast, happy hour, networking, workshop, all-week venue, session
- **Target audience** -- publishers, brands, agencies, adtech, senior leaders, women in media
- **Registration URL** -- direct link extracted from the schedule sheet
- **Crawled summary** -- 2-3 sentence description from the event's registration page
- **Speakers** -- name, company, and title where available
- **Coordinates** -- latitude/longitude for venue locations (91% coverage), enabling distance calculations and Google Maps links

### How the data is enriched

An enrichment pipeline reads the source sheets via the Google Sheets API, extracts registration hyperlinks, crawls each event page for context, classifies events by company type, event type, and target audience, and writes everything to a clean master sheet. The enriched data is then migrated to Supabase for production queries.

## Credits

Huge thanks to the incredible team at [The Digital Voice](https://www.thedigitalvoice.co.uk/cannes) and **Emily Palmer** for putting together such a great curated list of Cannes Lions events. Registration links sourced and maintained by the community.

Enrichment and MCP server by [MIMMS](https://mimms.tech).