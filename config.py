"""
config.py
---------
Central place for every constant, column name, and tunable threshold used
by the tendency report. Nothing in here talks to Google Sheets or does any
football math - it's just settings.
"""

from typing import List, Tuple

# ---------------------------------------------------------------------------
# Google Sheets tab names
# ---------------------------------------------------------------------------

ODK_SHEET_NAME: str = "ODK"                 # single source of truth for live data
SCOUT_SHEET_NAME: str = "WEEKLY DATA"       # 3+ weeks of scouted opponent film
OUTPUT_SHEET_NAME: str = "DEF ANALYSIS"     # defense report (opponent scout vs live)
OFF_OUTPUT_SHEET_NAME: str = "OFF ANALYSIS"  # offense report (self tendencies, no scout side)
STATS_OUTPUT_SHEET_NAME: str = "Stats"      # box score: QB line, ball carriers, def live yards

# ---------------------------------------------------------------------------
# Column names as they appear in the ODK sheet
# ---------------------------------------------------------------------------

COL_PLAY_NUM: str = "PLAY #"
COL_SIDE: str = "ODK"           # contains "O" / "D" / "K"
COL_DOWN: str = "DN"
COL_DISTANCE: str = "DIST"
COL_HASH: str = "HASH"
COL_GAIN_LOSS: str = "GN/LS"
COL_BALL_CARRIER: str = "BALL CARRIER"
COL_FIELD_POSITION: str = "YARD LN"     # signed yard line, offense perspective
COL_PLAY_TYPE: str = "PLAY TYPE"        # expected values: "Run" / "Pass"
COL_RESULT: str = "Result"
COL_FORMATION: str = "OFF FORM"
COL_DEFENSE: str = "Defense"
COL_MOTION: str = "Motion"
COL_PLAY_CALL: str = "OFF PLAY"
COL_RPO: str = "RPO"
COL_PLAY_DIR: str = "PLAY DIR"
COL_STUNT: str = "STUNT"
COL_COVERAGE: str = "COV"
COL_BLITZ: str = "BLITZ"

COL_BACKFIELD: str = "BACKFIELD"
COL_PROTECTION: str = "PROTECTION"

SIDE_DEFENSE: str = "D"
SIDE_OFFENSE: str = "O"

PLAY_TYPE_RUN: str = "Run"
PLAY_TYPE_PASS: str = "Pass"

# ---------------------------------------------------------------------------
# Result values (COL_RESULT) - used for ball-carrier / QB stat attribution
# ---------------------------------------------------------------------------
RESULT_COMPLETE: str = "Complete"
RESULT_COMPLETE_TD: str = "Complete, TD"
RESULT_INCOMPLETE: str = "Incomplete"
RESULT_INTERCEPTION: str = "Interception"
RESULT_FUMBLE: str = "Fumble"
RESULT_RUSH: str = "Rush"
RESULT_RUSH_TD: str = "Rush, TD"

# ---------------------------------------------------------------------------
# Down & distance buckets
# ---------------------------------------------------------------------------
DIST_SHORT_MAX: int = 3
DIST_MEDIUM_MAX: int = 7

DOWNS_TRACKED: List[int] = [1, 2, 3]
DOWN_ORDINALS: dict = {1: "1st", 2: "2nd", 3: "3rd"}

# ---------------------------------------------------------------------------
# Explosive play thresholds (yards gained)
# ---------------------------------------------------------------------------
EXPLOSIVE_RUN_THRESHOLD: int = 10
EXPLOSIVE_PASS_THRESHOLD: int = 15

TOP_N_FORMATIONS: int = 3
TOP_N_PLAYS: int = 3

# ---------------------------------------------------------------------------
# Field position zones
# ---------------------------------------------------------------------------
FIELD_ZONES: List[Tuple[str, int, int]] = [
    ("Own 1-20", 0, 20),
    ("Own 21-49", 20, 45),
    ("Midfield", 45, 55),
    ("Opponent Territory", 55, 70),
    ("Red Zone", 70, 99),
    ("Goal Line", 99, 101),
]

# ---------------------------------------------------------------------------
# Google API scopes / env var names
# ---------------------------------------------------------------------------
GOOGLE_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

ENV_GOOGLE_CREDS: str = "GOOGLE_CREDS"
ENV_SPREADSHEET_ID: str = "SPREADSHEET_ID"

SCOUT_GAMES_COUNT: int = 3

ALERT_FORMATION_CHANGE_PCT: float = 15.0
ALERT_RUNPASS_CHANGE_PCT: float = 15.0
ALERT_ZONE_CHANGE_PCT: float = 20.0
ALERT_PLAY_CHANGE_PCT: float = 15.0

MIN_LIVE_PLAYS_FOR_COMPARISON: int = 10
NEW_PLAY_MIN_LIVE_COUNT: int = 2
LOW_USAGE_ALERT_MIN_SCOUT_COUNT: int = 5
LOW_USAGE_ALERT_MAX_LIVE_COUNT: int = 1
NEW_TENDENCY_USAGE_JUMP_PCT: float = 15.0

MIN_CONFIDENCE_SAMPLE: int = 5
MIN_SAMPLE_FOR_EXPECTATION: int = 5
EXPECTED_CALL_TOP_N: int = 3
SITUATION_CHANGE_ALERT_PCT: float = 20.0

STATUS_SAME: str = "Same tendency"
STATUS_MORE_PASS: str = "Passing more than expected"
STATUS_MORE_RUN: str = "Running more than expected"
STATUS_USING_MORE: str = "Using much more"
STATUS_USING_LESS: str = "Using much less"
STATUS_FLIPPED: str = "Completely different tendency"
STATUS_NEW: str = "New look"
STATUS_LOW_CONFIDENCE: str = "Low confidence"

BIGGEST_CHANGES_TOP_N: int = 4

GAME_PLAN_BAR_SEGMENTS: int = 10
GAME_PLAN_BAR_FILLED_CHAR: str = "\u2588"
GAME_PLAN_BAR_EMPTY_CHAR: str = "\u2591"

GAME_PLAN_WEIGHT_FORMATION: float = 0.40
GAME_PLAN_WEIGHT_RUNPASS: float = 0.20
GAME_PLAN_WEIGHT_TOP_PLAYS: float = 0.20
GAME_PLAN_WEIGHT_DOWN_DISTANCE: float = 0.20

GAME_PLAN_BANDS = [
    (90.0, "Following scout"),
    (70.0, "Minor adjustments"),
    (50.0, "Significant changes"),
    (0.0, "Completely different offense"),
]

POSITIVE_RUN_GAIN_THRESHOLD: int = 4
POSITIVE_PASS_GAIN_THRESHOLD: int = 7

RED_ZONE_FIELD_ZONES: List[str] = ["Red Zone", "Goal Line"]
THIRD_DOWN_LONG_GAIN_PCT: float = 0.70
