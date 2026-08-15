import pandas as pd

import analysis
import config
import sheets


def test_play_type_normalization_handles_case_and_whitespace():
    df = pd.DataFrame(
        {
            config.COL_PLAY_TYPE: ["run", " PASS ", "Run", "pass", "run"],
            config.COL_PLAY_CALL: ["Zone", "Slant", "Dive", "Go", "Power"],
            config.COL_GAIN_LOSS: [5, 12, 8, 22, 10],
        }
    )

    normalized = analysis.add_situational_columns(df)

    assert list(normalized[config.COL_PLAY_TYPE]) == [
        config.PLAY_TYPE_RUN,
        config.PLAY_TYPE_PASS,
        config.PLAY_TYPE_RUN,
        config.PLAY_TYPE_PASS,
        config.PLAY_TYPE_RUN,
    ]
    assert analysis._run_pass_split(normalized) == (60.0, 40.0)


def test_odk_columns_supports_b_and_h_positions():
    df = pd.DataFrame([
        ["Game 1", "O", "x", "x", "x", "x", "x", "Run"],
        ["Game 2", "D", "x", "x", "x", "x", "x", "Pass"],
        ["Game 3", "D", "x", "x", "x", "x", "x", "Run"],
        ["Game 4", "O", "x", "x", "x", "x", "x", "Pass"],
    ], columns=["Game", "ODK", "A", "B", "C", "D", "E", "PLAY TYPE"])

    result = analysis.analyze_def_play_types(df)

    assert result.total_defensive_plays == 2
    assert result.run_count == 1
    assert result.pass_count == 1
    assert result.run_pct == 50.0
    assert result.pass_pct == 50.0


def test_defensive_play_type_counts_r_and_p_shorthand():
    df = pd.DataFrame([
        ["Game 1", "D", "x", "x", "x", "x", "x", "R"],
        ["Game 2", "D", "x", "x", "x", "x", "x", "P"],
        ["Game 3", "D", "x", "x", "x", "x", "x", "Run"],
        ["Game 4", "O", "x", "x", "x", "x", "x", "Pass"],
    ], columns=["Game", "ODK", "A", "B", "C", "D", "E", "PLAY TYPE"])

    result = analysis.analyze_def_play_types(df)

    assert result.total_defensive_plays == 3
    assert result.run_count == 2
    assert result.pass_count == 1
    assert result.run_pct == 66.7
    assert result.pass_pct == 33.3
