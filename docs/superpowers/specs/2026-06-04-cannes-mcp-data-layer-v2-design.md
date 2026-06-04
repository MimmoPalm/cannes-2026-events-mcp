# Cannes Lions 2026 MCP -- Data Layer v2

## Problem

The MCP server reads two community-maintained Google Sheets directly. The data is messy:

- Schedule sheet row 1 packs all "all week" venues into a single mega-row
- Day headers ("SUNDAY 21ST") are inline rows, not structured fields
- Times are inconsistent ("09:00-17:00" vs "09:00 - 1800" vs "All week" vs "TBC")
- Link column contains the text "HERE" -- actual URLs are cell hyperlinks, invisible in CSV export
- No company classification, no event type, no target audience
- Most events have empty or minimal Details
- Registration sheet has no join key to the schedule

The MCP tools return raw, unstructured text. An AI agent cannot answer "what should a publisher do on Tuesday?" without structured metadata.

## Solution

Create an enrichment pipeline that reads both source sheets, parses/normalizes/crawls/classifies, and writes clean structured data to a new MIMMS-owned Google Sheet. The MCP server reads only this master sheet and exposes 8 tools with richer query capabilities.

## Source Sheet IDs

- **Schedule**: `1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE` (GID `1111568312`)
- **Registrations**: `1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8` (GID `835495045`)
- **Master sheet**: created by the enrichment script on first run via `gws` CLI. Sheet ID stored in `config.json` after creation. Subsequent runs read the ID from config and overwrite.

## Architecture

```
Raw Sheet 1 (schedule) -----+
Raw Sheet 2 (registrations)-+
                             |
            Enrichment Script (Python, local/cron)
            +-- Google Sheets API: read cells + extract hyperlinks
            +-- httpx: crawl each event URL (parallel, rate-limited)
            +-- Claude API: summarize pages, classify, infer audience
            +-- Google Sheets API: write to master sheet
                             |
            MIMMS Master Sheet (new, Mimmo's Google account)
            +-- Tab 1: Events (~200 rows, 16 columns)
            +-- Tab 2: Registrations (unmatched, ~20-30 rows)
                             |
            MCP Server (Modal, FastMCP)
            +-- Reads master sheet via CSV export
            +-- 8 tools
```

## Master Sheet Schema

### Tab 1: Events

| Col | Field | Type | Source | Notes |
|-----|-------|------|--------|-------|
| A | event_name | string | Schedule col 0 | Cleaned, trimmed |
| B | host | string | Schedule col 1 | Normalized company name |
| C | day | string | Extracted from day headers | sunday / monday / tuesday / wednesday / thursday / friday |
| D | date | string | Derived from day | 2026-06-21 through 2026-06-26 |
| E | start_time | string | Parsed from col 2 | HH:MM format, or "all_day" |
| F | end_time | string | Parsed from col 2 | HH:MM format, or blank |
| G | location | string | Schedule col 3 | Cleaned |
| H | event_url | string | Sheets API hyperlink extraction | Actual URL behind "HERE" text |
| I | details | string | Schedule col 5 | Original sheet details, cleaned |
| J | crawled_summary | string | httpx + Claude API | 2-3 sentence summary from crawled event page |
| K | company_type | string | Claude API classification | adtech / publisher / agency / brand / platform / media / industry_body / other |
| L | event_type | string | Claude API classification | party / panel / breakfast / happy_hour / networking / workshop / all_week_venue / session / other |
| M | target_audience | string | Claude API inference | publishers / brands / agencies / adtech / everyone / senior_leaders / women_in_media / creators. Can be comma-separated for multiple. |
| N | registration_url | string | Fuzzy-matched from registrations sheet | |
| O | registration_notes | string | From registrations sheet | |
| P | status | string | Derived from data | confirmed / coming_soon / tbc |

### Tab 2: Unmatched Registrations

For companies with registration pages but no matching schedule events.

| Col | Field |
|-----|-------|
| A | company |
| B | registration_url |
| C | notes |
| D | crawled_summary |
| E | company_type |

## Enrichment Pipeline

Python script: `enrich.py` in the cannes-lions-mcp repo.

### Step 1: Read source sheets via Sheets API

- Use `gws sheets get` to read cell values from both sheets
- For hyperlink extraction: use `gws sheets get --format=hyperlink` if supported, otherwise fall back to the Google Sheets API v4 directly (`spreadsheets.get` with `fields=sheets.data.rowData.values.hyperlink`). The bot account token at `~/.config/gdrive_token.pickle` provides auth.
- Read registration sheet: cell values only (URLs are in plain text, not hyperlinks)
- Extract actual URLs from hyperlink metadata on the schedule sheet (solves the "HERE" problem)

### Step 2: Parse and normalize

- Split the mega first row: the Sheets API returns each column as a single cell with newline-delimited values. Split each column's cell by newlines, then zip across columns to create one row per venue. Verify row counts match across columns; if mismatched, log a warning and pad shorter columns with empty strings.
- Identify day-header rows ("SUNDAY 21ST", "MONDAY 22ND" etc.), assign `day` and `date` to all subsequent event rows until the next day header
- Parse time strings:
  - "09:00-17:00" or "09:00 - 17:00" -> start_time=09:00, end_time=17:00
  - "All week" -> start_time=all_day, end_time=blank
  - "Coming soon" / "TBC" -> start_time=blank, end_time=blank
  - Handle inconsistent separators (hyphen, en-dash, em-dash)
- Set `status`: if time/location contains "Coming soon" or "TBC", status=coming_soon/tbc, else confirmed
- Clean whitespace, normalize encoding

### Step 3: Crawl event pages

- For each event_url, fetch the page with httpx (timeout 15s, retry once on failure)
- Concurrency: max 10 total, max 2 per domain, 0.5s delay between requests to the same host
- Extract visible text content (strip HTML tags, collapse whitespace), truncate to ~3000 chars
- Cache crawled pages locally in `.cache/crawled/` (keyed by URL hash, 24h TTL). Re-runs skip cached URLs.
- Store raw crawled text for Step 4
- Skip URLs containing "Coming soon". Crawl Splashthat/Luma/Eventbrite pages (they often have event descriptions worth extracting).

### Step 4: Classify with Claude API

- Batch events into groups of ~20 for efficiency
- For each batch, send one Claude API call with structured output (tool_use response format)
- Model: claude-sonnet-4-6
- **Error handling**: retry failed batches up to 2 times with exponential backoff (2s, 8s). If a batch still fails after retries, write the events with empty classification fields (company_type="unknown", event_type="other", target_audience="everyone", crawled_summary="") and log a warning. Never block the full pipeline on a single batch failure. Partial writes to the master sheet are acceptable.
- **Prompt template**:

```
You are classifying Cannes Lions 2026 events. For each event, return JSON.

Allowed values:
- company_type: adtech | publisher | agency | brand | platform | media | industry_body | other
- event_type: party | panel | breakfast | happy_hour | networking | workshop | all_week_venue | session | other
- target_audience: comma-separated from: publishers, brands, agencies, adtech, everyone, senior_leaders, women_in_media, creators

Rules:
- Use ONLY the allowed values above. Do not invent new categories.
- target_audience can combine values: "publishers, adtech" is valid.
- crawled_summary: 2-3 sentences. If no crawled text available, summarize from event name and details only.

Events:
[array of {event_name, host, details, crawled_text}]

Return: [array of {company_type, event_type, target_audience, crawled_summary}]
```

- **Validation**: after parsing the response, check each field against the allowed enum values. If a field has an unexpected value, map to "other" / "everyone" as appropriate and log a warning.

### Step 5: Join registrations

- For each registration sheet entry, fuzzy-match company name against schedule hosts
- **Algorithm**: normalize both strings (lowercase, strip "@ Cannes", "at Cannes", leading/trailing whitespace), then use `thefuzz.fuzz.token_set_ratio`. Threshold: >= 80 is a match. Add a `match_confidence` field (not written to sheet, but logged) so ambiguous matches can be reviewed.
- Where matched: populate registration_url and registration_notes on the events row. If one registration matches multiple events (e.g. "Microsoft" matches 8 events), apply to all.
- Unmatched registration entries go to Tab 2

### Step 6: Write to master sheet

- Clear existing data in master sheet (both tabs)
- Write all rows with headers
- Write a `_metadata` tab with: last_updated timestamp, source sheet IDs, row counts, any warnings from the pipeline
- Log summary to stdout: X events written, Y registrations matched, Z unmatched, W classification failures

### Running the script

- Requires: `ANTHROPIC_API_KEY` env var, `gws` CLI authenticated
- Run: `python enrich.py`
- Flags: `--dry-run` (parse + normalize only, no crawl/classify/write -- for debugging), `--no-crawl` (skip crawling, use cache or empty), `--no-classify` (skip Claude API, leave classification fields empty)
- Can be re-run safely (overwrites master sheet each time)
- Schedule via cron during Cannes week if source sheets update frequently

## MCP Server Tools (8 total)

### Upgraded existing tools

**1. `search_schedule(query: str, limit: int = 15)`**
Keyword search across event_name, host, location, details, crawled_summary. Returns enriched results including company_type, target_audience, event_type. Capped at `limit` results.

**2. `list_schedule_by_day(day: str)`**
Filter by day. Returns all events for that day with full metadata, sorted by start_time.

**3. `list_schedule_by_host(host: str)`**
Find all events by a host company. Returns full metadata.

### New tools

**4. `recommend_events(role: str, day: str = "", limit: int = 20)`**
Given a role (publisher, brand, agency, adtech, creator, senior_leader), returns the most relevant events. Matching logic: normalize the role input, then check if any value in the event's `target_audience` field starts with the same stem (e.g. "publisher" matches "publishers"). Also includes events where target_audience is "everyone". Optionally filtered by day. Results sorted by day then start_time. Capped at `limit`. This powers queries like "What should a publisher do on Tuesday?"

**5. `filter_events(audience: str = "", company_type: str = "", event_type: str = "", day: str = "")`**
Multi-criteria filter. All parameters optional, combine any. Example: audience=publishers, event_type=happy_hour, day=wednesday returns publisher-relevant happy hours on Wednesday.

**6. `get_event_details(event_name: str)`**
Fuzzy-match on event name, return full details for one event: all fields including crawled_summary, registration_url, location, host info. For deep-dive queries.

**7. `find_registration(company: str)`**
Search for registration info by company. Checks both matched registrations on events (Tab 1) and unmatched registrations (Tab 2). Returns registration URL, notes, and any associated events.

### Kept as-is

**8. `list_registrations()`**
Dump all registration links (from both tabs).

### Dropped

- `search_registrations(company)` -- replaced by `find_registration` which is smarter.

## Output Format

All tools return markdown-formatted text. Each event in a list shows:

```
**Event Name**
Host: Company Name (adtech)
Day: Monday 22 June | 10:00-17:00
Location: 64 Bd de la Croisette, 06400 Cannes
Audience: publishers, brands
Type: all_week_venue
Summary: 2-3 sentence crawled summary here.
Registration: https://...
Status: confirmed
---
```

## Files

| File | Purpose |
|------|---------|
| `enrich.py` | Enrichment pipeline script |
| `modal_app.py` | Updated MCP server with 8 tools reading master sheet |
| `docs/superpowers/specs/2026-06-04-cannes-mcp-data-layer-v2-design.md` | This spec |

## Dependencies

- `httpx` -- HTTP client for crawling
- `anthropic` -- Claude API for classification
- `thefuzz` -- fuzzy string matching for registration join
- `gws` CLI -- Google Sheets read/write (already installed)
- `mcp` SDK -- MCP server (already in use)
- Google Sheets API v4 -- for hyperlink extraction (auth via bot account token at `~/.config/gdrive_token.pickle`)

## Notes

- Some event URLs point to generic company pages rather than specific event pages. The Claude prompt should instruct: "If the crawled text does not describe a specific Cannes event, note this in the summary."
- The enrichment script sets the master sheet to "anyone with the link can view" via the Google Drive API after creation. This allows the MCP server on Modal to fetch it via CSV export without auth.
