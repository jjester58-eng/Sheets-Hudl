"""
Sheets-Hudl Tendency Analysis
------------------------------
Reads:
  - "ALL INFO SHEET"  -> live game data (this week's game, charted in real time)
  - "WEEKLY DATA"      -> scouted opponent film (3+ weeks, upcoming opponent)

Writes:
  - "DEF ANALYSIS"     -> side-by-side offensive reports:
                            Live Game in columns A:E
                            Scout (3wk) in columns G:K
                            (column F left blank as a visual gap)

Column layout (both sheets, A:P):
  A: PLAY #    B: SERIES    C: DN        D: DIST      E: BACKFIELD
  F: OFF FORM  G: OFF PLAY  H: PROTECTION I: PLAY TYPE J: GN/LS
  K: FRONT     L: STUNT     M: BLITZ     N: COV       O: STR/WK
  P: DEF NOTES

This version only looks at offensive tendencies (formation, play type,
down/distance, explosive plays). FRONT, STUNT, BLITZ, COV, and STR/WK are
not used.

Uses gspread only. Validates both source tabs exist and have data before
doing any analysis, and stops immediately with a clear message if not.

Reports (built separately for LIVE GAME and SCOUT data):
  - build_summary            overall counts, run/pass split, yards, big plays
  - top_formations           formation usage ranked by frequency
  - formation_breakdowns     play-type mix and efficiency within each formation
  - down_distance_report     play-type tendency by down & distance
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

# How far apart Live vs Scout % has to be before we flag it as a tendency shift
FLAG_THRESHOLD_PCT = 15.0

# Side-by-side layout: Live Game in A:E, gap at F, Scout in G:K
LEFT_WIDTH = 5
RIGHT_WIDTH = 5


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
    return merged.drop(columns=["total"])


# ---------------------------------------------------------------------------
# Report builders - each takes one dataset (Live Game or Scout) and returns
# either a single DataFrame or a dict of {title: DataFrame}.
# All tables are kept to 5 columns or fewer to fit the side-by-side layout.
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
        rows.append((f"Explosive Plays (>= {EXPLOSIVE_THRESHOLD} yds)",
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
    """Play-type tendency by down and distance bucket (offense only -
    no defensive front/coverage data used)."""
    if df.empty or "PLAY TYPE" not in df.columns:
        return pd.DataFrame()

    return pct_by_group(df, ["DN", "DIST_BUCKET"], "PLAY TYPE")


def explosive_report(df):
    """Lists individual explosive plays (>= EXPLOSIVE_THRESHOLD yards) and
    summarizes which formation tends to produce them."""
    tables = {}
    if df.empty or "GN/LS" not in df.columns:
        return tables

    explosive = df[df["GN/LS"] >= EXPLOSIVE_THRESHOLD].copy()
    title = f"Explosive Plays (>= {EXPLOSIVE_THRESHOLD} yds)"

    if explosive.empty:
        tables[title] = pd.DataFrame()
        return tables

    if "DN" in explosive.columns and "DIST" in explosive.columns:
        explosive["SITUATION"] = (
            explosive["DN"].astype("Int64").astype(str) + " & " + explosive["DIST"].astype("Int64").astype(str)
        )

    cols_wanted = ["PLAY #", "SITUATION", "OFF FORM", "PLAY TYPE", "GN/LS"]
    cols_present = [c for c in cols_wanted if c in explosive.columns]
    tables[title] = explosive[cols_present].sort_values("GN/LS", ascending=False)

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

    cols_wanted = ["PLAY #", "DN", "DIST", "DEF NOTES"]
    cols_present = [c for c in cols_wanted if c in notes.columns]
    return notes[cols_present]


def build_all_reports(df):
    """Runs every report builder against one dataset and returns an ordered
    list of (title, DataFrame) tuples, ready to stack into a column block."""
    tables = []

    tables.append(("Summary", build_summary(df)))
    tables.append(("Top Formations", top_formations(df)))

    for title, sub_df in formation_breakdowns(df).items():
        tables.append((title, sub_df))

    tables.append(("Play Type by Down/Distance", down_distance_report(df)))

    for title, sub_df in explosive_report(df).items():
        tables.append((title, sub_df))

    tables.append(("Coach Notes", coach_notes(df)))

    return tables


def compare_situational_tendency(live_df, scout_df, group_cols, target_col):
    """Compares % usage of target_col within each group_cols combo between
    Live Game and Scout data, flagging differences >= FLAG_THRESHOLD_PCT."""
    live_pct = pct_by_group(live_df, group_cols, target_col)
    scout_pct = pct_by_group(scout_df, group_cols, target_col)

    if live_pct.empty or scout_pct.empty:
        return pd.DataFrame()

    merged = live_pct.merge(
        scout_pct,
        on=group_cols + [target_col],
        how="outer",
        suffixes=(" (Live)", " (Scout)"),
    )
    merged["pct (Live)"] = merged["pct (Live)"].fillna(0)
    merged["pct (Scout)"] = merged["pct (Scout)"].fillna(0)
    merged["DIFF"] = (merged["pct (Live)"] - merged["pct (Scout)"]).round(1)
    merged["FLAG"] = merged["DIFF"].abs() >= FLAG_THRESHOLD_PCT
    merged = merged.sort_values("DIFF", key=abs, ascending=False)

    cols = group_cols + [target_col, "pct (Live)", "pct (Scout)", "DIFF", "FLAG"]
    return merged[cols]


def compare_formation_usage(live_df, scout_df):
    """Compares overall formation usage % between Live Game and Scout data,
    flagging differences >= FLAG_THRESHOLD_PCT. Handled separately from
    compare_situational_tendency since it isn't grouped by a situation."""
    if live_df.empty or scout_df.empty or "OFF FORM" not in live_df.columns:
        return pd.DataFrame()

    live_total = len(live_df)
    scout_total = len(scout_df)
    live_counts = live_df["OFF FORM"].value_counts()
    scout_counts = scout_df["OFF FORM"].value_counts()
    all_forms = sorted(set(live_counts.index) | set(scout_counts.index))

    rows = []
    for form in all_forms:
        live_pct = round(live_counts.get(form, 0) / live_total * 100, 1) if live_total else 0.0
        scout_pct = round(scout_counts.get(form, 0) / scout_total * 100, 1) if scout_total else 0.0
        diff = round(live_pct - scout_pct, 1)
        rows.append((form, live_pct, scout_pct, diff, abs(diff) >= FLAG_THRESHOLD_PCT))

    out = pd.DataFrame(rows, columns=["OFF FORM", "pct (Live)", "pct (Scout)", "DIFF", "FLAG"])
    return out.sort_values("DIFF", key=abs, ascending=False)


def build_comparison_tables(live_df, scout_df):
    """Returns the ordered list of (title, df) comparison tables that go
    in the full-width section below the two side-by-side blocks."""
    tables = []

    play_type_cmp = compare_situational_tendency(live_df, scout_df, ["DN", "DIST_BUCKET"], "PLAY TYPE")
    tables.append((f"Play Type Tendency: Live vs Scout (flag if diff >= {FLAG_THRESHOLD_PCT}%)", play_type_cmp))

    formation_cmp = compare_formation_usage(live_df, scout_df)
    tables.append((f"Formation Usage: Live vs Scout (flag if diff >= {FLAG_THRESHOLD_PCT}%)", formation_cmp))

    return tables


# ---------------------------------------------------------------------------
# Writing results - side by side layout
# ---------------------------------------------------------------------------

def build_column_block(tables_in_order, width):
    """Stacks (title, df) pairs into a list of rows, each row padded/truncated
    to exactly `width` columns."""
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

    padded = [(row + [""] * width)[:width] for row in rows]
    return padded


def combine_side_by_side(left_rows, right_rows):
    """Merges two column blocks into one grid: left block, one blank gap
    column, then right block."""
    max_len = max(len(left_rows), len(right_rows))
    grid = []
    for i in range(max_len):
        left = left_rows[i] if i < len(left_rows) else [""] * LEFT_WIDTH
        right = right_rows[i] if i < len(right_rows) else [""] * RIGHT_WIDTH
        grid.append(left + [""] + right)
    return grid


def write_side_by_side(spreadsheet, live_tables, scout_tables, comparison_tables):
    """Clears (or creates) DEF ANALYSIS and writes Live Game in A:E and
    Scout in G:K, with column F left blank as a visual gap. A full-width
    comparison section is appended below both blocks."""
    try:
        ws = spreadsheet.worksheet(OUTPUT_SHEET_NAME)
        ws.clear()
        print(f"Cleared existing '{OUTPUT_SHEET_NAME}' tab")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=OUTPUT_SHEET_NAME, rows=1000, cols=20)
        print(f"Created new '{OUTPUT_SHEET_NAME}' tab")

    left_rows = [["LIVE GAME"]] + [[""] * LEFT_WIDTH] + build_column_block(live_tables, LEFT_WIDTH)
    right_rows = [["SCOUT (3wk)"]] + [[""] * RIGHT_WIDTH] + build_column_block(scout_tables, RIGHT_WIDTH)

    left_rows = [(row + [""] * LEFT_WIDTH)[:LEFT_WIDTH] for row in left_rows]
    right_rows = [(row + [""] * RIGHT_WIDTH)[:RIGHT_WIDTH] for row in right_rows]

    grid = combine_side_by_side(left_rows, right_rows)
    full_width = LEFT_WIDTH + 1 + RIGHT_WIDTH  # match total sheet width used above

    comparison_header = [["TENDENCY COMPARISON (LIVE vs SCOUT)"]] + [[""] * full_width]
    comparison_block = build_column_block(comparison_tables, full_width)
    comparison_rows = [(row + [""] * full_width)[:full_width] for row in comparison_header + comparison_block]

    gap_row = [[""] * full_width]
    full_grid = grid + gap_row + comparison_rows

    ws.update(range_name="A1", values=full_grid, value_input_option="RAW")
    print(f"Wrote {len(full_grid)} rows to '{OUTPUT_SHEET_NAME}' "
          f"(Live Game A:E, Scout G:K, comparison below)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    gc = get_client()
    spreadsheet = open_spreadsheet(gc)
    validate_required_tabs(spreadsheet)

    live_df = load_sheet_as_df(spreadsheet, SOURCE_SHEET_NAME)
    scout_df = load_sheet_as_df(spreadsheet, SCOUT_SHEET_NAME)

    live_tables = build_all_reports(live_df)
    scout_tables = build_all_reports(scout_df)
    comparison_tables = build_comparison_tables(live_df, scout_df)

    write_side_by_side(spreadsheet, live_tables, scout_tables, comparison_tables)
    print("Done.")


if __name__ == "__main__":
    main()
