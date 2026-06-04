"""Classify events using Claude API."""

import json
import os
import time

COMPANY_TYPES = {"adtech", "publisher", "agency", "brand", "platform", "media", "industry_body", "other"}
EVENT_TYPES = {"party", "panel", "breakfast", "happy_hour", "networking", "workshop", "all_week_venue", "session", "other"}
AUDIENCE_VALUES = {"publishers", "brands", "agencies", "adtech", "everyone", "senior_leaders", "women_in_media", "creators"}

BATCH_SIZE = 20
MAX_RETRIES = 2
RETRY_DELAYS = [2, 8]  # seconds, per spec

PROMPT_TEMPLATE = """You are classifying Cannes Lions 2026 events. For each event, return JSON.

Allowed values:
- company_type: adtech | publisher | agency | brand | platform | media | industry_body | other
- event_type: party | panel | breakfast | happy_hour | networking | workshop | all_week_venue | session | other
- target_audience: comma-separated from: publishers, brands, agencies, adtech, everyone, senior_leaders, women_in_media, creators

Rules:
- Use ONLY the allowed values above. Do not invent new categories.
- target_audience can combine values: "publishers, adtech" is valid.
- crawled_summary: 2-3 sentences. If no crawled text available, summarize from event name and details only.
- If the crawled text does not describe a specific Cannes event, note this in the summary.

Events:
{events_json}

Return a JSON array of objects, one per event, in the same order:
[{{"company_type": "...", "event_type": "...", "target_audience": "...", "crawled_summary": "..."}}]
"""


def validate_classification(raw: dict) -> dict:
    """Validate and normalize a single classification result."""
    company_type = raw.get("company_type", "other")
    if company_type not in COMPANY_TYPES:
        company_type = "other"

    event_type = raw.get("event_type", "other")
    if event_type not in EVENT_TYPES:
        event_type = "other"

    target_audience = raw.get("target_audience", "everyone")
    if target_audience:
        parts = [p.strip() for p in target_audience.split(",")]
        valid_parts = [p for p in parts if p in AUDIENCE_VALUES]
        target_audience = ", ".join(valid_parts) if valid_parts else "everyone"

    return {
        "company_type": company_type,
        "event_type": event_type,
        "target_audience": target_audience,
        "crawled_summary": raw.get("crawled_summary", ""),
    }


def _default_classification() -> dict:
    return {
        "company_type": "other",
        "event_type": "other",
        "target_audience": "everyone",
        "crawled_summary": "",
    }


def classify_batch(events: list[dict]) -> list[dict]:
    """Classify a batch of events using Claude API."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set, returning defaults")
        return [_default_classification() for _ in events]

    client = anthropic.Anthropic(api_key=api_key)
    events_json = json.dumps(events, indent=2)
    prompt = PROMPT_TEMPLATE.format(events_json=events_json)

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON array found in response")
            results = json.loads(text[start:end])
            validated = []
            for r in results:
                validated.append(validate_classification(r))
            while len(validated) < len(events):
                validated.append(_default_classification())
            return validated[:len(events)]
        except Exception as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt]
                print(f"  Retry {attempt + 1}/{MAX_RETRIES} after error: {e} (waiting {delay}s)")
                time.sleep(delay)
            else:
                print(f"  Warning: classification failed after {MAX_RETRIES + 1} attempts: {e}")
                return [_default_classification() for _ in events]


def classify_events(events: list[dict]) -> list[dict]:
    """Classify all events in batches."""
    all_results = []
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i:i + BATCH_SIZE]
        print(f"  Classifying batch {i // BATCH_SIZE + 1} ({len(batch)} events)...")
        results = classify_batch(batch)
        all_results.extend(results)
    return all_results
