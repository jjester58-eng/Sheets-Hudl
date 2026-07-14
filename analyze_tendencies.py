"""
Sheets-Hudl Tendency Analysis
------------------------------
Reads:
  - "ALL INFO SHEET"  -> live game data (this week's game, charted in real time)
  - "WEEKLY DATA"      -> scouted opponent film (3+ weeks, upcoming opponent)

Writes:
  - "DEF ANALYSIS"     -> tendency tables + a comparison flagging where
                          this week's live game tendencies and scout
                          tendencies disagree

Column layout (both sheets, A:P):
  A: PLAY #    B: SERIES    C: DN        D: DIST      E: BACKFIELD
  F: OFF FORM  G: OFF PLAY  H: PROTECTION I: PLAY TYPE J: GN/LS
  K: FRONT     L: STUNT     M: BLITZ     N: COV       O: STR/WK
  P: DEF NOTES
"""

import os
import json
import urllib.parse
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SOURCE_SHEET_NAME = "ALL INFO SHEET"
SCOUT_SHEET_NAME = "WEEKLY DATA"
OUTPUT_SHEET_NAME = "DEF ANALYSIS"

# How far apart live-game vs scout % has to be before we flag it as a "shift"
FLAG_THRESHOLD_PCT = 15.0


def get_credentials():
    creds_json = os.environ["GOOGLE_CREDS"]
    creds_dict = json.loads(creds_json)
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)


def get_client(creds):
    return gspread.authorize(creds)


def fetch_values_raw(session, spreadsheet_id, tab_name):
    """Calls the Sheets API directly so we can see the real status/body on failure."""
    encoded_tab = urllib.parse.quote(tab_name)
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_tab}"
    resp = session.get(url)
    print(f"[{tab_name}] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[{tab_name}] Response body (first 1000 chars): {resp.text[:1000]}")
        resp.raise_for_status()
    data = resp.json()
    return data.get("values", [])


def values_to_df(values):
    if not values or len(values) < 1:
        return pd.DataFrame()

    header = values[0]
    rows = values[1:]
    # pad short rows so every row matches the header length
    padded = [r + [""] * (len(header) - len(r)) for r in rows]
    df = pd.DataFrame(padded, columns=header)
    return df


def load_sheet_as_df(session, spreadsheet_id, tab_name):
    try:
        values = fetch_values_raw(session, spreadsheet_id, tab_name)
    except Exception as e:
        print(f"Failed to read '{tab_name}': {type(e).__name__}: {e}")
        return pd.DataFrame()

    print(f"'{tab_name}': {len(values)} rows fetched (including header)")

    df = values_to_df(values)

    if df.empty:
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
    if pd.isna(dist):
        return "Unknown"
    if dist <= 3:
        return "Short"
    if dist <= 7:
        return "Med"
    return "Long"


def pct_table(df, group_cols, target_col):
    if df.empty or target_col not in df.columns:
        return pd.DataFrame()

    counts = df.groupby(group_cols + [target_col]).size().reset_index(name="count")
    totals = df.groupby(group_cols).size().reset_index(name="total")
    merged = counts.merge(totals, on=group_cols)
    merged["pct"] = (merged["count"] / merged["total"] * 100).round(1)
    return merged


def build_tendency_tables(df, label):
    tables = {}

    if df.empty:
        return tables

    tables[f"{label} - FRONT by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "FRONT")
    tables[f"{label} - BLITZ by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "BLITZ")
    tables[f"{label} - COV by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "COV")
    tables[f"{label} - STUNT by DN/DIST"] = pct_table(df, ["DN", "DIST_BUCKET"], "STUNT")
    tables[f"{label} - FRONT by OFF FORM"] = pct_table(df, ["OFF FORM"], "FRONT")
    tables[f"{label} - BLITZ by OFF FORM"] = pct_table(df, ["OFF FORM"], "BLITZ")

    if "GN/LS" in df.columns:
        eff = df.groupby(["FRONT"])["GN/LS"].mean().round(1).reset_index()
        eff.columns = ["FRONT", "AVG GN/LS"]
        tables[f"{label} - Efficiency by FRONT"] = eff

    return tables


def build_comparison(live_df, scout_df):
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


def write_tables_to_sheet(spreadsheet, tables_in_order):
    try:
        ws = spreadsheet.worksheet(OUTPUT_SHEET_NAME)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=OUTPUT_SHEET_NAME, rows=500, cols=20)

    rows = []
    for title, df in tables_in_order:
        rows.append([title])
        if df is None or df.empty:
            rows.append(["(no data)"])
        else:
            rows.append(list(df.columns))
            for _, r in df.iterrows():
                rows.append([str(v) for v in r.tolist()])
        rows.append([])

    ws.update(rows, value_input_option="RAW")


def main():
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    creds = get_credentials()
    session = AuthorizedSession(creds)

    live_df = load_sheet_as_df(session, spreadsheet_id, SOURCE_SHEET_NAME)
    scout_df = load_sheet_as_df(session, spreadsheet_id, SCOUT_SHEET_NAME)

    live_tables = build_tendency_tables(live_df, "LIVE GAME")
    scout_tables = build_tendency_tables(scout_df, "SCOUT (3wk)")
    comparison = build_comparison(live_df, scout_df)

    output = []
    output.append(("Live Game vs Scout - FRONT tendency comparison (flagged if diff >= "
                    f"{FLAG_THRESHOLD_PCT}%)", comparison))

    for title, df in live_tables.items():
        output.append((title, df))
    for title, df in scout_tables.items():
        output.append((title, df))

    gc = get_client(creds)
    spreadsheet = gc.open_by_key(spreadsheet_id)
    write_tables_to_sheet(spreadsheet, output)
    print("Done. Wrote results to:", OUTPUT_SHEET_NAME)


if __name__ == "__main__":
    main()
