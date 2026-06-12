# Location & Directions Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two MCP tools (`get_event_location`, `get_directions_between_events`) that let users query event locations and walking times between events, backed by pre-geocoded coordinates stored on the `events` table.

**Architecture:** Add `latitude`/`longitude` columns to Supabase `events` table, run a one-time geocoding script to populate them, add two new tools to `modal_app.py` that use Haversine math + Google Maps URL generation. Update the mimms.tech/cannes page and GitHub README to reflect 10 tools.

**Tech Stack:** Python 3.12, FastMCP, Supabase (PostgREST), httpx, thefuzz, math (Haversine), Google Geocoding API (one-time), Next.js/Tailwind (mimms.tech page)

---

## Chunk 1: Schema + Geocoding + MCP Tools

### Task 1: Add latitude/longitude columns to Supabase

**Files:** None (Supabase migration)

- [ ] **Step 1: Apply migration**

Run via Supabase MCP `apply_migration`:

```sql
ALTER TABLE public.events ADD COLUMN latitude DOUBLE PRECISION;
ALTER TABLE public.events ADD COLUMN longitude DOUBLE PRECISION;
```

- [ ] **Step 2: Verify columns exist**

Run via Supabase MCP `execute_sql`:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'events' AND column_name IN ('latitude', 'longitude');
```

Expected: two rows, both `double precision`.

---

### Task 2: Create geocoding script

**Files:**
- Create: `geocode_events.py`

- [ ] **Step 1: Write the geocoding script**

```python
"""One-time geocoding of Cannes event locations via Google Geocoding API.

Usage:
    GOOGLE_MAPS_API_KEY=... SUPABASE_URL=... SUPABASE_KEY=... python geocode_events.py
"""

import os
import sys
import time

import httpx

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GOOGLE_MAPS_API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

SKIP_PATTERNS = [
    "coming soon", "tbc", "tbd", "tba", "n/a", "online", "virtual",
]

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode(location: str) -> tuple[float, float] | None:
    """Geocode a location string, biased toward Cannes, France."""
    params = {
        "address": f"{location}, Cannes, France",
        "key": GOOGLE_MAPS_API_KEY,
        "bounds": "43.53,6.93|43.57,7.05",  # Cannes bounding box
    }
    resp = httpx.get(GEOCODE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["status"] == "OK" and data["results"]:
        loc = data["results"][0]["geometry"]["location"]
        lat, lng = loc["lat"], loc["lng"]
        # Sanity check: must be within ~15km of Cannes center (43.5528, 7.0174)
        if abs(lat - 43.55) > 0.15 or abs(lng - 7.02) > 0.15:
            print(f"  SKIP (outside Cannes): {location} -> {lat}, {lng}")
            return None
        return lat, lng
    return None


def main():
    # Fetch distinct locations
    url = f"{SUPABASE_URL}/rest/v1/events?select=location&location=not.is.null&location=not.eq."
    resp = httpx.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    all_events = resp.json()

    locations = sorted(set(e["location"].strip() for e in all_events if e.get("location", "").strip()))
    print(f"Found {len(locations)} distinct locations")

    geocoded = 0
    skipped = 0
    failed = 0

    for loc in locations:
        if any(p in loc.lower() for p in SKIP_PATTERNS) or len(loc) < 5:
            print(f"  SKIP (pattern): {loc}")
            skipped += 1
            continue

        coords = geocode(loc)
        if not coords:
            print(f"  FAIL: {loc}")
            failed += 1
            continue

        lat, lng = coords
        print(f"  OK: {loc} -> {lat}, {lng}")

        # Update all events with this exact location
        from urllib.parse import quote
        patch_url = f"{SUPABASE_URL}/rest/v1/events?location=eq.{quote(loc)}"
        patch_resp = httpx.patch(
            patch_url,
            json={"latitude": lat, "longitude": lng},
            headers=HEADERS,
            timeout=10,
        )
        patch_resp.raise_for_status()
        geocoded += 1

        time.sleep(0.1)  # Rate limit courtesy

    print(f"\nDone: {geocoded} geocoded, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the geocoding script**

You need a Google Maps API key with Geocoding API enabled. Run:

```bash
cd /tmp/cannes-2026-events-mcp
GOOGLE_MAPS_API_KEY="..." \
SUPABASE_URL="<from Modal secret cannes-lions-config>" \
SUPABASE_KEY="<from Modal secret cannes-lions-config>" \
python geocode_events.py
```

Expected: majority of locations geocoded successfully, a few skipped/failed.

- [ ] **Step 3: Verify geocoded data in Supabase**

Run via Supabase MCP `execute_sql`:

```sql
SELECT
  COUNT(*) as total,
  COUNT(latitude) as geocoded,
  COUNT(*) - COUNT(latitude) as missing
FROM public.events
WHERE location IS NOT NULL AND location != '';
```

Expected: geocoded count is high (120+), missing is low.

- [ ] **Step 4: Commit**

```bash
cd /tmp/cannes-2026-events-mcp
git add geocode_events.py
git commit -m "feat: add one-time geocoding script for event locations"
```

---

### Task 3: Add get_event_location tool to modal_app.py

**Files:**
- Modify: `modal_app.py` (inside the `web()` function, after the `list_registrations` tool at line ~215)

- [ ] **Step 1: Add the get_event_location tool**

Add this tool function inside `web()`, after `list_registrations`:

```python
@mcp.tool()
def get_event_location(event_name: str) -> str:
    """Get the location of a Cannes Lions 2026 event with a Google Maps link. Uses fuzzy matching on event name."""
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
    name = best_match.get("event_name", "")
    location = best_match.get("location") or "No location listed"
    lat = best_match.get("latitude")
    lng = best_match.get("longitude")
    parts = [f"**{name}**", f"Location: {location}"]
    if lat and lng:
        parts.append(f"Coordinates: {lat}, {lng}")
        parts.append(f"Google Maps: https://www.google.com/maps?q={lat},{lng}")
    else:
        parts.append("Note: exact coordinates not available for this venue")
    day = (best_match.get("day") or "").title()
    start = best_match.get("start_time") or ""
    end = best_match.get("end_time") or ""
    if day:
        time_str = f" | {start}-{end}" if start else ""
        parts.append(f"When: {day}{time_str}")
    return "\n".join(parts)
```

- [ ] **Step 2: Verify existing tools still listed**

Check that all 8 existing `@mcp.tool()` decorators are still present in the file. The new tool should appear after `list_registrations`.

- [ ] **Step 3: Commit**

```bash
cd /tmp/cannes-2026-events-mcp
git add modal_app.py
git commit -m "feat: add get_event_location MCP tool"
```

---

### Task 4: Add get_directions_between_events tool to modal_app.py

**Files:**
- Modify: `modal_app.py` (inside `web()`, after `get_event_location`)

- [ ] **Step 1: Add the Haversine helper and directions tool**

Add this code inside `web()`, right after `get_event_location`:

```python
import math

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in metres between two lat/lng points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _fuzzy_find(events: list[dict], name: str) -> dict | None:
    """Find best fuzzy match for an event name. Returns None if score < 50."""
    best, best_score = None, 0
    for e in events:
        score = fuzz.token_set_ratio(name.lower(), (e.get("event_name") or "").lower())
        if score > best_score:
            best_score = score
            best = e
    return best if best_score >= 50 else None

@mcp.tool()
def get_directions_between_events(from_event: str, to_event: str) -> str:
    """Get walking distance and estimated time between two Cannes Lions 2026 events, with a Google Maps directions link."""
    events = _load_events()
    if not events:
        return "No events data available."
    ev_from = _fuzzy_find(events, from_event)
    ev_to = _fuzzy_find(events, to_event)
    if not ev_from:
        return f"No event found matching '{from_event}'."
    if not ev_to:
        return f"No event found matching '{to_event}'."
    name_from = ev_from.get("event_name", "")
    name_to = ev_to.get("event_name", "")
    loc_from = ev_from.get("location") or "unknown"
    loc_to = ev_to.get("location") or "unknown"
    lat1, lng1 = ev_from.get("latitude"), ev_from.get("longitude")
    lat2, lng2 = ev_to.get("latitude"), ev_to.get("longitude")
    parts = [
        f"**From:** {name_from}",
        f"Location: {loc_from}",
        f"**To:** {name_to}",
        f"Location: {loc_to}",
    ]
    if lat1 and lng1 and lat2 and lng2:
        distance_m = _haversine(lat1, lng1, lat2, lng2)
        walk_distance = distance_m * 1.3  # Street routing factor
        walk_minutes = walk_distance / (5000 / 60)  # 5 km/h walking speed
        parts.append(f"Straight-line distance: {distance_m:.0f}m")
        parts.append(f"Estimated walking distance: {walk_distance:.0f}m")
        parts.append(f"Estimated walking time: {walk_minutes:.0f} minutes")
        parts.append(f"Google Maps directions: https://www.google.com/maps/dir/{lat1},{lng1}/{lat2},{lng2}/@{lat1},{lng1},15z/data=!4m2!4m1!3e2")
    else:
        missing = []
        if not (lat1 and lng1):
            missing.append(f"'{name_from}' ({loc_from})")
        if not (lat2 and lng2):
            missing.append(f"'{name_to}' ({loc_to})")
        parts.append(f"Cannot calculate distance: coordinates not available for {', '.join(missing)}")
    return "\n".join(parts)
```

- [ ] **Step 2: Move the `import math` to the top of `web()`**

The `import math` should go at the top of the `web()` function alongside the other imports (line ~23 area, after `from thefuzz import fuzz`). Do NOT leave it inline with the tool.

- [ ] **Step 3: Refactor get_event_location to use _fuzzy_find**

Now that `_fuzzy_find` exists, update `get_event_location` to use it:

Replace the manual fuzzy matching block in `get_event_location` with:

```python
best_match = _fuzzy_find(events, event_name)
if not best_match:
    return f"No event found matching '{event_name}'."
```

- [ ] **Step 4: Commit**

```bash
cd /tmp/cannes-2026-events-mcp
git add modal_app.py
git commit -m "feat: add get_directions_between_events MCP tool with Haversine"
```

---

### Task 5: Deploy to Modal and test all 10 tools

**Files:** None (deployment + testing)

- [ ] **Step 1: Deploy to Modal**

```bash
cd /tmp/cannes-2026-events-mcp
modal deploy modal_app.py
```

Expected: successful deployment, endpoint at `https://mimmopalm--cannes-lions-mcp-web.modal.run/mcp`

- [ ] **Step 2: Test get_event_location via the Cannes MCP**

Use the `mcp__claude_ai_Cannes_MCP__get_event_details` tool (or equivalent) to verify the MCP is responding. Then test the new location tool.

Test cases:
1. Exact name: an event with a known address
2. Fuzzy name: partial event name
3. Non-existent event: should return "No event found"
4. Event with no coordinates: should return "coordinates not available"

- [ ] **Step 3: Test get_directions_between_events**

Test cases:
1. Two events with coordinates: should return distance, walk time, Google Maps link
2. One event without coordinates: should return error mentioning which event lacks coordinates
3. Same event for both: should return 0m, 0 minutes
4. Events at opposite ends of Croisette: walk time should be ~25-40 minutes

- [ ] **Step 4: Regression test existing tools**

Run each existing tool to verify nothing broke:
1. `search_schedule` with query "Microsoft"
2. `list_schedule_by_day` with day "tuesday"
3. `list_schedule_by_host` with host "Google"
4. `recommend_events` with role "publisher"
5. `filter_events` with event_type "party"
6. `get_event_details` with a known event name
7. `find_registration` with a known company
8. `list_registrations`

---

## Chunk 2: README + mimms.tech Page

### Task 6: Update GitHub README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the tool table in README.md**

In the "8 tools" section (line 67-79), change heading to "10 tools" and add two rows:

```markdown
## 10 tools

| Tool | What it does |
|---|---|
| `search_schedule` | Keyword search across event names, hosts, locations, details, and summaries |
| `list_schedule_by_day` | All events for a specific day (Sunday through Friday), sorted by time |
| `list_schedule_by_host` | Every event from a specific company |
| `recommend_events` | Personalized recommendations by role: publisher, brand, agency, adtech, senior leader |
| `filter_events` | Multi-criteria filter combining audience, company type, event type, and day |
| `get_event_details` | Full details for a specific event with fuzzy name matching |
| `find_registration` | Registration links and notes for a specific company |
| `list_registrations` | All known registration links across events |
| `get_event_location` | Venue location with Google Maps pin link for a specific event |
| `get_directions_between_events` | Walking distance, estimated time, and Google Maps directions between two events |
```

- [ ] **Step 2: Add location data note to the Data section**

After line 103 (the "Speakers" bullet), add:

```markdown
- **Coordinates** -- latitude/longitude for venue locations, enabling distance calculations and map links
```

- [ ] **Step 3: Add example queries for new tools to the "What you can do" section**

After line 19 (the last example query), add:

```markdown
- "Where is the Equativ party?"
- "How long to walk from the Google Beach to the TikTok event?"
```

- [ ] **Step 4: Commit**

```bash
cd /tmp/cannes-2026-events-mcp
git add README.md
git commit -m "docs: update README with location and directions tools"
```

- [ ] **Step 5: Push to GitHub**

```bash
cd /tmp/cannes-2026-events-mcp
git push origin main
```

---

### Task 7: Recreate and update mimms.tech/cannes page

**Files:**
- Create: `~/mimms-tech/app/cannes/page.tsx`

This page currently exists on Vercel but is NOT in the repo. Recreate it following the existing mimms-tech patterns (Navigation, Footer, ContactCTA components, Tailwind theme with `background`, `text-primary`, `text-secondary`, `accent` colors, `font-serif` for headings, `font-sans` for body).

- [ ] **Step 1: Create `app/cannes/page.tsx`**

Build the page with these sections (matching the live page structure captured earlier):
1. Metadata (title, description, OG)
2. Navigation
3. Hero section: "MCP Tool" label + "Cannes Lions 2026" heading + intro copy
4. MCP Endpoint with copy button
5. "What You Can Ask" -- 10 example queries (add 2 location queries)
6. Setup instructions (ChatGPT, Claude Desktop, Claude Code, Cursor/Windsurf, Any MCP client)
7. **10 Tools** table (updated from 8)
8. Pro Tip section
9. Credits
10. ContactCTA + Footer

The page must use the site's existing design system:
- `font-serif` for section headings
- `text-label` uppercase for labels
- `max-w-container` for content width
- `bg-background` page background
- `border` color for dividers
- `accent` color for highlights

- [ ] **Step 2: Test locally**

```bash
cd ~/mimms-tech
npm run dev
```

Open `http://localhost:3000/cannes` and verify:
- Page renders without errors
- All 10 tools listed in the table
- New example queries appear
- Copy button works for MCP endpoint
- Navigation and footer match other pages
- Mobile responsive

- [ ] **Step 3: Commit**

```bash
cd ~/mimms-tech
git add app/cannes/page.tsx
git commit -m "feat: add /cannes page with 10 MCP tools"
```

- [ ] **Step 4: Push to deploy**

```bash
cd ~/mimms-tech
git push origin main
```

Vercel will auto-deploy. Verify at `https://mimms.tech/cannes` that the page is live and matches.

---

## Summary

| Task | What | Repo |
|------|------|------|
| 1 | Add lat/lng columns to Supabase | cannes-mcp (Supabase) |
| 2 | Geocode all event locations | cannes-2026-events-mcp |
| 3 | Add `get_event_location` tool | cannes-2026-events-mcp |
| 4 | Add `get_directions_between_events` tool | cannes-2026-events-mcp |
| 5 | Deploy to Modal + test all 10 tools | cannes-2026-events-mcp |
| 6 | Update README on GitHub | cannes-2026-events-mcp |
| 7 | Recreate /cannes page with 10 tools | mimms-tech |

**Dependencies:** Task 1 before 2, Task 2 before 3-4, Tasks 3-4 before 5, Task 5 before 6-7. Tasks 6 and 7 are independent of each other.
