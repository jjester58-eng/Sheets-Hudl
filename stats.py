"""
stats.py
--------
Box-score/stat attribution from the ODK live sheet.

ODK has no separate QB/Passer column. Passing attribution is therefore
inferred from PLAY TYPE + Result, while BALL CARRIER identifies the receiver
or rusher. Fumbles are credited to BALL CARRIER but are never QB pass attempts.
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
    result = df[config.COL_RESULT].astype(str).str.lower()
    return df[~result.str.contains("penalty", na=False)].copy()


def build_qb_stats(df: pd.DataFrame) -> QBStats:
    """Infer QB passing stats from PASS + Result.

    Attempts are ONLY Complete, Complete TD, Incomplete, and Interception.
    Fumbles are deliberately excluded because the ODK fumble record belongs
    to BALL CARRIER and is not a QB passing attempt.
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
    """Build rushing/receiving/fumble stats from BALL CARRIER.

    Run + Rush/Rush TD = carry and rushing yards.
    Pass + Complete/Complete TD = reception and receiving yards.
    Rush TD goes to the rusher; Complete TD goes to both QB and receiver.
    Fumble always goes to BALL CARRIER, regardless of Run/Pass, but never adds
    receiving yards or QB attempts. A rushing fumble is a carry with zero
    recorded yards when GN/LS is blank.
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
    work[config.COL_BALL_CARRIER] = work[config.COL_BALL_CARRIER].fillna("").astype(str).str.strip()
    work = work[work[config.COL_BALL_CARRIER] != ""]
    if work.empty:
        return []

    result = work[config.COL_RESULT].map(_result)
    work["_result"] = result
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)

    rush = _result(config.RESULT_RUSH)
    rush_td = _result(config.RESULT_RUSH_TD)
    complete = _result(config.RESULT_COMPLETE)
    complete_td = _result(config.RESULT_COMPLETE_TD)
    fumble = _result(config.RESULT_FUMBLE)

    players = []
    for carrier, group in work.groupby(config.COL_BALL_CARRIER, sort=True):
        is_run = group[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN
        is_pass = group[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS
        res = group["_result"]

        # A rushing fumble is still a rushing attempt. A passing fumble is not.
        carries = int((is_run & res.isin({rush, rush_td, fumble})).sum())
        rush_yards = float(group.loc[is_run & res.isin({rush, rush_td}), "_yards"].sum())
        rush_tds = int((is_run & (res == rush_td)).sum())

        receptions = int((is_pass & res.isin({complete, complete_td})).sum())
        rec_yards = float(group.loc[is_pass & res.isin({complete, complete_td}), "_yards"].sum())
        rec_tds = int((is_pass & (res == complete_td)).sum())

        fumbles = int((res == fumble).sum())

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
    """Opponent live offensive yards recorded on D rows.

    Fumbles have no GN/LS by design and therefore contribute zero yards.
    """
    clean = _clean(df)
    required = {config.COL_PLAY_TYPE, config.COL_GAIN_LOSS}
    if clean.empty or not required.issubset(clean.columns):
        return PlayTypeYards(0.0, 0.0)

    work = clean.copy()
    work["_result"] = work[config.COL_RESULT].map(_result)
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)
    work.loc[work["_result"] == _result(config.RESULT_FUMBLE), "_yards"] = 0.0

    rushing = float(work.loc[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN, "_yards"].sum())
    passing = float(work.loc[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS, "_yards"].sum())
    return PlayTypeYards(rushing, passing)
