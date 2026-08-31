"""
analyze_tendencies.py
----------------------
Orchestrator for tendency analysis and live stats.
"""
import sys
import analysis
import config
import reports
import sheets
import stats


def main() -> None:
    print("=" * 70)
    print("SHEETS-HUDL TENDENCY ANALYSIS")
    print("=" * 70)
    try:
        gc = sheets.get_client()
        spreadsheet = sheets.open_spreadsheet(gc)
        sheets.validate_required_tabs(spreadsheet, [config.ODK_SHEET_NAME, config.SCOUT_SHEET_NAME])
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    scout_df = sheets.load_sheet_as_df(spreadsheet, config.SCOUT_SHEET_NAME)
    scout_ready = not scout_df.empty
    if scout_ready:
        scout_df = analysis.add_situational_columns(scout_df)

    odk_df = sheets.load_sheet_as_df(spreadsheet, config.ODK_SHEET_NAME)
    live_df = sheets.filter_odk_by_side(odk_df, config.SIDE_DEFENSE)
    off_live_df = sheets.filter_odk_by_side(odk_df, config.SIDE_OFFENSE)
    live_ready = not live_df.empty
    off_ready = not off_live_df.empty
    if live_ready:
        live_df = analysis.add_situational_columns(live_df)
    if off_ready:
        off_live_df = analysis.add_situational_columns(off_live_df)

    _write_defense_report(spreadsheet, scout_df, scout_ready, live_df, live_ready)
    _write_offense_report(spreadsheet, off_live_df, off_ready)
    _write_stats_report(spreadsheet, off_live_df, off_ready, live_df, live_ready)
    print("ANALYSIS COMPLETE")


def _write_defense_report(spreadsheet, scout_df, scout_ready, live_df, live_ready):
    scout_summary = analysis.build_summary(scout_df) if scout_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)
    live_summary = analysis.build_summary(live_df) if live_ready else analysis.Summary(0, 0.0, 0.0, 0, 0)
    identity = analysis.build_identity_comparison(scout_summary, live_summary)
    formation_comparisons = analysis.build_formation_comparisons(scout_df, live_df, top_n=config.TOP_N_FORMATIONS * 5) if scout_ready and live_ready else []
    down_distance_expectations = analysis.build_down_distance_expectations(scout_df, live_df) if scout_ready and live_ready else []
    field_zone_expectations = analysis.build_field_zone_expectations(scout_df, live_df) if scout_ready and live_ready else []
    formation_changes = analysis.compare_formations(scout_df, live_df) if scout_ready and live_ready else []
    run_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_RUN) if scout_ready and live_ready else []
    pass_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_PASS) if scout_ready and live_ready else []
    coach_alerts = analysis.build_coach_alerts(identity, formation_comparisons, formation_changes, run_changes, pass_changes, down_distance_expectations, field_zone_expectations) if scout_ready and live_ready else []
    verdict = analysis.build_scout_fidelity_verdict(identity, formation_changes, run_changes, pass_changes) if scout_ready and live_ready else "Not enough data yet"
    rows = reports.build_quick_defense_report(identity=identity, formation_comparisons=formation_comparisons, down_distance_expectations=down_distance_expectations, verdict=verdict, notable_alerts=coach_alerts)
    ws = sheets.write_report(spreadsheet, rows, sheet_name=config.OUTPUT_SHEET_NAME)
    sheets.format_report_layout(ws, len(rows))
    sheets.apply_trend_formatting(ws, [c.change for c in formation_changes])


def _write_offense_report(spreadsheet, off_live_df, off_ready):
    if not off_ready:
        return
    summary = analysis.build_summary(off_live_df)
    formations = analysis.build_top_formations(off_live_df, top_n=config.TOP_N_FORMATIONS * 2)
    top_runs = analysis.build_top_plays(off_live_df, config.PLAY_TYPE_RUN, top_n=config.TOP_N_PLAYS * 2)
    top_passes = analysis.build_top_plays(off_live_df, config.PLAY_TYPE_PASS, top_n=config.TOP_N_PLAYS * 2)
    down_distance_summary = analysis.build_down_distance_summary(off_live_df)
    field_zone_summary = analysis.build_field_zone_summary(off_live_df)
    explosive = analysis.build_explosive_report(off_live_df, top_n=config.TOP_N_PLAYS * 2)
    rows = reports.build_offense_report(summary, formations, top_runs, top_passes, down_distance_summary, field_zone_summary, analysis.has_field_position_data(off_live_df), explosive)
    ws = sheets.write_report(spreadsheet, rows, sheet_name=config.OFF_OUTPUT_SHEET_NAME)
    sheets.format_report_layout(ws, len(rows))


def _write_stats_report(spreadsheet, off_live_df, off_ready, live_df, live_ready):
    print("Building Stats tab...")
    qb_stats = stats.build_qb_stats(off_live_df) if off_ready else analysis.QBStats(0, 0, 0.0, 0.0, 0, 0)
    ball_carrier_stats = stats.build_ball_carrier_stats(off_live_df) if off_ready else []
    def_live_yards = stats.build_def_live_yards(live_df) if live_ready else analysis.PlayTypeYards(0.0, 0.0)
    rows = reports.build_stats_report(qb_stats=qb_stats, ball_carrier_stats=ball_carrier_stats, def_live_yards=def_live_yards)
    ws = sheets.write_report(spreadsheet, rows, sheet_name=config.STATS_OUTPUT_SHEET_NAME)
    if ws is None:
        print("ERROR: Failed to write Stats report.")
        sys.exit(1)
    sheets.format_report_layout(ws, len(rows))
    print("Stats tab written and formatted.")


if __name__ == "__main__":
    main()
