"""Write enriched data to the MIMMS master Google Sheet.

Uses Google Sheets API v4 and Drive API v3 directly via the bot account
token at ~/.config/gdrive_token.pickle (has drive scope).
"""

import json
import pickle
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


def _get_credentials():
    """Load bot account credentials from pickle file."""
    token_path = Path.home() / ".config" / "gdrive_token.pickle"
    if not token_path.exists():
        raise FileNotFoundError(f"Bot account token not found at {token_path}")
    with open(token_path, "rb") as f:
        return pickle.load(f)


def _get_sheets_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_get_credentials())


def _get_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_credentials())


def _create_master_sheet() -> str:
    """Create a new Google Sheet with 3 tabs and return its ID."""
    service = _get_sheets_service()
    body = {
        "properties": {"title": "Cannes Lions 2026 - Master (MIMMS)"},
        "sheets": [
            {"properties": {"title": "Events", "index": 0}},
            {"properties": {"title": "Unmatched Registrations", "index": 1}},
            {"properties": {"title": "_metadata", "index": 2}},
        ],
    }
    result = service.spreadsheets().create(body=body).execute()
    return result["spreadsheetId"]


def _make_sheet_public(sheet_id: str):
    """Make the sheet viewable by anyone with the link."""
    try:
        drive = _get_drive_service()
        drive.permissions().create(
            fileId=sheet_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()
    except Exception as e:
        print(f"  Warning: could not make sheet public: {e}")


def _get_tab_gids(sheet_id: str) -> dict[str, str]:
    """Retrieve GIDs for all tabs in a sheet."""
    service = _get_sheets_service()
    result = service.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets.properties",
    ).execute()
    gids = {}
    for sheet in result.get("sheets", []):
        props = sheet.get("properties", {})
        title = props.get("title", "").lower()
        gid = str(props.get("sheetId", ""))
        gids[title] = gid
    return gids


def _ensure_tabs_exist(sheet_id: str, tab_names: list[str]):
    """Ensure all required tabs exist in the sheet."""
    service = _get_sheets_service()
    result = service.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets.properties.title",
    ).execute()
    existing = {s["properties"]["title"] for s in result.get("sheets", [])}

    requests = []
    for name in tab_names:
        if name not in existing:
            requests.append({"addSheet": {"properties": {"title": name}}})

    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": requests},
        ).execute()


def _write_tab(sheet_id: str, tab_name: str, headers: list[str], rows: list[list[str]]):
    """Clear a tab and write headers + rows."""
    service = _get_sheets_service()

    # Clear existing data
    range_name = f"'{tab_name}'!A:Z"
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=range_name,
        body={},
    ).execute()

    # Write new data
    values = [headers] + rows
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


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
    else:
        # Ensure tabs exist on re-runs
        _ensure_tabs_exist(sheet_id, ["Events", "Unmatched Registrations", "_metadata"])

    # Write Events tab
    print("Writing Events tab...")
    event_rows = [_event_to_row(e) for e in events]
    _write_tab(sheet_id, "Events", EVENT_HEADERS, event_rows)

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
    _write_tab(sheet_id, "Unmatched Registrations", UNREG_HEADERS, unreg_rows)

    # Write _metadata tab
    print("Writing _metadata tab...")
    now = datetime.now(timezone.utc).isoformat()
    meta_rows = [
        ["last_updated", now],
        ["schedule_sheet_id", "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"],
        ["registration_sheet_id", "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"],
        ["event_count", str(len(events))],
        ["unmatched_reg_count", str(len(unmatched_regs))],
        *[["warning", w] for w in warnings],
    ]
    _write_tab(sheet_id, "_metadata", ["key", "value"], meta_rows)

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
        print("  Warning: could not auto-detect tab GIDs.")
        print(f"  Open https://docs.google.com/spreadsheets/d/{sheet_id}")
        warnings.append("Tab GIDs not auto-detected.")

    return config
