# Location & Directions Tools for Cannes MCP

**Date:** 2026-06-12
**Status:** Approved

## Problem

Users ask "where is this event?" and "how long from event A to event B?" but the MCP has no location intelligence. The `location` column contains raw venue names/addresses with no coordinates.

## Solution

Hybrid approach: pre-geocode venues, store lat/lng on the `events` table, calculate walking times locally, and return Google Maps links for exact routing.

## Schema Change

Add two nullable columns to `events` table in `cannes-mcp` Supabase project (`iodptxzzztiqyxyoyuaq`):

```sql
ALTER TABLE public.events ADD COLUMN latitude DOUBLE PRECISION;
ALTER TABLE public.events ADD COLUMN longitude DOUBLE PRECISION;
```

## Geocoding (One-Time Enrichment)

Python script (`geocode_events.py`) that:

1. Queries all distinct `location` values from Supabase (144 distinct locations)
2. Geocodes each using Google Geocoding API with bias toward Cannes, France
3. Skips un-geocodable values ("coming soon", "TBC", empty strings)
4. Updates all matching rows with lat/lng
5. Requires `GOOGLE_MAPS_API_KEY` env var (one-time use, well under free tier)

## New MCP Tools

### `get_event_location(event_name: str) -> str`

- Fuzzy-matches event name using existing `thefuzz` pattern (token_set_ratio, threshold 50)
- Returns: event name, venue/location string, lat/lng, Google Maps pin link
- If no coordinates: returns raw location string with note "Location not geocoded"
- Google Maps link format: `https://www.google.com/maps?q={lat},{lng}`

### `get_directions_between_events(from_event: str, to_event: str) -> str`

- Fuzzy-matches both event names
- Calculates estimated walking time: Haversine distance x 1.3 (street routing factor) / 5 km/h
- Returns: both locations, straight-line distance (m), estimated walk time (min), Google Maps directions link with walking mode
- Google Maps directions format: `https://www.google.com/maps/dir/{lat1},{lng1}/{lat2},{lng2}/@{lat1},{lng1},15z/data=!4m2!4m1!3e2`
- Edge cases: if either event lacks coordinates, return error with raw location strings

## Files Changed

### `cannes-2026-events-mcp` repo
- `modal_app.py` -- add two new tool functions inside `web()`
- `geocode_events.py` (new) -- one-time geocoding script
- `README.md` -- update tool table from 8 to 10

### `mimms-tech` repo
- `app/cannes/page.tsx` (new) -- recreate the /cannes landing page (currently live but not in repo)
- Update tool table from 8 to 10, add example queries for location tools

## Testing

- Verify geocoding script populates lat/lng for majority of venues
- Test `get_event_location` with exact, fuzzy, and non-existent event names
- Test `get_directions_between_events` with two known events, verify walk time is reasonable (Cannes Croisette is ~3km end to end, ~35 min walk)
- Test edge cases: events with no coordinates, same location for both events
- Verify existing 8 tools still work after deployment
- Test the /cannes page renders correctly and lists 10 tools

## No Ongoing Costs

- Geocoding is one-time (Google Geocoding API, ~144 requests)
- MCP tools do math locally (Haversine) and build Google Maps URLs
- No API calls at runtime for directions
