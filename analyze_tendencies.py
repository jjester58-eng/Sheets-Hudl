"""
Sheets-Hudl Tendency Analysis
------------------------------
Reads:
  - "ALL INFO SHEET"  -> live game data (this week's game, charted in real time)
  - "WEEKLY DATA"      -> scouted opponent film (3+ weeks, upcoming opponent)

Writes:
  - "DEF ANALYSIS"     -> tendency tables + a Live Game vs Scout comparison,
                          flagging any FRONT tendency by down/distance that
                          differs by 15%+ between the two

Column layout (both sheets, A:P):
  A: PLAY #    B: SERIES    C: DN        D: DIST      E: BACKFIELD
  F: OFF FORM  G: OFF PLAY  H: PROTECTION I: PLAY TYPE J: GN/LS
  K: FRONT     L: STUNT     M: BLITZ     N: COV       O: STR/WK
  P: DEF NOTES

Uses gspread only. Validates both source tabs exist and have data before
doing any analysis, and stops immediately with a clear message if not.
"""

import os
import sys
import json
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SOURCE_SHEET_NAME = "ALL INFO SHEET"
SCOUT_SHEET_NAME = "WEEKLY DATA"
OUTPUT_SHEET_NAME = "DEF ANALYSIS"

# How far apart Live Game vs Scout % has to be before we flag it as a "shift"
FLAG_THRESHOLD_PCT = 15.0


# ---------------------------------------------------------------------------
# Connection / setup
# ---------------------------------------------------------------------------

def get_client():
    """Authenticates with the service account and returns a gspread client."""
    creds_json = os.environ["GOOGLE_CREDS"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(gc):
    """Opens the target spreadsheet, stripping any accidental whitespace
    from the ID (a trailing space/newline from copy-paste is a common,
    hard-to-spot cause of 'not found' errors)."""
    raw_id = os.environ["SPREADSHEET_ID"]
    spreadsheet_id = raw_id.strip()

    if raw_id != spreadsheet_id:
        print("Warning: SPREADSHEET_ID had leading/trailing whitespace - stripped it.")

    print(f"Spreadsheet ID length: {len(spreadsheet_id)}")

    spreadsheet = gc.open_by_key(spreadsheet_id)
    print(f"Opened spreadsheet: '{spreadsheet.title}'")
    return spreadsheet


def validate_required_tabs(spreadsheet):
    """Confirms both source tabs exist before we do any analysis at all.
    Fails fast with a clear message rather than partway through."""
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Tabs found in spreadsheet: {existing_titles}")

    missing = [name for name in (SOURCE_SHEET_NAME, SCOUT_SHEET_NAME)
               if name not in existing_titles]

    if missing:
        print(f"ERROR: required tab(s) not found: {missing}")
        print(f"Available tabs are: {existing_titles}")
        print("Check for typos, extra spaces, or different capitalization "
              "in the tab name(s) above.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Reading + shaping data
# ---------------------------------------------------------------------------

def load_sheet_as_df(spreadsheet, tab_name):
    """Loads a tab into a DataFrame, adding a DIST_BUCKET column and coercing
    numeric fields. Fails fast with a clear message if the tab can't be read."""
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

    if "GN/LS" in df.columns:
        df["GN/LS"] = pd.to_numeric(df["GN/LS"], errors="coerce")

    if "DIST" in df.columns:
        df["DIST"] = pd.to_numeric(df["DIST"], errors="coerce")
        df["DIST_BUCKET"] = df["DIST"].apply(dist_bucket)

    if "DN" in df.columns:
        df["DN"] = pd.to_numeric(df["DN"], errors="coerce")

    return df


def dist_bucket(dist):
    """Buckets distance-to-go into Short/Med/Long for grouping."""
    if pd.isna(dist):
        return "Unknown"
    if dist <= 3:
        return "Short"
    if dist <= 7:
        return "Med"
    return "Long"


# ---------------------------------------------------------------------------
# Tendency calculations
# ---------------------------------------------------------------------------

def pct_table(df, group_cols, target_col):
    """Returns count and % breakdown of target_col within each group_cols combo."""
    if df.empty or target_col not in df.columns:
        return pd.DataFrame()

    counts = df.groupby(group_cols + [target_col]).size().reset_index(name="count")
    totals = df.groupby(group_cols).size().reset_index(name="total")
    merged = counts.merge(totals, on=group_cols)
    merged["pct"] = (merged["count"] / merged["total"] * 100).round(1)
    return merged


def build_tendency_tables(df, label):
    """Builds the core defensive-tendency breakdowns for one dataset
    (either the live game or the scout film)."""
    tables = {}
    if df.empty:
        return tables

    tables[f"{label} - FRONT by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "FRONT")
    tables[f"{label} - BLITZ by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "BLITZ")
    tables[f"{label} - COVERAGE by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "COV")
    tables[f"{label} - STUNT by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "STUNT")
    tables[f"{label} - FRONT by FORMATION"] = pct_table(df, ["OFF FORM"], "FRONT")
    tables[f"{label} - BLITZ by FORMATION"] = pct_table(df, ["OFF FORM"], "BLITZ")

    if "GN/LS" in df.columns and "FRONT" in df.columns:
        eff = df.groupby("FRONT")["GN/LS"].mean().round(1).reset_index()
        eff.columns = ["FRONT", "AVG GN/LS"]
        tables[f"{label} - Avg GN/LS by FRONT"] = eff

    return tables


def build_comparison(live_df, scout_df):
    """Compares Live Game vs Scout FRONT tendency by down/distance, flagging
    any combination where usage % differs by FLAG_THRESHOLD_PCT or more."""
    if live_df.empty or scout_df.empty:
        return pd.DataFrame()

    live_pct = pct_table(live_df, ["DN", "DIST_BUCKET"], "FRONT")
    scout_pct = pct_table(scout_df, ["DN", "DIST_BUCKET"], "FRONT")

    if live_pct.empty or scout_pct.empty:
        return pd.DataFrame()

    merged = live_pct.merge(
        scout_pct,
        on=["DN", "DIST_BUCKET", "FRONT"],
        how="outer",
        suffixes=(" (Live Game)", " (Scout)"),
    )
    merged["pct (Live Game)"] = merged["pct (Live Game)"].fillna(0)
    merged["pct (Scout)"] = merged["pct (Scout)"].fillna(0)
    merged["DIFF"] = (merged["pct (Live Game)"] - merged["pct (Scout)"]).round(1)
    merged["FLAG"] = merged["DIFF"].abs() >= FLAG_THRESHOLD_PCT
    merged = merged.sort_values("DIFF", key=abs, ascending=False)

    cols = ["DN", "DIST_BUCKET", "FRONT", "pct (Live Game)", "pct (Scout)", "DIFF", "FLAG"]
    return merged[cols]


# ---------------------------------------------------------------------------
# Writing results
# ---------------------------------------------------------------------------

def write_tables_to_sheet(spreadsheet, tables_in_order):
    """Clears (or creates) DEF ANALYSIS and writes each (title, dataframe)
    pair stacked vertically with a blank row between tables."""
    try:
        ws = spreadsheet.worksheet(OUTPUT_SHEET_NAME)
        ws.clear()
        print(f"Cleared existing '{OUTPUT_SHEET_NAME}' tab")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=OUTPUT_SHEET_NAME, rows=1000, cols=20)
        print(f"Created new '{OUTPUT_SHEET_NAME}' tab")

    rows = []
    for title, df in tables_in_order:
        rows.append([title])
        if df is None or df.empty:
            rows.append(["(no data)"])
        else:
            rows.append([str(c) for c in df.columns])
            for _, r in df.iterrows():
                rows.append([str(v) for v in r.tolist()])
        rows.append([])

    ws.update(rows, value_input_option="RAW")
    print(f"Wrote {len(rows)} rows to '{OUTPUT_SHEET_NAME}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    gc = get_client()
    spreadsheet = open_spreadsheet(gc)
    validate_required_tabs(spreadsheet)

    live_df = load_sheet_as_df(spreadsheet, SOURCE_SHEET_NAME)
    scout_df = load_sheet_as_df(spreadsheet, SCOUT_SHEET_NAME)

    live_tables = build_tendency_tables(live_df, "LIVE GAME")
    scout_tables = build_tendency_tables(scout_df, "SCOUT (3wk)")
    comparison = build_comparison(live_df, scout_df)

    output = [
        ("Live Game vs Scout - FRONT tendency comparison "
         f"(flagged if diff >= {FLAG_THRESHOLD_PCT}%)", comparison)
    ]
    output += list(live_tables.items())
    output += list(scout_tables.items())

    write_tables_to_sheet(spreadsheet, output)
    print("Done.")


if __name__ == "__main__":
    main()
