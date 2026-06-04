# Cannes Lions 2026 MCP Events  

MCP server that lets AI agents query Cannes Lions 2026 event schedules and registration links.

## Data Sources

1. **Event Schedule** — Full timetable curated by [The Digital Voice](https://www.thedigitalvoice.co.uk/cannes), including the A-Z of beaches, apartments, and week-long activations
2. **Registration Links** — Community-sourced sheet of event registration URLs

Both are published Google Sheets — no auth required.

## Tools

| Tool | Description |
|---|---|
| `search_schedule` | Search events by keyword (name, host, location, details) |
| `list_schedule_by_day` | Filter events by day (sunday/monday/tuesday/etc.) |
| `list_schedule_by_host` | Find all events from a specific company |
| `search_registrations` | Search registration links by company name |
| `list_registrations` | List all known registration links |

## Usage

Run directly via `uvx`:

```bash
uvx --from git+https://github.com/MimmoPalm/cannes-lions-mcp.git cannes-lions-mcp
```

Or add to your MCP client config:

```json
{
  "mcpServers": {
    "cannes-lions": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/MimmoPalm/cannes-lions-mcp.git", "cannes-lions-mcp"]
    }
  }
}
```

Hermes Agent `config.yaml`:

```yaml
mcp_servers:
  cannes-lions:
    command: "uvx"
    args: ["--from", "git+https://github.com/MimmoPalm/cannes-lions-mcp.git", "cannes-lions-mcp"]
```

## Example Queries

- "What events is Equativ hosting at Cannes?"
- "Find all Monday sessions"
- "Where is the Microsoft Beach House?"
- "Show me the TikTok registration link"
