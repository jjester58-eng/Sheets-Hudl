"""
stats.py
--------
Box-score/stat attribution from the ODK live sheet.

ODK has no separate QB/Passer column. Passing attribution is inferred from
PLAY TYPE + Result, while BALL CARRIER identifies the receiver or rusher.
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
    Fumbles are never QB attempts.
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

    IMPORTANT FUMBLE RULE:
    Every ODK Fumble with a BALL CARRIER is counted as ONE carry, regardless
    of whether PLAY TYPE says RUN or PASS. Fumbles have zero rushing yards
    and zero receiving yards. A fumble is never a QB attempt.

    Normal plays:
      RUN + Rush/Rush TD -> carry/rushing yards; Rush TD -> rushing TD.
      PASS + Complete/Complete TD -> reception/receiving yards;
          Complete TD -> receiving TD.
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
    complete = _result(config.RESULT_COMPLETE)
    complete_td = _result(config.RESULT_COMPLETE_TD)
    fumble = _result(config.RESULT_FUMBLE)

    players = []
    for carrier, group in work.groupby(config.COL_BALL_CARRIER, sort=True):
        res = group["_result"]
        play_type = group["_play_type"]
        is_run = play_type == run_type
        is_pass = play_type == pass_type
        is_fumble = res == fumble

        # EVERY fumble with a named BALL CARRIER is a carry.
        # This intentionally does not depend on PLAY TYPE.
        carries = int((is_run & res.isin({rush, rush_td})).sum() + is_fumble.sum())

        # Fumble yards are always zero, even if GN/LS happens to contain a value.
        rush_yards = float(
            group.loc[is_run & res.isin({rush, rush_td}), "_yards"].sum()
        )
        rush_tds = int((is_run & (res == rush_td)).sum())

        receptions = int((is_pass & res.isin({complete, complete_td})).sum())
        rec_yards = float(
            group.loc[is_pass & res.isin({complete, complete_td}), "_yards"].sum()
        )
        rec_tds = int((is_pass & (res == complete_td)).sum())
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
    """Opponent live offensive yards on D rows; fumbles add zero yards."""
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
