import pandas as pd

import analysis
import config


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
