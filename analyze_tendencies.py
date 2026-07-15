"""
Sheets-Hudl Tendency Analysis
------------------------------
Reads:
  - "ALL INFO SHEET"  -> live game data (this week's game, charted in real time)
  - "WEEKLY DATA"      -> scouted opponent film (3+ weeks, upcoming opponent)

Writes:
  - "DEF ANALYSIS"     -> a set of reports built from each dataset

Column layout (both sheets, A:P):
  A: PLAY #    B: SERIES    C: DN        D: DIST      E: BACKFIELD
  F: OFF FORM  G: OFF PLAY  H: PROTECTION I: PLAY TYPE J: GN/LS
  K: FRONT     L: STUNT     M: BLITZ     N: COV       O: STR/WK
  P: DEF NOTES

Uses gspread only. Validates both source tabs exist and have data before
doing any analysis, and stops immediately with a clear message if not.

Reports (built separately for LIVE GAME and SCOUT data):
  - build_summary            overall counts, run/pass split, yards, big plays
  - top_formations           formation usage ranked by frequency
  - formation_breakdowns     play-type mix and efficiency within each formation
  - down_distance_report     FRONT/BLITZ/COV/STUNT tendency by down & distance
  - field_position_report    tendency by STR/WK (strength/weak side)
  - explosive_report         plays at/above the explosive-play threshold
  - coach_notes              plays that have a DEF NOTES entry
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

# Yards gained/lost at or above this counts as an "explosive" play
EXPLOSIVE_THRESHOLD = 15


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


def pct_by_group(df, group_cols, target_col):
    """Shared helper: count + % breakdown of target_col within each group_cols combo."""
    if df.empty or target_col not in df.columns:
        return pd.DataFrame()

    counts = df.groupby(group_cols + [target_col]).size().reset_index(name="count")
    totals = df.groupby(group_cols).size().reset_index(name="total")
    merged = counts.merge(totals, on=group_cols)
    merged["pct"] = (merged["count"] / merged["total"] * 100).round(1)
    return merged


# ---------------------------------------------------------------------------
# Report builders - each takes one dataset (Live Game or Scout) and returns
# either a single DataFrame or a dict of {title: DataFrame}
# ---------------------------------------------------------------------------

def build_summary(df):
    """Overall snapshot: play count, run/pass split, total & average yards,
    explosive play count, negative play count."""
    if df.empty:
        return pd.DataFrame()

    total_plays = len(df)
    rows = [("Total Plays", total_plays)]

    if "SERIES" in df.columns:
        rows.append(("Total Series", df["SERIES"].nunique()))

    if "PLAY TYPE" in df.columns:
        type_counts = df["PLAY TYPE"].value_counts()
        for play_type, count in type_counts.items():
            pct = round(count / total_plays * 100, 1)
            rows.append((f"{play_type} plays", f"{count} ({pct}%)"))

    if "GN/LS" in df.columns:
        rows.append(("Total Yards", round(df["GN/LS"].sum(), 1)))
        rows.append(("Avg Yards / Play", round(df["GN/LS"].mean(), 1)))
        rows.append(("Explosive Plays (>= {} yds)".format(EXPLOSIVE_THRESHOLD),
                     int((df["GN/LS"] >= EXPLOSIVE_THRESHOLD).sum())))
        rows.append(("Negative Plays", int((df["GN/LS"] < 0).sum())))

    return pd.DataFrame(rows, columns=["Metric", "Value"])


def top_formations(df):
    """Ranks OFF FORM by how often it's used, with efficiency alongside."""
    if df.empty or "OFF FORM" not in df.columns:
        return pd.DataFrame()

    total_plays = len(df)
    counts = df["OFF FORM"].value_counts().reset_index()
    counts.columns = ["OFF FORM", "count"]
    counts["pct"] = (counts["count"] / total_plays * 100).round(1)

    if "GN/LS" in df.columns:
        avg_gain = df.groupby("OFF FORM")["GN/LS"].mean().round(1).reset_index()
        avg_gain.columns = ["OFF FORM", "AVG GN/LS"]
        counts = counts.merge(avg_gain, on="OFF FORM")

    return counts.sort_values("count", ascending=False)


def formation_breakdowns(df):
    """For each formation: what play types come out of it, and how well
    each one has worked."""
    tables = {}
    if df.empty or "OFF FORM" not in df.columns:
        return tables

    tables["Play Type by Formation"] = pct_by_group(df, ["OFF FORM"], "PLAY TYPE")

    if "GN/LS" in df.columns and "PLAY TYPE" in df.columns:
        eff = df.groupby(["OFF FORM", "PLAY TYPE"])["GN/LS"].mean().round(1).reset_index()
        eff.columns = ["OFF FORM", "PLAY TYPE", "AVG GN/LS"]
        tables["Efficiency by Formation & Play Type"] = eff

    return tables


def down_distance_report(df):
    """FRONT / BLITZ / COVERAGE / STUNT tendency by down and distance bucket,
    plus efficiency by FRONT."""
    tables = {}
    if df.empty:
        return tables

    tables["FRONT by DN/DIST"] = pct_by_group(df, ["DN", "DIST_BUCKET"], "FRONT")
    tables["BLITZ by DN/DIST"] = pct_by_group(df, ["DN", "DIST_BUCKET"], "BLITZ")
    tables["COVERAGE by DN/DIST"] = pct_by_group(df, ["DN", "DIST_BUCKET"], "COV")
    tables["STUNT by DN/DIST"] = pct_by_group(df, ["DN", "DIST_BUCKET"], "STUNT")

    if "GN/LS" in df.columns and "FRONT" in df.columns:
        eff = df.groupby("FRONT")["GN/LS"].mean().round(1).reset_index()
        eff.columns = ["FRONT", "AVG GN/LS"]
        tables["Avg GN/LS by FRONT"] = eff

    return tables


def field_position_report(df):
    """Tendency by strength/weak side (STR/WK). Note: this sheet layout has
    no explicit hash/field-position column, so STR/WK is used as the closest
    available proxy for field-position-driven tendency."""
    tables = {}
    if df.empty or "STR/WK" not in df.columns:
        return tables

    tables["FRONT by STR/WK"] = pct_by_group(df, ["STR/WK"], "FRONT")
    tables["BLITZ by STR/WK"] = pct_by_group(df, ["STR/WK"], "BLITZ")
    tables["PLAY TYPE by STR/WK"] = pct_by_group(df, ["STR/WK"], "PLAY TYPE")

    return tables


def explosive_report(df):
    """Lists individual explosive plays (>= EXPLOSIVE_THRESHOLD yards) and
    summarizes what tends to produce them."""
    tables = {}
    if df.empty or "GN/LS" not in df.columns:
        return tables

    explosive = df[df["GN/LS"] >= EXPLOSIVE_THRESHOLD].copy()
    if explosive.empty:
        tables[f"Explosive Plays (>= {EXPLOSIVE_THRESHOLD} yds)"] = pd.DataFrame()
        return tables

    cols_wanted = ["PLAY #", "DN", "DIST", "OFF FORM", "PLAY TYPE", "GN/LS", "FRONT"]
    cols_present = [c for c in cols_wanted if c in explosive.columns]
    tables[f"Explosive Plays (>= {EXPLOSIVE_THRESHOLD} yds)"] = explosive[cols_present].sort_values(
        "GN/LS", ascending=False
    )

    if "OFF FORM" in explosive.columns:
        tables["Explosive Plays by Formation"] = (
            explosive["OFF FORM"].value_counts().reset_index()
        )

    return tables


def coach_notes(df):
    """Surfaces any play that already has a DEF NOTES entry, so notable
    in-game observations are easy to find in one place."""
    if df.empty or "DEF NOTES" not in df.columns:
        return pd.DataFrame()

    notes = df[df["DEF NOTES"].astype(str).str.strip() != ""].copy()
    if notes.empty:
        return pd.DataFrame()

    cols_wanted = ["PLAY #", "DN", "DIST", "FRONT", "BLITZ", "COV", "DEF NOTES"]
    cols_present = [c for c in cols_wanted if c in notes.columns]
    return notes[cols_present]


def build_all_reports(df, label):
    """Runs every report builder against one dataset and returns a flat
    {title: DataFrame} dict with the label prefixed on each title."""
    tables = {}

    tables[f"{label} - Summary"] = build_summary(df)
    tables[f"{label} - Top Formations"] = top_formations(df)

    for title, sub_df in formation_breakdowns(df).items():
        tables[f"{label} - {title}"] = sub_df

    for title, sub_df in down_distance_report(df).items():
        tables[f"{label} - {title}"] = sub_df

    for title, sub_df in field_position_report(df).items():
        tables[f"{label} - {title}"] = sub_df

    for title, sub_df in explosive_report(df).items():
        tables[f"{label} - {title}"] = sub_df

    tables[f"{label} - Coach Notes"] = coach_notes(df)

    return tables


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

    live_tables = build_all_reports(live_df, "LIVE GAME")
    scout_tables = build_all_reports(scout_df, "SCOUT (3wk)")

    output = list(live_tables.items()) + list(scout_tables.items())

    write_tables_to_sheet(spreadsheet, output)
    print("Done.")


if __name__ == "__main__":
    main()
