"""
reports.py
----------
Turns the data structures produced by analysis.py into rows of text ready
to write to a Google Sheet. This module does zero calculation - if you're
computing a percentage or an average in here, it belongs in analysis.py
instead.

Design goal: the whole report fits on one tab without horizontal
scrolling, and a coach can read any single section in under 20 seconds.
That means short lines, narrow tables (4 columns max), and summarizing
rather than printing every statistic.

Report structure:
    WHAT TO EXPECT              <- the single most useful section, read first
    SCOUT REPORT (static)       <- what film says to expect
    LIVE REPORT                 <- what's actually happening tonight (same format)
    LIVE ADJUSTMENTS            <- exactly what changed, and by how much
    COACH ALERTS                <- plain-English observations
    GAME PLAN MATCH             <- one score, one label

Every function returns a List[List[str]] - each inner list is one row of
cells, ready to hand to sheets.py for writing.
"""

from typing import List, Optional

import config
from analysis import (
    Summary,
    FormationSummary,
    SituationBucket,
    PlayCallStat,
    FormationChange,
    PlayChange,
    FormationDeepDive,
    SituationComparison,
    ExpectationItem,
    GamePlanScore,
)

Row = List[str]

# Max columns any table in this report should use, to guarantee everything
# fits on one screen without horizontal scrolling.
MAX_TABLE_WIDTH = 4


def _blank_row() -> Row:
    return [""]


def _section_header(title: str) -> Row:
    return [f"===== {title} ====="]


def _sub_header(title: str) -> Row:
    return [f"— {title} —"]


# ---------------------------------------------------------------------------
# WHAT TO EXPECT
# ---------------------------------------------------------------------------

def build_what_to_expect_section(items: List[ExpectationItem]) -> List[Row]:
    """The predictive, glance-and-go section at the very top of the report."""
    rows: List[Row] = [_section_header("WHAT TO EXPECT")]

    if not items:
        rows.append(["(not enough data yet for a confident prediction)"])
        rows.append(_blank_row())
        return rows

    for item in items:
        rows.append([f"{item.label}  ({item.category})"])
        rows.append([f"{item.dominant_pct:.0f}% {item.dominant_type}"])
        if item.likely_plays:
            rows.append([f"Likely: {', '.join(item.likely_plays)}"])
        rows.append(_blank_row())

    return rows


# ---------------------------------------------------------------------------
# SCOUT REPORT / LIVE REPORT (same formatter, used for both)
# ---------------------------------------------------------------------------

def build_summary_lines(summary: Summary) -> List[Row]:
    rows: List[Row] = [
        [f"Plays: {summary.total_plays}"],
        [f"Run {summary.run_pct:.0f}%  /  Pass {summary.pass_pct:.0f}%"],
        [f"Explosive Runs (10+): {summary.explosive_run_count}   "
         f"Explosive Passes (15+): {summary.explosive_pass_count}"],
    ]
    return rows


def build_formations_lines(formations: List[FormationSummary]) -> List[Row]:
    rows: List[Row] = []
    if not formations:
        return [["(no formation data)"]]

    for f in formations:
        rows.append([f"{f.formation} — {f.usage_pct:.0f}% usage, "
                     f"Run {f.run_pct:.0f}% / Pass {f.pass_pct:.0f}%"])
        if f.top_run_plays:
            rows.append([f"  Run: {', '.join(f.top_run_plays)}"])
        if f.top_pass_plays:
            rows.append([f"  Pass: {', '.join(f.top_pass_plays)}"])
    return rows


def build_top_plays_lines(title: str, plays: List[PlayCallStat]) -> List[Row]:
    rows: List[Row] = [_sub_header(title)]
    if not plays:
        rows.append(["(no data)"])
        return rows
    for p in plays:
        rows.append([f"{p.play_name} — {p.calls} calls, {p.avg_gain:.1f} avg"])
    return rows


def build_situation_lines(buckets: List[SituationBucket], empty_message: str) -> List[Row]:
    rows: List[Row] = []
    if not buckets:
        return [[empty_message]]
    for b in buckets:
        rows.append([f"{b.label} — Run {b.run_pct:.0f}% / Pass {b.pass_pct:.0f}%"])
    return rows


def build_explosive_lines(explosive: dict) -> List[Row]:
    rows: List[Row] = []
    runs = explosive.get("runs", [])
    passes = explosive.get("passes", [])
    if not runs and not passes:
        return [["(no explosive plays yet)"]]
    for p in runs:
        rows.append([f"Run: {p.play_name} — {p.explosive_count}x, {p.avg_gain:.1f} avg"])
    for p in passes:
        rows.append([f"Pass: {p.play_name} — {p.explosive_count}x, {p.avg_gain:.1f} avg"])
    return rows


def build_report_half(
    title: str,
    summary: Summary,
    formations: List[FormationSummary],
    top_runs: List[PlayCallStat],
    top_passes: List[PlayCallStat],
    down_distance_buckets: List[SituationBucket],
    field_zones: List[SituationBucket],
    field_position_available: bool,
    explosive: dict,
) -> List[Row]:
    """Builds either the Scout Report or the Live Report - same layout for
    both, so a coach can compare them just by scanning down the tab."""
    rows: List[Row] = [_section_header(title)]

    rows.append(_sub_header("Summary"))
    rows += build_summary_lines(summary)
    rows.append(_blank_row())

    rows.append(_sub_header("Top 3 Formations"))
    rows += build_formations_lines(formations)
    rows.append(_blank_row())

    rows += build_top_plays_lines("Top 3 Run Concepts", top_runs)
    rows.append(_blank_row())
    rows += build_top_plays_lines("Top 3 Pass Concepts", top_passes)
    rows.append(_blank_row())

    rows.append(_sub_header("Down & Distance"))
    rows += build_situation_lines(down_distance_buckets, "(no down/distance data)")
    rows.append(_blank_row())

    field_empty = (
        "(no field position data - add a 'FIELD POS' column to enable this section)"
        if not field_position_available else "(no field position data)"
    )
    rows.append(_sub_header("Field Position"))
    rows += build_situation_lines(field_zones, field_empty)
    rows.append(_blank_row())

    rows.append(_sub_header("Explosive Plays"))
    rows += build_explosive_lines(explosive)
    rows.append(_blank_row())

    return rows


# ---------------------------------------------------------------------------
# LIVE ADJUSTMENTS
# ---------------------------------------------------------------------------

def build_formation_changes_table(changes: List[FormationChange], top_n: int = 5) -> List[Row]:
    """Compact 4-column table: Formation | Scout% | Live% | Change.
    Shows only the top N by absolute change - biggest surprises first."""
    rows: List[Row] = [_sub_header("Formation Changes")]
    if not changes:
        rows.append(["(no comparable data yet)"])
        return rows

    rows.append(["Formation", "Scout", "Live", "Change"])
    for c in changes[:top_n]:
        change_label = "NEW" if c.is_new else f"{c.change:+.0f}%"
        rows.append([c.formation, f"{c.scout_pct:.0f}%", f"{c.live_pct:.0f}%", change_label])
    return rows


def build_formation_deep_dive_section(deep_dives: List[FormationDeepDive]) -> List[Row]:
    """One compact scout-vs-live block per top formation."""
    rows: List[Row] = [_sub_header("Formation Deep Dive (Top 3)")]
    if not deep_dives:
        rows.append(["(no comparable data yet)"])
        return rows

    for d in deep_dives:
        rows.append([f"{d.formation}"])
        rows.append([f"  Scout: Run {d.scout_run_pct:.0f}% / Pass {d.scout_pass_pct:.0f}%  "
                     f"({', '.join(d.scout_top_runs) or '—'} | {', '.join(d.scout_top_passes) or '—'})"])
        rows.append([f"  Live : Run {d.live_run_pct:.0f}% / Pass {d.live_pass_pct:.0f}%  "
                     f"({', '.join(d.live_top_runs) or '—'} | {', '.join(d.live_top_passes) or '—'})"])

        callouts = []
        if abs(d.run_pct_change) >= 15 or abs(d.pass_pct_change) >= 15:
            callouts.append(f"Run/Pass shifted {d.run_pct_change:+.0f}% / {d.pass_pct_change:+.0f}%")
        if d.new_plays:
            callouts.append(f"New: {', '.join(d.new_plays)}")
        if callouts:
            rows.append([f"  ⚠ {'  |  '.join(callouts)}"])

        rows.append(_blank_row())

    return rows


def build_run_pass_shift_section(scout_summary: Summary, live_summary: Summary) -> List[Row]:
    rows: List[Row] = [_sub_header("Run/Pass Shift")]
    rows.append([f"Scout: Run {scout_summary.run_pct:.0f}% / Pass {scout_summary.pass_pct:.0f}%"])
    rows.append([f"Live : Run {live_summary.run_pct:.0f}% / Pass {live_summary.pass_pct:.0f}%"])
    return rows


def _play_status_tags(scout_top: List[PlayCallStat], live_top: List[PlayCallStat],
                       changes: List[PlayChange]) -> dict:
    """Builds a {play_name: status} map ('NEW', 'UP', 'DOWN') for every play
    appearing in either top-3 list, using the full change list for context."""
    changes_by_name = {c.play_name: c for c in changes}
    scout_names = {p.play_name for p in scout_top}
    live_names = {p.play_name for p in live_top}

    tags = {}
    for name in scout_names | live_names:
        change = changes_by_name.get(name)
        if change is None:
            continue
        if change.is_new:
            tags[name] = "NEW"
        elif change.change >= 15:
            tags[name] = "UP"
        elif change.change <= -15:
            tags[name] = "DOWN"
    return tags


def build_top_play_changes_section(
    title: str,
    scout_top: List[PlayCallStat],
    live_top: List[PlayCallStat],
    changes: List[PlayChange],
) -> List[Row]:
    rows: List[Row] = [_sub_header(title)]

    tags = _play_status_tags(scout_top, live_top, changes)

    def _format_list(plays: List[PlayCallStat]) -> str:
        parts = []
        for p in plays:
            tag = tags.get(p.play_name)
            parts.append(f"{p.play_name} ({tag})" if tag else p.play_name)
        return ", ".join(parts) if parts else "—"

    rows.append([f"Scout: {_format_list(scout_top)}"])
    rows.append([f"Live : {_format_list(live_top)}"])
    return rows


def build_situation_changes_section(title: str, comparisons: List[SituationComparison],
                                     empty_message: str) -> List[Row]:
    """Only shows buckets that actually have a notable story - per the
    'summarize, don't print everything' instruction, buckets with a small,
    unremarkable change are omitted rather than listed for completeness."""
    rows: List[Row] = [_sub_header(title)]

    notable = [c for c in comparisons if c.alert_text or abs(c.pass_pct_change) >= 10]
    if not notable:
        rows.append([empty_message])
        return rows

    for c in notable:
        rows.append([f"{c.label}"])
        rows.append([f"  Scout: Pass {c.scout_pass_pct:.0f}%   Live: Pass {c.live_pass_pct:.0f}%"])
        if c.alert_text:
            rows.append([f"  ⚠ {c.alert_text}"])

    return rows


# ---------------------------------------------------------------------------
# COACH ALERTS
# ---------------------------------------------------------------------------

def build_coach_alerts_section(alerts: List[str]) -> List[Row]:
    rows: List[Row] = [_section_header("COACH ALERTS")]
    if not alerts:
        rows.append(["(nothing significant yet - offense is following the scouting report)"])
        return rows
    for alert in alerts:
        rows.append([f"• {alert}"])
    return rows


# ---------------------------------------------------------------------------
# GAME PLAN MATCH
# ---------------------------------------------------------------------------

def build_game_plan_section(gps: Optional[GamePlanScore]) -> List[Row]:
    rows: List[Row] = [_section_header("GAME PLAN MATCH")]
    if gps is None:
        rows.append(["N/A - not enough live data yet"])
        return rows
    rows.append([f"{gps.score:.0f}%  —  {gps.band_label}"])
    rows.append([f"Formation {gps.formation_component:.0f}  |  "
                 f"Run/Pass {gps.runpass_component:.0f}  |  "
                 f"Top Plays {gps.top_plays_component:.0f}  |  "
                 f"Down & Dist {gps.down_distance_component:.0f}"])
    return rows


# ---------------------------------------------------------------------------
# Full report assembly
# ---------------------------------------------------------------------------

def build_full_report(
    what_to_expect: List[ExpectationItem],
    scout_summary: Summary,
    scout_formations: List[FormationSummary],
    scout_top_runs: List[PlayCallStat],
    scout_top_passes: List[PlayCallStat],
    scout_buckets: List[SituationBucket],
    scout_zones: List[SituationBucket],
    scout_field_available: bool,
    scout_explosive: dict,
    live_summary: Summary,
    live_formations: List[FormationSummary],
    live_top_runs: List[PlayCallStat],
    live_top_passes: List[PlayCallStat],
    live_buckets: List[SituationBucket],
    live_zones: List[SituationBucket],
    live_field_available: bool,
    live_explosive: dict,
    formation_changes: List[FormationChange],
    formation_deep_dives: List[FormationDeepDive],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
    down_distance_comparisons: List[SituationComparison],
    field_zone_comparisons: List[SituationComparison],
    coach_alerts: List[str],
    game_plan_score: GamePlanScore,
) -> List[Row]:
    """Assembles every section, in order, into the final list of rows."""
    rows: List[Row] = []

    rows += build_what_to_expect_section(what_to_expect)

    rows += build_report_half(
        "SCOUT REPORT (STATIC)", scout_summary, scout_formations, scout_top_runs, scout_top_passes,
        scout_buckets, scout_zones, scout_field_available, scout_explosive,
    )

    rows += build_report_half(
        "LIVE REPORT", live_summary, live_formations, live_top_runs, live_top_passes,
        live_buckets, live_zones, live_field_available, live_explosive,
    )

    rows.append(_section_header("LIVE ADJUSTMENTS"))

    if live_summary.total_plays < config.MIN_LIVE_PLAYS_FOR_COMPARISON:
        rows.append([f"(only {live_summary.total_plays} live play(s) charted so far - "
                      f"need {config.MIN_LIVE_PLAYS_FOR_COMPARISON}+ before scout-vs-live "
                      f"comparisons are reliable. Check back after a few more series.)"])
        rows.append(_blank_row())
        rows.append(_section_header("COACH ALERTS"))
        rows.append(["(not enough live data yet)"])
        rows.append(_blank_row())
        rows += build_game_plan_section(None)
        return rows

    rows += build_formation_changes_table(formation_changes)
    rows.append(_blank_row())
    rows += build_formation_deep_dive_section(formation_deep_dives)
    rows += build_run_pass_shift_section(scout_summary, live_summary)
    rows.append(_blank_row())
    rows += build_top_play_changes_section("Top Run Changes", scout_top_runs, live_top_runs, run_changes)
    rows.append(_blank_row())
    rows += build_top_play_changes_section("Top Pass Changes", scout_top_passes, live_top_passes, pass_changes)
    rows.append(_blank_row())
    rows += build_situation_changes_section(
        "Down & Distance Changes", down_distance_comparisons, "(no significant down/distance changes yet)"
    )
    rows.append(_blank_row())
    rows += build_situation_changes_section(
        "Field Position Changes", field_zone_comparisons, "(no significant field position changes yet)"
    )
    rows.append(_blank_row())

    rows += build_coach_alerts_section(coach_alerts)
    rows.append(_blank_row())

    rows += build_game_plan_section(game_plan_score)

    return rows
