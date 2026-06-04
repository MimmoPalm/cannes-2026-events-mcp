"""Fuzzy-match registrations to schedule events."""

import re

from thefuzz import fuzz

from enrich.parser import Event

MATCH_THRESHOLD = 80


def normalize_name(name: str) -> str:
    """Normalize a company name for matching."""
    s = name.strip().lower()
    s = re.sub(r"\s*@\s*cannes\s*(lions)?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+at\s+cannes\s*(lions)?\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def match_registrations(
    events: list[Event],
    registrations: list[dict],
) -> list[dict]:
    """Match registration entries to events by fuzzy company name matching.

    Modifies events in-place (sets registration_url and registration_notes).
    Logs match confidence for each match per spec.

    Returns:
        List of unmatched registration dicts.
    """
    unmatched = []

    for reg in registrations:
        company = reg.get("company", "")
        url = reg.get("url", "")
        notes = reg.get("notes", "")

        if not company:
            continue

        norm_company = normalize_name(company)
        matched_any = False

        for event in events:
            norm_host = normalize_name(event.host)
            score = fuzz.token_set_ratio(norm_company, norm_host)

            if score >= MATCH_THRESHOLD:
                event.registration_url = url
                event.registration_notes = notes
                matched_any = True
                print(f"    Matched '{company}' -> '{event.host}' (confidence: {score})")

        if not matched_any:
            unmatched.append(reg)

    return unmatched
