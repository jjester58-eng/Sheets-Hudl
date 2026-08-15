"""
sheets.py
---------
Everything that talks to Google Sheets lives here, and nothing else does.
No football math, no report formatting structure - just authentication, reading
tabs into DataFrames, writing rows back out, and applying presentation layouts.

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
    """Opens the target spreadsheet, stripping any accidental whitespace from the ID."""
    raw_id = os.environ[config.ENV_SPREADSHEET_ID]
    spreadsheet_id = raw_id.strip()

    if raw_id != spreadsheet_id:
        print("Warning: SPREADSHEET_ID had leading/trailing whitespace - stripped it.")

    print(f"Spreadsheet ID length: {len(spreadsheet_id)}")

    spreadsheet = gc.open_by_key(spreadsheet_id)
    print(f"Opened spreadsheet: '{spreadsheet.title}'")
    return spreadsheet


def validate_required_tabs(spreadsheet: gspread.Spreadsheet, required: List[str]) -> None:
    """Confirms every tab in `required` exists before any analysis runs."""
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Tabs found in spreadsheet: {existing_titles}")

    missing = [name for name in required if name not in existing_titles]
    if missing:
        print(f"ERROR: required tab(s) not found: {missing}")
        print(f"Available tabs are: {existing_titles}")
        sys.exit(1)


def _clean_dataframe_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans DataFrame headers and automatically casts key football columns 
    (Down, Distance, Yards Gained, etc.) to numeric types, and normalizes 
    string columns like PLAY TYPE so math operations and filters don't fail.
    """
    if df.empty:
        return df

    # Strip white space from column names
    df.columns = df.columns.astype(str).str.strip()

    # Identify potential numeric down & distance columns dynamically
    numeric_candidates = [
        getattr(config, "COL_DOWN", "DN"),
        getattr(config, "COL_DIST", "DIST"),
        getattr(config, "COL_DISTANCE", "DISTANCE"),
        getattr(config, "COL_GAIN", "GN"),
        getattr(config, "COL_YARDS", "YARDS"),
        "DOWN", "DIST", "DISTANCE", "DN", "GN", "YARDS"
    ]

    for col in df.columns:
        # Cast numeric candidates to float/int safely
        if col.upper() in [c.upper() for c in numeric_candidates if c]:
            df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors="coerce").fillna(0)
        
        # Clean string dropdown columns (like PLAY TYPE, OFF PLAY TYPE, FORMATION)
        else:
            df[col] = df[col].astype(str).str.strip()

    return df


def load_sheet_as_df(spreadsheet: gspread.Spreadsheet, tab_name: str) -> pd.DataFrame:
    """
    Loads a tab into a DataFrame safely using raw matrix values.
    This prevents missing header crashes, cleans up dropdown spacing,
    and converts numeric columns automatically.
    """
    ws = spreadsheet.worksheet(tab_name)
    print(f"Reading '{tab_name}': {ws.row_count} rows x {ws.col_count} cols")

    try:
        rows = ws.get_all_values()
    except gspread.exceptions.APIError as e:
        print(f"ERROR: could not read '{tab_name}': {e}")
        sys.exit(1)

    if not rows:
        print(f"Warning: '{tab_name}' is completely empty.")
        return pd.DataFrame()

    # Locate the header row (first non-empty row)
    header_idx = 0
    for i, r in enumerate(rows):
        if any(cell.strip() for cell in r):
            header_idx = i
            break

    headers = [str(col).strip() for col in rows[header_idx]]
    data = rows[header_idx + 1 :]

    df = pd.DataFrame(data, columns=headers)
    df = _clean_dataframe_types(df)

    print(f"'{tab_name}': {len(df)} data rows loaded")

    if df.empty:
        print(f"Warning: '{tab_name}' has no data rows yet.")

    return df


def load_defense_live_df(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    """
    Loads ODK - the single source of truth for live data - and returns
    only the defensive snaps (ODK column == 'D'). Normalizes matching logic
    case-insensitively.
    """
    df = load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)

    if df.empty:
        print(f"Warning: '{config.ODK_SHEET_NAME}' is empty.")
        return df

    target_col = str(config.COL_SIDE).strip()

    if target_col not in df.columns:
        print(
            f"ERROR: Column '{target_col}' not found in '{config.ODK_SHEET_NAME}'. "
            f"Available columns are: {list(df.columns)}"
        )
        return pd.DataFrame()

    target_val = str(config.SIDE_DEFENSE).strip().upper()

    # Robust case-insensitive and whitespace-stripped matching for ODK == 'D'
    mask = (
        df[target_col]
        .astype(str)
        .str.strip()
        .str.upper() == target_val
    )

    live_df = df[mask].reset_index(drop=True)
    print(
        f"'{config.ODK_SHEET_NAME}': {len(live_df)} defensive rows "
        f"(Matching '{target_col}' == '{target_val}')"
    )

    # Diagnostic print for live Play Type dropdown options
    play_type_col = getattr(config, "COL_PLAY_TYPE", "PLAY TYPE")
    if play_type_col in live_df.columns:
        unique_plays = live_df[play_type_col].unique()
        print(f"Live ODK '{play_type_col}' dropdown values detected: {list(unique_plays)}")

    return live_df


def get_down_dist_splits(df: pd.DataFrame, down: int, min_dist: int, max_dist: int) -> dict:
    """
    Helper function to calculate down & distance run/pass splits cleanly.
    Fully case-insensitive and works for both Scout and Live ODK data.
    """
    play_col = getattr(config, "COL_PLAY_TYPE", "PLAY TYPE")
    dn_col = getattr(config, "COL_DOWN", "DN")
    dist_col = getattr(config, "COL_DIST", "DIST")

    if df.empty or play_col not in df.columns or dn_col not in df.columns or dist_col not in df.columns:
        return {"snaps": 0, "runs": 0, "passes": 0, "run_pct": 0.0, "pass_pct": 0.0}

    # Extract down and distance as numbers
    downs = pd.to_numeric(df[dn_col], errors='coerce').fillna(0)
    dists = pd.to_numeric(df[dist_col], errors='coerce').fillna(0)

    # Upper case Play Type series
    play_types = df[play_col].astype(str).str.strip().str.upper()

    # Filter mask for down & distance range
    mask = (downs == down) & (dists >= min_dist) & (dists <= max_dist)
    filtered_plays = play_types[mask]

    total_snaps = len(filtered_plays)
    if total_snaps == 0:
        return {"snaps": 0, "runs": 0, "passes": 0, "run_pct": 0.0, "pass_pct": 0.0}

    # Flexible case-insensitive matching (handles 'RUN', 'Run', 'R', 'PASS', 'Pass', 'P')
    runs = filtered_plays.str.contains(r'RUN|^R$', regex=True, na=False).sum()
    passes = filtered_plays.str.contains(r'PASS|^P$', regex=True, na=False).sum()

    run_pct = round((runs / total_snaps) * 100, 1)
    pass_pct = round((passes / total_snaps) * 100, 1)

    return {
        "snaps": total_snaps,
        "runs": runs,
        "passes": passes,
        "run_pct": run_pct,
        "pass_pct": pass_pct
    }


def write_report(spreadsheet: gspread.Spreadsheet, rows: List[List[str]]) -> gspread.Worksheet:
    """
    Clears (or creates) the output tab and writes the report starting
    at A1. Every row is padded to the same width so the write is a clean
    rectangle. Returns the worksheet object for further formatting.
    """
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

    ws.update_configuration({"textFormat": {"fontSize": 10}})

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

        # Check for Metric Table Sub-headers (Covers A and B keys too)
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