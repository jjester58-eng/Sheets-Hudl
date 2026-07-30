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


def write_report(spreadsheet: gspread.Spreadsheet, rows: List[List[str]]) -> None:
    """Clears (or creates) the output tab and writes the report starting
    at A1. Every row is padded to the same width so the write is a clean
    rectangle."""
    print(f"write_report: {len(rows)} rows")
    if not rows:
        print("ERROR: 0 rows — not clearing tab.")
        return

    try:
        ws = spreadsheet.worksheet(config.OUTPUT_SHEET_NAME)
        ws.clear()
        print(f"Cleared existing '{config.OUTPUT_SHEET_NAME}' tab")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=config.OUTPUT_SHEET_NAME, rows=1000, cols=10)
        print(f"Created new '{config.OUTPUT_SHEET_NAME}' tab")

    max_width = max(len(row) for row in rows)
    padded_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    padded_rows = [row + [""] * (max_width - len(row)) for row in padded_rows]

    try:
        ws.update(range_name="A1", values=padded_rows, value_input_option="RAW")
    except TypeError:
        ws.update("A1", padded_rows, value_input_option="RAW")

    print(f"Wrote {len(padded_rows)} rows to '{config.OUTPUT_SHEET_NAME}'")