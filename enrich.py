#!/usr/bin/env python3
"""Cannes Lions 2026 enrichment pipeline.

Usage:
    python enrich.py                # Full run
    python enrich.py --dry-run      # Parse + normalize only
    python enrich.py --no-crawl     # Skip crawling
    python enrich.py --no-classify  # Skip Claude API classification
"""

import argparse

from enrich.sheets_reader import read_schedule_rows, read_registration_csv, extract_hyperlinks
from enrich.parser import parse_schedule_rows
from enrich.crawler import crawl_urls_sync
from enrich.classifier import classify_events
from enrich.matcher import match_registrations
from enrich.writer import write_master_sheet


def main():
    parser = argparse.ArgumentParser(description="Cannes Lions 2026 enrichment pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Parse + normalize only, no crawl/classify/write")
    parser.add_argument("--no-crawl", action="store_true", help="Skip crawling, use cache or empty")
    parser.add_argument("--no-classify", action="store_true", help="Skip Claude API classification")
    args = parser.parse_args()

    warnings = []

    # Step 1: Read source sheets
    print("Step 1: Reading source sheets...")
    schedule_rows = read_schedule_rows()
    print(f"  Schedule: {len(schedule_rows)} raw rows")

    registrations_raw = read_registration_csv()
    print(f"  Registrations: {len(registrations_raw)} entries")

    # Extract hyperlinks
    hyperlinks = {}
    try:
        print("  Extracting hyperlinks from schedule sheet...")
        hyperlinks = extract_hyperlinks()
        print(f"  Found {len(hyperlinks)} hyperlinks")
    except Exception as e:
        msg = f"Hyperlink extraction failed: {e}. Using CSV link values."
        print(f"  Warning: {msg}")
        warnings.append(msg)

    # Step 2: Parse and normalize
    print("\nStep 2: Parsing and normalizing...")
    events = parse_schedule_rows(schedule_rows, hyperlinks)
    print(f"  Parsed {len(events)} events")

    days = {}
    for e in events:
        days[e.day] = days.get(e.day, 0) + 1
    for day, count in sorted(days.items()):
        print(f"    {day}: {count} events")

    if args.dry_run:
        print("\n--- DRY RUN: stopping before crawl/classify/write ---")
        for e in events[:5]:
            print(f"  {e.day} | {e.start_time}-{e.end_time} | {e.host}: {e.event_name}")
        print(f"  ... and {len(events) - 5} more")
        return

    # Step 3: Crawl event pages
    crawled = {}
    if not args.no_crawl:
        print("\nStep 3: Crawling event pages...")
        urls = [e.event_url for e in events if e.event_url]
        unique_urls = list(set(urls))
        print(f"  {len(unique_urls)} unique URLs to crawl")
        crawled = crawl_urls_sync(unique_urls)
        print(f"  Crawled {len(crawled)} pages")
    else:
        print("\nStep 3: Skipping crawl (--no-crawl)")

    # Step 4: Classify with Claude API
    if not args.no_classify:
        print("\nStep 4: Classifying events with Claude API...")
        classify_input = [
            {
                "event_name": e.event_name,
                "host": e.host,
                "details": e.details,
                "crawled_text": crawled.get(e.event_url, ""),
            }
            for e in events
        ]
        classifications = classify_events(classify_input)

        for i, c in enumerate(classifications):
            events[i].crawled_summary = c["crawled_summary"]
            events[i].company_type = c["company_type"]
            events[i].event_type = c["event_type"]
            events[i].target_audience = c["target_audience"]

        classified_count = sum(1 for c in classifications if c["company_type"] != "other")
        print(f"  Classified {classified_count}/{len(events)} events with specific types")
    else:
        print("\nStep 4: Skipping classification (--no-classify)")

    # Step 4b: Set registration_url from event_url (schedule sheet "HERE" links)
    prefilled = 0
    for e in events:
        if e.event_url and not e.registration_url:
            e.registration_url = e.event_url
            prefilled += 1
    print(f"  Pre-filled {prefilled}/{len(events)} registration URLs from schedule sheet links")

    # Step 5: Match registrations
    print("\nStep 5: Matching registrations...")
    reg_data = []
    for r in registrations_raw:
        vals = list(r.values())
        company = vals[0] if len(vals) > 0 else ""
        url = vals[1] if len(vals) > 1 else ""
        notes = vals[2] if len(vals) > 2 else ""
        if company and "company or event" not in company.lower():
            reg_data.append({"company": company, "url": url, "notes": notes})

    unmatched = match_registrations(events, reg_data)
    matched_count = len(reg_data) - len(unmatched)
    print(f"  Matched {matched_count}/{len(reg_data)} registrations")
    print(f"  Unmatched: {len(unmatched)}")

    # Step 6: Write to master sheet
    print("\nStep 6: Writing to master sheet...")
    config = write_master_sheet(events, unmatched, warnings)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"ENRICHMENT COMPLETE")
    print(f"{'=' * 50}")
    print(f"  Events written: {len(events)}")
    print(f"  Registrations matched: {matched_count}")
    print(f"  Unmatched registrations: {len(unmatched)}")
    print(f"  Warnings: {len(warnings)}")
    print(f"  Master sheet: https://docs.google.com/spreadsheets/d/{config['master_sheet_id']}")
    print()
    print("  Modal secrets to set (for MCP server deployment):")
    print(f"    MASTER_SHEET_ID={config['master_sheet_id']}")
    print(f"    EVENTS_GID={config.get('events_gid', '0')}")
    print(f"    UNREG_GID={config.get('unreg_gid', '')}")
    print()
    print("  Run: modal secret create cannes-lions-config \\")
    print(f"    MASTER_SHEET_ID={config['master_sheet_id']} \\")
    print(f"    EVENTS_GID={config.get('events_gid', '0')} \\")
    print(f"    UNREG_GID={config.get('unreg_gid', '')}")


if __name__ == "__main__":
    main()
