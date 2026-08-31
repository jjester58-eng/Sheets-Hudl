"""
analysis.py
-----------
All football calculations live here.
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import config


@dataclass
class Summary:
    total_plays: int
    run_pct: float
    pass_pct: float
    explosive_run_count: int
    explosive_pass_count: int


@dataclass
class PlayTypeYards:
    rushing_yards: float
    passing_yards: float


@dataclass
class BallCarrierStats:
    ball_carrier: str
    carries: int
    rush_yards: float
    yards_per_carry: float
    rush_td: int
    receptions: int
    rec_yards: float
    rec_td: int
    fumbles: int


@dataclass
class QBStats:
    attempts: int
    completions: int
    comp_pct: float
    pass_yards: float
    pass_td: int
    interceptions: int


@dataclass
class PenaltyStats:
    offense_count: int
    offense_yards: float
    defense_count: int
    defense_yards: float


@dataclass
class PlayCallStat:
    play_name: str
    calls: int
    avg_gain: float
    explosive_count: int


@dataclass
class PlayProbability:
    play_name: str
    pct: float
    count: int


@dataclass
class FormationSummary:
    formation: str
    usage_pct: float
    run_pct: float
    pass_pct: float
    top_run_plays: List[str]
    top_pass_plays: List[str]


_RUN_TOKENS = {"run", "rush", "r"}
_PASS_TOKENS = {"pass", "throw", "p", "pa", "ps"}


def _normalize_play_type(value):
    if pd.isna(value):
        return value
    text = str(value).strip().lower()
    if text in _RUN_TOKENS:
        return config.PLAY_TYPE_RUN
    if text in _PASS_TOKENS:
        return config.PLAY_TYPE_PASS
    return str(value).strip()


def _normalize_result(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _filter_out_penalties(df: pd.DataFrame) -> pd.DataFrame:
    """Removes any play where Result contains 'Penalty'."""
    if df.empty or config.COL_RESULT not in df.columns:
        return df
    res_lower = df[config.COL_RESULT].astype(str).str.lower()
    return df[~res_lower.str.contains("penalty", na=False)].copy()


def add_situational_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    if config.COL_PLAY_TYPE in df.columns:
        df[config.COL_PLAY_TYPE] = df[config.COL_PLAY_TYPE].map(_normalize_play_type)

    if config.COL_GAIN_LOSS in df.columns:
        df[config.COL_GAIN_LOSS] = pd.to_numeric(df[config.COL_GAIN_LOSS], errors="coerce")

    if config.COL_DISTANCE in df.columns:
        df[config.COL_DISTANCE] = pd.to_numeric(df[config.COL_DISTANCE], errors="coerce")

    if config.COL_DOWN in df.columns:
        df[config.COL_DOWN] = pd.to_numeric(df[config.COL_DOWN], errors="coerce")

    if config.COL_DISTANCE in df.columns:
        df["DIST_BUCKET"] = df[config.COL_DISTANCE].apply(_distance_bucket)

    if config.COL_DOWN in df.columns and "DIST_BUCKET" in df.columns:
        df["DOWN_DISTANCE_LABEL"] = df.apply(
            lambda row: _down_distance_label(row[config.COL_DOWN], row["DIST_BUCKET"]),
            axis=1,
        )

    if config.COL_FIELD_POSITION in df.columns:
        df[config.COL_FIELD_POSITION] = pd.to_numeric(df[config.COL_FIELD_POSITION], errors="coerce")
        df["FIELD_ZONE"] = df[config.COL_FIELD_POSITION].apply(_field_zone)

    return df


def _distance_bucket(distance: Optional[float]) -> str:
    if pd.isna(distance):
        return "Unknown"
    if distance <= config.DIST_SHORT_MAX:
        return "Short"
    if distance <= config.DIST_MEDIUM_MAX:
        return "Medium"
    return "Long"


def _down_distance_label(down: Optional[float], dist_bucket: str) -> str:
    if pd.isna(down) or int(down) not in config.DOWN_ORDINALS:
        return "Other"
    return f"{config.DOWN_ORDINALS[int(down)]} & {dist_bucket}"


def _yards_from_own_goal(v: Optional[float]) -> Optional[float]:
    if pd.isna(v):
        return None
    return -v if v < 0 else 100 - v


def _field_zone(position: Optional[float]) -> str:
    y = _yards_from_own_goal(position)
    if y is None:
        return "Unknown"
    for zone_name, low, high in config.FIELD_ZONES:
        if low <= y < high:
            return zone_name
    return "Unknown"


def has_field_position_data(df: pd.DataFrame) -> bool:
    clean_df = _filter_out_penalties(df)
    return (
        not clean_df.empty
        and config.COL_FIELD_POSITION in clean_df.columns
        and clean_df[config.COL_FIELD_POSITION].notna().any()
    )


def _run_pass_split(df: pd.DataFrame) -> tuple:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty or config.COL_PLAY_TYPE not in clean_df.columns:
        return 0.0, 0.0

    total = len(clean_df)
    run_count = (clean_df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN).sum()
    pass_count = (clean_df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS).sum()

    run_pct = round(run_count / total * 100, 1) if total else 0.0
    pass_pct = round(pass_count / total * 100, 1) if total else 0.0
    return run_pct, pass_pct


def build_play_type_yards(df: pd.DataFrame) -> PlayTypeYards:
    clean_df = _filter_out_penalties(df)
    required = {config.COL_PLAY_TYPE, config.COL_GAIN_LOSS}
    if clean_df.empty or not required.issubset(clean_df.columns):
        return PlayTypeYards(0.0, 0.0)

    work = clean_df.copy()
    work["_res"] = work[config.COL_RESULT].map(_normalize_result)
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)
    
    # Zero out fumble yards
    work.loc[work["_res"] == _normalize_result(config.RESULT_FUMBLE), "_yards"] = 0.0

    rushing_yards = float(work.loc[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN, "_yards"].sum())
    passing_yards = float(work.loc[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS, "_yards"].sum())
    return PlayTypeYards(rushing_yards, passing_yards)


def build_ball_carrier_stats(df: pd.DataFrame) -> List[BallCarrierStats]:
    clean_df = _filter_out_penalties(df)
    required = {
        config.COL_BALL_CARRIER,
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    }
    if clean_df.empty or not required.issubset(clean_df.columns):
        return []

    work = clean_df.loc[:, [
        config.COL_BALL_CARRIER,
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    ]].copy()
    work[config.COL_BALL_CARRIER] = work[config.COL_BALL_CARRIER].fillna("").astype(str).str.strip()
    work = work[work[config.COL_BALL_CARRIER] != ""]
    if work.empty:
        return []

    work["_result"] = work[config.COL_RESULT].map(_normalize_result)
    work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)

    rush_result = _normalize_result(config.RESULT_RUSH)
    rush_td_result = _normalize_result(config.RESULT_RUSH_TD)
    complete_result = _normalize_result(config.RESULT_COMPLETE)
    complete_td_result = _normalize_result(config.RESULT_COMPLETE_TD)
    fumble_result = _normalize_result(config.RESULT_FUMBLE)

    players = []
    for ball_carrier, group in work.groupby(config.COL_BALL_CARRIER, sort=True):
        is_run = group[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN
        is_pass = group[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS

        # Carries count Rush, Rush TD, and Fumble on run plays
        rush_mask = is_run & group["_result"].isin({rush_result, rush_td_result, fumble_result})
        carries = int(rush_mask.sum())
        
        # Zero yardage contribution on fumbles
        rush_yards_mask = is_run & group["_result"].isin({rush_result, rush_td_result})
        rush_yards = float(group.loc[rush_yards_mask, "_yards"].sum())
        rush_td = int((is_run & (group["_result"] == rush_td_result)).sum())

        rec_mask = is_pass & group["_result"].isin({complete_result, complete_td_result})
        receptions = int(rec_mask.sum())
        rec_yards = float(group.loc[rec_mask, "_yards"].sum())
        rec_td = int((is_pass & (group["_result"] == complete_td_result)).sum())

        fumbles = int((group["_result"] == fumble_result).sum())

        players.append(BallCarrierStats(
            ball_carrier=ball_carrier,
            carries=carries,
            rush_yards=rush_yards,
            yards_per_carry=round(rush_yards / carries, 1) if carries else 0.0,
            rush_td=rush_td,
            receptions=receptions,
            rec_yards=rec_yards,
            rec_td=rec_td,
            fumbles=fumbles,
        ))

    return sorted(players, key=lambda p: (-(p.rush_yards + p.rec_yards), p.ball_carrier))


def build_qb_stats(df: pd.DataFrame) -> QBStats:
    clean_df = _filter_out_penalties(df)
    required = {config.COL_PLAY_TYPE, config.COL_RESULT, config.COL_GAIN_LOSS}
    if clean_df.empty or not required.issubset(clean_df.columns):
        return QBStats(0, 0, 0.0, 0.0, 0, 0)

    pass_df = clean_df[clean_df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS]
    if pass_df.empty:
        return QBStats(0, 0, 0.0, 0.0, 0, 0)

    result = pass_df[config.COL_RESULT].map(_normalize_result)
    yards = pd.to_numeric(pass_df[config.COL_GAIN_LOSS], errors="coerce").fillna(0)

    complete_result = _normalize_result(config.RESULT_COMPLETE)
    complete_td_result = _normalize_result(config.RESULT_COMPLETE_TD)
    incomplete_result = _normalize_result(config.RESULT_INCOMPLETE)
    interception_result = _normalize_result(config.RESULT_INTERCEPTION)
    fumble_result = _normalize_result(config.RESULT_FUMBLE)

    # Attempts include Completions, Incompletions, Interceptions, and Fumbles on pass plays
    attempt_values = {complete_result, complete_td_result, incomplete_result, interception_result, fumble_result}
    is_attempt = result.isin(attempt_values)
    attempts = int(is_attempt.sum())

    is_complete = result.isin({complete_result, complete_td_result})
    completions = int(is_complete.sum())
    pass_yards = float(yards[is_complete].sum())
    pass_td = int((result == complete_td_result).sum())
    interceptions = int((result == interception_result).sum())

    comp_pct = round(completions / attempts * 100, 1) if attempts else 0.0

    return QBStats(
        attempts=attempts,
        completions=completions,
        comp_pct=comp_pct,
        pass_yards=pass_yards,
        pass_td=pass_td,
        interceptions=interceptions,
    )


def build_penalty_stats(odk_df: pd.DataFrame) -> PenaltyStats:
    """Calculates penalty counts and net yardages for Offense and Defense."""
    if odk_df.empty or config.COL_RESULT not in odk_df.columns or config.COL_SIDE not in odk_df.columns:
        return PenaltyStats(0, 0.0, 0, 0.0)

    work = odk_df.copy()
    work["_res"] = work[config.COL_RESULT].astype(str).str.lower()
    pen_df = work[work["_res"].str.contains("penalty", na=False)]

    if pen_df.empty:
        return PenaltyStats(0, 0.0, 0, 0.0)

    yards = pd.to_numeric(pen_df[config.COL_GAIN_LOSS], errors="coerce").fillna(0)
    
    off_mask = pen_df[config.COL_SIDE] == config.SIDE_OFFENSE
    def_mask = pen_df[config.COL_SIDE] == config.SIDE_DEFENSE

    off_count = int(off_mask.sum())
    off_yards = float(yards[off_mask].sum())
    def_count = int(def_mask.sum())
    def_yards = float(yards[def_mask].sum())

    return PenaltyStats(
        offense_count=off_count,
        offense_yards=off_yards,
        defense_count=def_count,
        defense_yards=def_yards,
    )


def _top_play_calls(df: pd.DataFrame, play_type: str, top_n: int) -> List[str]:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty or config.COL_PLAY_CALL not in clean_df.columns or config.COL_PLAY_TYPE not in clean_df.columns:
        return []

    subset = clean_df[clean_df[config.COL_PLAY_TYPE] == play_type]
    if subset.empty:
        return []

    counts = subset[config.COL_PLAY_CALL].value_counts()
    return counts.head(top_n).index.tolist()


def _play_call_stats(df: pd.DataFrame, play_type: str) -> List[PlayCallStat]:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty or config.COL_PLAY_CALL not in clean_df.columns or config.COL_PLAY_TYPE not in clean_df.columns:
        return []

    subset = clean_df[clean_df[config.COL_PLAY_TYPE] == play_type].copy()
    if subset.empty:
        return []

    threshold = (
        config.EXPLOSIVE_RUN_THRESHOLD if play_type == config.PLAY_TYPE_RUN
        else config.EXPLOSIVE_PASS_THRESHOLD
    )

    stats = []
    for play_name, group in subset.groupby(config.COL_PLAY_CALL):
        # Zero out fumble yardages for average and explosive math
        group_yards = pd.to_numeric(group[config.COL_GAIN_LOSS], errors="coerce").fillna(0).copy()
        is_fumble = group[config.COL_RESULT].map(_normalize_result) == _normalize_result(config.RESULT_FUMBLE)
        group_yards[is_fumble] = 0.0

        avg_gain = round(group_yards.mean(), 1) if not group_yards.empty else 0.0
        explosive_count = int((group_yards >= threshold).sum())

        stats.append(PlayCallStat(
            play_name=play_name,
            calls=len(group),
            avg_gain=avg_gain,
            explosive_count=explosive_count,
        ))

    return sorted(stats, key=lambda s: s.calls, reverse=True)


def _play_probabilities(df: pd.DataFrame, play_type: Optional[str], top_n: int) -> List[PlayProbability]:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty or config.COL_PLAY_CALL not in clean_df.columns:
        return []

    subset = clean_df
    if play_type is not None:
        if config.COL_PLAY_TYPE not in clean_df.columns:
            return []
        subset = clean_df[clean_df[config.COL_PLAY_TYPE] == play_type]

    total = len(subset)
    if total == 0:
        return []

    counts = subset[config.COL_PLAY_CALL].value_counts()
    return [
        PlayProbability(
            play_name=name,
            pct=round(count / total * 100, 1),
            count=int(count),
        )
        for name, count in counts.head(top_n).items()
    ]


def is_confident(play_count: int) -> bool:
    return play_count >= config.MIN_CONFIDENCE_SAMPLE


def build_summary(df: pd.DataFrame) -> Summary:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty:
        return Summary(0, 0.0, 0.0, 0, 0)

    total_plays = len(clean_df)
    run_pct, pass_pct = _run_pass_split(clean_df)

    explosive_run_count = 0
    explosive_pass_count = 0
    if config.COL_GAIN_LOSS in clean_df.columns and config.COL_PLAY_TYPE in clean_df.columns:
        work = clean_df.copy()
        work["_res"] = work[config.COL_RESULT].map(_normalize_result)
        work["_yards"] = pd.to_numeric(work[config.COL_GAIN_LOSS], errors="coerce").fillna(0)
        work.loc[work["_res"] == _normalize_result(config.RESULT_FUMBLE), "_yards"] = 0.0

        runs = work[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN]
        passes = work[work[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS]
        explosive_run_count = int((runs["_yards"] >= config.EXPLOSIVE_RUN_THRESHOLD).sum())
        explosive_pass_count = int((passes["_yards"] >= config.EXPLOSIVE_PASS_THRESHOLD).sum())

    return Summary(
        total_plays=total_plays,
        run_pct=run_pct,
        pass_pct=pass_pct,
        explosive_run_count=explosive_run_count,
        explosive_pass_count=explosive_pass_count,
    )


def build_top_formations(df: pd.DataFrame, top_n: int = config.TOP_N_FORMATIONS) -> List[FormationSummary]:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty or config.COL_FORMATION not in clean_df.columns:
        return []

    total_plays = len(clean_df)
    usage_counts = clean_df[config.COL_FORMATION].value_counts()

    summaries = []
    for formation, count in usage_counts.head(top_n).items():
        formation_df = clean_df[clean_df[config.COL_FORMATION] == formation]
        run_pct, pass_pct = _run_pass_split(formation_df)
        summaries.append(FormationSummary(
            formation=formation,
            usage_pct=round(count / total_plays * 100, 1),
            run_pct=run_pct,
            pass_pct=pass_pct,
            top_run_plays=_top_play_calls(formation_df, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            top_pass_plays=_top_play_calls(formation_df, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
        ))

    return summaries


def build_top_plays(df: pd.DataFrame, play_type: str, top_n: int = config.TOP_N_PLAYS) -> List[PlayCallStat]:
    return _play_call_stats(df, play_type)[:top_n]


def build_explosive_report(df: pd.DataFrame, top_n: int = config.TOP_N_PLAYS) -> dict:
    clean_df = _filter_out_penalties(df)
    if clean_df.empty:
        return {"runs": [], "passes": []}

    run_stats = _play_call_stats(clean_df, config.PLAY_TYPE_RUN)
    pass_stats = _play_call_stats(clean_df, config.PLAY_TYPE_PASS)

    top_runs = sorted(run_stats, key=lambda s: s.explosive_count, reverse=True)[:top_n]
    top_passes = sorted(pass_stats, key=lambda s: s.explosive_count, reverse=True)[:top_n]

    top_runs = [s for s in top_runs if s.explosive_count > 0]
    top_passes = [s for s in top_passes if s.explosive_count > 0]

    return {"runs": top_runs, "passes": top_passes}


@dataclass
class IdentityComparison:
    scout_plays: int
    live_plays: int
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    run_pct_change: float
    pass_pct_change: float
    scout_explosive_run: int
    scout_explosive_pass: int
    live_explosive_run: int
    live_explosive_pass: int


def build_identity_comparison(scout: Summary, live: Summary) -> IdentityComparison:
    return IdentityComparison(
        scout_plays=scout.total_plays,
        live_plays=live.total_plays,
        scout_run_pct=scout.run_pct,
        scout_pass_pct=scout.pass_pct,
        live_run_pct=live.run_pct,
        live_pass_pct=live.pass_pct,
        run_pct_change=round(live.run_pct - scout.run_pct, 1),
        pass_pct_change=round(live.pass_pct - scout.pass_pct, 1),
        scout_explosive_run=scout.explosive_run_count,
        scout_explosive_pass=scout.explosive_pass_count,
        live_explosive_run=live.explosive_run_count,
        live_explosive_pass=live.explosive_pass_count,
    )


@dataclass
class FormationChange:
    formation: str
    scout_pct: float
    live_pct: float
    change: float
    is_new: bool


@dataclass
class PlayChange:
    play_name: str
    scout_pct: float
    live_pct: float
    scout_count: int
    live_count: int
    change: float
    is_new: bool


def compare_formations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[FormationChange]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)

    if config.COL_FORMATION not in c_scout.columns and config.COL_FORMATION not in c_live.columns:
        return []

    scout_total = len(c_scout)
    live_total = len(c_live)
    scout_counts = c_scout[config.COL_FORMATION].value_counts() if scout_total else pd.Series(dtype=int)
    live_counts = c_live[config.COL_FORMATION].value_counts() if live_total else pd.Series(dtype=int)

    all_formations = sorted(set(scout_counts.index) | set(live_counts.index))
    changes = []
    for formation in all_formations:
        scout_count = int(scout_counts.get(formation, 0))
        live_count = int(live_counts.get(formation, 0))
        scout_pct = round(scout_count / scout_total * 100, 1) if scout_total else 0.0
        live_pct = round(live_count / live_total * 100, 1) if live_total else 0.0

        changes.append(FormationChange(
            formation=formation,
            scout_pct=scout_pct,
            live_pct=live_pct,
            change=round(live_pct - scout_pct, 1),
            is_new=(scout_count == 0 and live_count > 0),
        ))

    return sorted(changes, key=lambda c: abs(c.change), reverse=True)


def compare_plays(scout_df: pd.DataFrame, live_df: pd.DataFrame, play_type: str) -> List[PlayChange]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)

    scout_subset = c_scout[c_scout.get(config.COL_PLAY_TYPE) == play_type] if not c_scout.empty else c_scout
    live_subset = c_live[c_live.get(config.COL_PLAY_TYPE) == play_type] if not c_live.empty else c_live

    scout_total = len(scout_subset)
    live_total = len(live_subset)

    if config.COL_PLAY_CALL not in c_scout.columns and config.COL_PLAY_CALL not in c_live.columns:
        return []

    scout_counts = scout_subset[config.COL_PLAY_CALL].value_counts() if scout_total else pd.Series(dtype=int)
    live_counts = live_subset[config.COL_PLAY_CALL].value_counts() if live_total else pd.Series(dtype=int)

    all_plays = sorted(set(scout_counts.index) | set(live_counts.index))
    changes = []
    for play_name in all_plays:
        scout_count = int(scout_counts.get(play_name, 0))
        live_count = int(live_counts.get(play_name, 0))
        scout_pct = round(scout_count / scout_total * 100, 1) if scout_total else 0.0
        live_pct = round(live_count / live_total * 100, 1) if live_total else 0.0

        changes.append(PlayChange(
            play_name=play_name,
            scout_pct=scout_pct,
            live_pct=live_pct,
            scout_count=scout_count,
            live_count=live_count,
            change=round(live_pct - scout_pct, 1),
            is_new=(scout_count == 0 and live_count > 0),
        ))

    return sorted(changes, key=lambda c: abs(c.change), reverse=True)


@dataclass
class FormationComparison:
    formation: str
    scout_pct: float
    live_pct: float
    change: float
    is_new: bool
    scout_count: int
    live_count: int
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    pass_pct_change: float
    scout_top_runs: List[str]
    scout_top_passes: List[str]
    live_top_runs: List[str]
    live_top_passes: List[str]
    new_plays: List[str]
    status: str
    confident: bool


def _formation_status(scout_count: int, live_count: int, change: float, is_new: bool) -> str:
    if live_count == 0:
        return "Not seen live yet"
    if not is_confident(live_count):
        return f"{config.STATUS_LOW_CONFIDENCE} ({live_count} live)"
    if is_new:
        return config.STATUS_NEW
    if change >= config.ALERT_FORMATION_CHANGE_PCT:
        return config.STATUS_USING_MORE
    if change <= -config.ALERT_FORMATION_CHANGE_PCT:
        return config.STATUS_USING_LESS
    return config.STATUS_SAME


def build_formation_comparisons(
    scout_df: pd.DataFrame,
    live_df: pd.DataFrame,
    top_n: int = config.TOP_N_FORMATIONS,
) -> List[FormationComparison]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)

    have_scout = config.COL_FORMATION in c_scout.columns and not c_scout.empty
    have_live = config.COL_FORMATION in c_live.columns and not c_live.empty
    if not have_scout and not have_live:
        return []

    scout_total = len(c_scout)
    live_total = len(c_live)
    scout_counts = c_scout[config.COL_FORMATION].value_counts() if have_scout else pd.Series(dtype=int)
    live_counts = c_live[config.COL_FORMATION].value_counts() if have_live else pd.Series(dtype=int)

    comparisons = []
    for formation in set(scout_counts.index) | set(live_counts.index):
        scout_count = int(scout_counts.get(formation, 0))
        live_count = int(live_counts.get(formation, 0))
        scout_pct = round(scout_count / scout_total * 100, 1) if scout_total else 0.0
        live_pct = round(live_count / live_total * 100, 1) if live_total else 0.0

        scout_subset = c_scout[c_scout[config.COL_FORMATION] == formation] if have_scout else pd.DataFrame()
        live_subset = c_live[c_live[config.COL_FORMATION] == formation] if have_live else pd.DataFrame()

        scout_run_pct, scout_pass_pct = _run_pass_split(scout_subset)
        live_run_pct, live_pass_pct = _run_pass_split(live_subset)

        scout_plays = set(scout_subset[config.COL_PLAY_CALL]) if config.COL_PLAY_CALL in scout_subset.columns else set()
        live_plays = set(live_subset[config.COL_PLAY_CALL]) if config.COL_PLAY_CALL in live_subset.columns else set()

        change = round(live_pct - scout_pct, 1)
        is_new = scout_count == 0 and live_count > 0

        comparisons.append(FormationComparison(
            formation=formation,
            scout_pct=scout_pct,
            live_pct=live_pct,
            change=change,
            is_new=is_new,
            scout_count=scout_count,
            live_count=live_count,
            scout_run_pct=scout_run_pct,
            scout_pass_pct=scout_pass_pct,
            live_run_pct=live_run_pct,
            live_pass_pct=live_pass_pct,
            pass_pct_change=round(live_pass_pct - scout_pass_pct, 1),
            scout_top_runs=_top_play_calls(scout_subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            scout_top_passes=_top_play_calls(scout_subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
            live_top_runs=_top_play_calls(live_subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            live_top_passes=_top_play_calls(live_subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
            new_plays=sorted(live_plays - scout_plays),
            status=_formation_status(scout_count, live_count, change, is_new),
            confident=is_confident(live_count),
        ))

    comparisons.sort(key=lambda c: max(c.scout_pct, c.live_pct), reverse=True)
    return comparisons[:top_n]


@dataclass
class SituationExpectation:
    label: str
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    scout_dominant_type: str
    scout_dominant_pct: float
    live_dominant_type: str
    live_dominant_pct: float
    scout_expected_plays: List[PlayProbability]
    live_top_plays: List[PlayProbability]
    scout_count: int
    live_count: int
    pass_pct_change: float
    verdict: str
    changed: bool
    scout_confident: bool
    live_confident: bool


def _dominant(run_pct: float, pass_pct: float) -> tuple:
    if pass_pct >= run_pct:
        return "Pass", pass_pct
    return "Run", run_pct


def _play_type_of(dominant_type: str) -> str:
    return config.PLAY_TYPE_PASS if dominant_type == "Pass" else config.PLAY_TYPE_RUN


def _situation_verdict(
    scout_dom: str, live_dom: str, pass_change: float,
    live_confident: bool, live_count: int,
) -> tuple:
    if live_count == 0:
        return "Not seen live yet", False
    if not live_confident:
        return f"{config.STATUS_LOW_CONFIDENCE} ({live_count} live)", False
    if scout_dom != live_dom:
        return config.STATUS_FLIPPED, True
    if pass_change >= config.SITUATION_CHANGE_ALERT_PCT:
        return config.STATUS_MORE_PASS, True
    if pass_change <= -config.SITUATION_CHANGE_ALERT_PCT:
        return config.STATUS_MORE_RUN, True
    return config.STATUS_SAME, False


def _situation_expectation(label: str, scout_subset: pd.DataFrame, live_subset: pd.DataFrame) -> SituationExpectation:
    c_scout = _filter_out_penalties(scout_subset)
    c_live = _filter_out_penalties(live_subset)

    scout_run_pct, scout_pass_pct = _run_pass_split(c_scout)
    live_run_pct, live_pass_pct = _run_pass_split(c_live)
    scout_count = len(c_scout)
    live_count = len(c_live)

    scout_dom, scout_dom_pct = _dominant(scout_run_pct, scout_pass_pct)
    live_dom, live_dom_pct = _dominant(live_run_pct, live_pass_pct)

    scout_confident = scout_count >= config.MIN_SAMPLE_FOR_EXPECTATION
    live_confident = is_confident(live_count)

    pass_change = round(live_pass_pct - scout_pass_pct, 1)
    verdict, changed = _situation_verdict(scout_dom, live_dom, pass_change, live_confident, live_count)

    return SituationExpectation(
        label=label,
        scout_run_pct=scout_run_pct,
        scout_pass_pct=scout_pass_pct,
        live_run_pct=live_run_pct,
        live_pass_pct=live_pass_pct,
        scout_dominant_type=scout_dom,
        scout_dominant_pct=scout_dom_pct,
        live_dominant_type=live_dom,
        live_dominant_pct=live_dom_pct,
        scout_expected_plays=_play_probabilities(c_scout, _play_type_of(scout_dom), config.EXPECTED_CALL_TOP_N),
        live_top_plays=_play_probabilities(c_live, _play_type_of(live_dom), config.EXPECTED_CALL_TOP_N),
        scout_count=scout_count,
        live_count=live_count,
        pass_pct_change=pass_change,
        verdict=verdict,
        changed=changed,
        scout_confident=scout_confident,
        live_confident=live_confident,
    )


def _build_situation_expectations(
    scout_df: pd.DataFrame, live_df: pd.DataFrame,
    label_col: str, ordered_labels: List[str],
) -> List[SituationExpectation]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)
    results = []
    for label in ordered_labels:
        scout_subset = c_scout[c_scout[label_col] == label] if label_col in c_scout.columns else pd.DataFrame()
        live_subset = c_live[c_live[label_col] == label] if label_col in c_live.columns else pd.DataFrame()
        if scout_subset.empty and live_subset.empty:
            continue
        results.append(_situation_expectation(label, scout_subset, live_subset))
    return results


def _down_distance_labels() -> List[str]:
    return [
        "1st & Long",
        "2nd & Long",
        "2nd & Medium",
        "2nd & Short",
        "3rd & Long",
        "3rd & Medium",
        "3rd & Short",
    ]


def build_down_distance_expectations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[SituationExpectation]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)

    results = _build_situation_expectations(
        c_scout, c_live, "DOWN_DISTANCE_LABEL", _down_distance_labels()
    )

    for bucket in ("Long", "Medium", "Short"):
        scout_subset = (
            c_scout[c_scout["DIST_BUCKET"] == bucket]
            if "DIST_BUCKET" in c_scout.columns else pd.DataFrame()
        )
        live_subset = (
            c_live[c_live["DIST_BUCKET"] == bucket]
            if "DIST_BUCKET" in c_live.columns else pd.DataFrame()
        )
        if scout_subset.empty and live_subset.empty:
            continue
        results.append(_situation_expectation(bucket, scout_subset, live_subset))

    return results


def build_field_zone_expectations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[SituationExpectation]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)
    if not (has_field_position_data(c_scout) or has_field_position_data(c_live)):
        return []
    labels = [zone_name for zone_name, _low, _high in config.FIELD_ZONES]
    return _build_situation_expectations(c_scout, c_live, "FIELD_ZONE", labels)


@dataclass
class SituationSelfSummary:
    label: str
    play_count: int
    run_pct: float
    pass_pct: float
    top_plays: List[PlayProbability]
    confident: bool


def _self_situation_summary(label: str, df: pd.DataFrame) -> SituationSelfSummary:
    clean_df = _filter_out_penalties(df)
    run_pct, pass_pct = _run_pass_split(clean_df)
    dom, _dom_pct = _dominant(run_pct, pass_pct)
    return SituationSelfSummary(
        label=label,
        play_count=len(clean_df),
        run_pct=run_pct,
        pass_pct=pass_pct,
        top_plays=_play_probabilities(clean_df, _play_type_of(dom), config.EXPECTED_CALL_TOP_N),
        confident=is_confident(len(clean_df)),
    )


def build_down_distance_summary(df: pd.DataFrame) -> List[SituationSelfSummary]:
    clean_df = _filter_out_penalties(df)
    results = []
    for label in _down_distance_labels():
        subset = clean_df[clean_df["DOWN_DISTANCE_LABEL"] == label] if "DOWN_DISTANCE_LABEL" in clean_df.columns else pd.DataFrame()
        if subset.empty:
            continue
        results.append(_self_situation_summary(label, subset))

    for bucket in ("Long", "Medium", "Short"):
        subset = clean_df[clean_df["DIST_BUCKET"] == bucket] if "DIST_BUCKET" in clean_df.columns else pd.DataFrame()
        if subset.empty:
            continue
        results.append(_self_situation_summary(bucket, subset))

    return results


def build_field_zone_summary(df: pd.DataFrame) -> List[SituationSelfSummary]:
    clean_df = _filter_out_penalties(df)
    if not has_field_position_data(clean_df):
        return []
    results = []
    for zone_name, _low, _high in config.FIELD_ZONES:
        subset = clean_df[clean_df["FIELD_ZONE"] == zone_name] if "FIELD_ZONE" in clean_df.columns else pd.DataFrame()
        if subset.empty:
            continue
        results.append(_self_situation_summary(zone_name, subset))
    return results


@dataclass
class ExplosiveComparison:
    play_name: str
    play_type: str
    scout_count: int
    live_count: int


def build_explosive_comparison(
    scout_df: pd.DataFrame, live_df: pd.DataFrame,
    top_n: int = config.TOP_N_PLAYS,
) -> List[ExplosiveComparison]:
    c_scout = _filter_out_penalties(scout_df)
    c_live = _filter_out_penalties(live_df)

    scout_ex = build_explosive_report(c_scout, top_n=10 ** 6)
    live_ex = build_explosive_report(c_live, top_n=10 ** 6)

    rows: List[ExplosiveComparison] = []
    for play_type, key in ((config.PLAY_TYPE_RUN, "runs"), (config.PLAY_TYPE_PASS, "passes")):
        scout_map = {s.play_name: s.explosive_count for s in scout_ex[key]}
        live_map = {s.play_name: s.explosive_count for s in live_ex[key]}
        for name in set(scout_map) | set(live_map):
            rows.append(ExplosiveComparison(
                play_name=name,
                play_type=play_type,
                scout_count=scout_map.get(name, 0),
                live_count=live_map.get(name, 0),
            ))

    rows.sort(key=lambda r: max(r.scout_count, r.live_count), reverse=True)
    return rows[: top_n * 2]


@dataclass
class BiggestChanges:
    formation_movers: List[FormationChange]
    play_movers: List[PlayChange]
    new_plays: List[str]
    new_formations: List[str]


def build_biggest_changes(
    formation_changes: List[FormationChange],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
    top_n: int = config.BIGGEST_CHANGES_TOP_N,
) -> BiggestChanges:
    def movers(changes, min_change):
        confident = [c for c in changes if not c.is_new and abs(c.change) >= min_change]
        confident.sort(key=lambda c: abs(c.change), reverse=True)
        return confident[:top_n]

    formation_movers = movers(formation_changes, config.ALERT_FORMATION_CHANGE_PCT)
    play_movers = movers(run_changes + pass_changes, config.ALERT_PLAY_CHANGE_PCT)

    new_formations = [c.formation for c in formation_changes if c.is_new and c.live_pct > 0]
    new_plays = [
        c.play_name for c in (run_changes + pass_changes)
        if c.is_new and c.live_count >= config.NEW_PLAY_MIN_LIVE_COUNT
    ]

    return BiggestChanges(
        formation_movers=formation_movers,
        play_movers=play_movers,
        new_plays=new_plays,
        new_formations=new_formations,
    )


def build_coach_alerts(
    identity: IdentityComparison,
    formation_comparisons: List[FormationComparison],
    formation_changes: List[FormationChange],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
    down_distance_expectations: List[SituationExpectation],
    field_zone_expectations: List[SituationExpectation],
) -> List[str]:
    alerts: List[str] = []

    if abs(identity.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT:
        direction = "more" if identity.pass_pct_change > 0 else "less"
        alerts.append(f"Passing {abs(identity.pass_pct_change):.0f}% {direction} than the scouting report.")

    for c in formation_changes:
        if c.is_new and c.live_pct > 0:
            alerts.append(f"{c.formation} has appeared for the first time ({c.live_pct:.0f}% of live snaps).")
        elif abs(c.change) >= config.ALERT_FORMATION_CHANGE_PCT:
            direction = "increased" if c.change > 0 else "decreased"
            alerts.append(f"{c.formation} usage has {direction} {abs(c.change):.0f}%.")

    for fc in formation_comparisons:
        if not fc.confident:
            continue
        if fc.pass_pct_change >= config.ALERT_RUNPASS_CHANGE_PCT:
            alerts.append(f"They are throwing much more from {fc.formation} ({fc.live_pass_pct:.0f}% pass).")
        elif fc.pass_pct_change <= -config.ALERT_RUNPASS_CHANGE_PCT:
            alerts.append(f"They are running much more from {fc.formation} ({fc.live_run_pct:.0f}% run).")

    for changes, label in ((run_changes, "run"), (pass_changes, "pass")):
        for c in changes:
            if c.is_new and c.live_count >= config.NEW_PLAY_MIN_LIVE_COUNT:
                alerts.append(f"{c.play_name} has appeared - not on scout film.")
            elif (c.scout_count >= config.LOW_USAGE_ALERT_MIN_SCOUT_COUNT
                  and c.live_count <= config.LOW_USAGE_ALERT_MAX_LIVE_COUNT):
                alerts.append(f"{c.play_name} was a scout favorite, barely used live.")

        risers = [c for c in changes if c.change >= config.ALERT_PLAY_CHANGE_PCT]
        if risers:
            top_riser = max(risers, key=lambda c: c.live_pct)
            if top_riser.live_pct == max((c.live_pct for c in changes), default=0):
                alerts.append(f"{top_riser.play_name} has become their primary {label}.")

    for exp in down_distance_expectations:
        if not (exp.changed and exp.live_confident):
            continue
        if exp.verdict == config.STATUS_FLIPPED:
            alerts.append(
                f"{exp.label} has flipped from {exp.scout_dominant_type.lower()}-heavy "
                f"to {exp.live_dominant_type.lower()}-heavy."
            )
        else:
            alerts.append(f"On {exp.label} they are {exp.verdict.lower()} "
                          f"({exp.live_pass_pct:.0f}% pass vs {exp.scout_pass_pct:.0f}% scouted).")

    for exp in field_zone_expectations:
        if not exp.live_confident:
            continue
        if exp.live_dominant_type == "Pass" and exp.live_pass_pct >= 65:
            alerts.append(f"In the {exp.label} they are throwing {exp.live_pass_pct:.0f}%.")
        elif exp.live_dominant_type == "Run" and exp.live_run_pct >= 65:
            alerts.append(f"In the {exp.label} they are running {exp.live_run_pct:.0f}%.")

    return alerts


def build_scout_fidelity_verdict(
    identity: IdentityComparison,
    formation_changes: List[FormationChange],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
) -> str:
    has_big_rp_shift = abs(identity.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT
    has_big_form_shift = any(abs(c.change) >= config.ALERT_FORMATION_CHANGE_PCT for c in formation_changes)
    has_new_form = any(c.is_new and c.live_pct > 0 for c in formation_changes)

    if has_big_rp_shift and (has_big_form_shift or has_new_form):
        return "Completely different offense"
    if has_big_rp_shift or has_big_form_shift or has_new_form:
        return "Significant changes"
    return "Following scout"
