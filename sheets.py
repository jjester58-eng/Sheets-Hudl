"""
sheets.py
---------
Everything that talks to Google Sheets lives here, and nothing else does.
No football math, no report formatting structure - just authentication, reading
tabs into DataFrames, writing rows back out, and applying presentation layouts.

Normalization (Run/Pass canonicalization, numeric casting, situational
buckets) is NOT done here - that's analysis.add_situational_columns()'s job,
called exactly once by analyze_tendencies.py. Doing it in two places is how
the Run/Pass split silently broke last time.

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
import analysis


def get_client() -> gspread.Client:
    """Return an authenticated Google Sheets client from the configured env vars."""
    creds_raw = os.environ.get(config.ENV_GOOGLE_CREDS)
    spreadsheet_id = os.environ.get(config.ENV_SPREADSHEET_ID)
    if not creds_raw:
        raise RuntimeError(
            f"Missing {config.ENV_GOOGLE_CREDS} environment variable. "
            "Set it to the service-account JSON string before running the report."
        )
    if not spreadsheet_id:
        raise RuntimeError(
            f"Missing {config.ENV_SPREADSHEET_ID} environment variable. "
            "Set it to the target Google Sheet ID before running the report."
        )

    creds_dict = json.loads(creds_raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=config.GOOGLE_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(gc: gspread.Client) -> gspread.Spreadsheet:
    """Open the target spreadsheet using the configured Spreadsheet ID."""
    spreadsheet_id = os.environ[config.ENV_SPREADSHEET_ID].strip()
    spreadsheet = gc.open_by_key(spreadsheet_id)
    print(f"Opened spreadsheet: '{spreadsheet.title}'")
    return spreadsheet


def validate_required_tabs(spreadsheet: gspread.Spreadsheet, required: List[str]) -> None:
    """Confirm required tabs exist before analysis runs."""
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Tabs found in spreadsheet: {existing_titles}")
    missing = [name for name in required if name not in existing_titles]
    if missing:
        raise RuntimeError(f"Required tab(s) not found: {missing}")


def load_sheet_as_df(
    spreadsheet: gspread.Spreadsheet,
    tab_name: str
) -> pd.DataFrame:
    """
    Load a Google Sheet tab into a DataFrame.

    Handles:
    - blank columns at the end of a sheet
    - duplicate/blank headers
    - completely empty rows
    - whitespace around values

    No football normalization happens here.
    """

    ws = spreadsheet.worksheet(tab_name)

    print(
        f"Reading '{tab_name}': "
        f"{ws.row_count} rows x {ws.col_count} cols"
    )

    try:
        rows = ws.get_all_values()
    except gspread.exceptions.APIError as e:
        raise RuntimeError(
            f"Could not read '{tab_name}': {e}"
        ) from e

    if not rows:
        print(f"Warning: '{tab_name}' is completely empty.")
        return pd.DataFrame()

    # ------------------------------------------------------------
    # Find the first row containing actual header information
    # ------------------------------------------------------------
    header_idx = next(
        (
            i
            for i, row in enumerate(rows)
            if any(str(cell).strip() for cell in row)
        ),
        None,
    )

    if header_idx is None:
        print(f"Warning: '{tab_name}' contains no usable data.")
        return pd.DataFrame()

    raw_headers = rows[header_idx]

    # ------------------------------------------------------------
    # Remove trailing completely blank columns
    # ------------------------------------------------------------
    last_header = -1

    for i, header in enumerate(raw_headers):
        if str(header).strip():
            last_header = i

    if last_header < 0:
        print(f"Warning: '{tab_name}' has no headers.")
        return pd.DataFrame()

    headers = [
        str(header).strip()
        for header in raw_headers[:last_header + 1]
    ]

    # ------------------------------------------------------------
    # Make duplicate headers unique
    # ------------------------------------------------------------
    seen = {}
    unique_headers = []

    for header in headers:
        if header == "":
            # Ignore unnamed columns entirely
            unique_headers.append(None)
            continue

        if header in seen:
            seen[header] += 1
            unique_headers.append(
                f"{header}_{seen[header]}"
            )
        else:
            seen[header] = 0
            unique_headers.append(header)

    # Remove columns with no header
    keep_indexes = [
        i for i, header in enumerate(unique_headers)
        if header is not None
    ]

    unique_headers = [
        unique_headers[i]
        for i in keep_indexes
    ]

    duplicates = [
        header
        for header, count in seen.items()
        if count > 0
    ]

    if duplicates:
        print(
            f"WARNING: Duplicate headers found in "
            f"'{tab_name}': {duplicates}"
        )

    print(f"Headers found in '{tab_name}':")
    print(unique_headers)

    # ------------------------------------------------------------
    # Build data rows
    # ------------------------------------------------------------
    data = []

    for row in rows[header_idx + 1:]:
        # Make sure row is long enough
        padded = list(row) + [""] * (
            len(raw_headers) - len(row)
        )

        cleaned = [
            padded[i]
            for i in keep_indexes
        ]

        # Skip completely empty rows
        if any(str(cell).strip() for cell in cleaned):
            data.append(cleaned)

    # ------------------------------------------------------------
    # Create DataFrame
    # ------------------------------------------------------------
    df = pd.DataFrame(
        data,
        columns=unique_headers
    )

    # Strip whitespace from every value
    for col in df.columns:
        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    print(
        f"'{tab_name}': "
        f"{len(df)} data rows loaded"
    )

    if df.empty:
        print(
            f"Warning: '{tab_name}' "
            f"has no data rows yet."
        )

    return df

def load_defense_live_df(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    """Load ODK and keep only defensive rows, then normalize to canonical Run/Pass values."""
    df = load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)
    if df.empty:
        return df

    if config.COL_SIDE not in df.columns:
        print(f"ERROR: '{config.ODK_SHEET_NAME}' has no '{config.COL_SIDE}' column. Found columns: {list(df.columns)}")
        return df

    live_df = df[df[config.COL_SIDE].astype(str).str.upper().str.contains('D', na=False)].reset_index(drop=True)
    print(f"'{config.ODK_SHEET_NAME}': {len(live_df)} defensive rows (ODK contains 'D')")

    if config.COL_PLAY_TYPE in live_df.columns:
        raw_values = live_df[config.COL_PLAY_TYPE].value_counts(dropna=False)
        print(f"Raw '{config.COL_PLAY_TYPE}' values in defensive rows: {raw_values.to_dict()}")
        live_df = analysis.add_situational_columns(live_df)
        print(f"Normalized defensive play types: {live_df[config.COL_PLAY_TYPE].value_counts(dropna=False).to_dict()}")
    else:
        print(f"WARNING: '{config.COL_PLAY_TYPE}' column not found in ODK. Found columns: {list(live_df.columns)}")

    return live_df


def write_report(spreadsheet: gspread.Spreadsheet, rows: List[List[str]]) -> gspread.Worksheet:
    """Clears (or creates) the output tab and writes the report starting
    at A1. Every row is padded to the same width so the write is a clean
    rectangle. Returns the worksheet object for further formatting."""
    print(f"write_report: {len(rows)} rows")
    if not rows:
        print("ERROR: 0 rows — not clearing tab.")
        return None

    try:
        ws = spreadsheet.worksheet(config.OUTPUT_SHEET_NAME)
        ws.clear()
        print(f"Cleared existing '{config.OUTPUT_SHEET_NAME}' tab")
    except gspread.exceptions.WorksheetNotFound:
        # Expanded to 12 columns (A-L) to naturally accommodate side-by-side splits
        ws = spreadsheet.add_worksheet(title=config.OUTPUT_SHEET_NAME, rows=1000, cols=12)
        print(f"Created new '{config.OUTPUT_SHEET_NAME}' tab")

    max_width = max(len(row) for row in rows)
    padded_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    padded_rows = [row + [""] * (max_width - len(row)) for row in padded_rows]

    try:
        ws.update(range_name="A1", values=padded_rows, value_input_option="RAW")
    except TypeError:
        ws.update("A1", padded_rows, value_input_option="RAW")

    print(f"Wrote {len(padded_rows)} rows to '{config.OUTPUT_SHEET_NAME}'")
    return ws


def format_report_layout(ws: gspread.Worksheet, total_rows: int, max_cols_letter: str = "L") -> None:
    """
    Applies the full theme styling based on the provided team dashboard image:
    - Bold deep navy blue banner styles for major sections
    - Bold light gray header rows for table metric descriptions
    - Bold, left-aligned text for Columns A and B identifiers (Formations & Plays side-by-side)
    - Center alignment for numerical metric values
    - Forces visible cell gridlines
    """
    if not ws or total_rows <= 0:
        return

    print("Formatting report presentation layout...")

    # Color Palette Specifications (Dark Navy Blue Theme)
    blue_theme = {
        "userEnteredFormat": {
            "backgroundColor": {"red": 0.04, "green": 0.22, "blue": 0.42},
            "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}, "bold": True, "fontSize": 11},
            "horizontalAlignment": "LEFT"
        }
    }

    table_header_theme = {
        "userEnteredFormat": {
            "backgroundColor": {"red": 0.92, "green": 0.92, "blue": 0.94},
            "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}, "bold": True, "fontSize": 10},
            "horizontalAlignment": "CENTER"
        }
    }

    identifiers_theme = {
        "userEnteredFormat": {
            "textFormat": {"bold": True},
            "horizontalAlignment": "LEFT"
        }
    }

    center_metrics_theme = {
        "userEnteredFormat": {
            "horizontalAlignment": "CENTER"
        }
    }

    all_values = ws.get_all_values()
    formats = []

   
    # 1. Base alignment formatting pass (Center numerical metrics across C through L)
    formats.append({
        "range": f"C1:{max_cols_letter}{total_rows}",
        "format": center_metrics_theme
    })

    # 2. Row by row rule parser scanning for dynamic styling placements
    for idx, row in enumerate(all_values):
        row_num = idx + 1
        row_str = " ".join([str(cell) for cell in row]).upper()

        # Check for Section Title Banner Rows
        if "REPORT" in row_str or "PROFILE:" in row_str or "TENDENCIES" in row_str or "CHANGES" in row_str:
            formats.append({
                "range": f"A{row_num}:{max_cols_letter}{row_num}",
                "format": blue_theme
            })

        # Check for Metric Table Sub-headers (Now covers A and B keys too)
        elif "SNAPS" in row_str or "RUN %" in row_str:
            formats.append({
                "range": f"A{row_num}:{max_cols_letter}{row_num}",
                "format": table_header_theme
            })

        # Standard Data Rows: Ensure Column A and B elements are bolded/left-aligned
        else:
            if len(row) > 1 and (row[0].strip() != "" or row[1].strip() != ""):
                if "SELECT" not in row_str:
                    formats.append({
                        "range": f"A{row_num}:B{row_num}",
                        "format": identifiers_theme
                    })

    if formats:
        ws.batch_format(formats)

    ws.update_view_setting(show_grid_lines=True)
    print("Report layout styling successfully drawn.")


def apply_trend_formatting(ws: gspread.Worksheet, trend_types: List[str]) -> None:
    """
    Applies analytical green/red highlights to data cell backdrops.
    - 'stay': soft pastel green background
    - 'new': soft pastel red background
    """
    if not ws or not trend_types:
        return

    print("Applying conditional trend markers...")

    green_format = {"userEnteredFormat": {"backgroundColor": {"red": 0.88, "green": 0.95, "blue": 0.88}}}
    red_format = {"userEnteredFormat": {"backgroundColor": {"red": 0.97, "green": 0.87, "blue": 0.87}}}

    formats = []

    for idx, trend in enumerate(trend_types):
        row_num = idx + 2
        cleaned_trend = str(trend).strip().lower()

        if "stay" in cleaned_trend:
            formats.append({
                "range": f"A{row_num}:L{row_num}",
                "format": green_format
            })
        elif "new" in cleaned_trend:
            formats.append({
                "range": f"A{row_num}:L{row_num}",
                "format": red_format
            })

    if formats:
        ws.batch_format(formats)
        print(f"Marked {len(formats)} trend rows.")