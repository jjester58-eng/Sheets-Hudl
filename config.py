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

ODK_SHEET_NAME: str = "ODK"                 # single source of truth for live data
SCOUT_SHEET_NAME: str = "WEEKLY DATA"       # 3+ weeks of scouted opponent film
OUTPUT_SHEET_NAME: str = "DEF ANALYSIS"     # defense report (opponent scout vs live)
OFF_OUTPUT_SHEET_NAME: str = "OFF ANALYSIS"  # offense report (self tendencies, no scout side)
STATS_SHEET_NAME: str = "Stats"             # ball carrier / QB / def live-yards stat lines

# ---------------------------------------------------------------------------
# Column names as they appear in the ODK sheet
# ---------------------------------------------------------------------------

COL_PLAY_NUM: str = "PLAY #"
COL_SIDE: str = "ODK"           # contains "O" / "D" / "K"
COL_DOWN: str = "DN"
COL_DISTANCE: str = "DIST"
COL_HASH: str = "HASH"
COL_GAIN_LOSS: str = "GN/LS"
COL_BALL_CARRIER: str = "BALL CARRIER"      # rusher on Run rows, receiver on Pass rows
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

# Present in WEEKLY DATA but not ODK - harmless if unused.
COL_BACKFIELD: str = "BACKFIELD"
COL_PROTECTION: str = "PROTECTION"

SIDE_DEFENSE: str = "D"
SIDE_OFFENSE: str = "O"

# Values expected in COL_PLAY_TYPE
PLAY_TYPE_RUN: str = "Run"
PLAY_TYPE_PASS: str = "Pass"

# ---------------------------------------------------------------------------
# Result dropdown values (COL_RESULT) that drive QB / ball-carrier stats.
# There are other values in the sheet's dropdown (e.g. sacks, penalties) -
# anything not listed here is simply not counted toward these stats, not
# treated as an error.
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
# Short = 1-3, Medium = 4-7, Long = 8+

DIST_SHORT_MAX: int = 3
DIST_MEDIUM_MAX: int = 7

# Only 1st/2nd/3rd down get their own bucket - 4th down situations are rare
# enough that they don't get a dedicated report line.
DOWNS_TRACKED: List[int] = [1, 2, 3]
DOWN_ORDINALS: dict = {1: "1st", 2: "2nd", 3: "3rd"}

# Down & distance rows shown in the DEF ANALYSIS quick view, in this exact
# order. (1st & Medium/Short and 2nd & ... below are still computed by the
# full Expected Call engine in analysis.py - this list just controls what
# the condensed coach page displays.)
QUICK_DOWN_DISTANCE_LABELS: List[str] = [
    "1st & Long",
    "2nd & Long",
    "2nd & Medium",
    "2nd & Short",
    "3rd & Long",
    "3rd & Medium",
    "3rd & Short",
]

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
# ODK's YARD LN uses the coach's own convention: own side negative (-1 =
# own 1, -49 = own 49, near midfield), opponent side positive counting DOWN
# (49 = just past midfield, 1 = opponent's 1, 50 = midfield either sign).
# Internally this gets converted to a continuous 0-100 "yards from own goal
# line" scale before zoning (see analysis._yards_from_own_goal), so these
# boundaries are plain 0-100 numbers, not raw YARD LN values.
# Adjust freely - these are a starting convention, not gospel.
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

# ---------------------------------------------------------------------------
# Offense efficiency tables (OFF ANALYSIS - run/pass/red zone/3rd down)
# ---------------------------------------------------------------------------
# A "positive" run or pass is one that gains at least this many yards -
# these are separate, lower bars than EXPLOSIVE_RUN_THRESHOLD/
# EXPLOSIVE_PASS_THRESHOLD above, which mark a much bigger gain.
POSITIVE_RUN_GAIN_THRESHOLD: int = 4
POSITIVE_PASS_GAIN_THRESHOLD: int = 7

# Which FIELD_ZONES bucket(s) count as "red zone" for the efficiency table.
# Must match zone names in FIELD_ZONES above.
RED_ZONE_FIELD_ZONES: List[str] = ["Red Zone", "Goal Line"]

# Third down is "successful" if distance is gained on short/medium (<= this
# many yards - reuses the same Short/Medium/Long cutoff as DIST_MEDIUM_MAX
# elsewhere) or, on long down-and-distance, if the gain reaches this
# fraction of what's needed. This 70% rule is a coaching judgment call, not
# a universal stat - adjust freely.
THIRD_DOWN_LONG_GAIN_PCT: float = 0.70
