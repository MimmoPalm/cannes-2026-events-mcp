"""One-time geocoding of Cannes event locations via Nominatim (OpenStreetMap).

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python geocode_events.py
"""

import os
import time
from urllib.parse import quote

import httpx

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "cannes-mcp-geocoder/1.0 (mimmo@mimms.tech)"}

SKIP_PATTERNS = [
    "coming soon", "tbc", "tbd", "tba", "n/a", "online", "virtual",
]

# Cannes center for sanity check
CANNES_LAT, CANNES_LNG = 43.5528, 7.0174


def geocode(location: str) -> tuple[float, float] | None:
    """Geocode a location string using Nominatim, biased toward Cannes."""
    # Try with ", Cannes, France" suffix first
    for query in [f"{location}, Cannes, France", location]:
        resp = httpx.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
            # Sanity: must be within ~15km of Cannes center
            if abs(lat - CANNES_LAT) < 0.15 and abs(lng - CANNES_LNG) < 0.15:
                return lat, lng
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec
    return None


def main():
    # Fetch distinct locations
    url = f"{SUPABASE_URL}/rest/v1/events?select=location&location=not.is.null&location=neq."
    resp = httpx.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    all_events = resp.json()

    locations = sorted(set(
        e["location"].strip() for e in all_events
        if e.get("location", "").strip()
    ))
    print(f"Found {len(locations)} distinct locations\n")

    geocoded = 0
    skipped = 0
    failed = 0
    failed_list = []

    for loc in locations:
        if any(p in loc.lower() for p in SKIP_PATTERNS) or len(loc) < 5:
            print(f"  SKIP: {loc}")
            skipped += 1
            continue

        coords = geocode(loc)
        if not coords:
            print(f"  FAIL: {loc}")
            failed += 1
            failed_list.append(loc)
            continue

        lat, lng = coords
        print(f"  OK:   {loc[:70]:70s} -> {lat:.6f}, {lng:.6f}")

        patch_url = f"{SUPABASE_URL}/rest/v1/events?location=eq.{quote(loc)}"
        patch_resp = httpx.patch(
            patch_url,
            json={"latitude": lat, "longitude": lng},
            headers=HEADERS,
            timeout=10,
        )
        patch_resp.raise_for_status()
        geocoded += 1

    print(f"\nDone: {geocoded} geocoded, {skipped} skipped, {failed} failed")
    if failed_list:
        print(f"\nFailed locations:")
        for f in failed_list:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
