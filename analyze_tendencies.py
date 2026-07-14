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

This script talks to the Sheets API directly (no gspread) so that any
error response -- JSON or not -- gets printed in full instead of crashing
inside a library's own error-handling code.
"""

import os
import json
import urllib.parse
import pandas as pd
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SOURCE_SHEET_NAME = "ALL INFO SHEET"
SCOUT_SHEET_NAME = "WEEKLY DATA"
OUTPUT_SHEET_NAME = "DEF ANALYSIS"

FLAG_THRESHOLD_PCT = 15.0

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


def get_session():
    creds_json = os.environ["GOOGLE_CREDS"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return AuthorizedSession(creds)


def quoted_range(tab_name):
    """Sheet names with spaces must be single-quoted inside the A1 range."""
    escaped = tab_name.replace("'", "''")
    return urllib.parse.quote(f"'{escaped}'")


def get_sheet_metadata(session, spreadsheet_id):
    """Returns list of existing tab titles in the spreadsheet."""
    url = f"{SHEETS_API}/{spreadsheet_id}"
    resp = session.get(url)
    print(f"[metadata] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[metadata] Response body (first 1000 chars): {resp.text[:1000]}")
        resp.raise_for_status()
    data = resp.json()
    return [s["properties"]["title"] for s in data.get("sheets", [])]


def fetch_values(session, spreadsheet_id, tab_name):
    url = f"{SHEETS_API}/{spreadsheet_id}/values/{quoted_range(tab_name)}"
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
    padded = [r + [""] * (len(header) - len(r)) for r in rows]
    return pd.DataFrame(padded, columns=header)


def load_sheet_as_df(session, spreadsheet_id, tab_name):
    try:
        values = fetch_values(session, spreadsheet_id, tab_name)
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


def ensure_output_tab_exists(session, spreadsheet_id, tab_name):
    titles = get_sheet_metadata(session, spreadsheet_id)
    if tab_name in titles:
        return

    print(f"Creating missing tab: {tab_name}")
    url = f"{SHEETS_API}/{spreadsheet_id}:batchUpdate"
    body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    resp = session.post(url, json=body)
    print(f"[create tab] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[create tab] Response body (first 1000 chars): {resp.text[:1000]}")
        resp.raise_for_status()


def clear_output_tab(session, spreadsheet_id, tab_name):
    url = f"{SHEETS_API}/{spreadsheet_id}/values/{quoted_range(tab_name)}:clear"
    resp = session.post(url)
    print(f"[clear {tab_name}] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[clear {tab_name}] Response body (first 1000 chars): {resp.text[:1000]}")
        resp.raise_for_status()


def write_tables_to_sheet(session, spreadsheet_id, tables_in_order):
    ensure_output_tab_exists(session, spreadsheet_id, OUTPUT_SHEET_NAME)
    clear_output_tab(session, spreadsheet_id, OUTPUT_SHEET_NAME)

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

    url = f"{SHEETS_API}/{spreadsheet_id}/values/{quoted_range(OUTPUT_SHEET_NAME)}"
    params = {"valueInputOption": "RAW"}
    body = {"values": rows}
    resp = session.put(url, params=params, json=body)
    print(f"[write {OUTPUT_SHEET_NAME}] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[write {OUTPUT_SHEET_NAME}] Response body (first 1000 chars): {resp.text[:1000]}")
        resp.raise_for_status()


def main():
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    print(f"Spreadsheet ID length: {len(spreadsheet_id)}")  # sanity check, no leak
    session = get_session()

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

    write_tables_to_sheet(session, spreadsheet_id, output)
    print("Done. Wrote results to:", OUTPUT_SHEET_NAME)


if __name__ == "__main__":
    main()
