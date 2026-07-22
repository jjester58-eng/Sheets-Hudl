"""
analysis.py
-----------
All football calculations live here. Every function takes a pandas
DataFrame (or a value derived from one) and returns plain data structures
(dataclasses, dicts, lists) - no Google Sheets code, no formatting/string
layout. That separation is what lets reports.py and sheets.py stay simple.

The guiding question this module answers, in pieces:
    "Given the formation, down, distance, and field position,
     what is the offense most likely to run?"
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Data shapes returned by this module
# ---------------------------------------------------------------------------

@dataclass
class Summary:
    """Section 1: the headline numbers for a whole dataset."""
    total_plays: int
    run_pct: float
    pass_pct: float
    explosive_run_count: int
    explosive_pass_count: int


@dataclass
class PlayCallStat:
    """A single play call's usage and effectiveness."""
    play_name: str
    calls: int
    avg_gain: float
    explosive_count: int


@dataclass
class PlayProbability:
    """One play's likelihood inside a slice of plays - the atom the Expected
    Call engine is built from. `pct` is the play's share among the plays it
    was ranked within (e.g. share of all runs on 1st & Long)."""
    play_name: str
    pct: float
    count: int


@dataclass
class FormationSummary:
    """Section 2: one formation's usage rate and its go-to plays."""
    formation: str
    usage_pct: float
    run_pct: float
    pass_pct: float
    top_run_plays: List[str]
    top_pass_plays: List[str]


# ---------------------------------------------------------------------------
# Column prep
# ---------------------------------------------------------------------------

def add_situational_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adds derived columns used throughout the analysis: a down/distance
    bucket label and (if the data supports it) a field position zone.

    Safe to call on an empty DataFrame - returns it unchanged.
    """
    if df.empty:
        return df

    df = df.copy()

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
    """Buckets distance-to-go into Short/Medium/Long."""
    if pd.isna(distance):
        return "Unknown"
    if distance <= config.DIST_SHORT_MAX:
        return "Short"
    if distance <= config.DIST_MEDIUM_MAX:
        return "Medium"
    return "Long"


def _down_distance_label(down: Optional[float], dist_bucket: str) -> str:
    """Builds a label like '2nd & Long'. Returns 'Other' for downs we don't
    track (e.g. 4th down) so callers can filter it out cleanly."""
    if pd.isna(down) or int(down) not in config.DOWN_ORDINALS:
        return "Other"
    return f"{config.DOWN_ORDINALS[int(down)]} & {dist_bucket}"


def _field_zone(position: Optional[float]) -> str:
    """Maps a signed field position value to a named zone. Returns
    'Unknown' if the value doesn't fall in any configured zone."""
    if pd.isna(position):
        return "Unknown"
    for zone_name, low, high in config.FIELD_ZONES:
        if low <= position < high:
            return zone_name
    return "Unknown"


def has_field_position_data(df: pd.DataFrame) -> bool:
    """Whether this dataset has usable field position data. Used to decide
    whether Section 6 can be produced at all."""
    return (
        not df.empty
        and config.COL_FIELD_POSITION in df.columns
        and df[config.COL_FIELD_POSITION].notna().any()
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_pass_split(df: pd.DataFrame) -> tuple:
    """Returns (run_pct, pass_pct) for a slice of plays. Defensive against
    an empty slice or a missing PLAY TYPE column."""
    if df.empty or config.COL_PLAY_TYPE not in df.columns:
        return 0.0, 0.0

    total = len(df)
    run_count = (df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN).sum()
    pass_count = (df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS).sum()

    run_pct = round(run_count / total * 100, 1) if total else 0.0
    pass_pct = round(pass_count / total * 100, 1) if total else 0.0
    return run_pct, pass_pct


def _top_play_calls(df: pd.DataFrame, play_type: str, top_n: int) -> List[str]:
    """Returns just the play call names (no stats) for the most-called
    plays of a given type, most-called first. Used for the compact
    'Runs: Counter, Power, Dive' style lines."""
    if df.empty or config.COL_PLAY_CALL not in df.columns or config.COL_PLAY_TYPE not in df.columns:
        return []

    subset = df[df[config.COL_PLAY_TYPE] == play_type]
    if subset.empty:
        return []

    counts = subset[config.COL_PLAY_CALL].value_counts()
    return counts.head(top_n).index.tolist()


def _play_call_stats(df: pd.DataFrame, play_type: str) -> List[PlayCallStat]:
    """Returns every play call of the given type with usage count, average
    gain, and explosive count - used to build the ranked Top Plays lists."""
    if df.empty or config.COL_PLAY_CALL not in df.columns or config.COL_PLAY_TYPE not in df.columns:
        return []

    subset = df[df[config.COL_PLAY_TYPE] == play_type]
    if subset.empty:
        return []

    threshold = (
        config.EXPLOSIVE_RUN_THRESHOLD if play_type == config.PLAY_TYPE_RUN
        else config.EXPLOSIVE_PASS_THRESHOLD
    )

    stats = []
    for play_name, group in subset.groupby(config.COL_PLAY_CALL):
        avg_gain = round(group[config.COL_GAIN_LOSS].mean(), 1) if config.COL_GAIN_LOSS in group.columns else 0.0
        explosive_count = (
            int((group[config.COL_GAIN_LOSS] >= threshold).sum())
            if config.COL_GAIN_LOSS in group.columns else 0
        )
        stats.append(PlayCallStat(
            play_name=play_name,
            calls=len(group),
            avg_gain=avg_gain,
            explosive_count=explosive_count,
        ))

    return sorted(stats, key=lambda s: s.calls, reverse=True)


def _play_probabilities(df: pd.DataFrame, play_type: Optional[str], top_n: int) -> List[PlayProbability]:
    """Ranks play calls by frequency and returns each one's probability
    (share of the slice), most-likely first. This is what powers the
    'Most likely: 1. Counter 38%  2. Power 29%' Expected Call lines.

    If `play_type` is given, plays are ranked and shared *within* that type
    (share of all runs, or all passes); if None, within the whole slice.
    """
    if df.empty or config.COL_PLAY_CALL not in df.columns:
        return []

    subset = df
    if play_type is not None:
        if config.COL_PLAY_TYPE not in df.columns:
            return []
        subset = df[df[config.COL_PLAY_TYPE] == play_type]

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
    """Whether a slice has enough plays to trust a tendency drawn from it."""
    return play_count >= config.MIN_CONFIDENCE_SAMPLE


# ---------------------------------------------------------------------------
# Section 1: Summary
# ---------------------------------------------------------------------------

def build_summary(df: pd.DataFrame) -> Summary:
    """Headline numbers for the whole dataset."""
    if df.empty:
        return Summary(0, 0.0, 0.0, 0, 0)

    total_plays = len(df)
    run_pct, pass_pct = _run_pass_split(df)

    explosive_run_count = 0
    explosive_pass_count = 0
    if config.COL_GAIN_LOSS in df.columns and config.COL_PLAY_TYPE in df.columns:
        runs = df[df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_RUN]
        passes = df[df[config.COL_PLAY_TYPE] == config.PLAY_TYPE_PASS]
        explosive_run_count = int((runs[config.COL_GAIN_LOSS] >= config.EXPLOSIVE_RUN_THRESHOLD).sum())
        explosive_pass_count = int((passes[config.COL_GAIN_LOSS] >= config.EXPLOSIVE_PASS_THRESHOLD).sum())

    return Summary(
        total_plays=total_plays,
        run_pct=run_pct,
        pass_pct=pass_pct,
        explosive_run_count=explosive_run_count,
        explosive_pass_count=explosive_pass_count,
    )


# ---------------------------------------------------------------------------
# Section 2: Top Formations
# ---------------------------------------------------------------------------

def build_top_formations(df: pd.DataFrame, top_n: int = config.TOP_N_FORMATIONS) -> List[FormationSummary]:
    """Ranks formations by usage and returns the top N, each with its
    run/pass split and go-to plays."""
    if df.empty or config.COL_FORMATION not in df.columns:
        return []

    total_plays = len(df)
    usage_counts = df[config.COL_FORMATION].value_counts()

    summaries = []
    for formation, count in usage_counts.head(top_n).items():
        formation_df = df[df[config.COL_FORMATION] == formation]
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


# ---------------------------------------------------------------------------
# Sections 3 & 4: Top Run Plays / Top Pass Plays (overall)
# ---------------------------------------------------------------------------

def build_top_plays(df: pd.DataFrame, play_type: str, top_n: int = config.TOP_N_PLAYS) -> List[PlayCallStat]:
    """Top N plays of one type (Run or Pass), overall, ranked by how often
    they're called."""
    return _play_call_stats(df, play_type)[:top_n]


# ---------------------------------------------------------------------------
# Explosive Plays (per dataset - the raw material for the comparison table)
# ---------------------------------------------------------------------------

def build_explosive_report(df: pd.DataFrame, top_n: int = config.TOP_N_PLAYS) -> dict:
    """Returns {'runs': [...], 'passes': [...]} of the plays that produce
    the most explosive gains, ranked by explosive count."""
    if df.empty:
        return {"runs": [], "passes": []}

    run_stats = _play_call_stats(df, config.PLAY_TYPE_RUN)
    pass_stats = _play_call_stats(df, config.PLAY_TYPE_PASS)

    top_runs = sorted(run_stats, key=lambda s: s.explosive_count, reverse=True)[:top_n]
    top_passes = sorted(pass_stats, key=lambda s: s.explosive_count, reverse=True)[:top_n]

    # Drop plays that haven't actually produced any explosive gains -
    # showing a "top explosive play" with zero explosive plays isn't useful.
    top_runs = [s for s in top_runs if s.explosive_count > 0]
    top_passes = [s for s in top_passes if s.explosive_count > 0]

    return {"runs": top_runs, "passes": top_passes}


# ---------------------------------------------------------------------------
# --- Everything below this line is COMPARISON-FIRST. Each structure       --
# --- answers the same four questions for one slice of the game:           --
# ---   1. What did scout say?                                             --
# ---   2. What are they doing tonight (live)?                            --
# ---   3. Did they change?                                               --
# ---   4. If they line up here again, what should we expect?             --
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Section 1: Overall Identity (scout vs live headline)
# ---------------------------------------------------------------------------

@dataclass
class IdentityComparison:
    """Section 1: the one-glance 'who are they, and have they changed' line."""
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
    """Folds the scout and live Summaries into one side-by-side identity."""
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


# ---------------------------------------------------------------------------
# Raw usage movers (feed Biggest Changes, Coach Alerts, Game Plan Match)
# ---------------------------------------------------------------------------

@dataclass
class FormationChange:
    """How one formation's usage rate differs between scout and live."""
    formation: str
    scout_pct: float
    live_pct: float
    change: float       # live_pct - scout_pct (or live_pct if is_new)
    is_new: bool        # never appeared in scout data at all


@dataclass
class PlayChange:
    """How one play call's usage rate differs between scout and live."""
    play_name: str
    scout_pct: float
    live_pct: float
    scout_count: int
    live_count: int
    change: float
    is_new: bool


def compare_formations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[FormationChange]:
    """Compares formation usage % between scout and live, sorted by the
    largest absolute change first (biggest surprises float to the top)."""
    if config.COL_FORMATION not in scout_df.columns and config.COL_FORMATION not in live_df.columns:
        return []

    scout_total = len(scout_df)
    live_total = len(live_df)
    scout_counts = scout_df[config.COL_FORMATION].value_counts() if scout_total else pd.Series(dtype=int)
    live_counts = live_df[config.COL_FORMATION].value_counts() if live_total else pd.Series(dtype=int)

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
    """Compares play-call usage % (within the given play type) between
    scout and live, sorted by largest absolute change first."""
    scout_subset = scout_df[scout_df.get(config.COL_PLAY_TYPE) == play_type] if not scout_df.empty else scout_df
    live_subset = live_df[live_df.get(config.COL_PLAY_TYPE) == play_type] if not live_df.empty else live_df

    scout_total = len(scout_subset)
    live_total = len(live_subset)

    if config.COL_PLAY_CALL not in scout_df.columns and config.COL_PLAY_CALL not in live_df.columns:
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


# ---------------------------------------------------------------------------
# Section 2: Top Formations (scout vs live, per formation, with a status)
# ---------------------------------------------------------------------------

@dataclass
class FormationComparison:
    """Section 2: one formation, scout vs live - usage, run/pass tendency,
    go-to plays on each side, and a plain status. Answers 'are they lining up
    here as much, and doing the same things out of it?'"""
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
    new_plays: List[str]        # called live out of this formation, never on film
    status: str
    confident: bool


def _formation_status(scout_count: int, live_count: int, change: float, is_new: bool) -> str:
    """Plain one-liner for a formation's usage: same / more / less / new,
    guarded by confidence so a 2-snap sample never reads as a real trend."""
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
    """Builds a scout-vs-live comparison for the formations that matter most
    (highest usage on either side), each with its run/pass tendency, go-to
    plays, anything brand new, and a status."""
    have_scout = config.COL_FORMATION in scout_df.columns and not scout_df.empty
    have_live = config.COL_FORMATION in live_df.columns and not live_df.empty
    if not have_scout and not have_live:
        return []

    scout_total = len(scout_df)
    live_total = len(live_df)
    scout_counts = scout_df[config.COL_FORMATION].value_counts() if have_scout else pd.Series(dtype=int)
    live_counts = live_df[config.COL_FORMATION].value_counts() if have_live else pd.Series(dtype=int)

    comparisons = []
    for formation in set(scout_counts.index) | set(live_counts.index):
        scout_count = int(scout_counts.get(formation, 0))
        live_count = int(live_counts.get(formation, 0))
        scout_pct = round(scout_count / scout_total * 100, 1) if scout_total else 0.0
        live_pct = round(live_count / live_total * 100, 1) if live_total else 0.0

        scout_subset = scout_df[scout_df[config.COL_FORMATION] == formation] if have_scout else pd.DataFrame()
        live_subset = live_df[live_df[config.COL_FORMATION] == formation] if have_live else pd.DataFrame()

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


# ---------------------------------------------------------------------------
# Sections 4 & 5: Down & Distance / Field Position + the Expected Call engine
# ---------------------------------------------------------------------------

@dataclass
class SituationExpectation:
    """One situation (a down/distance bucket or a field zone), fully answered:
    what scout expected, what's happening live, whether it changed, and the
    ranked Expected Call for if they line up here again."""
    label: str
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    scout_dominant_type: str        # "Run" / "Pass"
    scout_dominant_pct: float
    live_dominant_type: str
    live_dominant_pct: float
    scout_expected_plays: List[PlayProbability]   # ranked within the dominant type
    live_top_plays: List[PlayProbability]
    scout_count: int
    live_count: int
    pass_pct_change: float
    verdict: str
    changed: bool
    scout_confident: bool
    live_confident: bool


def _dominant(run_pct: float, pass_pct: float) -> tuple:
    """Returns ('Pass', pass_pct) or ('Run', run_pct) - ties go to Pass since
    a balanced-to-passing look is the one a defense worries about more."""
    if pass_pct >= run_pct:
        return "Pass", pass_pct
    return "Run", run_pct


def _play_type_of(dominant_type: str) -> str:
    return config.PLAY_TYPE_PASS if dominant_type == "Pass" else config.PLAY_TYPE_RUN


def _situation_verdict(
    scout_dom: str, live_dom: str, pass_change: float,
    live_confident: bool, live_count: int,
) -> tuple:
    """Returns (verdict_text, changed) for a situation - the core 'did they
    change?' judgement, refusing to assert change off a tiny live sample."""
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
    scout_run_pct, scout_pass_pct = _run_pass_split(scout_subset)
    live_run_pct, live_pass_pct = _run_pass_split(live_subset)
    scout_count = len(scout_subset)
    live_count = len(live_subset)

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
        scout_expected_plays=_play_probabilities(scout_subset, _play_type_of(scout_dom), config.EXPECTED_CALL_TOP_N),
        live_top_plays=_play_probabilities(live_subset, _play_type_of(live_dom), config.EXPECTED_CALL_TOP_N),
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
    """Shared engine for Down & Distance and Field Position: for every label
    that has plays on either side, builds a full SituationExpectation."""
    results = []
    for label in ordered_labels:
        scout_subset = scout_df[scout_df[label_col] == label] if label_col in scout_df.columns else pd.DataFrame()
        live_subset = live_df[live_df[label_col] == label] if label_col in live_df.columns else pd.DataFrame()
        if scout_subset.empty and live_subset.empty:
            continue
        results.append(_situation_expectation(label, scout_subset, live_subset))
    return results


def _down_distance_labels() -> List[str]:
    return [
        _down_distance_label(down, dist_bucket)
        for down in config.DOWNS_TRACKED
        for dist_bucket in ("Short", "Medium", "Long")
    ]


def build_down_distance_expectations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[SituationExpectation]:
    """Down & Distance version of the Expected Call engine."""
    return _build_situation_expectations(scout_df, live_df, "DOWN_DISTANCE_LABEL", _down_distance_labels())


def build_field_zone_expectations(scout_df: pd.DataFrame, live_df: pd.DataFrame) -> List[SituationExpectation]:
    """Field Position version of the Expected Call engine. Empty if neither
    dataset has usable field position data."""
    if not (has_field_position_data(scout_df) or has_field_position_data(live_df)):
        return []
    labels = [zone_name for zone_name, _low, _high in config.FIELD_ZONES]
    return _build_situation_expectations(scout_df, live_df, "FIELD_ZONE", labels)


# ---------------------------------------------------------------------------
# Section 6: Explosive Plays (scout vs live, one small table)
# ---------------------------------------------------------------------------

@dataclass
class ExplosiveComparison:
    """One play's explosive-gain count, scout vs live."""
    play_name: str
    play_type: str      # "Run" / "Pass"
    scout_count: int
    live_count: int


def build_explosive_comparison(
    scout_df: pd.DataFrame, live_df: pd.DataFrame,
    top_n: int = config.TOP_N_PLAYS,
) -> List[ExplosiveComparison]:
    """The plays that produce explosive gains, scout vs live, in one table.
    A play appears if it went explosive on either side; ranked by its bigger
    of the two counts so the current game's threats surface."""
    scout_ex = build_explosive_report(scout_df, top_n=10 ** 6)
    live_ex = build_explosive_report(live_df, top_n=10 ** 6)

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


# ---------------------------------------------------------------------------
# Section 3: Biggest Changes (the section a coordinator reads first)
# ---------------------------------------------------------------------------

@dataclass
class BiggestChanges:
    """The handful of things that actually moved: usage risers/fallers among
    formations and plays, plus anything brand new."""
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
    """Distills the raw change lists down to the biggest confident movers and
    the brand-new looks - nothing small or noisy."""
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


# ---------------------------------------------------------------------------
# Section 9: Coach Alerts (plain-English, actionable, confidence-gated)
# ---------------------------------------------------------------------------

def build_coach_alerts(
    identity: IdentityComparison,
    formation_comparisons: List[FormationComparison],
    formation_changes: List[FormationChange],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
    down_distance_expectations: List[SituationExpectation],
    field_zone_expectations: List[SituationExpectation],
) -> List[str]:
    """Turns every comparison into short, plain-English observations a coach
    can act on between series. Live-based alerts fire only when the live
    sample is big enough to trust."""
    alerts: List[str] = []

    # Overall run/pass shift
    if abs(identity.pass_pct_change) >= config.ALERT_RUNPASS_CHANGE_PCT:
        direction = "more" if identity.pass_pct_change > 0 else "less"
        alerts.append(f"Passing {abs(identity.pass_pct_change):.0f}% {direction} than the scouting report.")

    # Formation usage swings (across all formations)
    for c in formation_changes:
        if c.is_new and c.live_pct > 0:
            alerts.append(f"{c.formation} has appeared for the first time ({c.live_pct:.0f}% of live snaps).")
        elif abs(c.change) >= config.ALERT_FORMATION_CHANGE_PCT:
            direction = "increased" if c.change > 0 else "decreased"
            alerts.append(f"{c.formation} usage has {direction} {abs(c.change):.0f}%.")

    # Per-formation pass tendency (only for the tracked top formations, confident)
    for fc in formation_comparisons:
        if not fc.confident:
            continue
        if fc.pass_pct_change >= config.ALERT_RUNPASS_CHANGE_PCT:
            alerts.append(f"They are throwing much more from {fc.formation} ({fc.live_pass_pct:.0f}% pass).")
        elif fc.pass_pct_change <= -config.ALERT_RUNPASS_CHANGE_PCT:
            alerts.append(f"They are running much more from {fc.formation} ({fc.live_run_pct:.0f}% run).")

    # Play-level: new plays, dropped favorites, promoted plays
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

    # Situational shifts (down & distance, then field position)
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


# ---------------------------------------------------------------------------
# Game Plan Match Score
# ---------------------------------------------------------------------------

@dataclass
class GamePlanScore:
    """The overall Game Plan Match Score and its components."""
    score: float
    band_label: str
    formation_component: float
    runpass_component: float
    top_plays_component: float
    down_distance_component: float


def _distribution_similarity(scout_pcts: dict, live_pcts: dict) -> float:
    """Total-variation-distance based similarity between two % distributions
    (e.g. formation usage). Returns 0-100, where 100 means identical."""
    all_keys = set(scout_pcts) | set(live_pcts)
    if not all_keys:
        return 100.0

    total_variation = 0.5 * sum(
        abs(scout_pcts.get(k, 0.0) - live_pcts.get(k, 0.0)) for k in all_keys
    )
    similarity = 100.0 - total_variation  # pcts are already 0-100 scale
    return max(0.0, min(100.0, similarity))


def _band_label(score: float) -> str:
    """Looks up the Game Plan Match band label for a given score."""
    for lower_bound, label in config.GAME_PLAN_BANDS:
        if score >= lower_bound:
            return label
    return config.GAME_PLAN_BANDS[-1][1]


def compute_game_plan_score(
    formation_changes: List[FormationChange],
    scout_summary: Summary,
    live_summary: Summary,
    scout_top_runs: List[PlayCallStat],
    scout_top_passes: List[PlayCallStat],
    live_top_runs: List[PlayCallStat],
    live_top_passes: List[PlayCallStat],
    down_distance_expectations: List[SituationExpectation],
) -> GamePlanScore:
    """Computes the weighted Game Plan Match Score:
        40% Formation Usage similarity
        20% Run/Pass Ratio similarity
        20% Top Plays overlap (top 3 run + top 3 pass, scout vs live)
        20% Down & Distance tendency similarity

    Each component is 0-100; the final score is their weighted sum.
    """
    scout_formation_pcts = {c.formation: c.scout_pct for c in formation_changes}
    live_formation_pcts = {c.formation: c.live_pct for c in formation_changes}
    formation_component = _distribution_similarity(scout_formation_pcts, live_formation_pcts)

    runpass_component = max(0.0, 100.0 - abs(live_summary.pass_pct - scout_summary.pass_pct))

    def _overlap_pct(scout_top, live_top):
        scout_names = {s.play_name for s in scout_top}
        live_names = {s.play_name for s in live_top}
        if not scout_names:
            return 100.0  # nothing to compare against - treat as neutral
        return len(scout_names & live_names) / len(scout_names) * 100.0

    run_overlap = _overlap_pct(scout_top_runs, live_top_runs)
    pass_overlap = _overlap_pct(scout_top_passes, live_top_passes)
    top_plays_component = (run_overlap + pass_overlap) / 2.0

    comparable = [e for e in down_distance_expectations if e.live_count > 0]
    if comparable:
        avg_deviation = sum(abs(e.pass_pct_change) for e in comparable) / len(comparable)
        down_distance_component = max(0.0, 100.0 - avg_deviation)
    else:
        down_distance_component = 100.0  # no comparable buckets yet - neutral

    score = (
        config.GAME_PLAN_WEIGHT_FORMATION * formation_component
        + config.GAME_PLAN_WEIGHT_RUNPASS * runpass_component
        + config.GAME_PLAN_WEIGHT_TOP_PLAYS * top_plays_component
        + config.GAME_PLAN_WEIGHT_DOWN_DISTANCE * down_distance_component
    )
    score = round(max(0.0, min(100.0, score)), 1)

    return GamePlanScore(
        score=score,
        band_label=_band_label(score),
        formation_component=round(formation_component, 1),
        runpass_component=round(runpass_component, 1),
        top_plays_component=round(top_plays_component, 1),
        down_distance_component=round(down_distance_component, 1),
    )
