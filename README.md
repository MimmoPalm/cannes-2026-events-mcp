# Cannes Lions 2026 MCP Events  

MCP server that lets AI agents query the Cannes Lions 2026 event schedule and registration links.

Built by [MIMMS](https://mimms.tech).

## Credits

The underlying data is curated and maintained by two incredible community efforts:

- **Event schedule** — [The Digital Voice](https://www.thedigitalvoice.co.uk/cannes) and **Emily Palmer**, who built and maintain the A-Z of Cannes beaches, apartments, and week-long activations
- **Registration links** — a community-sourced sheet of event registration URLs, kept current by contributors across the industry

Both sheets are published to web (no auth required). This MCP server simply wraps them for AI agent access.

## Data Sources

| Sheet | Source | Curation |
|---|---|---|
| [Full Schedule](https://docs.google.com/spreadsheets/d/1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE) | The Digital Voice x Emily Palmer | Events, times, locations, hosts, details |
| [Registration Links](https://docs.google.com/spreadsheets/d/1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8) | Community-sourced | Company name + registration URL |

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
