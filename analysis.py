def build_ball_carrier_stats(df: pd.DataFrame) -> List[BallCarrierStats]:
    """
    Build rushing/receiving/fumble stats from BALL CARRIER.

    Rules:
    - Run + Rush/Rush TD = carry and rushing yards.
    - Run + Fumble = carry, but ZERO rushing yards.
    - Pass + Complete/Complete TD = reception and receiving yards.
    - Pass + Fumble = reception, but ZERO receiving yards.
    - Rush TD gets rushing TD credit.
    - Complete TD gets receiving TD credit.
    - Fumble is credited to BALL CARRIER.
    - Penalty rows are excluded from player statistics.
    """

    required = {
        config.COL_BALL_CARRIER,
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    }

    if df.empty or not required.issubset(df.columns):
        return []

    work = df.loc[:, [
        config.COL_BALL_CARRIER,
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    ]].copy()

    # ---------------------------------------------------------------
    # REMOVE PENALTY PLAYS
    # ---------------------------------------------------------------
    # Penalty yardage will be handled separately later.
    result_text = (
        work[config.COL_RESULT]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    penalty_mask = result_text.str.contains("penalty", na=False)
    work = work[~penalty_mask].copy()

    if work.empty:
        return []

    # ---------------------------------------------------------------
    # CLEAN BALL CARRIER
    # ---------------------------------------------------------------
    work[config.COL_BALL_CARRIER] = (
        work[config.COL_BALL_CARRIER]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    work = work[work[config.COL_BALL_CARRIER] != ""]

    if work.empty:
        return []

    # ---------------------------------------------------------------
    # NORMALIZE DATA
    # ---------------------------------------------------------------
    work[config.COL_PLAY_TYPE] = work[config.COL_PLAY_TYPE].map(
        _normalize_play_type
    )

    work["_result"] = work[config.COL_RESULT].map(
        _normalize_result
    )

    work["_yards"] = pd.to_numeric(
        work[config.COL_GAIN_LOSS],
        errors="coerce"
    ).fillna(0)

    rush_result = _normalize_result(config.RESULT_RUSH)
    rush_td_result = _normalize_result(config.RESULT_RUSH_TD)

    complete_result = _normalize_result(config.RESULT_COMPLETE)
    complete_td_result = _normalize_result(config.RESULT_COMPLETE_TD)

    fumble_result = _normalize_result(config.RESULT_FUMBLE)

    players = []

    for ball_carrier, group in work.groupby(
        config.COL_BALL_CARRIER,
        sort=True
    ):
        is_run = (
            group[config.COL_PLAY_TYPE]
            == config.PLAY_TYPE_RUN
        )

        is_pass = (
            group[config.COL_PLAY_TYPE]
            == config.PLAY_TYPE_PASS
        )

        result = group["_result"]

        # ===========================================================
        # RUSHING
        # ===========================================================
        #
        # Run + Rush       = Carry + yards
        # Run + Rush TD    = Carry + yards + TD
        # Run + Fumble     = Carry + ZERO yards
        #
        rush_attempt_mask = (
            is_run
            & result.isin({
                rush_result,
                rush_td_result,
                fumble_result,
            })
        )

        carries = int(rush_attempt_mask.sum())

        # Fumbles do NOT receive rushing yards.
        rush_yard_mask = (
            is_run
            & result.isin({
                rush_result,
                rush_td_result,
            })
        )

        rush_yards = float(
            group.loc[
                rush_yard_mask,
                "_yards"
            ].sum()
        )

        rush_td = int(
            (
                is_run
                & (result == rush_td_result)
            ).sum()
        )

        # ===========================================================
        # RECEIVING
        # ===========================================================
        #
        # Pass + Complete       = Reception + yards
        # Pass + Complete TD    = Reception + yards + TD
        # Pass + Fumble         = Reception + ZERO yards
        #
        reception_mask = (
            is_pass
            & result.isin({
                complete_result,
                complete_td_result,
                fumble_result,
            })
        )

        receptions = int(
            reception_mask.sum()
        )

        # Fumbles do NOT receive receiving yards.
        rec_yard_mask = (
            is_pass
            & result.isin({
                complete_result,
                complete_td_result,
            })
        )

        rec_yards = float(
            group.loc[
                rec_yard_mask,
                "_yards"
            ].sum()
        )

        rec_td = int(
            (
                is_pass
                & (result == complete_td_result)
            ).sum()
        )

        # ===========================================================
        # FUMBLES
        # ===========================================================
        fumbles = int(
            (result == fumble_result).sum()
        )

        players.append(
            BallCarrierStats(
                ball_carrier=str(ball_carrier),

                carries=carries,

                rush_yards=rush_yards,

                yards_per_carry=(
                    round(
                        rush_yards / carries,
                        1
                    )
                    if carries
                    else 0.0
                ),

                rush_td=rush_td,

                receptions=receptions,

                rec_yards=rec_yards,

                rec_td=rec_td,

                fumbles=fumbles,
            )
        )

    return sorted(
        players,
        key=lambda p: (
            -(p.rush_yards + p.rec_yards),
            p.ball_carrier
        )
    )


def build_qb_stats(df: pd.DataFrame) -> QBStats:
    """
    Build QB passing statistics.

    Passing attempts:
        Complete
        Complete, TD
        Incomplete
        Interception
        Fumble

    IMPORTANT:
    PASS + Fumble counts as a completed pass for the QB,
    but receives ZERO passing yards.

    Penalty rows are excluded.
    """

    required = {
        config.COL_PLAY_TYPE,
        config.COL_RESULT,
        config.COL_GAIN_LOSS,
    }

    if df.empty or not required.issubset(df.columns):
        return QBStats(
            0,
            0,
            0.0,
            0.0,
            0,
            0
        )

    # ---------------------------------------------------------------
    # REMOVE PENALTY PLAYS
    # ---------------------------------------------------------------
    result_text = (
        df[config.COL_RESULT]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    clean = df[
        ~result_text.str.contains(
            "penalty",
            na=False
        )
    ].copy()

    if clean.empty:
        return QBStats(
            0,
            0,
            0.0,
            0.0,
            0,
            0
        )

    # ---------------------------------------------------------------
    # NORMALIZE PLAY TYPE
    # ---------------------------------------------------------------
    clean[config.COL_PLAY_TYPE] = (
        clean[config.COL_PLAY_TYPE]
        .map(_normalize_play_type)
    )

    passes = clean[
        clean[config.COL_PLAY_TYPE]
        == config.PLAY_TYPE_PASS
    ].copy()

    if passes.empty:
        return QBStats(
            0,
            0,
            0.0,
            0.0,
            0,
            0
        )

    result = passes[
        config.COL_RESULT
    ].map(_normalize_result)

    yards = pd.to_numeric(
        passes[config.COL_GAIN_LOSS],
        errors="coerce"
    ).fillna(0)

    complete_result = _normalize_result(
        config.RESULT_COMPLETE
    )

    complete_td_result = _normalize_result(
        config.RESULT_COMPLETE_TD
    )

    incomplete_result = _normalize_result(
        config.RESULT_INCOMPLETE
    )

    interception_result = _normalize_result(
        config.RESULT_INTERCEPTION
    )

    fumble_result = _normalize_result(
        config.RESULT_FUMBLE
    )

    # ===============================================================
    # PASSING ATTEMPTS
    # ===============================================================
    #
    # Complete
    # Complete TD
    # Incomplete
    # Interception
    # Fumble
    #
    # A PASS + Fumble is an attempt.
    #
    attempt_values = {
        complete_result,
        complete_td_result,
        incomplete_result,
        interception_result,
        fumble_result,
    }

    is_attempt = result.isin(
        attempt_values
    )

    attempts = int(
        is_attempt.sum()
    )

    # ===============================================================
    # COMPLETIONS
    # ===============================================================
    #
    # Complete
    # Complete TD
    # Fumble
    #
    # PASS + Fumble counts as a completion,
    # but receives ZERO passing yards.
    #
    is_complete = result.isin({
        complete_result,
        complete_td_result,
        fumble_result,
    })

    completions = int(
        is_complete.sum()
    )

    # ===============================================================
    # PASSING YARDS
    # ===============================================================
    #
    # Only normal completions and TD completions
    # receive passing yards.
    #
    # Fumbles = ZERO yards.
    #
    pass_yard_mask = result.isin({
        complete_result,
        complete_td_result,
    })

    pass_yards = float(
        yards[pass_yard_mask].sum()
    )

    # ===============================================================
    # TOUCHDOWNS
    # ===============================================================
    pass_td = int(
        (
            result
            == complete_td_result
        ).sum()
    )

    # ===============================================================
    # INTERCEPTIONS
    # ===============================================================
    interceptions = int(
        (
            result
            == interception_result
        ).sum()
    )

    # ===============================================================
    # COMPLETION PERCENTAGE
    # ===============================================================
    comp_pct = (
        round(
            completions / attempts * 100,
            1
        )
        if attempts
        else 0.0
    )

    return QBStats(
        attempts=attempts,
        completions=completions,
        comp_pct=comp_pct,
        pass_yards=pass_yards,
        pass_td=pass_td,
        interceptions=interceptions,
    )
