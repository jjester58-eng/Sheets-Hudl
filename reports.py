"""
reports.py
----------
Turns the data structures produced by analysis.py into rows of text ready
to write to a Google Sheet. This module does zero calculation.
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

UP = "\u25b2"       # ▲
DOWN = "\u25bc"     # ▼
CHECK = "\u2713"    # ✓
WARN = "\u26a0"     # ⚠


def _blank_row() -> Row:
    return [""]


def _section_header(title: str) -> Row:
    return [f"===== {title} ====="]


def _sub_header(title: str) -> Row:
    return [f"— {title} —"]


def _pct(value: float) -> str:
    return f"{value:.0f}%"


def _run_pass_cell(run_pct: float, pass_pct: float, play_count: int) -> str:
    if play_count == 0:
        return "—"
    return f"{run_pct:.0f}R/{pass_pct:.0f}P"


def _arrow_change(change: float) -> str:
    if change > 0:
        return f"{UP} +{change:.0f}%"
    if change < 0:
        return f"{DOWN} {change:.0f}%"
    return CHECK


def _status_mark(status: str) -> str:
    mark = CHECK if status == config.STATUS_SAME else WARN
    return f"{mark} {status}"


def _expected_play_names(plays: List[PlayProbability]) -> str:
    return ", ".join(p.play_name for p in plays) if plays else "—"


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
        "Run/Pass",
        f"{_pct(identity.scout_run_pct)}/{_pct(identity.scout_pass_pct)}",
        f"{_pct(identity.live_run_pct)}/{_pct(identity.live_pass_pct)}",
        trend,
    ])
    rows.append([
        "X-Run (10+)",
        str(identity.scout_explosive_run), str(identity.live_explosive_run), "",
    ])
    rows.append([
        "X-Pass (15+)",
        str(identity.scout_explosive_pass), str(identity.live_explosive_pass), "",
    ])
    rows.append(_blank_row())
    return rows


def _match_bar(score: float) -> str:
    segments = config.GAME_PLAN_BAR_SEGMENTS
    filled = int(round(score / 100.0 * segments))
    filled = max(0, min(segments, filled))
    return (config.GAME_PLAN_BAR_FILLED_CHAR * filled
            + config.GAME_PLAN_BAR_EMPTY_CHAR * (segments - filled))


def build_game_plan_section(gps: Optional[GamePlanScore], live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("GAME PLAN MATCH")]

    if gps is None or not live_ready:
        rows.append([f"{_match_bar(0)}  —  not enough live data yet"])
        rows.append([f"Need {config.MIN_LIVE_PLAYS_FOR_COMPARISON}+ live plays."])
        rows.append(_blank_row())
        return rows

    rows.append([f"{_match_bar(gps.score)}  {gps.score:.0f}%  {gps.band_label}"])
    rows.append([
        f"Form {gps.formation_component:.0f} | R/P {gps.runpass_component:.0f} | "
        f"Top {gps.top_plays_component:.0f} | D&D {gps.down_distance_component:.0f}"
    ])
    rows.append(_blank_row())
    return rows


def build_biggest_changes_section(changes: BiggestChanges, live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("BIGGEST CHANGES")]

    if not live_ready:
        rows.append(["(waiting on more live plays)"])
        rows.append(_blank_row())
        return rows

    has_any = (changes.formation_movers or changes.play_movers
               or changes.new_formations or changes.new_plays)
    if not has_any:
        rows.append([f"{CHECK} Following scout."])
        rows.append(_blank_row())
        return rows

    for c in changes.formation_movers:
        arrow = UP if c.change > 0 else DOWN
        rows.append([f"{arrow} {c.formation}", f"{c.change:+.0f}%"])
    for c in changes.play_movers:
        arrow = UP if c.change > 0 else DOWN
        rows.append([f"{arrow} {c.play_name}", f"{c.change:+.0f}%"])
    for formation in changes.new_formations:
        rows.append(["NEW FORM", formation])
    for play in changes.new_plays:
        rows.append(["NEW PLAY", play])

    rows.append(_blank_row())
    return rows


def build_top_formations_section(comparisons: List[FormationComparison]) -> List[Row]:
    rows: List[Row] = [_section_header("TOP FORMATIONS")]
    if not comparisons:
        rows.append(["(no formation data)"])
        rows.append(_blank_row())
        return rows

    for f in comparisons:
        usage_trend = "NEW" if f.is_new else _arrow_change(f.change)
        rp_trend = (
            _arrow_change(f.pass_pct_change)
            if abs(f.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT
            else CHECK
        )
        rows.append([
            f.formation,
            f"Use {_pct(f.scout_pct)}→{_pct(f.live_pct)} {usage_trend}",
            f"R/P {_run_pass_cell(f.scout_run_pct, f.scout_pass_pct, f.scout_count)}"
            f"→{_run_pass_cell(f.live_run_pct, f.live_pass_pct, f.live_count)} {rp_trend}",
            _status_mark(f.status),
        ])
        detail_parts = []
        if f.scout_top_runs:
            detail_parts.append(f"Runs: {', '.join(f.scout_top_runs)}")
        if f.scout_top_passes:
            detail_parts.append(f"Pass: {', '.join(f.scout_top_passes)}")
        if f.new_plays:
            detail_parts.append(f"{WARN} New: {', '.join(f.new_plays)}")
        if detail_parts:
            rows.append(["  " + " | ".join(detail_parts)])
        rows.append(_blank_row())

    return rows


def build_formation_tendencies_section(formations: List[FormationSummary]) -> List[Row]:
    rows: List[Row] = [_section_header("FORMATION TENDENCIES (SCOUT)")]
    if not formations:
        rows.append(["(no formation data)"])
        rows.append(_blank_row())
        return rows

    rows.append(["Formation", "R%", "P%", "Fav Runs", "Fav Pass"])
    for f in formations:
        rows.append([
            f.formation,
            _pct(f.run_pct),
            _pct(f.pass_pct),
            ", ".join(f.top_run_plays) or "—",
            ", ".join(f.top_pass_plays) or "—",
        ])
    rows.append(_blank_row())
    return rows


def _situation_trend_cell(exp: SituationExpectation) -> str:
    if exp.live_count == 0:
        return "—"
    if not exp.live_confident:
        return f"low ({exp.live_count})"
    if exp.verdict == config.STATUS_SAME:
        return CHECK
    return f"{WARN} {exp.verdict}"


def _expected_call_block(exp: SituationExpectation) -> List[Row]:
    rows: List[Row] = [_sub_header(exp.label)]

    if exp.scout_confident and exp.scout_expected_plays:
        plays = " / ".join(f"{p.play_name} ({p.pct:.0f}%)" for p in exp.scout_expected_plays)
        rows.append([f"EXPECT {exp.scout_dominant_pct:.0f}% {exp.scout_dominant_type}: {plays}"])
    else:
        rows.append([f"EXPECT: low sample ({exp.scout_count})"])

    if exp.live_count == 0:
        rows.append(["LIVE: not seen"])
    elif not exp.live_confident:
        rows.append([
            f"LIVE {exp.live_dominant_pct:.0f}% {exp.live_dominant_type} "
            f"(low conf, {exp.live_count})"
        ])
    else:
        verdict_mark = CHECK if not exp.changed else WARN
        plays = " / ".join(f"{p.play_name} ({p.pct:.0f}%)" for p in exp.live_top_plays)
        rows.append([
            f"LIVE {exp.live_dominant_pct:.0f}% {exp.live_dominant_type} "
            f"{verdict_mark} {exp.verdict}: {plays}"
        ])

    return rows


def build_situation_section(
    title: str,
    expectations: List[SituationExpectation],
    empty_message: str,
) -> List[Row]:
    rows: List[Row] = [_section_header(title)]
    if not expectations:
        rows.append([empty_message])
        rows.append(_blank_row())
        return rows

    rows.append(["Situation", "Scout", "Live", "Trend", "Expected"])
    for exp in expectations:
        expected = (
            _expected_play_names(exp.scout_expected_plays)
            if exp.scout_confident
            else f"(n={exp.scout_count})"
        )
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


def build_explosive_section(explosive: List[ExplosiveComparison]) -> List[Row]:
    rows: List[Row] = [_section_header("EXPLOSIVE PLAYS")]
    if not explosive:
        rows.append(["(none yet)"])
        rows.append(_blank_row())
        return rows

    rows.append(["Play", "Type", "Scout", "Live"])
    for e in explosive:
        rows.append([e.play_name, e.play_type, str(e.scout_count), str(e.live_count)])
    rows.append(_blank_row())
    return rows


def build_coach_alerts_section(alerts: List[str], live_ready: bool) -> List[Row]:
    rows: List[Row] = [_section_header("COACH ALERTS")]
    if not live_ready:
        rows.append(["(need more live data)"])
        rows.append(_blank_row())
        return rows
    if not alerts:
        rows.append([f"{CHECK} Following scout."])
        rows.append(_blank_row())
        return rows
    for alert in alerts:
        rows.append([f"• {alert}"])
    rows.append(_blank_row())
    return rows


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
        "(no field pos data — add FIELD POS column)"
        if not field_position_available else "(no field position data)"
    )
    rows += build_situation_section("FIELD POSITION", field_zone_expectations, field_empty)

    rows += build_explosive_section(explosive)
    rows += build_coach_alerts_section(coach_alerts, live_ready)

    return rows