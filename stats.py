"""stats.py
--------
Box-score/stat attribution from the ODK live sheet.
"""

import pandas as pd

import config
from analysis import BallCarrierStats, PlayTypeYards, QBStats


def _result(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or config.COL_RESULT not in df.columns:
        return df.copy()
    result = df[config.COL_RESULT].astype(str).str.strip().str.lower()
    return df[~result.str.contains("penalty", na=False)].copy()


def build_qb_stats(df: pd.DataFrame) -> QBStats:
    """Infer QB passing stats from PASS + Result.

    Attempts are Complete, Complete TD, Incomplete, and Interception.
    Scrambles and sacks are excluded from passing attempts and passing yards.
    """
    clean = _clean(df)
    required = {config.COL_PLAY_TYPE, config.COL_RESULT, config.COL_GAIN_LOSS}
    if clean.empty or not required.issubset(clean.columns):
        return QBStats(0, 0, 0.0, 0.0, 0, 0)

    passes = clean[clean[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS].copy()
    if passes.empty:
        return QBStats(0, 0, 0.0, 0.0, 0, 0)

    result = passes[config.COL_RESULT].map(_result)
    yards = pd.to_numeric(passes[config.COL_GAIN_LOSS], errors="coerce").fillna(0)
    complete = _result(config.RESULT_COMPLETE)
    complete_td = _result(config.RESULT_COMPLETE_TD)
    incomplete = _result(config.RESULT_INCOMPLETE)
    interception = _result(config.RESULT_INTERCEPTION)

    attempt_mask = result.isin({complete, complete_td, incomplete, interception})
    completion_mask = result.isin({complete, complete_td})
    attempts = int(attempt_mask.sum())
    completions = int(completion_mask.sum())
    pass_yards = float(yards[completion_mask].sum())
    pass_td = int((result == complete_td).sum())
    interceptions = int((result == interception).sum())
    comp_pct = round(completions / attempts * 100, 1) if attempts else 0.0

    return QBStats(attempts, completions, comp_pct, pass_yards, pass_td, interceptions)


def build_ball_carrier_stats(df: pd.DataFrame) -> list[BallCarrierStats]:
    """Build rushing, receiving and fumble stats from BALL CARRIER.

    Scramble and Sack always count as rushing attempts and rushing yards for
    the named BALL CARRIER, even when PLAY TYPE is PASS.
    """
    clean = _clean(df)
    required = {
        config.COL_BALL_CARRIER,
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    }
    if clean.empty or not required.issubset(clean.columns):
        return []

    work = clean[list(required)].copy()
    work[config.COL_BALL_CARRIER] = (
        work[config.COL_BALL_CARRIER].fillna("").astype(str).str.strip()
    )
    work = work[work[config.COL_BALL_CARRIER] != ""]
    if work.empty:
        return []

    work["_result"] = work[config.COL_RESULT].map(_result)
    work["_play_type"] = work[config.COL_PLAY_TYPE].astype(str).str.strip().str.lower()
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)

    run_type = str(config.PLAY_TYPE_RUN).strip().lower()
    pass_type = str(config.PLAY_TYPE_PASS).strip().lower()
    rush = _result(config.RESULT_RUSH)
    rush_td = _result(config.RESULT_RUSH_TD)
    scramble = "scramble"
    sack = "sack"
    complete = _result(config.RESULT_COMPLETE)
    complete_td = _result(config.RESULT_COMPLETE_TD)
    fumble = _result(config.RESULT_FUMBLE)

    players = []
    for carrier, group in work.groupby(config.COL_BALL_CARRIER, sort=True):
        res = group["_result"]
        play_type = group["_play_type"]
        is_run = play_type == run_type
        is_pass = play_type == pass_type
        is_scramble_or_sack = res.isin({scramble, sack})
        is_fumble = res == fumble

        normal_rush = is_run & res.isin({rush, rush_td})
        rushing_plays = normal_rush | is_scramble_or_sack

        # Every fumble with a named BALL CARRIER is also counted as one carry.
        carries = int(rushing_plays.sum() + is_fumble.sum())
        rush_yards = float(group.loc[rushing_plays, "_yards"].sum())
        rush_tds = int((is_run & (res == rush_td)).sum())

        receiving_plays = (
            is_pass
            & ~is_scramble_or_sack
            & res.isin({complete, complete_td})
        )
        receptions = int(receiving_plays.sum())
        rec_yards = float(group.loc[receiving_plays, "_yards"].sum())
        rec_tds = int((receiving_plays & (res == complete_td)).sum())
        fumbles = int(is_fumble.sum())

        players.append(BallCarrierStats(
            ball_carrier=str(carrier),
            carries=carries,
            rush_yards=rush_yards,
            yards_per_carry=round(rush_yards / carries, 1) if carries else 0.0,
            rush_td=rush_tds,
            receptions=receptions,
            rec_yards=rec_yards,
            rec_td=rec_tds,
            fumbles=fumbles,
        ))

    return sorted(players, key=lambda p: (-(p.rush_yards + p.rec_yards), p.ball_carrier))


def build_def_live_yards(df: pd.DataFrame) -> PlayTypeYards:
    """Opponent live offensive yards.

    Scrambles and sacks are classified as rushing yards regardless of PLAY TYPE.
    Fumbles add zero yards.
    """
    clean = _clean(df)
    required = {config.COL_PLAY_TYPE, config.COL_RESULT, config.COL_GAIN_LOSS}
    if clean.empty or not required.issubset(clean.columns):
        return PlayTypeYards(0.0, 0.0)

    work = clean.copy()
    work["_result"] = work[config.COL_RESULT].map(_result)
    work["_play_type"] = work[config.COL_PLAY_TYPE].astype(str).str.strip().str.lower()
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)

    fumble = _result(config.RESULT_FUMBLE)
    work.loc[work["_result"] == fumble, "_yards"] = 0.0

    run_type = str(config.PLAY_TYPE_RUN).strip().lower()
    pass_type = str(config.PLAY_TYPE_PASS).strip().lower()
    is_scramble_or_sack = work["_result"].isin({"scramble", "sack"})

    rushing_mask = (work["_play_type"] == run_type) | is_scramble_or_sack
    passing_mask = (
        (work["_play_type"] == pass_type)
        & ~is_scramble_or_sack
    )

    rushing = float(work.loc[rushing_mask, "_yards"].sum())
    passing = float(work.loc[passing_mask, "_yards"].sum())
    return PlayTypeYards(rushing, passing)
