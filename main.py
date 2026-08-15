"""
main.py
-------
The orchestration layer that ties together sheets.py (I/O), analysis.py
(calculations), and reports.py (formatting) into a complete run.

This is the entry point for the full analysis and report generation pipeline.
It loads scout and live data, runs all analyses, and writes the formatted
report to Google Sheets.
"""

import sys

import sheets
import analysis
import reports
import config


def main():
    """Main orchestration: load data, run analysis, generate report."""
    
    # 1. Authenticate and open the spreadsheet
    print("=" * 70)
    print("SHEETS-HUDL ANALYSIS PIPELINE")
    print("=" * 70)
    print()
    
    try:
        gc = sheets.get_client()
        spreadsheet = sheets.open_spreadsheet(gc)
    except Exception as e:
        print(f"ERROR: Failed to authenticate or open spreadsheet: {e}")
        sys.exit(1)
    
    # 2. Validate required tabs exist
    required_tabs = [
        config.WEEKLY_DATA_SHEET_NAME,  # "WEEKLY DATA" - scout data
        config.ODK_SHEET_NAME,           # "ODK" - live data
    ]
    sheets.validate_required_tabs(spreadsheet, required_tabs)
    print()
    
    # 3. Load scout data
    print("Loading SCOUT DATA...")
    scout_df = sheets.load_sheet_as_df(spreadsheet, config.WEEKLY_DATA_SHEET_NAME)
    if scout_df.empty:
        print("WARNING: Scout data is empty. Report will have no baseline.")
        scout_ready = False
    else:
        scout_df = analysis.add_situational_columns(scout_df)
        scout_ready = True
    print()
    
    # 4. Load live data (defensive snaps only from ODK)
    print("Loading LIVE DATA (defensive snaps)...")
    live_df = sheets.load_defense_live_df(spreadsheet)
    live_ready = len(live_df) > 0
    if not live_ready:
        print("WARNING: No defensive snaps found in ODK. Live data is empty.")
    print()
    
    # 5. Build Summary statistics for scout and live
    print("Building summary statistics...")
    scout_summary = analysis.build_summary(scout_df) if scout_ready else analysis.Summary(
        total_plays=0, run_pct=0.0, pass_pct=0.0,
        explosive_run_count=0, explosive_pass_count=0
    )
    
    live_summary = analysis.build_summary(live_df) if live_ready else analysis.Summary(
        total_plays=0, run_pct=0.0, pass_pct=0.0,
        explosive_run_count=0, explosive_pass_count=0
    )
    
    print(f"  Scout: {scout_summary.total_plays} plays, {scout_summary.run_pct:.1f}R/{scout_summary.pass_pct:.1f}P")
    print(f"  Live:  {live_summary.total_plays} plays, {live_summary.run_pct:.1f}R/{live_summary.pass_pct:.1f}P")
    print()
    
    # 6. Analyze defensive play types (run vs pass breakdown)
    print("Analyzing defensive play types...")
    if live_ready:
        def_analysis = analysis.analyze_def_play_types(live_df)
        print(f"  Defensive snaps: {def_analysis.total_defensive_plays}")
        print(f"    Runs:  {def_analysis.run_count} ({def_analysis.run_pct:.1f}%)")
        print(f"    Passes: {def_analysis.pass_count} ({def_analysis.pass_pct:.1f}%)")
    else:
        def_analysis = None
        print("  (skipped: no defensive snaps)")
    print()
    
    # 7. Build core comparison sections
    print("Building analysis sections...")
    
    identity = analysis.build_identity_comparison(scout_summary, live_summary)
    print()
    
    # 8. Generate formatted report
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
    print(f"  Report: {len(rows)} rows")
    print()
    
    # 9. Write to Google Sheets
    print("Writing to Google Sheets...")
    ws = sheets.write_report(spreadsheet, rows)
    if ws:
        sheets.format_report_layout(ws, len(rows))
        sheets.apply_trend_formatting(ws, [c.change for c in formation_changes])
        print("Report written and formatted successfully.")
    else:
        print("ERROR: Failed to write report.")
        sys.exit(1)
    
    print()
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
