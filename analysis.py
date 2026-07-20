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
class FormationSummary:
    """Section 2: one formation's usage rate and its go-to plays."""
    formation: str
    usage_pct: float
    run_pct: float
    pass_pct: float
    top_run_plays: List[str]
    top_pass_plays: List[str]


@dataclass
class SituationBucket:
    """Shared shape for Section 5 (down & distance) and Section 6 (field
    position) - both are 'in this situation, what do they like to run'."""
    label: str
    run_pct: float
    pass_pct: float
    top_run_plays: List[str]
    top_pass_plays: List[str]
    play_count: int
    top_overall_play: Optional[str] = None
    top_overall_play_pct: float = 0.0


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


def _top_overall_play(df: pd.DataFrame) -> tuple:
    """Returns (play_name, pct_share) for the single most-called play in a
    slice, regardless of run or pass. Used for 'this situation becomes
    {play} football' style notes. Returns (None, 0.0) if there's no usable
    play-call data."""
    if df.empty or config.COL_PLAY_CALL not in df.columns:
        return None, 0.0

    counts = df[config.COL_PLAY_CALL].value_counts()
    if counts.empty:
        return None, 0.0

    top_play = counts.index[0]
    pct_share = round(counts.iloc[0] / len(df) * 100, 1)
    return top_play, pct_share


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
# Section 5: Down & Distance
# ---------------------------------------------------------------------------

def build_down_distance_buckets(df: pd.DataFrame) -> List[SituationBucket]:
    """One SituationBucket per down/distance combo (1st/2nd/3rd x
    Short/Medium/Long), in a fixed, predictable order. Buckets with no
    plays are skipped rather than shown empty."""
    if df.empty or "DOWN_DISTANCE_LABEL" not in df.columns:
        return []

    buckets = []
    for down in config.DOWNS_TRACKED:
        for dist_bucket in ("Short", "Medium", "Long"):
            label = _down_distance_label(down, dist_bucket)
            subset = df[df["DOWN_DISTANCE_LABEL"] == label]
            if subset.empty:
                continue

            run_pct, pass_pct = _run_pass_split(subset)
            top_play, top_play_pct = _top_overall_play(subset)
            buckets.append(SituationBucket(
                label=label,
                run_pct=run_pct,
                pass_pct=pass_pct,
                top_run_plays=_top_play_calls(subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
                top_pass_plays=_top_play_calls(subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
                play_count=len(subset),
                top_overall_play=top_play,
                top_overall_play_pct=top_play_pct,
            ))

    return buckets


# ---------------------------------------------------------------------------
# Section 6: Field Position
# ---------------------------------------------------------------------------

def build_field_zone_report(df: pd.DataFrame) -> List[SituationBucket]:
    """One SituationBucket per field zone. Returns an empty list if the
    dataset has no usable field position column - callers should check
    has_field_position_data() first to decide whether to show the section
    at all."""
    if not has_field_position_data(df):
        return []

    buckets = []
    for zone_name, _low, _high in config.FIELD_ZONES:
        subset = df[df["FIELD_ZONE"] == zone_name]
        if subset.empty:
            continue

        run_pct, pass_pct = _run_pass_split(subset)
        top_play, top_play_pct = _top_overall_play(subset)
        buckets.append(SituationBucket(
            label=zone_name,
            run_pct=run_pct,
            pass_pct=pass_pct,
            top_run_plays=_top_play_calls(subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            top_pass_plays=_top_play_calls(subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
            play_count=len(subset),
            top_overall_play=top_play,
            top_overall_play_pct=top_play_pct,
        ))

    return buckets


# ---------------------------------------------------------------------------
# Section 7: Explosive Plays
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
# Section 8: Coach Notes (dynamic bullet points)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# --- Everything below this line supports the LIVE vs SCOUT comparison  -----
# --- half of the report: formation/play changes, situational shifts,   -----
# --- the Game Plan Match Score, Coach Alerts, and What To Expect.      -----
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


@dataclass
class FormationDeepDive:
    """Full scout-vs-live comparison for a single formation: run/pass split,
    each side's top plays, and anything new or significantly different."""
    formation: str
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    scout_top_runs: List[str]
    scout_top_passes: List[str]
    live_top_runs: List[str]
    live_top_passes: List[str]
    new_plays: List[str]        # called live in this formation, never on scout film
    run_pct_change: float
    pass_pct_change: float


@dataclass
class SituationComparison:
    """Scout-vs-live comparison for one Down & Distance or Field Position
    bucket. Only built for buckets with real data on both sides."""
    label: str
    scout_run_pct: float
    scout_pass_pct: float
    live_run_pct: float
    live_pass_pct: float
    pass_pct_change: float
    alert_text: Optional[str]


@dataclass
class ExpectationItem:
    """One line of the 'What To Expect' predictive section - a single
    high-confidence situation and what's likely to be called."""
    category: str          # "Formation" / "Down & Distance" / "Field Position"
    label: str
    dominant_type: str     # "Pass" or "Run"
    dominant_pct: float
    likely_plays: List[str]


@dataclass
class GamePlanScore:
    """The overall Game Plan Match Score and its components."""
    score: float
    band_label: str
    formation_component: float
    runpass_component: float
    top_plays_component: float
    down_distance_component: float


# ---------------------------------------------------------------------------
# Formation & play usage changes
# ---------------------------------------------------------------------------

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
# Formation deep-dive (Scout vs Live, for each of the top 3 formations)
# ---------------------------------------------------------------------------

def build_formation_deep_dive(
    scout_df: pd.DataFrame,
    live_df: pd.DataFrame,
    formations_to_compare: List[str],
) -> List[FormationDeepDive]:
    """For each formation named in formations_to_compare (normally the
    scout's top 3), builds a full scout-vs-live comparison: run/pass split,
    each side's top plays, and any plays that are brand new."""
    results = []

    for formation in formations_to_compare:
        scout_subset = (
            scout_df[scout_df[config.COL_FORMATION] == formation]
            if config.COL_FORMATION in scout_df.columns else pd.DataFrame()
        )
        live_subset = (
            live_df[live_df[config.COL_FORMATION] == formation]
            if config.COL_FORMATION in live_df.columns else pd.DataFrame()
        )

        scout_run_pct, scout_pass_pct = _run_pass_split(scout_subset)
        live_run_pct, live_pass_pct = _run_pass_split(live_subset)

        scout_plays = set(scout_subset[config.COL_PLAY_CALL]) if config.COL_PLAY_CALL in scout_subset.columns else set()
        live_plays = set(live_subset[config.COL_PLAY_CALL]) if config.COL_PLAY_CALL in live_subset.columns else set()
        new_plays = sorted(live_plays - scout_plays)

        results.append(FormationDeepDive(
            formation=formation,
            scout_run_pct=scout_run_pct,
            scout_pass_pct=scout_pass_pct,
            live_run_pct=live_run_pct,
            live_pass_pct=live_pass_pct,
            scout_top_runs=_top_play_calls(scout_subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            scout_top_passes=_top_play_calls(scout_subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
            live_top_runs=_top_play_calls(live_subset, config.PLAY_TYPE_RUN, config.TOP_N_PLAYS),
            live_top_passes=_top_play_calls(live_subset, config.PLAY_TYPE_PASS, config.TOP_N_PLAYS),
            new_plays=new_plays,
            run_pct_change=round(live_run_pct - scout_run_pct, 1),
            pass_pct_change=round(live_pass_pct - scout_pass_pct, 1),
        ))

    return results


# ---------------------------------------------------------------------------
# Down & Distance / Field Position changes
# ---------------------------------------------------------------------------

def _compare_situation_buckets(
    scout_buckets: List[SituationBucket],
    live_buckets: List[SituationBucket],
) -> List[SituationComparison]:
    """Shared logic for comparing Down & Distance buckets or Field Position
    zones between scout and live. Only produces a comparison for labels
    present (with data) on both sides - a bucket that hasn't happened yet
    tonight isn't a meaningful comparison.
    """
    scout_by_label = {b.label: b for b in scout_buckets}
    live_by_label = {b.label: b for b in live_buckets}

    shared_labels = [label for label in scout_by_label if label in live_by_label]

    comparisons = []
    for label in shared_labels:
        scout_b = scout_by_label[label]
        live_b = live_by_label[label]

        pass_change = round(live_b.pass_pct - scout_b.pass_pct, 1)
        run_change = round(live_b.run_pct - scout_b.run_pct, 1)

        alert_text = None
        if run_change >= config.SITUATION_CHANGE_ALERT_PCT:
            alert_text = f"Running much more than expected on {label}."
        elif pass_change >= config.SITUATION_CHANGE_ALERT_PCT:
            alert_text = f"Passing much more than expected on {label}."

        comparisons.append(SituationComparison(
            label=label,
            scout_run_pct=scout_b.run_pct,
            scout_pass_pct=scout_b.pass_pct,
            live_run_pct=live_b.run_pct,
            live_pass_pct=live_b.pass_pct,
            pass_pct_change=pass_change,
            alert_text=alert_text,
        ))

    return comparisons


def compare_down_distance(
    scout_buckets: List[SituationBucket],
    live_buckets: List[SituationBucket],
) -> List[SituationComparison]:
    """Down & Distance version of the scout-vs-live situational comparison."""
    return _compare_situation_buckets(scout_buckets, live_buckets)


def compare_field_zones(
    scout_zones: List[SituationBucket],
    live_zones: List[SituationBucket],
) -> List[SituationComparison]:
    """Field Position version of the scout-vs-live situational comparison."""
    return _compare_situation_buckets(scout_zones, live_zones)


# ---------------------------------------------------------------------------
# What To Expect (predictive summary)
# ---------------------------------------------------------------------------

def build_what_to_expect(
    formations: List[FormationSummary],
    down_distance_buckets: List[SituationBucket],
    field_zones: List[SituationBucket],
) -> List[ExpectationItem]:
    """Picks the single most lopsided (highest-confidence) situation from
    each category - formation, down & distance, field position - and turns
    it into a plain prediction. This is the 'first thing a coordinator
    reads between series' section, so it stays to one item per category.
    """
    items: List[ExpectationItem] = []

    def _most_lopsided(candidates, get_run_pct, get_pass_pct, get_count, get_label):
        best = None
        best_margin = -1.0
        for c in candidates:
            if get_count(c) < config.MIN_SAMPLE_FOR_EXPECTATION:
                continue
            margin = max(get_run_pct(c), get_pass_pct(c))
            if margin > best_margin:
                best_margin = margin
                best = c
        return best

    # Formation - use usage_pct-weighted play count isn't tracked directly on
    # FormationSummary, so we treat every top formation as eligible (they're
    # already the highest-usage formations, so sample size is rarely an issue).
    best_formation = None
    best_formation_margin = -1.0
    for f in formations:
        margin = max(f.run_pct, f.pass_pct)
        if margin > best_formation_margin:
            best_formation_margin = margin
            best_formation = f

    if best_formation:
        dominant_type = "Pass" if best_formation.pass_pct >= best_formation.run_pct else "Run"
        dominant_pct = best_formation.pass_pct if dominant_type == "Pass" else best_formation.run_pct
        likely = best_formation.top_pass_plays if dominant_type == "Pass" else best_formation.top_run_plays
        items.append(ExpectationItem(
            category="Formation",
            label=best_formation.formation,
            dominant_type=dominant_type,
            dominant_pct=dominant_pct,
            likely_plays=likely,
        ))

    # Down & Distance
    best_bucket = _most_lopsided(
        down_distance_buckets,
        lambda b: b.run_pct, lambda b: b.pass_pct, lambda b: b.play_count, lambda b: b.label,
    )
    if best_bucket:
        dominant_type = "Pass" if best_bucket.pass_pct >= best_bucket.run_pct else "Run"
        dominant_pct = best_bucket.pass_pct if dominant_type == "Pass" else best_bucket.run_pct
        likely = best_bucket.top_pass_plays if dominant_type == "Pass" else best_bucket.top_run_plays
        items.append(ExpectationItem(
            category="Down & Distance",
            label=best_bucket.label,
            dominant_type=dominant_type,
            dominant_pct=dominant_pct,
            likely_plays=likely,
        ))

    # Field Position
    best_zone = _most_lopsided(
        field_zones,
        lambda z: z.run_pct, lambda z: z.pass_pct, lambda z: z.play_count, lambda z: z.label,
    )
    if best_zone:
        dominant_type = "Pass" if best_zone.pass_pct >= best_zone.run_pct else "Run"
        dominant_pct = best_zone.pass_pct if dominant_type == "Pass" else best_zone.run_pct
        likely = best_zone.top_pass_plays if dominant_type == "Pass" else best_zone.top_run_plays
        items.append(ExpectationItem(
            category="Field Position",
            label=best_zone.label,
            dominant_type=dominant_type,
            dominant_pct=dominant_pct,
            likely_plays=likely,
        ))

    return items


# ---------------------------------------------------------------------------
# Coach Alerts (dynamic, plain-English observations)
# ---------------------------------------------------------------------------

def build_coach_alerts(
    formation_changes: List[FormationChange],
    run_changes: List[PlayChange],
    pass_changes: List[PlayChange],
    scout_summary: Summary,
    live_summary: Summary,
    down_distance_comparisons: List[SituationComparison],
    field_zone_comparisons: List[SituationComparison],
) -> List[str]:
    """Generates single-line plain-English observations from every
    comparison already computed above. This is the 'coach reads this and
    immediately understands what changed' section - no raw tables.
    """
    alerts: List[str] = []

    # Formation usage swings
    for c in formation_changes:
        if c.is_new and c.live_pct > 0:
            alerts.append(f"{c.formation} has appeared for the first time ({c.live_pct:.0f}% of live snaps).")
        elif abs(c.change) >= config.ALERT_FORMATION_CHANGE_PCT:
            direction = "increased" if c.change > 0 else "decreased"
            alerts.append(f"{c.formation} usage {direction} by {abs(c.change):.0f}%.")

    # Overall run/pass shift
    pass_shift = round(live_summary.pass_pct - scout_summary.pass_pct, 1)
    if abs(pass_shift) >= config.ALERT_RUNPASS_CHANGE_PCT:
        direction = "more" if pass_shift > 0 else "less"
        alerts.append(f"Passing {abs(pass_shift):.0f}% {direction} than the scouting report.")

    # Play-level: new plays, dropped favorites, promoted plays
    for changes, label in ((run_changes, "run"), (pass_changes, "pass")):
        for c in changes:
            if c.is_new and c.live_count >= config.NEW_PLAY_MIN_LIVE_COUNT:
                alerts.append(f"{c.play_name} has appeared - not on scout film.")
            elif (c.scout_count >= config.LOW_USAGE_ALERT_MIN_SCOUT_COUNT
                  and c.live_count <= config.LOW_USAGE_ALERT_MAX_LIVE_COUNT):
                alerts.append(f"{c.play_name} was a scout favorite, barely used live.")

        # The single biggest riser of this type becomes "now primary" if it's
        # also the most-called live play of that type.
        risers = [c for c in changes if c.change >= config.ALERT_PLAY_CHANGE_PCT]
        if risers:
            top_riser = max(risers, key=lambda c: c.live_pct)
            if top_riser.live_pct == max((c.live_pct for c in changes), default=0):
                alerts.append(f"{top_riser.play_name} is now the primary {label}.")

    # Down & distance / field position deviations
    for comp in down_distance_comparisons + field_zone_comparisons:
        if comp.alert_text:
            alerts.append(comp.alert_text)

    return alerts


# ---------------------------------------------------------------------------
# Game Plan Match Score
# ---------------------------------------------------------------------------

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
    down_distance_comparisons: List[SituationComparison],
) -> GamePlanScore:
    """Computes the weighted Game Plan Match Score:
        40% Formation Usage similarity
        20% Run/Pass Ratio similarity
        20% Top Plays overlap (top 3 run + top 3 pass, scout vs live)
        20% Down & Distance tendency similarity

    Each component is 0-100; the final score is their weighted sum.
    """
    # Formation usage component
    scout_formation_pcts = {c.formation: c.scout_pct for c in formation_changes}
    live_formation_pcts = {c.formation: c.live_pct for c in formation_changes}
    formation_component = _distribution_similarity(scout_formation_pcts, live_formation_pcts)

    # Run/pass ratio component - simple single-number deviation
    runpass_component = max(0.0, 100.0 - abs(live_summary.pass_pct - scout_summary.pass_pct))

    # Top plays overlap component - what fraction of scout's top plays are
    # still showing up in live's top plays
    def _overlap_pct(scout_top, live_top):
        scout_names = {s.play_name for s in scout_top}
        live_names = {s.play_name for s in live_top}
        if not scout_names:
            return 100.0  # nothing to compare against - treat as neutral
        return len(scout_names & live_names) / len(scout_names) * 100.0

    run_overlap = _overlap_pct(scout_top_runs, live_top_runs)
    pass_overlap = _overlap_pct(scout_top_passes, live_top_passes)
    top_plays_component = (run_overlap + pass_overlap) / 2.0

    # Down & distance component - average how close pass% stayed per bucket
    if down_distance_comparisons:
        avg_deviation = sum(abs(c.pass_pct_change) for c in down_distance_comparisons) / len(down_distance_comparisons)
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
