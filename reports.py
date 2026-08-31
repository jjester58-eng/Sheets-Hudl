"""
reports.py
----------
Turns data structures into formatted sheet rows.
"""

from typing import List, Optional
import config
from analysis import (
    FormationSummary, PlayCallStat, PlayProbability, IdentityComparison,
    FormationComparison, SituationExpectation, SituationSelfSummary,
    ExplosiveComparison, BiggestChanges, GamePlanScore, Summary,
    PlayTypeYards, BallCarrierStats, QBStats,
)

Row = List[str]
UP = "\u25b2"
DOWN = "\u25bc"
CHECK = "\u2713"
WARN = "\u26a0"


def _blank_row() -> Row:
    return [""]


def _section_header(title: str) -> Row:
    return [f"===== {title} ====="]


def _sub_header(title: str) -> Row:
    return [f"— {title} —"]


def _pct(value: float) -> str:
    return f"{value:.0f}%"


def _yards(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


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


# ===========================================================================
# QUICK DEFENSE VIEW
# ===========================================================================

def build_quick_runpass_section(identity: IdentityComparison) -> List[Row]:
    rows: List[Row] = [_section_header("LIVE GAME RUN/PASS")]
    rows.append(["Live Snaps", str(identity.live_plays)])
    rows.append(["Live Run/Pass", f"{_pct(identity.live_run_pct)} / {_pct(identity.live_pass_pct)}"])
    rows.append(["Scout Run/Pass", f"{_pct(identity.scout_run_pct)} / {_pct(identity.scout_pass_pct)}"])
    rows.append(["Change (Pass)", _arrow_change(identity.pass_pct_change)])
    rows.append(_blank_row())
    return rows


def build_quick_formations_section(comparisons: List[FormationComparison], top_n: int = 3) -> List[Row]:
    rows: List[Row] = [_section_header("TOP 3 FORMATIONS")]
    top = sorted(comparisons, key=lambda c: c.live_count, reverse=True)[:top_n]
    top = [c for c in top if c.live_count > 0]
    if not top:
        rows.append(["(no live formation data yet)"])
        rows.append(_blank_row())
        return rows
    rows.append(["Formation", "Snaps", "Run%", "Pass%", "Scout R%", "Scout P%", "Change"])
    for f in top:
        rows.append([f.formation, str(f.live_count), _pct(f.live_run_pct), _pct(f.live_pass_pct), _pct(f.scout_run_pct), _pct(f.scout_pass_pct), _arrow_change(f.change)])
    rows.append(_blank_row())
    return rows


def build_quick_down_distance_section(expectations: List[SituationExpectation]) -> List[Row]:
    rows: List[Row] = [_section_header("DOWN/DISTANCE")]
    wanted = ["1st & Long", "2nd & Long", "2nd & Medium", "2nd & Short", "3rd & Long", "3rd & Medium", "3rd & Short"]
    by_label = {e.label: e for e in expectations}
    found = [by_label[w] for w in wanted if w in by_label]
    if not found:
        rows.append(["(no down/distance data yet)"])
        rows.append(_blank_row())
        return rows
    rows.append(["Situation", "Live R%", "Live P%", "Scout R%", "Scout P%", "Change"])
    for e in found:
        rows.append([e.label, _pct(e.live_run_pct), _pct(e.live_pass_pct), _pct(e.scout_run_pct), _pct(e.scout_pass_pct), _arrow_change(e.pass_pct_change)])
    rows.append(_blank_row())
    return rows


def build_quick_verdict_section(verdict: str) -> List[Row]:
    rows: List[Row] = [_section_header("TRUE TO SCOUT?")]
    rows.append([verdict])
    rows.append(_blank_row())
    return rows


def build_quick_notable_section(alerts: List[str], max_items: int = 5) -> List[Row]:
    rows: List[Row] = [_section_header("NOTABLE")]
    if not alerts:
        rows.append([f"{CHECK} Nothing unusual."])
        rows.append(_blank_row())
        return rows
    for alert in alerts[:max_items]:
        rows.append([f"• {alert}"])
    rows.append(_blank_row())
    return rows


def build_quick_defense_report(identity: IdentityComparison, formation_comparisons: List[FormationComparison], down_distance_expectations: List[SituationExpectation], verdict: str, notable_alerts: List[str]) -> List[Row]:
    rows: List[Row] = []
    rows += build_quick_runpass_section(identity)
    rows += build_quick_formations_section(formation_comparisons)
    rows += build_quick_down_distance_section(down_distance_expectations)
    rows += build_quick_verdict_section(verdict)
    rows += build_quick_notable_section(notable_alerts)
    return rows


# ===========================================================================
# OFFENSE REPORT
# ===========================================================================

def build_offense_identity_section(summary: Summary) -> List[Row]:
    rows: List[Row] = [_section_header("OFFENSE IDENTITY")]
    rows.append(["Plays", str(summary.total_plays)])
    rows.append(["Run/Pass", f"{_pct(summary.run_pct)}/{_pct(summary.pass_pct)}"])
    rows.append(["X-Run (10+)", str(summary.explosive_run_count)])
    rows.append(["X-Pass (15+)", str(summary.explosive_pass_count)])
    rows.append(_blank_row())
    return rows


def build_offense_formations_section(formations: List[FormationSummary]) -> List[Row]:
    rows: List[Row] = [_section_header("TOP FORMATIONS (SELF)")]
    if not formations:
        rows.append(["(no formation data)"])
        rows.append(_blank_row())
        return rows
    rows.append(["Formation", "Usage", "R%", "P%", "Top Runs", "Top Pass"])
    for f in formations:
        rows.append([f.formation, _pct(f.usage_pct), _pct(f.run_pct), _pct(f.pass_pct), ", ".join(f.top_run_plays) or "—", ", ".join(f.top_pass_plays) or "—"])
    rows.append(_blank_row())
    return rows


def build_offense_top_plays_section(title: str, plays: List[PlayCallStat]) -> List[Row]:
    rows: List[Row] = [_section_header(title)]
    if not plays:
        rows.append(["(none yet)"])
        rows.append(_blank_row())
        return rows
    rows.append(["Play", "Calls", "Avg Gain", "Explosive"])
    for p in plays:
        rows.append([p.play_name, str(p.calls), f"{p.avg_gain:.1f}", str(p.explosive_count)])
    rows.append(_blank_row())
    return rows


def build_offense_situation_section(title: str, situations: List[SituationSelfSummary], empty_message: str) -> List[Row]:
    rows: List[Row] = [_section_header(title)]
    if not situations:
        rows.append([empty_message])
        rows.append(_blank_row())
        return rows
    rows.append(["Situation", "Plays", "R/P", "Top Plays"])
    for s in situations:
        play_count_cell = str(s.play_count) if s.confident else f"{s.play_count} (low)"
        rows.append([s.label, play_count_cell, _run_pass_cell(s.run_pct, s.pass_pct, s.play_count), _expected_play_names(s.top_plays)])
    rows.append(_blank_row())
    return rows


def build_offense_explosive_section(explosive: dict) -> List[Row]:
    rows: List[Row] = [_section_header("EXPLOSIVE PLAYS (SELF)")]
    runs = explosive.get("runs", [])
    passes = explosive.get("passes", [])
    if not runs and not passes:
        rows.append(["(none yet)"])
        rows.append(_blank_row())
        return rows
    rows.append(["Play", "Type", "Calls", "Avg Gain", "Explosive"])
    for p in runs:
        rows.append([p.play_name, "Run", str(p.calls), f"{p.avg_gain:.1f}", str(p.explosive_count)])
    for p in passes:
        rows.append([p.play_name, "Pass", str(p.calls), f"{p.avg_gain:.1f}", str(p.explosive_count)])
    rows.append(_blank_row())
    return rows


def build_offense_report(summary: Summary, formations: List[FormationSummary], top_runs: List[PlayCallStat], top_passes: List[PlayCallStat], down_distance_summary: List[SituationSelfSummary], field_zone_summary: List[SituationSelfSummary], field_position_available: bool, explosive: dict) -> List[Row]:
    rows: List[Row] = []
    rows += build_offense_identity_section(summary)
    rows += build_offense_formations_section(formations)
    rows += build_offense_top_plays_section("TOP RUN PLAYS", top_runs)
    rows += build_offense_top_plays_section("TOP PASS PLAYS", top_passes)
    rows += build_offense_situation_section("DOWN & DISTANCE (SELF)", down_distance_summary, "(no down/distance data)")
    field_empty = "(no field pos data — add FIELD POS column)" if not field_position_available else "(no field position data)"
    rows += build_offense_situation_section("FIELD POSITION (SELF)", field_zone_summary, field_empty)
    rows += build_offense_explosive_section(explosive)
    return rows


# ===========================================================================
# STATS TAB
# ===========================================================================

def build_stats_qb_section(qb: QBStats) -> List[Row]:
    rows: List[Row] = [_section_header("QUARTERBACK")]
    rows.append(["Attempts", "Comp", "Comp%", "Pass Yds", "Pass TD", "INT"])
    rows.append([str(qb.attempts), str(qb.completions), _pct(qb.comp_pct), _yards(qb.pass_yards), str(qb.pass_td), str(qb.interceptions)])
    rows.append(_blank_row())
    return rows


def build_stats_ball_carrier_section(stats: List[BallCarrierStats]) -> List[Row]:
    rows: List[Row] = [_section_header("BALL CARRIERS")]
    if not stats:
        rows.append(["(no offensive plays yet)"])
        rows.append(_blank_row())
        return rows

    rows.append([
        "Player", "Car", "Rush Yds", "Avg/Car", "Rush TD",
        "Rec", "Rec Yds", "Total Yds", "Rec TD", "Fum",
    ])
    for s in stats:
        total_yards = float(s.rush_yards) + float(s.rec_yards)
        rows.append([
            s.ball_carrier,
            str(s.carries),
            _yards(s.rush_yards),
            f"{s.yards_per_carry:.1f}",
            str(s.rush_td),
            str(s.receptions),
            _yards(s.rec_yards),
            _yards(total_yards),
            str(s.rec_td),
            str(s.fumbles),
        ])
    rows.append(_blank_row())
    return rows


def build_stats_def_yards_section(live_yards: PlayTypeYards) -> List[Row]:
    rows: List[Row] = [_section_header("DEF LIVE YARDS (OPPONENT)")]
    rows.append(["Rushing", _yards(live_yards.rushing_yards)])
    rows.append(["Passing", _yards(live_yards.passing_yards)])
    rows.append(["Total", _yards(live_yards.rushing_yards + live_yards.passing_yards)])
    rows.append(_blank_row())
    return rows


def build_stats_penalties_section(penalty_count: int, penalty_yards: float) -> List[Row]:
    rows: List[Row] = [_section_header("PENALTIES")]
    rows.append(["Total Penalties", "Penalty Yards"])
    rows.append([str(penalty_count), _yards(penalty_yards)])
    rows.append(_blank_row())
    return rows


def build_stats_report(qb_stats: QBStats, ball_carrier_stats: List[BallCarrierStats], def_live_yards: PlayTypeYards, penalty_count: int = 0, penalty_yards: float = 0.0) -> List[Row]:
    rows: List[Row] = []
    rows += build_stats_qb_section(qb_stats)
    rows += build_stats_ball_carrier_section(ball_carrier_stats)
    rows += build_stats_def_yards_section(def_live_yards)
    rows += build_stats_penalties_section(penalty_count, penalty_yards)
    return rows
