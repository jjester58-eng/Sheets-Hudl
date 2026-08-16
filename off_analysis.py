"""
off_analysis.py
---------------
Offensive analysis from the ODK sheet.

SOURCE OF TRUTH:
    ODK

ANALYZE:
    O = Our offense

IGNORE:
    D = Opponent offense
    S = Special teams
    K = Special teams
    blank = No play

ODK columns used:
    B = ODK
    C = DN
    D = DIST
    F = GN/LS
    G = YARD LN
    H = PLAY TYPE
    J = OFF FORM
    M = OFF PLAY

REPORT:
    OFF ANALYSIS
"""

import os
import json
import re
from collections import Counter, defaultdict

import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_SHEET = "ODK"
OUTPUT_SHEET = "OFF ANALYSIS"

REQUIRED_ENV = [
    "SPREADSHEET_ID",
    "GOOGLE_CREDS",
]


# ============================================================
# ENVIRONMENT
# ============================================================

def get_environment():
    missing = [
        key for key in REQUIRED_ENV
        if not os.environ.get(key)
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    return (
        os.environ["SPREADSHEET_ID"],
        os.environ["GOOGLE_CREDS"],
    )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_to_sheets():

    spreadsheet_id, google_creds = get_environment()

    try:
        # Supports JSON credentials stored in GitHub Secrets
        creds_data = json.loads(google_creds)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            "GOOGLE_CREDS is not valid JSON."
        ) from e

    creds = Credentials.from_service_account_info(
        creds_data,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )

    client = gspread.authorize(creds)

    return client.open_by_key(spreadsheet_id)


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_header(value):
    """
    Converts headers such as:

        " OFF FORM "
        "Off Form"
        "OFF   FORM"

    into:

        "OFF FORM"
    """

    return re.sub(
        r"\s+",
        " ",
        clean(value).upper()
    )


def number(value):
    """
    Convert sheet value to float.

    Handles:
        5
        -3
        +5
        5.0
        5 yards
        blank
    """

    if value is None:
        return None

    text = clean(value)

    if not text:
        return None

    text = (
        text
        .replace("+", "")
        .replace("yards", "")
        .replace("yard", "")
        .strip()
    )

    try:
        return float(text)

    except ValueError:
        return None


def pct(success, attempts):

    if attempts == 0:
        return 0

    return success / attempts


def fmt_pct(value):

    return f"{value * 100:.1f}%"


# ============================================================
# LOAD ODK
# ============================================================

def load_offensive_plays(spreadsheet):

    ws = spreadsheet.worksheet(INPUT_SHEET)

    values = ws.get_all_values()

    if not values:
        return []

    # --------------------------------------------------------
    # NORMALIZE HEADERS
    # --------------------------------------------------------

    raw_headers = values[0]

    headers = [
        normalize_header(header)
        for header in raw_headers
    ]

    required_headers = [
        "ODK",
        "DN",
        "DIST",
        "GN/LS",
        "YARD LN",
        "PLAY TYPE",
        "OFF FORM",
        "OFF PLAY",
    ]

    missing = [
        header
        for header in required_headers
        if header not in headers
    ]

    if missing:
        raise RuntimeError(
            "ODK is missing required columns: "
            + ", ".join(missing)
        )

    # Map normalized header → column index
    header_index = {
        header: index
        for index, header in enumerate(headers)
    }

    plays = []

    # --------------------------------------------------------
    # READ DATA
    # --------------------------------------------------------

    for raw_row in values[1:]:

        # Make row same length as header
        row = raw_row + [""] * (
            len(headers) - len(raw_row)
        )

        def get(column):
            index = header_index[column]

            if index >= len(row):
                return ""

            return row[index]

        # ----------------------------------------------------
        # ONLY OUR OFFENSE
        # ----------------------------------------------------

        odk = clean(get("ODK")).upper()

        if odk != "O":
            continue

        # ----------------------------------------------------
        # RUN / PASS ONLY
        # ----------------------------------------------------

        play_type = clean(
            get("PLAY TYPE")
        ).upper()

        if play_type not in ("RUN", "PASS"):
            continue

        # ----------------------------------------------------
        # GAIN / LOSS
        # ----------------------------------------------------

        gain = number(get("GN/LS"))

        if gain is None:
            continue

        # ----------------------------------------------------
        # OTHER DATA
        # ----------------------------------------------------

        down = number(get("DN"))
        distance = number(get("DIST"))
        yard_line = number(get("YARD LN"))

        formation = clean(get("OFF FORM"))
        play = clean(get("OFF PLAY"))

        plays.append({
            "play_type": play_type,
            "gain": gain,
            "down": down,
            "distance": distance,
            "yard_line": yard_line,
            "formation": formation or "(No Formation)",
            "play": play or "(No Play)",
        })

    return plays


# ============================================================
# RUN EFFICIENCY
# ============================================================

def run_efficiency(plays):

    counts = defaultdict(
        lambda: {
            "attempts": 0,
            "success": 0,
            "yards": 0,
        }
    )

    for p in plays:

        if p["play_type"] != "RUN":
            continue

        key = (
            p["formation"],
            p["play"],
        )

        counts[key]["attempts"] += 1
        counts[key]["yards"] += p["gain"]

        # 4+ yard run
        if p["gain"] >= 4:
            counts[key]["success"] += 1

    return counts


# ============================================================
# EXPLOSIVE RUNS
# ============================================================

def explosive_runs(plays):

    return Counter(
        (
            p["formation"],
            p["play"],
        )
        for p in plays
        if p["play_type"] == "RUN"
        and p["gain"] >= 10
    )


# ============================================================
# PASS EFFICIENCY
# ============================================================

def pass_efficiency(plays):

    counts = defaultdict(
        lambda: {
            "attempts": 0,
            "success": 0,
            "yards": 0,
        }
    )

    for p in plays:

        if p["play_type"] != "PASS":
            continue

        key = (
            p["formation"],
            p["play"],
        )

        counts[key]["attempts"] += 1
        counts[key]["yards"] += p["gain"]

        # 7+ yard pass
        if p["gain"] >= 7:
            counts[key]["success"] += 1

    return counts


# ============================================================
# EXPLOSIVE PASSES
# ============================================================

def explosive_passes(plays):

    return Counter(
        (
            p["formation"],
            p["play"],
        )
        for p in plays
        if p["play_type"] == "PASS"
        and p["gain"] >= 15
    )


# ============================================================
# RED ZONE
# ============================================================

def red_zone(plays):

    counts = defaultdict(
        lambda: {
            "plays": 0,
            "success": 0,
            "yards": 0,
        }
    )

    for p in plays:

        yard_line = p["yard_line"]

        if yard_line is None:
            continue

        # 25 yards and in
        if not (1 <= yard_line <= 25):
            continue

        key = (
            p["formation"],
            p["play"],
        )

        counts[key]["plays"] += 1
        counts[key]["yards"] += p["gain"]

        # Positive gain
        if p["gain"] > 0:
            counts[key]["success"] += 1

    return counts


# ============================================================
# THIRD DOWN
# ============================================================

def third_down_success(play):

    if play["down"] != 3:
        return False

    distance = play["distance"]
    gain = play["gain"]

    if distance is None:
        return False

    # Short / medium:
    # gain the first down
    if distance <= 6:
        return gain >= distance

    # Long:
    # gain at least 70% of needed yardage
    return gain >= distance * 0.70


def third_down(plays):

    counts = defaultdict(
        lambda: {
            "attempts": 0,
            "success": 0,
            "yards": 0,
        }
    )

    for p in plays:

        if p["down"] != 3:
            continue

        key = (
            p["formation"],
            p["play"],
        )

        counts[key]["attempts"] += 1
        counts[key]["yards"] += p["gain"]

        if third_down_success(p):
            counts[key]["success"] += 1

    return counts


# ============================================================
# REPORT
# ============================================================

def build_report(plays):

    rows = []

    # ========================================================
    # IDENTITY
    # ========================================================

    rows.append(["===== OFFENSIVE IDENTITY ====="])
    rows.append([])

    total = len(plays)

    runs = sum(
        1 for p in plays
        if p["play_type"] == "RUN"
    )

    passes = sum(
        1 for p in plays
        if p["play_type"] == "PASS"
    )

    rows.append([
        "Offensive Plays",
        total
    ])

    rows.append([
        "Runs",
        runs,
        fmt_pct(pct(runs, total))
    ])

    rows.append([
        "Passes",
        passes,
        fmt_pct(pct(passes, total))
    ])

    rows.append([])

    # ========================================================
    # RUN EFFICIENCY
    # ========================================================

    rows.append([
        "===== RUN EFFICIENCY — 4+ YARDS ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Attempts",
        "4+ Yds",
        "Rate"
    ])

    for (formation, play), d in sorted(
        run_efficiency(plays).items(),
        key=lambda x: (
            -x[1]["success"],
            -x[1]["attempts"]
        )
    ):

        rows.append([
            formation,
            play,
            d["attempts"],
            d["success"],
            fmt_pct(
                pct(
                    d["success"],
                    d["attempts"]
                )
            )
        ])

    rows.append([])

    # ========================================================
    # EXPLOSIVE RUNS
    # ========================================================

    rows.append([
        "===== EXPLOSIVE RUNS — 10+ YARDS ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Explosive Runs"
    ])

    for (formation, play), count in \
            explosive_runs(plays).most_common():

        rows.append([
            formation,
            play,
            count
        ])

    rows.append([])

    # ========================================================
    # PASS EFFICIENCY
    # ========================================================

    rows.append([
        "===== PASS EFFICIENCY — 7+ YARDS ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Attempts",
        "7+ Yds",
        "Rate"
    ])

    for (formation, play), d in sorted(
        pass_efficiency(plays).items(),
        key=lambda x: (
            -x[1]["success"],
            -x[1]["attempts"]
        )
    ):

        rows.append([
            formation,
            play,
            d["attempts"],
            d["success"],
            fmt_pct(
                pct(
                    d["success"],
                    d["attempts"]
                )
            )
        ])

    rows.append([])

    # ========================================================
    # EXPLOSIVE PASSES
    # ========================================================

    rows.append([
        "===== EXPLOSIVE PASSES — 15+ YARDS ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Explosive Passes"
    ])

    for (formation, play), count in \
            explosive_passes(plays).most_common():

        rows.append([
            formation,
            play,
            count
        ])

    rows.append([])

    # ========================================================
    # RED ZONE
    # ========================================================

    rows.append([
        "===== RED ZONE — 25 AND IN ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Plays",
        "Positive Gain",
        "Rate"
    ])

    for (formation, play), d in sorted(
        red_zone(plays).items(),
        key=lambda x: (
            -x[1]["success"],
            -x[1]["plays"]
        )
    ):

        rows.append([
            formation,
            play,
            d["plays"],
            d["success"],
            fmt_pct(
                pct(
                    d["success"],
                    d["plays"]
                )
            )
        ])

    rows.append([])

    # ========================================================
    # THIRD DOWN
    # ========================================================

    rows.append([
        "===== 3RD DOWN EFFICIENCY ====="
    ])

    rows.append([
        "Formation",
        "Play",
        "Attempts",
        "Effective",
        "Rate"
    ])

    for (formation, play), d in sorted(
        third_down(plays).items(),
        key=lambda x: (
            -x[1]["success"],
            -x[1]["attempts"]
        )
    ):

        rows.append([
            formation,
            play,
            d["attempts"],
            d["success"],
            fmt_pct(
                pct(
                    d["success"],
                    d["attempts"]
                )
            )
        ])

    return rows


# ============================================================
# WRITE REPORT
# ============================================================

def write_report(spreadsheet, rows):

    if not rows:
        rows = [["No offensive data found."]]

    try:

        ws = spreadsheet.worksheet(
            OUTPUT_SHEET
        )

        ws.clear()

    except gspread.WorksheetNotFound:

        ws = spreadsheet.add_worksheet(
            title=OUTPUT_SHEET,
            rows=max(len(rows), 100),
            cols=10
        )

    max_cols = max(
        len(row)
        for row in rows
    )

    total_rows = len(rows)

    # Resize if necessary
    if ws.row_count < total_rows:

        ws.add_rows(
            total_rows - ws.row_count
        )

    if ws.col_count < max_cols:

        ws.add_cols(
            max_cols - ws.col_count
        )

    # Make rectangular
    padded_rows = [
        row + [""] * (
            max_cols - len(row)
        )
        for row in rows
    ]

    # Write
    ws.update(
        "A1",
        padded_rows
    )

    # Basic formatting
    ws.format(
        f"A1:{gspread.utils.rowcol_to_a1(total_rows, max_cols)}",
        {
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        }
    )

    ws.freeze(rows=1)

    # Column widths
    ws.set_column_width(1, 150)
    ws.set_column_width(2, 180)

    if max_cols >= 3:
        ws.set_column_width(3, 100)

    if max_cols >= 4:
        ws.set_column_width(4, 100)

    if max_cols >= 5:
        ws.set_column_width(5, 90)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("SHEETS-HUDL OFFENSIVE ANALYSIS")
    print("=" * 70)

    spreadsheet = connect_to_sheets()

    print(
        f"Opened spreadsheet: "
        f"'{spreadsheet.title}'"
    )

    plays = load_offensive_plays(
        spreadsheet
    )

    print(
        f"Offensive plays loaded: "
        f"{len(plays)}"
    )

    runs = sum(
        1 for p in plays
        if p["play_type"] == "RUN"
    )

    passes = sum(
        1 for p in plays
        if p["play_type"] == "PASS"
    )

    print(f"Runs:   {runs}")
    print(f"Passes: {passes}")

    print(
        "Building offensive report..."
    )

    rows = build_report(plays)

    print(
        f"Report rows: {len(rows)}"
    )

    write_report(
        spreadsheet,
        rows
    )

    print(
        f"Wrote report to "
        f"'{OUTPUT_SHEET}'"
    )

    print("=" * 70)
    print(
        "OFFENSIVE ANALYSIS COMPLETE"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()