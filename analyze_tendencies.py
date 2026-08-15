"""Thin orchestration for the DEF ANALYSIS pipeline.

This module should only coordinate calls to the data-access layer in sheets.py,
analysis.py, and reports.py. All Google Sheets auth, reads, and writes remain in
sheets.py so the project has a single source of truth for spreadsheet behavior.
"""

import sys

import analysis
import config
import reports
import sheets


def main() -> None:
    """Load ODK and weekly data, analyze them, and write the DEF ANALYSIS report."""
    print("=" * 70)
    print("SHEETS-HUDL DEF ANALYSIS")
    print("=" * 70)
    print()

    try:
        gc = sheets.get_client()
        spreadsheet = sheets.open_spreadsheet(gc)
    except Exception as exc:
        print(f"ERROR: Failed to authenticate or open spreadsheet: {exc}")
        sys.exit(1)

    required_tabs = [config.WEEKLY_DATA_SHEET_NAME, config.ODK_SHEET_NAME]
    try:
        sheets.validate_required_tabs(spreadsheet, required_tabs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("Loading weekly scout data...")
    scout_df = sheets.load_sheet_as_df(spreadsheet, config.WEEKLY_DATA_SHEET_NAME)
    scout_ready = not scout_df.empty
    if scout_ready:
        scout_df = analysis.add_situational_columns(scout_df)
    else:
        print("WARNING: Weekly data is empty. Scout comparisons will be skipped.")

    print("Loading live ODK data...")
    live_df = sheets.load_defense_live_df(spreadsheet)
    live_ready = not live_df.empty
    if not live_ready:
        print("WARNING: No defensive snaps found in ODK.")

    scout_summary = analysis.build_summary(scout_df) if scout_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)
    live_summary = analysis.build_summary(live_df) if live_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)

    if live_ready:
        def_analysis = analysis.analyze_def_play_types(live_df)
        print(f"  Defensive snaps: {def_analysis.total_defensive_plays}")
        print(f"    Runs:  {def_analysis.run_count} ({def_analysis.run_pct:.1f}%)")
        print(f"    Passes: {def_analysis.pass_count} ({def_analysis.pass_pct:.1f}%)")
    else:
        def_analysis = None

    print("Building analysis sections...")
    identity = analysis.build_identity_comparison(scout_summary, live_summary)
    formation_changes = analysis.compare_formations(scout_df, live_df) if scout_ready and live_ready else []
    run_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_RUN) if scout_ready and live_ready else []
    pass_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_PASS) if scout_ready and live_ready else []
    biggest_changes = (
        analysis.build_biggest_changes(formation_changes, run_changes, pass_changes)
        if scout_ready and live_ready
        else analysis.BiggestChanges([], [], [], [])
    )
    formation_comparisons = analysis.build_formation_comparisons(scout_df, live_df) if scout_ready and live_ready else []
    formation_tendencies = analysis.build_top_formations(live_df) if live_ready else []
    down_distance_expectations = analysis.build_down_distance_expectations(scout_df, live_df) if scout_ready and live_ready else []
    field_zone_expectations = analysis.build_field_zone_expectations(scout_df, live_df) if scout_ready and live_ready else []
    field_position_available = analysis.has_field_position_data(scout_df) or analysis.has_field_position_data(live_df)
    explosive = analysis.build_explosive_comparison(scout_df, live_df) if scout_ready and live_ready else []
    scout_top_runs = analysis.build_top_plays(scout_df, config.PLAY_TYPE_RUN) if scout_ready else []
    scout_top_passes = analysis.build_top_plays(scout_df, config.PLAY_TYPE_PASS) if scout_ready else []
    live_top_runs = analysis.build_top_plays(live_df, config.PLAY_TYPE_RUN) if live_ready else []
    live_top_passes = analysis.build_top_plays(live_df, config.PLAY_TYPE_PASS) if live_ready else []
    game_plan_score = (
        analysis.compute_game_plan_score(
            formation_changes,
            scout_summary,
            live_summary,
            scout_top_runs,
            scout_top_passes,
            live_top_runs,
            live_top_passes,
            down_distance_expectations,
        )
        if scout_ready and live_ready
        else None
    )
    coach_alerts = (
        analysis.build_coach_alerts(
            identity,
            formation_comparisons,
            formation_changes,
            run_changes,
            pass_changes,
            down_distance_expectations,
            field_zone_expectations,
        )
        if scout_ready and live_ready
        else []
    )

    print("Generating formatted report...")
    rows = reports.build_full_report(
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
        live_ready=live_ready,
    )
    print(f"  Report rows: {len(rows)}")

    print("Writing to Google Sheets...")
    print("========== BEFORE WRITE ==========")
    print(f"Report rows type: {type(rows)}")
    print(f"Report row count: {len(rows)}")

    if rows:
        print(f"First row: {rows[0]}")
        print(f"Last row: {rows[-1]}")
    else:
        print("REPORT IS EMPTY")

    ws = sheets.write_report(spreadsheet, rows)

    print("========== AFTER WRITE ==========")
    print(f"Worksheet returned: {ws.title if ws else None}")

    if ws is None:
        print("ERROR: Failed to write report.")
        sys.exit(1)

    sheets.format_report_layout(ws, len(rows))
    sheets.apply_trend_formatting(ws, [c.change for c in formation_changes])

    print("Report written and formatted successfully.")
    print()
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()