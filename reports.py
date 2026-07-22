"""
reports.py
----------
Turns the data structures produced by analysis.py into rows of text ready
to write to a Google Sheet. This module does zero calculation - if you're
computing a percentage or an average in here, it belongs in analysis.py
instead.

Design philosophy (this is a GAME PLAN, not a stats dump):
    Everything answers ONE question -
        "Are they doing what we scouted, or have they changed?"
    So the report is comparison-first. There is no standalone "scout
    section" and no duplicate "live section" - every number is shown as
    Scout vs Live vs Trend, side by side, once.

Report order (a DC needs ~6 answers, fast):
    1. OVERALL IDENTITY     - who are they, and have they changed?
    2. GAME PLAN MATCH      - one visual bar, one verdict
    3. BIGGEST CHANGES      - the movers a coordinator reads first
    4. TOP FORMATIONS       - usage + tendency + status, per formation
    5. FORMATION TENDENCIES - the book: run/pass split + favorites
    6. DOWN & DISTANCE      - Scout vs Live + the Expected Call engine
    7. FIELD POSITION       - same shape
    8. EXPLOSIVE PLAYS      - one small table
    9. COACH ALERTS         - plain-English, actionable

Every function returns a List[List[str]] - each inner list is one row of
cells, ready to hand to sheets.py for writing.
"""

from typing import List, Optional

import config
from analysis import (
    FormationSummary,
    PlayProbability,
    IdentityComparison,
    FormationComparison,
    SituationExpectation,
    ExplosiveComparison,
    BiggestChanges,
    GamePlanScore,
)

Row = List[str]

# Glyphs used throughout the report.
UP = "\u25b2"       # ▲
DOWN = "\u25bc"     # ▼
CHECK = "\u2713"    # ✓
WARN = "\u26a0"     # ⚠


def _blank_row() -> Row:
    return [""]


def _section_header(title: str) -> Row:
    return [f"===== {title} ====="]


def _sub_header(title: str) -> Row:
    return [f"\u2014 {title} \u2014"]


# ---------------------------------------------------------------------------
# Shared formatting helpers
# ---------------------------------------------------------------------------

def _pct(value: float) -> str:
    return f"{value:.0f}%"


def _run_pass_cell(run_pct: float, pass_pct: float, play_count: int) -> str:
    """The compact '72R/28P' cell, or a dash when there's nothing to show."""
    if play_count == 0:
        return "\u2014"
    return f"{run_pct:.0f}R/{pass_pct:.0f}P"


def _arrow_change(change: float) -> str:
    """'▲ +3%' / '▼ -15%' / '✓' for a signed percentage-point change."""
    if change > 0:
        return f"{UP} +{change:.0f}%"
    if change < 0:
        return f"{DOWN} {change:.0f}%"
    return CHECK


def _status_mark(status: str) -> str:
    """Prefixes a status with ✓ (following scout) or ⚠ (deviating)."""
    mark = CHECK if status == config.STATUS_SAME else WARN
    return f"{mark} {status}"


def _expected_play_names(plays: List[PlayProbability]) -> str:
    return ", ".join(p.play_name for p in plays) if plays else "\u2014"


# ---------------------------------------------------------------------------
# 1. OVERALL IDENTITY
# ---------------------------------------------------------------------------

def build_identity_section(identity: IdentityComparison) -> List[Row]:
    rows: List[Row] = [_section_header("OVERALL IDENTITY")]
    rows.append(["", "Scout", "Live", "Trend"])
    rows.append(["Plays", str(identity.scout_plays), str(identity.live_plays), ""])

    if abs(identity.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT:
        direction = "pass" if identity.pass_pct_change > 0 else "run"
        trend = f"{_arrow_change(identity.pass_pct_change)} {direction}"
    else:
        trend = CHECK
    rows.append([
        "Run / Pass",
        f"{_pct(identity.scout_run_pct)} / {_pct(identity.scout_pass_pct)}",
        f"{_pct(identity.live_run_pct)} / {_pct(identity.live_pass_pct)}",
        trend,
    ])
    rows.append([
        "Explosive Run (10+)",
        str(identity.scout_explosive_run), str(identity.live_explosive_run), "",
    ])
    rows.append([
        "Explosive Pass (15+)",
        str(identity.scout_explosive_pass), str(identity.live_explosive_pass), "",
    ])
    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# 2. GAME PLAN MATCH
# ---------------------------------------------------------------------------

def _match_bar(score: float) -> str:
    segments = config.GAME_PLAN_BAR_SEGMENTS
    filled = int(round(score / 100.0 * segments))
    filled = max(0, min(segments, filled))
    return (config.GAME_PLAN_BAR_FILLED_CHAR * filled
            + config.GAME_PLAN_BAR_EMPTY_CHAR * (segments - filled))


def build_game_plan_section(gps: Optional[GamePlanScore], live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("GAME PLAN MATCH")]

    if gps is None or not live_ready:
        rows.append([f"{_match_bar(0)}  \u2014  not enough live data yet"])
        rows.append(["Comparisons populate once enough plays are charted "
                     f"({config.MIN_LIVE_PLAYS_FOR_COMPARISON}+)."])
        rows.append(_blank_row())
        return rows

    rows.append([f"{_match_bar(gps.score)}  {gps.score:.0f}%"])
    rows.append([gps.band_label])
    rows.append([f"Formation {gps.formation_component:.0f}  |  "
                 f"Run/Pass {gps.runpass_component:.0f}  |  "
                 f"Top Plays {gps.top_plays_component:.0f}  |  "
                 f"Down & Dist {gps.down_distance_component:.0f}"])
    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# 3. BIGGEST CHANGES
# ---------------------------------------------------------------------------

def build_biggest_changes_section(changes: BiggestChanges, live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("BIGGEST CHANGES")]

    if not live_ready:
        rows.append(["(waiting on more live plays before flagging changes)"])
        rows.append(_blank_row())
        return rows

    has_any = (changes.formation_movers or changes.play_movers
               or changes.new_formations or changes.new_plays)
    if not has_any:
        rows.append([f"{CHECK} Nothing significant - offense is following the scout."])
        rows.append(_blank_row())
        return rows

    for c in changes.formation_movers:
        arrow = UP if c.change > 0 else DOWN
        rows.append([f"{arrow} {c.formation}", f"{c.change:+.0f}%"])
    for c in changes.play_movers:
        arrow = UP if c.change > 0 else DOWN
        rows.append([f"{arrow} {c.play_name}", f"{c.change:+.0f}%"])
    for formation in changes.new_formations:
        rows.append(["NEW FORMATION", formation])
    for play in changes.new_plays:
        rows.append(["NEW PLAY", play])

    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# 4. TOP FORMATIONS (scout vs live, per formation)
# ---------------------------------------------------------------------------

def build_top_formations_section(comparisons: List[FormationComparison]) -> List[Row]:
    rows: List[Row] = [_section_header("TOP FORMATIONS")]
    if not comparisons:
        rows.append(["(no formation data)"])
        rows.append(_blank_row())
        return rows

    for f in comparisons:
        rows.append([f.formation])
        rows.append(["", "Scout", "Live", "Trend"])
        usage_trend = "NEW" if f.is_new else _arrow_change(f.change)
        rows.append(["Usage", _pct(f.scout_pct), _pct(f.live_pct), usage_trend])
        rows.append([
            "Run/Pass",
            _run_pass_cell(f.scout_run_pct, f.scout_pass_pct, f.scout_count),
            _run_pass_cell(f.live_run_pct, f.live_pass_pct, f.live_count),
            _arrow_change(f.pass_pct_change) if abs(f.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT else CHECK,
        ])
        if f.scout_top_runs:
            rows.append(["Runs", ", ".join(f.scout_top_runs)])
        if f.scout_top_passes:
            rows.append(["Pass", ", ".join(f.scout_top_passes)])
        if f.new_plays:
            rows.append([f"{WARN} New", ", ".join(f.new_plays)])
        rows.append(["Status", _status_mark(f.status)])
        rows.append(_blank_row())

    return rows


# ---------------------------------------------------------------------------
# 5. FORMATION TENDENCIES (the book: run/pass split + favorites)
# ---------------------------------------------------------------------------

def build_formation_tendencies_section(formations: List[FormationSummary]) -> List[Row]:
    rows: List[Row] = [_section_header("FORMATION TENDENCIES (SCOUT)")]
    if not formations:
        rows.append(["(no formation data)"])
        rows.append(_blank_row())
        return rows

    rows.append(["Formation", "Run%", "Pass%", "Favorite Runs", "Favorite Passes"])
    for f in formations:
        rows.append([
            f.formation,
            _pct(f.run_pct),
            _pct(f.pass_pct),
            ", ".join(f.top_run_plays) or "\u2014",
            ", ".join(f.top_pass_plays) or "\u2014",
        ])
    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# 6 & 7. DOWN & DISTANCE / FIELD POSITION (+ Expected Call engine)
# ---------------------------------------------------------------------------

def _situation_trend_cell(exp: SituationExpectation) -> str:
    """The compact Trend cell for the situation table."""
    if exp.live_count == 0:
        return "\u2014"
    if not exp.live_confident:
        return f"low conf ({exp.live_count})"
    if exp.verdict == config.STATUS_SAME:
        return CHECK
    return f"{WARN} {exp.verdict}"


def _expected_call_block(exp: SituationExpectation) -> List[Row]:
    """The deep 'EXPECT vs LIVE' block - the between-series answer to
    'if they line up here again, what should we expect?'"""
    rows: List[Row] = [_sub_header(f"EXPECTED CALL: {exp.label}")]

    if exp.scout_confident and exp.scout_expected_plays:
        rows.append([f"EXPECT: {exp.scout_dominant_pct:.0f}% {exp.scout_dominant_type}"])
        for i, p in enumerate(exp.scout_expected_plays, start=1):
            rows.append([f"  {i}. {p.play_name} ({p.pct:.0f}%)"])
    else:
        rows.append([f"EXPECT: low scout sample ({exp.scout_count})"])

    if exp.live_count == 0:
        rows.append(["LIVE: not seen yet tonight"])
    elif not exp.live_confident:
        rows.append([f"LIVE: {exp.live_dominant_pct:.0f}% {exp.live_dominant_type}  "
                     f"(low confidence, {exp.live_count} plays)"])
    else:
        verdict_mark = CHECK if not exp.changed else WARN
        rows.append([f"LIVE: {exp.live_dominant_pct:.0f}% {exp.live_dominant_type}  "
                     f"{verdict_mark} {exp.verdict}"])
        for i, p in enumerate(exp.live_top_plays, start=1):
            rows.append([f"  {i}. {p.play_name} ({p.pct:.0f}%)"])

    return rows


def build_situation_section(
    title: str,
    expectations: List[SituationExpectation],
    empty_message: str,
) -> List[Row]:
    """Compact Scout|Live|Trend|Expected table, followed by an Expected Call
    block for every situation that has actually changed (confident)."""
    rows: List[Row] = [_section_header(title)]
    if not expectations:
        rows.append([empty_message])
        rows.append(_blank_row())
        return rows

    rows.append(["Situation", "Scout", "Live", "Trend", "Expected Plays"])
    for exp in expectations:
        expected = (_expected_play_names(exp.scout_expected_plays)
                    if exp.scout_confident else f"(low sample {exp.scout_count})")
        rows.append([
            exp.label,
            _run_pass_cell(exp.scout_run_pct, exp.scout_pass_pct, exp.scout_count),
            _run_pass_cell(exp.live_run_pct, exp.live_pass_pct, exp.live_count),
            _situation_trend_cell(exp),
            expected,
        ])
    rows.append(_blank_row())

    changed = [e for e in expectations if e.changed and e.live_confident]
    for exp in changed:
        rows += _expected_call_block(exp)
        rows.append(_blank_row())

    return rows


# ---------------------------------------------------------------------------
# 8. EXPLOSIVE PLAYS
# ---------------------------------------------------------------------------

def build_explosive_section(explosive: List[ExplosiveComparison]) -> List[Row]:
    rows: List[Row] = [_section_header("EXPLOSIVE PLAYS")]
    if not explosive:
        rows.append(["(no explosive plays yet)"])
        rows.append(_blank_row())
        return rows

    rows.append(["Play", "Type", "Scout", "Live"])
    for e in explosive:
        rows.append([e.play_name, e.play_type, str(e.scout_count), str(e.live_count)])
    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# 9. COACH ALERTS
# ---------------------------------------------------------------------------

def build_coach_alerts_section(alerts: List[str], live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("COACH ALERTS")]
    if not live_ready:
        rows.append(["(not enough live data yet)"])
        rows.append(_blank_row())
        return rows
    if not alerts:
        rows.append([f"{CHECK} Nothing significant yet - offense is following the scout."])
        rows.append(_blank_row())
        return rows
    for alert in alerts:
        rows.append([f"\u2022 {alert}"])
    rows.append(_blank_row())
    return rows


# ---------------------------------------------------------------------------
# Full report assembly
# ---------------------------------------------------------------------------

def build_full_report(
    identity: IdentityComparison,
    game_plan_score: Optional[GamePlanScore],
    biggest_changes: BiggestChanges,
    formation_comparisons: List[FormationComparison],
    formation_tendencies: List[FormationSummary],
    down_distance_expectations: List[SituationExpectation],
    field_zone_expectations: List[SituationExpectation],
    field_position_available: bool,
    explosive: List[ExplosiveComparison],
    coach_alerts: List[str],
    live_ready: bool,
) -> List[Row]:
    """Assembles every section, in order, into the final list of rows."""
    rows: List[Row] = []

    rows += build_identity_section(identity)
    rows += build_game_plan_section(game_plan_score, live_ready)
    rows += build_biggest_changes_section(biggest_changes, live_ready)
    rows += build_top_formations_section(formation_comparisons)
    rows += build_formation_tendencies_section(formation_tendencies)

    rows += build_situation_section(
        "DOWN & DISTANCE", down_distance_expectations,
        "(no down/distance data)",
    )

    field_empty = (
        "(no field position data - add a 'FIELD POS' column to enable this section)"
        if not field_position_available else "(no field position data)"
    )
    rows += build_situation_section("FIELD POSITION", field_zone_expectations, field_empty)

    rows += build_explosive_section(explosive)
    rows += build_coach_alerts_section(coach_alerts, live_ready)

    return rows
