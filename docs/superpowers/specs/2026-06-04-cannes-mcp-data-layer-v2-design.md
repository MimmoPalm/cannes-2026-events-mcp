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

- Read schedule sheet: cell values + hyperlinks (using `gws` CLI or Google Sheets API directly)
- Read registration sheet: cell values
- Extract actual URLs from hyperlink metadata (solves the "HERE" problem)

### Step 2: Parse and normalize

- Split the mega first row: detect "all week" entries by time column, create one row per venue
- Identify day-header rows ("SUNDAY 21ST", "MONDAY 22ND" etc.), assign `day` and `date` to all subsequent event rows until the next day header
- Parse time strings:
  - "09:00-17:00" or "09:00 - 17:00" -> start_time=09:00, end_time=17:00
  - "All week" -> start_time=all_day, end_time=blank
  - "Coming soon" / "TBC" -> start_time=blank, end_time=blank
  - Handle inconsistent separators (hyphen, en-dash, em-dash)
- Set `status`: if time/location contains "Coming soon" or "TBC", status=coming_soon/tbc, else confirmed
- Clean whitespace, normalize encoding

### Step 3: Crawl event pages

- For each event_url, fetch the page with httpx (timeout 15s, retry once)
- Run up to 10 concurrent requests with rate limiting
- Extract visible text content (strip HTML), truncate to ~3000 chars
- Store raw crawled text for Step 4
- Skip URLs that are "Coming soon" or clearly RSVP-only forms (Splashthat, Luma etc. still worth crawling for event descriptions)

### Step 4: Classify with Claude API

- Batch events into groups of ~20 for efficiency
- For each batch, send one Claude API call with:
  - Event name, host, details, crawled page text
  - Ask for: company_type, event_type, target_audience, crawled_summary (2-3 sentences)
- Use structured output (JSON) for reliable parsing
- Model: claude-sonnet-4-6 (fast, cheap, good enough for classification)

### Step 5: Join registrations

- For each registration sheet entry, fuzzy-match company name against schedule hosts
- Use simple normalized string matching (lowercase, strip suffixes like "@ Cannes")
- Where matched: populate registration_url and registration_notes on the events row
- Unmatched registration entries go to Tab 2

### Step 6: Write to master sheet

- Clear existing data in master sheet (both tabs)
- Write all rows with headers
- Log summary: X events written, Y registrations matched, Z unmatched

### Running the script

- Requires: `ANTHROPIC_API_KEY` env var, `gws` CLI authenticated
- Run: `python enrich.py`
- Can be re-run safely (overwrites master sheet each time)
- Schedule via cron during Cannes week if source sheets update frequently

## MCP Server Tools (8 total)

### Upgraded existing tools

**1. `search_schedule(query: str)`**
Keyword search across event_name, host, location, details, crawled_summary. Returns enriched results including company_type, target_audience, event_type.

**2. `list_schedule_by_day(day: str)`**
Filter by day. Returns all events for that day with full metadata, sorted by start_time.

**3. `list_schedule_by_host(host: str)`**
Find all events by a host company. Returns full metadata.

### New tools

**4. `recommend_events(role: str, day: str = "")`**
Given a role (publisher, brand, agency, adtech, creator, senior_leader), returns the most relevant events. Filters where `target_audience` contains the role or is "everyone". Optionally filtered by day. Results sorted by day then start_time. This powers queries like "What should a publisher do on Tuesday?"

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
- `gws` CLI -- Google Sheets read/write (already installed)
- `mcp` SDK -- MCP server (already in use)

## Open questions

- The mega first row in the schedule sheet contains ~70 "all week" venues concatenated. Parsing this reliably may require iterating over the raw cell arrays rather than CSV. The Sheets API gives us clean per-cell access which solves this.
- Some event URLs point to generic company pages rather than specific event pages. The crawled_summary should note when a page lacks specific event details.
- Fuzzy matching for registration join may have false positives (e.g. "Adobe" matching "Adobe x Lions Creator Beach"). Accept close matches, flag ambiguous ones for manual review in the sheet.
