"""
config.py
---------
Central place for every constant, column name, and tunable threshold used
by the tendency report. Nothing in here talks to Google Sheets or does any
football math - it's just settings.

If a coach wants to change what counts as an "explosive" play, adjust a
distance bucket, or rename a column, this is the only file that should
need to change.
"""

from typing import List, Tuple

# ---------------------------------------------------------------------------
# Google Sheets tab names
# ---------------------------------------------------------------------------

SOURCE_SHEET_NAME: str = "ALL INFO SHEET"   # this week's live game (charted in real time)
SCOUT_SHEET_NAME: str = "WEEKLY DATA"       # 3+ weeks of scouted opponent film
OUTPUT_SHEET_NAME: str = "DEF ANALYSIS"     # where the report gets written

# ---------------------------------------------------------------------------
# Column names as they appear in the sheet (A:P)
# ---------------------------------------------------------------------------

COL_PLAY_NUM: str = "PLAY #"
COL_SERIES: str = "SERIES"
COL_DOWN: str = "DN"
COL_DISTANCE: str = "DIST"
COL_BACKFIELD: str = "BACKFIELD"
COL_FORMATION: str = "OFF FORM"
COL_PLAY_CALL: str = "OFF PLAY"
COL_PROTECTION: str = "PROTECTION"
COL_PLAY_TYPE: str = "PLAY TYPE"        # expected values: "Run" / "Pass"
COL_GAIN_LOSS: str = "GN/LS"
COL_FRONT: str = "FRONT"
COL_STUNT: str = "STUNT"
COL_BLITZ: str = "BLITZ"
COL_COVERAGE: str = "COV"
COL_STR_WEAK: str = "STR/WK"
COL_DEF_NOTES: str = "DEF NOTES"

# Optional column - not present in the sheet yet. If a coach adds a column
# with this name (using the signed field-position system described below),
# the field position section will pick it up automatically. Until then,
# that section is skipped with a clear message instead of guessing.
COL_FIELD_POSITION: str = "FIELD POS"

# Values expected in COL_PLAY_TYPE
PLAY_TYPE_RUN: str = "Run"
PLAY_TYPE_PASS: str = "Pass"

# ---------------------------------------------------------------------------
# Down & distance buckets
# ---------------------------------------------------------------------------
# Short = 1-3, Medium = 4-7, Long = 8+

DIST_SHORT_MAX: int = 3
DIST_MEDIUM_MAX: int = 7

# Only 1st/2nd/3rd down get their own bucket - 4th down situations are rare
# enough that they don't get a dedicated report line.
DOWNS_TRACKED: List[int] = [1, 2, 3]
DOWN_ORDINALS: dict = {1: "1st", 2: "2nd", 3: "3rd"}

# ---------------------------------------------------------------------------
# Explosive play thresholds (yards gained)
# ---------------------------------------------------------------------------

EXPLOSIVE_RUN_THRESHOLD: int = 10
EXPLOSIVE_PASS_THRESHOLD: int = 15

# ---------------------------------------------------------------------------
# How many items to show in "Top N" lists
# ---------------------------------------------------------------------------

TOP_N_FORMATIONS: int = 3
TOP_N_PLAYS: int = 3

# ---------------------------------------------------------------------------
# Field position zones
# ---------------------------------------------------------------------------
# Field position convention (matches the coach's own numbering system):
#   -50 .......... 0 (50 yard line) .......... +50
#   negative = own side of the field, positive = opponent's side.
#
# Zone boundaries below are a starting convention - adjust freely if the
# coach's actual zone cutoffs differ. Each tuple is:
#   (zone_name, min_value_inclusive, max_value_exclusive)
FIELD_ZONES: List[Tuple[str, int, int]] = [
    ("Own 1-20", -50, -30),
    ("Own 21-50", -30, -5),
    ("Midfield", -5, 5),
    ("Opponent Territory", 5, 30),
    ("Red Zone", 30, 45),
    ("Goal Line", 45, 51),  # 51 so +50 itself is included
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

# ---------------------------------------------------------------------------
# Live vs Scout comparison settings
# ---------------------------------------------------------------------------

# Roughly how many games the scout data covers. There's no GAME/WEEK column
# in the sheet to derive this precisely, so it's a config estimate used only
# for the "X calls/game" style alert phrasing. Adjust to match reality.
SCOUT_GAMES_COUNT: int = 3

# Minimum swing (percentage points) before something becomes a "Live Alert"
ALERT_FORMATION_CHANGE_PCT: float = 15.0
ALERT_RUNPASS_CHANGE_PCT: float = 15.0
ALERT_ZONE_CHANGE_PCT: float = 20.0
ALERT_PLAY_CHANGE_PCT: float = 15.0

# Below this many live plays charted, scout-vs-live comparisons are too noisy
# to trust (e.g. 3 live plays makes every formation look like it "changed"
# by 30-100%). The report shows a plain "not enough data yet" message for
# every comparison section until this many plays are in.
MIN_LIVE_PLAYS_FOR_COMPARISON: int = 10

# A brand-new play (never on scout film) needs at least this many live reps
# before it's worth flagging - avoids a one-off trick play triggering noise.
NEW_PLAY_MIN_LIVE_COUNT: int = 2

# A play that WAS a scout favorite (>= this many scout reps) but has barely
# shown up live (<= this many reps) gets a "dropped off" alert.
LOW_USAGE_ALERT_MIN_SCOUT_COUNT: int = 5
LOW_USAGE_ALERT_MAX_LIVE_COUNT: int = 1

# Minimum usage jump (percentage points) to call out a "new tendency"
NEW_TENDENCY_USAGE_JUMP_PCT: float = 15.0

# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
# A tendency drawn from a tiny sample is meaningless ("3rd & Long: PASS 100%,
# 2 plays" tells a coach nothing). Any live situation with fewer than this
# many plays is tagged LOW CONFIDENCE rather than reported as fact, and the
# Expected Call engine will not assert that a tendency "changed" off a sample
# this small.
MIN_CONFIDENCE_SAMPLE: int = 5

# Minimum sample size before a scout situation is trusted enough to feed the
# Expected Call / expected-plays engine.
MIN_SAMPLE_FOR_EXPECTATION: int = 5

# How many ranked plays the Expected Call engine lists per situation
# (e.g. "1. Counter 38%  2. Power 29%  3. Zone 18%").
EXPECTED_CALL_TOP_N: int = 3

# Swing (percentage points) big enough to generate a Down & Distance or
# Field Position "running/passing much more than expected" alert
SITUATION_CHANGE_ALERT_PCT: float = 20.0

# ---------------------------------------------------------------------------
# Status / verdict labels (comparison-first wording used across the report)
# ---------------------------------------------------------------------------
STATUS_SAME: str = "Same tendency"
STATUS_MORE_PASS: str = "Passing more than expected"
STATUS_MORE_RUN: str = "Running more than expected"
STATUS_USING_MORE: str = "Using much more"
STATUS_USING_LESS: str = "Using much less"
STATUS_FLIPPED: str = "Completely different tendency"
STATUS_NEW: str = "New look"
STATUS_LOW_CONFIDENCE: str = "Low confidence"

# ---------------------------------------------------------------------------
# Biggest Changes section
# ---------------------------------------------------------------------------
# How many risers and fallers to surface in the "Biggest Changes" section.
BIGGEST_CHANGES_TOP_N: int = 4

# ---------------------------------------------------------------------------
# Game Plan Match visual bar
# ---------------------------------------------------------------------------
# The match score is drawn as a text bar (e.g. "████████░░ 82%") so it reads
# at a glance in a spreadsheet cell.
GAME_PLAN_BAR_SEGMENTS: int = 10
GAME_PLAN_BAR_FILLED_CHAR: str = "\u2588"   # full block
GAME_PLAN_BAR_EMPTY_CHAR: str = "\u2591"    # light shade

# Game Plan Match Score - component weights (must sum to 1.0)
GAME_PLAN_WEIGHT_FORMATION: float = 0.40
GAME_PLAN_WEIGHT_RUNPASS: float = 0.20
GAME_PLAN_WEIGHT_TOP_PLAYS: float = 0.20
GAME_PLAN_WEIGHT_DOWN_DISTANCE: float = 0.20

# Game Plan Match Score bands (lower bound, inclusive) -> label
GAME_PLAN_BANDS = [
    (90.0, "Following scout"),
    (70.0, "Minor adjustments"),
    (50.0, "Significant changes"),
    (0.0, "Completely different offense"),
]
