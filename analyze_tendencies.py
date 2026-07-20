"""
analyze_tendencies.py
----------------------
Orchestrator only. Loads scout and live data, runs every analysis
function, and writes the report. No football math (that's analysis.py)
and no report formatting (that's reports.py) - if you're tempted to add
either kind of logic here, it belongs in one of those modules instead.

Answers: "Given the formation, down, distance, and field position, what
is the offense most likely to run - and are they still doing it tonight?"
"""

import config
import sheets
import analysis
import reports


def main() -> None:
    gc = sheets.get_client()
    spreadsheet = sheets.open_spreadsheet(gc)
    sheets.validate_required_tabs(spreadsheet, [config.SOURCE_SHEET_NAME, config.SCOUT_SHEET_NAME])

    scout_df = analysis.add_situational_columns(sheets.load_sheet_as_df(spreadsheet, config.SCOUT_SHEET_NAME))
    live_df = analysis.add_situational_columns(sheets.load_sheet_as_df(spreadsheet, config.SOURCE_SHEET_NAME))

    # --- Scout Report (static) ---
    scout_summary = analysis.build_summary(scout_df)
    scout_formations = analysis.build_top_formations(scout_df)
    scout_top_runs = analysis.build_top_plays(scout_df, config.PLAY_TYPE_RUN)
    scout_top_passes = analysis.build_top_plays(scout_df, config.PLAY_TYPE_PASS)
    scout_buckets = analysis.build_down_distance_buckets(scout_df)
    scout_field_available = analysis.has_field_position_data(scout_df)
    scout_zones = analysis.build_field_zone_report(scout_df)
    scout_explosive = analysis.build_explosive_report(scout_df)

    # --- Live Report (same shape, live data) ---
    live_summary = analysis.build_summary(live_df)
    live_formations = analysis.build_top_formations(live_df)
    live_top_runs = analysis.build_top_plays(live_df, config.PLAY_TYPE_RUN)
    live_top_passes = analysis.build_top_plays(live_df, config.PLAY_TYPE_PASS)
    live_buckets = analysis.build_down_distance_buckets(live_df)
    live_field_available = analysis.has_field_position_data(live_df)
    live_zones = analysis.build_field_zone_report(live_df)
    live_explosive = analysis.build_explosive_report(live_df)

    # --- What To Expect (predictive, from scout data) ---
    what_to_expect = analysis.build_what_to_expect(scout_formations, scout_buckets, scout_zones)

    # --- Live Adjustments (scout vs live comparisons) ---
    formation_changes = analysis.compare_formations(scout_df, live_df)
    top_3_formation_names = [f.formation for f in scout_formations]
    formation_deep_dives = analysis.build_formation_deep_dive(scout_df, live_df, top_3_formation_names)
    run_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_RUN)
    pass_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_PASS)
    down_distance_comparisons = analysis.compare_down_distance(scout_buckets, live_buckets)
    field_zone_comparisons = analysis.compare_field_zones(scout_zones, live_zones)

    coach_alerts = analysis.build_coach_alerts(
        formation_changes, run_changes, pass_changes, scout_summary, live_summary,
        down_distance_comparisons, field_zone_comparisons,
    )

    game_plan_score = analysis.compute_game_plan_score(
        formation_changes, scout_summary, live_summary,
        scout_top_runs, scout_top_passes, live_top_runs, live_top_passes,
        down_distance_comparisons,
    )

    report_rows = reports.build_full_report(
        what_to_expect=what_to_expect,
        scout_summary=scout_summary, scout_formations=scout_formations,
        scout_top_runs=scout_top_runs, scout_top_passes=scout_top_passes,
        scout_buckets=scout_buckets, scout_zones=scout_zones,
        scout_field_available=scout_field_available, scout_explosive=scout_explosive,
        live_summary=live_summary, live_formations=live_formations,
        live_top_runs=live_top_runs, live_top_passes=live_top_passes,
        live_buckets=live_buckets, live_zones=live_zones,
        live_field_available=live_field_available, live_explosive=live_explosive,
        formation_changes=formation_changes, formation_deep_dives=formation_deep_dives,
        run_changes=run_changes, pass_changes=pass_changes,
        down_distance_comparisons=down_distance_comparisons,
        field_zone_comparisons=field_zone_comparisons,
        coach_alerts=coach_alerts, game_plan_score=game_plan_score,
    )

    sheets.write_report(spreadsheet, report_rows)
    print("Done.")


if __name__ == "__main__":
    main()
