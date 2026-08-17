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


def get_client() -> gspread.Client:
    """Authenticates with the service account and returns a gspread client."""
    try:
        creds_json = os.environ[config.ENV_GOOGLE_CREDS]
    except KeyError as exc:
        raise RuntimeError(f"Missing required environment variable: {exc}") from exc

    try:
        creds_dict = json.loads(creds_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{config.ENV_GOOGLE_CREDS} is not valid JSON.") from exc

    creds = Credentials.from_service_account_info(creds_dict, scopes=config.GOOGLE_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(gc: gspread.Client) -> gspread.Spreadsheet:
    """Opens the target spreadsheet, stripping any accidental whitespace
    from the ID - a trailing newline in the GitHub secret is a common,
    otherwise-silent cause of 'spreadsheet not found' errors."""
    try:
        raw_id = os.environ[config.ENV_SPREADSHEET_ID]
    except KeyError as exc:
        raise RuntimeError(f"Missing required environment variable: {exc}") from exc

    spreadsheet_id = raw_id.strip()
    if raw_id != spreadsheet_id:
        print(f"Warning: {config.ENV_SPREADSHEET_ID} had leading/trailing whitespace - stripped it.")
    print(f"Spreadsheet ID length: {len(spreadsheet_id)}")

    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except Exception as exc:
        raise RuntimeError(f"Could not open spreadsheet with {config.ENV_SPREADSHEET_ID}: {exc}") from exc

    print(f"Opened spreadsheet: '{spreadsheet.title}'")
    return spreadsheet


def validate_required_tabs(spreadsheet: gspread.Spreadsheet, required: List[str]) -> None:
    """Confirms every tab in `required` exists before any analysis runs."""
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Tabs found in spreadsheet: {existing_titles}")

    missing = [name for name in required if name not in existing_titles]
    if missing:
        raise RuntimeError(f"Missing required sheet tab(s): {', '.join(missing)}. "
                            f"Available tabs are: {existing_titles}")

    print(f"Required tabs found: {', '.join(required)}")


def _dedupe_headers(headers: List[str]) -> List[str]:
    """Guarantees every header is unique before it becomes a DataFrame
    column label. Blank headers (a sheet's used range wider than its actual
    data - the ODK crash: 26 columns reported, only 18 named) all collapse
    to the same '' label otherwise, and any duplicate label makes df[col]
    return a DataFrame instead of a Series, breaking every .str/.astype
    call downstream. Blank -> 'UNNAMED', 'UNNAMED_2', ...; a real duplicate
    name -> 'NAME', 'NAME_2', ..."""
    seen: dict = {}
    result = []
    for h in headers:
        name = h if h else "UNNAMED"
        if name in seen:
            seen[name] += 1
            result.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            result.append(name)
    return result


def load_sheet_as_df(spreadsheet: gspread.Spreadsheet, tab_name: str) -> pd.DataFrame:
    """Loads a tab into a DataFrame using raw values (not get_all_records),
    so a blank leading row or a stray duplicate header cell doesn't silently
    drop data. Cell values are stripped of surrounding whitespace; no type
    casting happens here - analysis.add_situational_columns() owns that."""
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

    # Use the first non-blank row as the header row.
    header_idx = next((i for i, r in enumerate(rows) if any(cell.strip() for cell in r)), 0)
    headers = _dedupe_headers([str(col).strip() for col in rows[header_idx]])
    data = rows[header_idx + 1:]

    df = pd.DataFrame(data, columns=headers)
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    print(f"'{tab_name}': {len(df)} data rows loaded")
    if df.empty:
        print(f"Warning: '{tab_name}' has no data rows yet.")

    return df


def filter_odk_by_side(df: pd.DataFrame, side: str) -> pd.DataFrame:
    """Filters an already-loaded ODK DataFrame to rows where the side column
    exactly matches `side` ('D' or 'O'). Nothing here touches PLAY TYPE
    values - that normalization happens once, in analyze_tendencies.py, via
    analysis.add_situational_columns()."""
    if df.empty:
        return df

    if config.COL_SIDE not in df.columns:
        print(f"ERROR: ODK data has no '{config.COL_SIDE}' column. "
              f"Found columns: {list(df.columns)}")
        return df

    filtered = df[df[config.COL_SIDE].str.upper() == side.upper()].reset_index(drop=True)
    print(f"'{config.ODK_SHEET_NAME}': {len(filtered)} rows where {config.COL_SIDE} == '{side}'")

    # Diagnostic: show exactly what raw PLAY TYPE values are coming in, so a
    # casing/shorthand mismatch (e.g. "RUN", "R") is visible in the logs
    # instead of silently producing a 0/0 Run-Pass split downstream.
    if config.COL_PLAY_TYPE in filtered.columns:
        raw_values = filtered[config.COL_PLAY_TYPE].value_counts(dropna=False)
        print(f"Raw '{config.COL_PLAY_TYPE}' values for side '{side}': {raw_values.to_dict()}")
    else:
        print(f"WARNING: '{config.COL_PLAY_TYPE}' column not found in ODK. "
              f"Found columns: {list(filtered.columns)}")

    return filtered


def load_defense_live_df(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    """Convenience wrapper: loads ODK and returns only defensive snaps.
    Reads the sheet fresh each call - if you also need the offense side in
    the same run, load ODK once with load_sheet_as_df() and call
    filter_odk_by_side() twice instead, to avoid a second API read."""
    df = load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)
    return filter_odk_by_side(df, config.SIDE_DEFENSE)


def load_offense_live_df(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    """Convenience wrapper: loads ODK and returns only offensive snaps.
    Same caveat as load_defense_live_df - prefer a single shared read when
    loading both sides in one run."""
    df = load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)
    return filter_odk_by_side(df, config.SIDE_OFFENSE)


def write_report(spreadsheet: gspread.Spreadsheet, rows: List[List[str]],
                  sheet_name: str = config.OUTPUT_SHEET_NAME) -> gspread.Worksheet:
    """Clears (or creates) the given output tab and writes the report
    starting at A1. Every row is padded to the same width so the write is a
    clean rectangle. Returns the worksheet object for further formatting."""
    print(f"write_report: {len(rows)} rows -> '{sheet_name}'")
    if not rows:
        print("ERROR: 0 rows — not clearing tab.")
        return None

    try:
        ws = spreadsheet.worksheet(sheet_name)
        ws.clear()
        print(f"Cleared existing '{sheet_name}' tab")
    except gspread.exceptions.WorksheetNotFound:
        # Expanded to 12 columns (A-L) to naturally accommodate side-by-side splits
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=12)
        print(f"Created new '{sheet_name}' tab")

    max_width = max(len(row) for row in rows)
    padded_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    padded_rows = [row + [""] * (max_width - len(row)) for row in padded_rows]

    try:
        ws.update(range_name="A1", values=padded_rows, value_input_option="RAW")
    except TypeError:
        ws.update("A1", padded_rows, value_input_option="RAW")

    print(f"Wrote {len(padded_rows)} rows to '{sheet_name}'")
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
    # NOTE: these are CellFormat dicts (backgroundColor, textFormat, etc.
    # directly) - gspread's batch_format() wraps each one in
    # userEnteredFormat itself. Adding that wrapper here double-nests it
    # and the Sheets API rejects the request outright.
    blue_theme = {
        "backgroundColor": {"red": 0.04, "green": 0.22, "blue": 0.42},
        "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}, "bold": True, "fontSize": 11},
        "horizontalAlignment": "LEFT"
    }

    table_header_theme = {
        "backgroundColor": {"red": 0.92, "green": 0.92, "blue": 0.94},
        "textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0}, "bold": True, "fontSize": 10},
        "horizontalAlignment": "CENTER"
    }

    identifiers_theme = {
        "textFormat": {"bold": True},
        "horizontalAlignment": "LEFT"
    }

    center_metrics_theme = {
        "horizontalAlignment": "CENTER"
    }

    all_values = ws.get_all_values()
    formats = []

    # 1. Default font size across the whole written range (was a bogus
    # ws.update_configuration() call - not a real gspread method).
    formats.append({
        "range": f"A1:{max_cols_letter}{total_rows}",
        "format": {"textFormat": {"fontSize": 10}},
    })

    # 2. Base alignment formatting pass (Center numerical metrics across C through L)
    formats.append({
        "range": f"C1:{max_cols_letter}{total_rows}",
        "format": center_metrics_theme
    })

    # 3. Row by row rule parser scanning for dynamic styling placements
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

    ws.show_gridlines()
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

    green_format = {"backgroundColor": {"red": 0.88, "green": 0.95, "blue": 0.88}}
    red_format = {"backgroundColor": {"red": 0.97, "green": 0.87, "blue": 0.87}}

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