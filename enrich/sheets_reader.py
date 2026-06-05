"""Read source Google Sheets and extract hyperlinks."""

import csv
import io
import pickle
from pathlib import Path

import httpx


SCHEDULE_SHEET_ID = "1vcWuAhU3PFakp0nhnnp0YLXRudbSJ1uTaJbIkdZN0DE"
SCHEDULE_GID = "1111568312"
SCHEDULE_TAB_NAME = "The Digital Voice\u2122: 2026 Event Guide"
REGISTRATION_SHEET_ID = "1VIVb0VFxXMQCKSJLgU-oMehyE58Tt5T0IB--g5Do4A8"
REGISTRATION_GID = "835495045"

CSV_TEMPLATE = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"


def read_schedule_rows() -> list[list[str]]:
    """Fetch schedule sheet via Sheets API, return list of rows (each row is list of strings).

    Uses the Sheets API instead of CSV export because the CSV export merges
    the 'all week' venues section into a single mega-row, losing ~80 events.
    """
    from googleapiclient.discovery import build

    creds = _get_sheets_credentials()
    service = build("sheets", "v4", credentials=creds)
    tab = f"'{SCHEDULE_TAB_NAME}'"

    result = service.spreadsheets().values().get(
        spreadsheetId=SCHEDULE_SHEET_ID,
        range=f"{tab}!A1:F500",
    ).execute()

    rows = result.get("values", [])
    # Pad short rows to 6 columns
    for i, row in enumerate(rows):
        while len(row) < 6:
            row.append("")
    return rows


def read_registration_csv() -> list[dict[str, str]]:
    """Fetch registration sheet as CSV, return list of dicts."""
    url = CSV_TEMPLATE.format(id=REGISTRATION_SHEET_ID, gid=REGISTRATION_GID)
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    data = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        record = {}
        for i, h in enumerate(headers):
            record[h] = row[i].strip() if i < len(row) else ""
        data.append(record)
    return data


def _get_sheets_credentials():
    """Load bot account credentials from pickle file."""
    token_path = Path.home() / ".config" / "gdrive_token.pickle"
    if not token_path.exists():
        raise FileNotFoundError(
            f"Bot account token not found at {token_path}. "
            "Run the auth flow first."
        )
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    return creds


def extract_hyperlinks() -> dict[int, str]:
    """Extract hyperlinks from the schedule sheet's Link column (col index 4).

    Returns a dict mapping raw row index (0-based, including header) to URL.
    These indices correspond to the original sheet rows BEFORE any mega-row
    splitting. The parser must re-index after splitting.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = _get_sheets_credentials()
    service = build("sheets", "v4", credentials=creds)

    tab = f"'{SCHEDULE_TAB_NAME}'"
    result = service.spreadsheets().get(
        spreadsheetId=SCHEDULE_SHEET_ID,
        ranges=[f"{tab}!A:F"],
        fields="sheets.data.rowData.values.hyperlink",
    ).execute()

    hyperlinks = {}
    sheets_data = result.get("sheets", [])
    if not sheets_data:
        return hyperlinks

    row_data = sheets_data[0].get("data", [{}])[0].get("rowData", [])
    for row_idx, row in enumerate(row_data):
        values = row.get("values", [])
        if len(values) > 4:
            link_cell = values[4]
            url = link_cell.get("hyperlink", "")
            if url:
                hyperlinks[row_idx] = url

    return hyperlinks
