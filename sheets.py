"""
sheets.py
---------
Everything that talks to Google Sheets lives here, and nothing else does.
No football math, no report formatting - just authentication, reading
tabs into DataFrames, and writing rows back out.

Uses gspread exclusively (no manual REST calls).
"""

import os
import sys
import json
from typing import List

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config


def get_client() -> gspread.Client:
    """Authenticates with the service account and returns a gspread client."""
    creds_json = os.environ[config.ENV_GOOGLE_CREDS]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=config.GOOGLE_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(gc: gspread.Client) -> gspread.Spreadsheet:
    """Opens the target spreadsheet, stripping any accidental whitespace
    from the ID (a trailing space/newline from copy-paste is a common,
    hard-to-spot cause of 'not found' errors)."""
    raw_id = os.environ[config.ENV_SPREADSHEET_ID]
    spreadsheet_id = raw_id.strip()

    if raw_id != spreadsheet_id:
        print("Warning: SPREADSHEET_ID had leading/trailing whitespace - stripped it.")

    print(f"Spreadsheet ID length: {len(spreadsheet_id)}")

    spreadsheet = gc.open_by_key(spreadsheet_id)
    print(f"Opened spreadsheet: '{spreadsheet.title}'")
    return spreadsheet


def validate_required_tabs(spreadsheet: gspread.Spreadsheet, required: List[str]) -> None:
    """Confirms every tab in `required` exists before any analysis runs.
    Fails fast with a clear message rather than partway through."""
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Tabs found in spreadsheet: {existing_titles}")

    missing = [name for name in required if name not in existing_titles]
    if missing:
        print(f"ERROR: required tab(s) not found: {missing}")
        print(f"Available tabs are: {existing_titles}")
        print("Check for typos, extra spaces, or different capitalization "
              "in the tab name(s) above.")
        sys.exit(1)


def load_sheet_as_df(spreadsheet: gspread.Spreadsheet, tab_name: str) -> pd.DataFrame:
    """Loads a tab into a DataFrame. Fails fast with a clear message if the
    tab can't be read. Does not transform or coerce any columns - that's
    analysis.py's job."""
    ws = spreadsheet.worksheet(tab_name)
    print(f"Reading '{tab_name}': {ws.row_count} rows x {ws.col_count} cols (sheet dimensions)")

    try:
        records = ws.get_all_records()
    except gspread.exceptions.APIError as e:
        print(f"ERROR: could not read '{tab_name}': {e}")
        sys.exit(1)

    print(f"'{tab_name}': {len(records)} data rows loaded")

    df = pd.DataFrame(records)
    if df.empty:
        print(f"Warning: '{tab_name}' has no data rows yet.")

    return df


def _apply_report_formatting(ws: gspread.Worksheet, rows: List[List[str]], max_width: int) -> None:
    """Applies simple visual formatting after the values are written:
      - Section headers (===== ... =====): bold + dark fill
      - Column header rows (Scout/Live/Trend, Component/Score/Read, etc.): bold + light fill
      - Change / alert rows (contain ⚠, NEW, ▲, ▼): light red fill
      - Stable rows (contain ✓ and not ⚠): light green fill
    """
    # Unicode glyphs used in reports.py
    warn = "\u26a0"   # ⚠
    check = "\u2713"  # ✓
    up = "\u25b2"     # ▲
    down = "\u25bc"   # ▼

    requests = []
    sheet_id = ws.id

    def _range(row_idx: int):
        """0-based row index → GridRange for the full report width."""
        return {
            "sheetId": sheet_id,
            "startRowIndex": row_idx,
            "endRowIndex": row_idx + 1,
            "startColumnIndex": 0,
            "endColumnIndex": max_width,
        }

    def _repeat(row_idx: int, fmt: dict):
        requests.append({
            "repeatCell": {
                "range": _range(row_idx),
                "cell": {"userEnteredFormat": fmt},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })

    header_keywords = {
        "scout", "live", "trend", "component", "score", "read",
        "situation", "expected", "formation", "r%", "p%", "play", "type",
        "fav runs", "fav pass", "run%", "pass%",
    }

    for i, row in enumerate(rows):
        text = " ".join(str(c) for c in row).strip()
        if not text:
            continue

        # Section headers: ===== TITLE =====
        if text.startswith("====="):
            _repeat(i, {
                "backgroundColor": {"red": 0.15, "green": 0.20, "blue": 0.30},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            })
            continue

        # Sub-headers: — title —
        if text.startswith("—") or text.startswith("\u2014"):
            _repeat(i, {
                "backgroundColor": {"red": 0.85, "green": 0.88, "blue": 0.92},
                "textFormat": {"bold": True},
            })
            continue

        # Column header rows (short label rows)
        first = str(row[0]).strip().lower() if row else ""
        if first in header_keywords or (len(row) >= 3 and first == ""):
            # blank-first header like ["", "Scout", "Live", "Trend"]
            joined_lower = text.lower()
            if any(k in joined_lower for k in ("scout", "component", "situation", "play", "formation")):
                _repeat(i, {
                    "backgroundColor": {"red": 0.90, "green": 0.92, "blue": 0.95},
                    "textFormat": {"bold": True},
                })
                continue

        # Alert / change rows → light red
        if warn in text or "NEW FORM" in text or "NEW PLAY" in text or up in text or down in text:
            if "NEW FORM" in text or "NEW PLAY" in text or warn in text:
                _repeat(i, {
                    "backgroundColor": {"red": 0.96, "green": 0.80, "blue": 0.80},
                    "textFormat": {"bold": False},
                })
            else:
                # ▲ / ▼ movers — softer amber/red
                _repeat(i, {
                    "backgroundColor": {"red": 0.98, "green": 0.90, "blue": 0.80},
                })
            continue

        # Stable / following-scout rows → light green
        if check in text and warn not in text:
            _repeat(i, {
                "backgroundColor": {"red": 0.85, "green": 0.94, "blue": 0.85},
            })
            continue

    if not requests:
        return

    try:
        ws.spreadsheet.batch_update({"requests": requests})
        print(f"Applied formatting to {len(requests)} rows")
    except Exception as e:
        # Formatting is best-effort — never fail the report write for it
        print(f"Warning: could not apply sheet formatting: {e}")


def write_report(spreadsheet: gspread.Spreadsheet, rows: List[List[str]]) -> None:
    """Clears (or creates) the output tab and writes the report starting
    at A1. Every row is padded to the same width so the write is a clean
    rectangle. Then applies section/alert color formatting.

    Safety: refuse to clear if there are no rows; surface write errors
    clearly so a failed run cannot look like a successful blank sheet.
    """
    if not rows:
        print("ERROR: report has 0 rows — refusing to clear the output tab.")
        return

    max_width = max((len(row) for row in rows), default=1)
    padded_rows = [row + [""] * (max_width - len(row)) for row in rows]
    print(f"Report ready: {len(padded_rows)} rows x {max_width} cols")

    try:
        ws = spreadsheet.worksheet(config.OUTPUT_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=config.OUTPUT_SHEET_NAME,
            rows=max(len(padded_rows) + 50, 1000),
            cols=max(max_width + 2, 10),
        )
        print(f"Created new '{config.OUTPUT_SHEET_NAME}' tab")

    try:
        if ws.row_count < len(padded_rows):
            ws.resize(rows=len(padded_rows) + 50)
        if ws.col_count < max_width:
            ws.resize(cols=max_width + 2)
    except Exception as e:
        print(f"Warning: could not resize worksheet: {e}")

    try:
        ws.clear()
        print(f"Cleared existing '{config.OUTPUT_SHEET_NAME}' tab")
        ws.update(range_name="A1", values=padded_rows, value_input_option="RAW")
        print(f"Wrote {len(padded_rows)} rows to '{config.OUTPUT_SHEET_NAME}'")
    except Exception as e:
        print(f"ERROR: failed writing report values: {e}")
        raise

    try:
        _apply_report_formatting(ws, padded_rows, max_width)
    except Exception as e:
        print(f"Warning: formatting skipped: {e}")