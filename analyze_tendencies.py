"""
analyze_tendencies.py
----------------------
Orchestrator only. Loads scout and live data, runs every analysis
function, and writes the report. No football math (that's analysis.py)
and no report formatting (that's reports.py) - if you're tempted to add
either kind of logic here, it belongs in one of those modules instead.

Answers, comparison-first: "Are they doing what we scouted, or have they
changed - and if they line up here again, what should we expect?"
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

    # --- Headline numbers for each side (building blocks) ---
    scout_summary = analysis.build_summary(scout_df)
    live_summary = analysis.build_summary(live_df)
    scout_top_runs = analysis.build_top_plays(scout_df, config.PLAY_TYPE_RUN)
    scout_top_passes = analysis.build_top_plays(scout_df, config.PLAY_TYPE_PASS)
    live_top_runs = analysis.build_top_plays(live_df, config.PLAY_TYPE_RUN)
    live_top_passes = analysis.build_top_plays(live_df, config.PLAY_TYPE_PASS)

    # --- 1. Overall Identity (scout vs live) ---
    identity = analysis.build_identity_comparison(scout_summary, live_summary)

    # --- 4. Top Formations (comparison, per formation) ---
    formation_comparisons = analysis.build_formation_comparisons(scout_df, live_df)

    # --- 5. Formation Tendencies (the scout "book") ---
    formation_tendencies = analysis.build_top_formations(scout_df, top_n=config.TOP_N_FORMATIONS * 2)

    # --- 6 & 7. Down & Distance / Field Position + Expected Call engine ---
    down_distance_expectations = analysis.build_down_distance_expectations(scout_df, live_df)
    field_zone_expectations = analysis.build_field_zone_expectations(scout_df, live_df)
    field_position_available = (
        analysis.has_field_position_data(scout_df) or analysis.has_field_position_data(live_df)
    )

    # --- 8. Explosive Plays (comparison) ---
    explosive = analysis.build_explosive_comparison(scout_df, live_df)

    # --- Raw movers (feed Biggest Changes, Coach Alerts, Game Plan Match) ---
    formation_changes = analysis.compare_formations(scout_df, live_df)
    run_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_RUN)
    pass_changes = analysis.compare_plays(scout_df, live_df, config.PLAY_TYPE_PASS)

    # --- 3. Biggest Changes ---
    biggest_changes = analysis.build_biggest_changes(formation_changes, run_changes, pass_changes)

    # --- 9. Coach Alerts ---
    coach_alerts = analysis.build_coach_alerts(
        identity, formation_comparisons, formation_changes,
        run_changes, pass_changes,
        down_distance_expectations, field_zone_expectations,
    )

    # --- 2. Game Plan Match ---
    live_ready = live_summary.total_plays >= config.MIN_LIVE_PLAYS_FOR_COMPARISON
    game_plan_score = analysis.compute_game_plan_score(
        formation_changes, scout_summary, live_summary,
        scout_top_runs, scout_top_passes, live_top_runs, live_top_passes,
        down_distance_expectations,
    ) if live_ready else None

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
        live_ready=live_ready,
    )

    sheets.write_report(spreadsheet, report_rows)
    print("Done.")


if __name__ == "__main__":
    main()
