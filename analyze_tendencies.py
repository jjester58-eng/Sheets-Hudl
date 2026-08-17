"""
analyze_tendencies.py
----------------------
Orchestrator only. Loads scout and live data, runs every analysis
function, and writes both reports. No football math (that's analysis.py)
and no report formatting (that's reports.py) - if you're tempted to add
either kind of logic here, it belongs in one of those modules instead.

ALL live data comes from ONE place: the ODK tab, read once and split by
side (ODK column == "D" or "O"). No other tab is read for the live side of
either report.

Writes two tabs:
    DEF ANALYSIS - comparison-first: "Are they doing what we scouted, or
        have they changed - and if they line up here again, what should we
        expect?" (opponent offense, scout vs live)
    OFF ANALYSIS - self-tendency only, no scout side: "What do WE tend to
        call, and how often?" (our offense, live only)

Guarded throughout for a sheet being empty (e.g. early season, before
enough scout film or live snaps exist) - every section degrades to an
empty/neutral result instead of crashing.
"""

import sys

import analysis
import config
import reports
import sheets


def main() -> None:
    print("=" * 70)
    print("SHEETS-HUDL TENDENCY ANALYSIS")
    print("=" * 70)
    print()

    try:
        gc = sheets.get_client()
        spreadsheet = sheets.open_spreadsheet(gc)
    except Exception as exc:
        print(f"ERROR: Failed to authenticate or open spreadsheet: {exc}")
        sys.exit(1)

    try:
        sheets.validate_required_tabs(spreadsheet, [config.ODK_SHEET_NAME, config.SCOUT_SHEET_NAME])
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("Loading weekly scout data...")
    scout_df = sheets.load_sheet_as_df(spreadsheet, config.SCOUT_SHEET_NAME)
    scout_ready = not scout_df.empty
    if scout_ready:
        scout_df = analysis.add_situational_columns(scout_df)
    else:
        print("WARNING: Weekly data is empty. Scout comparisons will be skipped.")

    print("Loading live ODK data...")
    # Read ODK once, split by side - avoids reading the sheet twice.
    odk_df = sheets.load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)
    live_df = sheets.filter_odk_by_side(odk_df, config.SIDE_DEFENSE)
    off_live_df = sheets.filter_odk_by_side(odk_df, config.SIDE_OFFENSE)

    live_ready = not live_df.empty
    if live_ready:
        live_df = analysis.add_situational_columns(live_df)
    else:
        print("WARNING: No defensive snaps found in ODK.")

    off_ready = not off_live_df.empty
    if off_ready:
        off_live_df = analysis.add_situational_columns(off_live_df)
    else:
        print("WARNING: No offensive snaps found in ODK.")

    _write_defense_report(spreadsheet, scout_df, scout_ready, live_df, live_ready)
    _write_offense_report(spreadsheet, off_live_df, off_ready)

    print()
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


def _write_defense_report(spreadsheet, scout_df, scout_ready: bool, live_df, live_ready: bool) -> None:
    """DEF ANALYSIS: opponent offense, scout vs live comparison."""

    if live_ready:
        def_analysis = analysis.analyze_def_play_types(live_df)
        print(f"  Defensive snaps: {def_analysis.total_defensive_plays}")
        print(f"    Runs:   {def_analysis.run_count} ({def_analysis.run_pct:.1f}%)")
        print(f"    Passes: {def_analysis.pass_count} ({def_analysis.pass_pct:.1f}%)")

    print("Building DEF ANALYSIS sections...")

    scout_summary = analysis.build_summary(scout_df) if scout_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)
    live_summary = analysis.build_summary(live_df) if live_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)
    scout_top_runs = analysis.build_top_plays(scout_df, config.PLAY_TYPE_RUN) if scout_ready else []
    scout_top_passes = analysis.build_top_plays(scout_df, config.PLAY_TYPE_PASS) if scout_ready else []
    live_top_runs = analysis.build_top_plays(live_df, config.PLAY_TYPE_RUN) if live_ready else []
    live_top_passes = analysis.build_top_plays(live_df, config.PLAY_TYPE_PASS) if live_ready else []

    identity = analysis.build_identity_comparison(scout_summary, live_summary)

    formation_comparisons = (
        analysis.build_formation_comparisons(scout_df, live_df) if scout_ready and live_ready else []
    )
    formation_tendencies = analysis.build_top_formations(scout_df, top_n=config.TOP_N_FORMATIONS * 2) if scout_ready else []

    down_distance_expectations = (
        analysis.build_down_distance_expectations(scout_df, live_df) if scout_ready and live_ready else []
    )
    field_zone_expectations = (
        analysis.build_field_zone_expectations(scout_df, live_df) if scout_ready and live_ready else []
    )
    field_position_available = (
        (analysis.has_field_position_data(scout_df) if scout_ready else False)
        or (analysis.has_field_position_data(live_df) if live_ready else False)
    )

    explosive = analysis.build_explosive_comparison(scout_df, live_df) if scout_ready and live_ready else []

    formation_changes = analysis.compare_formations(scout_df, live_df) if scout_ready and live_ready else []
    run_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_RUN) if scout_ready and live_ready else []
    pass_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_PASS) if scout_ready and live_ready else []

    biggest_changes = (
        analysis.build_biggest_changes(formation_changes, run_changes, pass_changes)
        if scout_ready and live_ready
        else analysis.BiggestChanges([], [], [], [])
    )

    coach_alerts = (
        analysis.build_coach_alerts(
            identity, formation_comparisons, formation_changes,
            run_changes, pass_changes,
            down_distance_expectations, field_zone_expectations,
        )
        if scout_ready and live_ready
        else []
    )

    live_plays_ready = live_summary.total_plays >= config.MIN_LIVE_PLAYS_FOR_COMPARISON
    game_plan_score = (
        analysis.compute_game_plan_score(
            formation_changes, scout_summary, live_summary,
            scout_top_runs, scout_top_passes, live_top_runs, live_top_passes,
            down_distance_expectations,
        )
        if scout_ready and live_ready and live_plays_ready
        else None
    )

    report_rows = reports.build_full_report(
        identity=identity,
        game_plan_score=game_plan_score,
        biggest_changes=biggest_changes,
        formation_comparisons=formation_comparisons,
        formation_tendencies=formation_tendencies,
        down_distance_expectations=down_distance_expectations,
        field_zone_expectations=field_zone_expectations,
        field_position_available=field_position_available,
        explosive=explosive,
        coach_alerts=coach_alerts,
        live_ready=live_plays_ready,
    )
    print(f"  DEF ANALYSIS report rows: {len(report_rows)}")

    ws = sheets.write_report(spreadsheet, report_rows, sheet_name=config.OUTPUT_SHEET_NAME)
    if ws is None:
        print("ERROR: Failed to write DEF ANALYSIS report.")
        sys.exit(1)

    sheets.format_report_layout(ws, len(report_rows))
    sheets.apply_trend_formatting(ws, [c.change for c in formation_changes])
    print("DEF ANALYSIS written and formatted.")


def _write_offense_report(spreadsheet, off_live_df, off_ready: bool) -> None:
    """OFF ANALYSIS: our offense, self-tendency only - no scout side."""

    print("Building OFF ANALYSIS sections...")

    if off_ready:
        summary = analysis.build_summary(off_live_df)
        formations = analysis.build_top_formations(off_live_df, top_n=config.TOP_N_FORMATIONS * 2)
        top_runs = analysis.build_top_plays(off_live_df, config.PLAY_TYPE_RUN, top_n=config.TOP_N_PLAYS * 2)
        top_passes = analysis.build_top_plays(off_live_df, config.PLAY_TYPE_PASS, top_n=config.TOP_N_PLAYS * 2)
        run_efficiency = analysis.build_run_efficiency(off_live_df)
        pass_efficiency = analysis.build_pass_efficiency(off_live_df)
        explosive_runs_by_formation = analysis.build_explosive_runs_by_formation(off_live_df)
        explosive_passes_by_formation = analysis.build_explosive_passes_by_formation(off_live_df)
        red_zone_efficiency = analysis.build_red_zone_efficiency(off_live_df)
        third_down_efficiency = analysis.build_third_down_efficiency(off_live_df)
        down_distance_summary = analysis.build_down_distance_summary(off_live_df)
        field_zone_summary = analysis.build_field_zone_summary(off_live_df)
        field_position_available = analysis.has_field_position_data(off_live_df)
        explosive = analysis.build_explosive_report(off_live_df, top_n=config.TOP_N_PLAYS * 2)
    else:
        summary = analysis.Summary(0, 0.0, 0.0, 0, 0)
        formations, top_runs, top_passes = [], [], []
        run_efficiency, pass_efficiency = [], []
        explosive_runs_by_formation, explosive_passes_by_formation = [], []
        red_zone_efficiency, third_down_efficiency = [], []
        down_distance_summary, field_zone_summary = [], []
        field_position_available = False
        explosive = {"runs": [], "passes": []}

    report_rows = reports.build_offense_report(
        summary=summary,
        formations=formations,
        top_runs=top_runs,
        top_passes=top_passes,
        run_efficiency=run_efficiency,
        explosive_runs_by_formation=explosive_runs_by_formation,
        pass_efficiency=pass_efficiency,
        explosive_passes_by_formation=explosive_passes_by_formation,
        red_zone_efficiency=red_zone_efficiency,
        third_down_efficiency=third_down_efficiency,
        down_distance_summary=down_distance_summary,
        field_zone_summary=field_zone_summary,
        field_position_available=field_position_available,
        explosive=explosive,
    )
    print(f"  OFF ANALYSIS report rows: {len(report_rows)}")

    ws = sheets.write_report(spreadsheet, report_rows, sheet_name=config.OFF_OUTPUT_SHEET_NAME)
    if ws is None:
        print("ERROR: Failed to write OFF ANALYSIS report.")
        sys.exit(1)

    sheets.format_report_layout(ws, len(report_rows))
    print("OFF ANALYSIS written and formatted.")


if __name__ == "__main__":
    main()