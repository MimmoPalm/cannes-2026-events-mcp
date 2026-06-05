# Cannes Lions 2026 MCP

Add the full Cannes Lions 2026 event schedule to ChatGPT, Claude, or any MCP-compatible AI agent. 259 events, enriched with classifications, speaker details, registration links, and crawled summaries.

**MCP endpoint:** `https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp`

Built by [MIMMS](https://mimms.tech).

## What you can do

Ask your AI agent natural questions about Cannes Lions 2026:

- "What should a publisher do on Tuesday?"
- "Find all happy hours on Wednesday"
- "What's Equativ doing at Cannes?"
- "Who's speaking at the Adelaide event?"
- "Show me all adtech networking events"
- "What panels are relevant for agencies this week?"
- "Get me the registration link for the Microsoft Beach House"
- "What invite-only events are happening on Thursday?"

## Setup

### ChatGPT
Settings > Tools & integrations > Add MCP tool > paste the endpoint URL.

### Claude Desktop
Settings > MCP Servers > Add remote server > paste the endpoint URL.

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

## 8 tools

| Tool | What it does |
|---|---|
| `search_schedule` | Keyword search across event names, hosts, locations, details, and summaries |
| `list_schedule_by_day` | All events for a specific day (Sunday through Friday), sorted by time |
| `list_schedule_by_host` | Every event from a specific company |
| `recommend_events` | Personalized recommendations by role: publisher, brand, agency, adtech, senior leader |
| `filter_events` | Multi-criteria filter combining audience, company type, event type, and day |
| `get_event_details` | Full details for a specific event with fuzzy name matching |
| `find_registration` | Registration links and notes for a specific company |
| `list_registrations` | All known registration links across events and unmatched entries |

## Data

259 events across 6 days (Sunday 21 June -- Friday 26 June) plus 61 all-week venues.

Each event includes:
- **Event name, host, day, date, time, location**
- **Company type** -- adtech, publisher, agency, brand, platform, media, industry body
- **Event type** -- party, panel, breakfast, happy hour, networking, workshop, all-week venue, session
- **Target audience** -- publishers, brands, agencies, adtech, senior leaders, women in media
- **Registration URL** -- direct link extracted from the schedule sheet
- **Crawled summary** -- 2-3 sentence description from the event's registration page
- **Speakers** -- name, company, and title where available

### How the data is enriched

The raw schedule is maintained by The Digital Voice and Emily Palmer. An enrichment pipeline reads the source sheets via the Google Sheets API, extracts registration hyperlinks, crawls each event page for context, classifies events by company type, event type, and target audience, and writes everything to a clean master sheet. The MCP server reads the master sheet live on each request.

## Credits

- **Event schedule** -- [The Digital Voice](https://www.thedigitalvoice.co.uk/cannes) and **Emily Palmer**
- **Registration links** -- community-sourced, maintained by Emily Palmer and contributors across the industry
- **Enrichment and MCP server** -- [MIMMS](https://mimms.tech)
