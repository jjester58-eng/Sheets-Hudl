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


def load_sheet_as_df(spreadsheet: gspread.Spreadsheet, tab_name: str) -> pd.DataFrame:
    """Loads a tab into a DataFrame."""
    ws = spreadsheet.worksheet(tab_name)
    print(f"Reading '{tab_name}': {ws.row_count} rows x {ws.col_count} cols")

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
        
        # Check for Metric Table Sub-headers (Now covers A and B keys too)
        elif "SNAPS" in row_str or "RUN %" in row_str:
            formats.append({
                "range": f"A{row_num}:{max_cols_letter}{row_num}",
                "format": table_header_theme
            })
            
        # Standard Data Rows: Ensure Column A and B elements are bolded/left-aligned
        else:
            if row[0].strip() != "" or row[1].strip() != "":
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


# =====================================================================
# UTILITY HELPER FOR YOUR PROCESSING (Use this inside analysis.py)
# =====================================================================
def map_down_and_distance(down: int, distance: int) -> str:
    """
    Translates raw Down and Distance numerical integers into your specific
    coaching framework nomenclature labels.
    """
    d_int = int(down)
    dist_int = int(distance)
    
    if d_int == 4:
        return "4th Down"
        
    if d_int == 1:
        if dist_int >= 11:
            return "1st and Long"
        return "1st and Med"
        
    if d_int == 2:
        if dist_int <= 3:
            return "2nd and Short"
        elif 4 <= dist_int <= 7:
            return "2nd and Med"
        return "2nd and Long"
        
    if d_int == 3:
        if dist_int <= 3:
            return "3rd & Short"
        elif 4 <= dist_int <= 7:
            return "3rd & Med"
        return "3rd and Long"
        
    return f"{d_int} no classification"