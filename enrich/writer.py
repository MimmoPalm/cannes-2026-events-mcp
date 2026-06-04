"""Write enriched data to the MIMMS master Google Sheet."""

import csv
import io
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from enrich.parser import Event

CONFIG_PATH = Path("config.json")

EVENT_HEADERS = [
    "event_name", "host", "day", "date", "start_time", "end_time",
    "location", "event_url", "details", "crawled_summary",
    "company_type", "event_type", "target_audience",
    "registration_url", "registration_notes", "status",
]

UNREG_HEADERS = ["company", "registration_url", "notes", "crawled_summary", "company_type"]


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"master_sheet_id": "", "events_gid": "", "unreg_gid": ""}


def _save_config(config: dict):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def _run_gws(args: list[str]) -> str:
    """Run a gws CLI command and return stdout."""
    result = subprocess.run(
        ["gws"] + args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gws command failed: {result.stderr}")
    return result.stdout.strip()


def _create_master_sheet() -> str:
    """Create a new Google Sheet and return its ID."""
    title = "Cannes Lions 2026 - Master (MIMMS)"
    output = _run_gws(["sheets", "create", title])
    sheet_id = output.strip()
    if "spreadsheets/d/" in sheet_id:
        sheet_id = sheet_id.split("spreadsheets/d/")[1].split("/")[0]
    return sheet_id


def _make_sheet_public(sheet_id: str):
    """Make the sheet viewable by anyone with the link."""
    try:
        _run_gws(["drive", "share", sheet_id, "--type", "anyone", "--role", "reader"])
    except Exception as e:
        print(f"  Warning: could not make sheet public: {e}")


def _get_tab_gids(sheet_id: str) -> dict[str, str]:
    """Retrieve GIDs for all tabs in a sheet using gws CLI."""
    try:
        output = _run_gws(["sheets", "info", sheet_id])
        gids = {}
        for line in output.splitlines():
            line = line.strip()
            if "gid" in line.lower():
                match = re.search(r"(.+?)\s*\(?gid[:\s]*(\d+)", line, re.IGNORECASE)
                if match:
                    tab_name = match.group(1).strip().lower()
                    gid = match.group(2)
                    gids[tab_name] = gid
        return gids
    except Exception as e:
        print(f"  Warning: could not retrieve tab GIDs: {e}")
        return {}


def _event_to_row(event: Event) -> list[str]:
    """Convert an Event to a list of strings matching EVENT_HEADERS."""
    return [
        event.event_name,
        event.host,
        event.day,
        event.date,
        event.start_time,
        event.end_time,
        event.location,
        event.event_url,
        event.details,
        event.crawled_summary,
        event.company_type,
        event.event_type,
        event.target_audience,
        event.registration_url,
        event.registration_notes,
        event.status,
    ]


def _to_csv_string(headers: list[str], rows: list[list[str]]) -> str:
    """Convert headers and rows to a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def write_master_sheet(
    events: list[Event],
    unmatched_regs: list[dict],
    warnings: list[str],
) -> dict:
    """Write enriched data to the master Google Sheet.

    Creates the sheet on first run, overwrites on subsequent runs.
    Stores sheet ID and tab GIDs in config.json.

    Returns:
        Config dict with keys: master_sheet_id, events_gid, unreg_gid.
    """
    config = _load_config()
    sheet_id = config.get("master_sheet_id", "")

    if not sheet_id:
        print("Creating master sheet...")
        sheet_id = _create_master_sheet()
        config["master_sheet_id"] = sheet_id
        _save_config(config)
        _make_sheet_public(sheet_id)
        print(f"  Created: https://docs.google.com/spreadsheets/d/{sheet_id}")

    # Write Events tab
    print("Writing Events tab...")
    event_rows = [_event_to_row(e) for e in events]
    events_csv = _to_csv_string(EVENT_HEADERS, event_rows)
    csv_path = Path("/tmp/cannes_events.csv")
    csv_path.write_text(events_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path), "--sheet", "Events", "--replace"])

    # Write Unmatched Registrations tab
    print("Writing Unmatched Registrations tab...")
    unreg_rows = [
        [
            r.get("company", ""),
            r.get("url", ""),
            r.get("notes", ""),
            r.get("crawled_summary", ""),
            r.get("company_type", ""),
        ]
        for r in unmatched_regs
    ]
    unreg_csv = _to_csv_string(UNREG_HEADERS, unreg_rows)
    csv_path2 = Path("/tmp/cannes_unreg.csv")
    csv_path2.write_text(unreg_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path2), "--sheet", "Unmatched Registrations", "--replace"])

    # Write _metadata tab
    print("Writing _metadata tab...")
    now = datetime.now(timezone.utc).isoformat()
    meta_csv = _to_csv_string(
        ["key", "value"],
        [
            ["last_updated", now],
            ["schedule_sheet_id", "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"],
            ["registration_sheet_id", "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"],
            ["event_count", str(len(events))],
            ["unmatched_reg_count", str(len(unmatched_regs))],
            *[["warning", w] for w in warnings],
        ],
    )
    csv_path3 = Path("/tmp/cannes_meta.csv")
    csv_path3.write_text(meta_csv)
    _run_gws(["sheets", "import", sheet_id, str(csv_path3), "--sheet", "_metadata", "--replace"])

    # Retrieve tab GIDs
    print("Retrieving tab GIDs...")
    tab_gids = _get_tab_gids(sheet_id)
    config["events_gid"] = tab_gids.get("events", "0")
    config["unreg_gid"] = tab_gids.get("unmatched registrations", "")
    _save_config(config)

    if config["unreg_gid"]:
        print(f"  Events GID: {config['events_gid']}")
        print(f"  Unmatched Registrations GID: {config['unreg_gid']}")
    else:
        print("  Warning: could not auto-detect tab GIDs. Check config.json manually.")
        print(f"  Open https://docs.google.com/spreadsheets/d/{sheet_id} and note the gid= parameter for each tab.")
        warnings.append("Tab GIDs not auto-detected. Set events_gid and unreg_gid in config.json manually.")

    # Clean up temp files
    for p in [csv_path, csv_path2, csv_path3]:
        p.unlink(missing_ok=True)

    return config
