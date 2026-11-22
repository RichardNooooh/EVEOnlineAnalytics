import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def imports():
    from datetime import date

    import marimo as mo
    import numpy as np
    import polars as pl
    from transform.notebook_access import open_analysis_connection

    return date, mo, np, open_analysis_connection, pl


@app.cell(hide_code=True)
def plotting_imports():
    from html import escape
    from textwrap import wrap

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    return escape, go, make_subplots, wrap


@app.cell
def study_configuration(date):
    HISTORY_START = date(2022, 6, 1)
    HISTORY_END = date(2026, 9, 1)
    return HISTORY_END, HISTORY_START


@app.cell
def feature_columns():
    FEATURE_COLUMNS = (
        "price_log_change", "upward_excursion", "downward_excursion", "median_shift",
        "mean_relative_range", "peak_timing", "trough_timing", "upward_residence",
        "downward_residence", "directional_balance", "terminal_settling",
        "focal_prior_price", "next_prior_price", "volume_ratio", "order_count_ratio",
        "next_volume_ratio", "next_order_count_ratio", "peak_day_volume_share",
        "price_activity_alignment",
    )
    return (FEATURE_COLUMNS,)


@app.cell(hide_code=True)
def feature_presentation():
    # ASCII chart labels avoid doubling large outputs in Marimo's Unicode size check.
    FEATURE_FAMILIES = {
        "Price movement": (
            "price_log_change", "upward_excursion", "downward_excursion",
            "median_shift", "mean_relative_range",
        ),
        "Timing and persistence": (
            "peak_timing", "trough_timing", "upward_residence", "downward_residence",
            "directional_balance", "terminal_settling",
        ),
        "Price context": ("focal_prior_price", "next_prior_price"),
        "Activity and alignment": (
            "volume_ratio", "order_count_ratio", "next_volume_ratio",
            "next_order_count_ratio", "peak_day_volume_share", "price_activity_alignment",
        ),
    }
    FEATURE_LABELS = {
        "price_log_change": "Price log change",
        "upward_excursion": "Upward excursion",
        "downward_excursion": "Downward excursion",
        "median_shift": "Median shift",
        "mean_relative_range": "Mean relative range",
        "peak_timing": "Peak timing",
        "trough_timing": "Trough timing",
        "upward_residence": "Upward residence",
        "downward_residence": "Downward residence",
        "directional_balance": "Directional balance",
        "terminal_settling": "Terminal settling",
        "focal_prior_price": "Focal/prior log price",
        "next_prior_price": "Next/prior log price",
        "volume_ratio": "Focal/prior volume",
        "order_count_ratio": "Focal/prior order count",
        "next_volume_ratio": "Next/prior volume",
        "next_order_count_ratio": "Next/prior order count",
        "peak_day_volume_share": "Peak-day volume share",
        "price_activity_alignment": "Price-activity alignment",
    }
    FEATURE_DESCRIPTIONS = {
        "price_log_change": "Log change from the last valid prior-week price to the last focal-week price.",
        "upward_excursion": "Largest upward log displacement from the prior-week boundary price.",
        "downward_excursion": "Largest downward log displacement from the prior-week boundary price.",
        "median_shift": "Log ratio of late to early median prices in the boundary-plus-focal path.",
        "mean_relative_range": "Mean daily high-low range divided by VWAP.",
        "peak_timing": "Average peak weekday, scaled from Sunday (0) to Saturday (1).",
        "trough_timing": "Average trough weekday, scaled from Sunday (0) to Saturday (1).",
        "upward_residence": "Mean positive log displacement from the prior median divided by its maximum; zero without upward displacement.",
        "downward_residence": "Mean negative log displacement magnitude from the prior median divided by its maximum; zero without downward displacement.",
        "directional_balance": "Mean sign of valid adjacent-day log returns, including zero returns.",
        "terminal_settling": "Mean absolute value of the last three valid focal-day log returns, or all when fewer exist.",
        "focal_prior_price": "Log ratio of focal-week to prior-week median VWAP.",
        "next_prior_price": "Log ratio of next-week to prior-week median VWAP.",
        "volume_ratio": "Focal-week volume divided by prior-week volume.",
        "order_count_ratio": "Focal-week historical order count divided by the prior-week count.",
        "next_volume_ratio": "Next-week volume divided by prior-week volume.",
        "next_order_count_ratio": "Next-week historical order count divided by the prior-week count.",
        "peak_day_volume_share": "Busiest focal day's share of total focal-week volume.",
        "price_activity_alignment": "Volume-weighted minus ordinary mean log VWAP on the same valid price-volume pairs.",
    }
    return FEATURE_DESCRIPTIONS, FEATURE_FAMILIES, FEATURE_LABELS


@app.cell
def introduction(mo):
    mo.md("""
    # Weekly behavioral descriptors

    Raw retrospective item-week descriptors for the selected Forge panel. Each focal
    Sunday-Saturday week uses the immediately preceding and following week. The
    [feature definitions](feature_sources.md) specify coverage and missingness.
    """)
    return


@app.cell
def load_panel(HISTORY_END, HISTORY_START, open_analysis_connection):
    _input_sql = """
    select type_id, region_id, type_name, study_category, market_date,
           average as vwap, highest, lowest, volume, order_count
    from main.int_study_panel_history
    where market_date between ? and ?
    order by type_id, market_date
    """
    with open_analysis_connection() as _connection:
        history_df = _connection.execute(_input_sql, [HISTORY_START, HISTORY_END]).pl()
    if history_df.is_empty():
        raise ValueError("The configured study period has no history.")
    return (history_df,)


@app.cell
def validate_history(HISTORY_END, HISTORY_START, history_df, pl):
    study_history_df = history_df.filter(
        pl.col("market_date").is_between(HISTORY_START, HISTORY_END)
    ).with_columns(pl.col("market_date").cast(pl.Date))

    if study_history_df.is_empty():
        raise ValueError("No observed history in the study period.")
    if study_history_df.select(
        pl.any_horizontal(pl.col(key).is_null() for key in ("type_id", "market_date")).any()
    ).item():
        raise ValueError("Item IDs and dates must be present.")
    if study_history_df.select(pl.struct("type_id", "market_date").is_duplicated().any()).item():
        raise ValueError("Expected one observed row per item-date.")
    return (study_history_df,)


@app.cell
def validate_item_metadata(pl, study_history_df):
    item_metadata_df = study_history_df.select(
        "type_id", "region_id", "type_name", "study_category"
    ).unique()
    if item_metadata_df.select(pl.col("type_id").is_duplicated().any()).item():
        raise ValueError("Item metadata must be consistent across the study period.")
    return (item_metadata_df,)


@app.cell
def expand_daily_calendar(
    HISTORY_END,
    HISTORY_START,
    item_metadata_df,
    pl,
    study_history_df,
):
    _calendar_df = pl.DataFrame({
        "market_date": pl.date_range(HISTORY_START, HISTORY_END, "1d", eager=True)
    })
    _observed_df = study_history_df.drop(
        "region_id", "type_name", "study_category"
    ).with_columns(pl.lit(True).alias("is_observed"))
    applicable_history_df = (
        _calendar_df.join(item_metadata_df, how="cross")
        .join(_observed_df, on=["type_id", "market_date"], how="left")
        .with_columns(pl.col("is_observed").fill_null(False))
        .with_columns(
            pl.when(~pl.col("is_observed"))
            .then(0)
            .otherwise(pl.col(column))
            .alias(column)
            for column in ("volume", "order_count")
        )
        .select(
            "market_date", "type_id", "region_id", "type_name", "study_category",
            "vwap", "highest", "lowest", "volume", "order_count",
        )
        .sort("type_id", "market_date")
    )
    return (applicable_history_df,)


@app.cell
def daily_feature_preparation(applicable_history_df, pl):
    _daily_df = applicable_history_df.select(
        "type_id", "market_date", "vwap", "highest", "lowest", "volume", "order_count",
    ).sort("type_id", "market_date")
    _valid_price = (pl.col("vwap").is_finite() & (pl.col("vwap") > 0)).fill_null(False)
    daily_features_df = _daily_df.with_columns(
        (pl.col("market_date") - pl.duration(days=pl.col("market_date").dt.weekday() % 7))
        .alias("focal_week_start"),
        pl.when(_valid_price & _valid_price.shift(1).over("type_id").fill_null(False))
        .then(pl.col("vwap").log() - pl.col("vwap").shift(1).over("type_id").log())
        .alias("daily_log_return"),
    ).select(
        "type_id", "market_date", "focal_week_start", "vwap", "highest", "lowest",
        "volume", "order_count", "daily_log_return",
    )
    return (daily_features_df,)


@app.cell
def weekly_context(HISTORY_END, HISTORY_START, daily_features_df, pl):
    _valid_vwap = pl.when(pl.col("vwap").is_finite() & (pl.col("vwap") > 0)).then(pl.col("vwap"))
    _summary_df = (
        daily_features_df.group_by("type_id", "focal_week_start", maintain_order=True)
        .agg(
            _valid_vwap.count().cast(pl.Int64).alias("valid_prices"),
            _valid_vwap.drop_nulls().alias("prices"),
            _valid_vwap.median().alias("median_price"),
            _valid_vwap.drop_nulls().last().alias("last_price"),
            pl.col("daily_log_return").count().cast(pl.Int64).alias("valid_returns"),
            *(
                pl.when((pl.col(name).is_null() | ~pl.col(name).is_finite() | (pl.col(name) < 0)).any())
                .then(None).otherwise(pl.col(name).sum()).alias(name + "_total")
                for name in ("volume", "order_count")
            ),
        )
    )

    _prior_df = _summary_df.select(
        "type_id", (pl.col("focal_week_start") + pl.duration(days=7)).alias("focal_week_start"),
        pl.col("valid_prices").alias("prior_valid_prices"),
        pl.col("median_price").alias("prior_median"),
        pl.col("last_price").alias("boundary_price"),
        pl.col("volume_total").alias("prior_volume_total"),
        pl.col("order_count_total").alias("prior_order_count_total"),
    )
    _next_df = _summary_df.select(
        "type_id", (pl.col("focal_week_start") - pl.duration(days=7)).alias("focal_week_start"),
        pl.col("valid_prices").alias("next_valid_prices"),
        pl.col("median_price").alias("next_median"),
        pl.col("volume_total").alias("next_volume_total"),
        pl.col("order_count_total").alias("next_order_count_total"),
    )
    _context_df = (
        _summary_df.rename({
            "valid_prices": "focal_valid_prices", "median_price": "focal_median",
            "valid_returns": "focal_valid_returns", "volume_total": "focal_volume_total",
            "order_count_total": "focal_order_count_total",
        })
        .join(_prior_df, on=["type_id", "focal_week_start"], how="left")
        .join(_next_df, on=["type_id", "focal_week_start"], how="left")
        .with_columns(pl.col("prior_valid_prices", "next_valid_prices").fill_null(0))
    )

    weekly_context_df = _context_df.with_columns(
        (pl.col("focal_week_start") + pl.duration(days=6)).alias("focal_week_end"),
        pl.max_horizontal(
            pl.lit(HISTORY_START), pl.col("focal_week_start") - pl.duration(days=7)
        ).alias("support_start"),
        pl.min_horizontal(
            pl.lit(HISTORY_END), pl.col("focal_week_start") + pl.duration(days=13)
        ).alias("support_end"),
        pl.all_horizontal(
            pl.col("prior_valid_prices", "focal_valid_prices", "next_valid_prices") >= 5
        ).alias("coverage_eligible"),
        pl.concat_list(
            pl.when(pl.col("prior_valid_prices") < 5).then(pl.lit("prior")),
            pl.when(pl.col("focal_valid_prices") < 5).then(pl.lit("focal")),
            pl.when(pl.col("next_valid_prices") < 5).then(pl.lit("next")),
        ).list.drop_nulls().alias("coverage_exclusions"),
    ).select(
        "type_id", "focal_week_start", "focal_week_end", "support_start", "support_end",
        "prior_valid_prices", "focal_valid_prices", "next_valid_prices", "focal_valid_returns",
        "coverage_eligible", "coverage_exclusions", "prices", "focal_median", "last_price",
        "prior_median", "boundary_price", "next_median",
        "prior_volume_total", "focal_volume_total", "next_volume_total",
        "prior_order_count_total", "focal_order_count_total", "next_order_count_total",
    )
    return (weekly_context_df,)


@app.cell
def weekly_price_features(daily_features_df, pl, weekly_context_df):
    _path_df = (
        weekly_context_df.with_columns(
            pl.concat_list("boundary_price", "prices").alias("price_path")
        )
        .with_columns((pl.col("price_path").list.len() // 2).alias("split_index"))
        .with_columns(
            pl.col("price_path").list.slice(0, pl.col("split_index"))
            .list.median().alias("early_median"),
            pl.col("price_path").list.slice(pl.col("split_index"))
            .list.median().alias("late_median"),
        )
    )
    _path_features_df = _path_df.select(
        "type_id", "focal_week_start",
        (pl.col("last_price").log() - pl.col("boundary_price").log())
        .alias("price_log_change"),
        (
            pl.max_horizontal(pl.col("boundary_price"), pl.col("prices").list.max()).log()
            - pl.col("boundary_price").log()
        ).alias("upward_excursion"),
        (
            pl.col("boundary_price").log()
            - pl.min_horizontal(pl.col("boundary_price"), pl.col("prices").list.min()).log()
        ).alias("downward_excursion"),
        (pl.col("late_median").log() - pl.col("early_median").log()).alias("median_shift"),
        (pl.col("focal_median").log() - pl.col("prior_median").log()).alias("focal_prior_price"),
        (pl.col("next_median").log() - pl.col("prior_median").log()).alias("next_prior_price"),
    )

    _valid_df = (
        daily_features_df.filter(pl.col("vwap").is_finite() & (pl.col("vwap") > 0))
        .join(
            weekly_context_df.select("type_id", "focal_week_start", "prior_median"),
            on=["type_id", "focal_week_start"],
        )
        .with_columns(
            (pl.col("vwap").log() - pl.col("prior_median").log())
            .alias("relative_log_price"),
            (pl.col("market_date") - pl.col("focal_week_start"))
            .dt.total_days().alias("weekday"),
        )
    )
    _shape_df = _valid_df.group_by("type_id", "focal_week_start", maintain_order=True).agg(
        pl.when(
            pl.col("highest").is_finite() & pl.col("lowest").is_finite()
            & (pl.col("lowest") >= 0) & (pl.col("highest") >= pl.col("lowest"))
        ).then((pl.col("highest") - pl.col("lowest")) / pl.col("vwap"))
        .mean().alias("mean_relative_range"),
        pl.col("weekday")
        .filter(pl.col("vwap") == pl.col("vwap").max())
        .mean().truediv(6).alias("peak_timing"),
        pl.col("weekday")
        .filter(pl.col("vwap") == pl.col("vwap").min())
        .mean().truediv(6).alias("trough_timing"),
        pl.col("relative_log_price").clip(lower_bound=0).mean().alias("up_mean"),
        pl.col("relative_log_price").clip(lower_bound=0).max().alias("up_max"),
        (-pl.col("relative_log_price")).clip(lower_bound=0).mean().alias("down_mean"),
        (-pl.col("relative_log_price")).clip(lower_bound=0).max().alias("down_max"),
    )
    _shape_features_df = _shape_df.select(
        "type_id", "focal_week_start", "mean_relative_range", "peak_timing", "trough_timing",
        pl.when(pl.col("up_max") > 0)
        .then(pl.col("up_mean") / pl.col("up_max"))
        .otherwise(0.0).alias("upward_residence"),
        pl.when(pl.col("down_max") > 0)
        .then(pl.col("down_mean") / pl.col("down_max"))
        .otherwise(0.0).alias("downward_residence"),
    )

    _return_features_df = daily_features_df.group_by(
        "type_id", "focal_week_start", maintain_order=True
    ).agg(
        pl.col("daily_log_return").sign().mean().alias("directional_balance"),
        pl.col("daily_log_return").drop_nulls().tail(3).abs().mean().alias("terminal_settling"),
    )

    weekly_price_features_df = (
        _path_features_df.join(_shape_features_df, on=["type_id", "focal_week_start"], how="left")
        .join(_return_features_df, on=["type_id", "focal_week_start"], how="left")
    )
    return (weekly_price_features_df,)


@app.cell
def assemble_weekly_descriptors(
    FEATURE_COLUMNS,
    daily_features_df,
    item_metadata_df,
    pl,
    weekly_context_df,
    weekly_price_features_df,
):
    _valid_pair = (
        pl.col("vwap").is_finite() & (pl.col("vwap") > 0)
        & pl.col("volume").is_finite() & (pl.col("volume") >= 0)
    ).fill_null(False)
    _activity_summary_df = daily_features_df.group_by(
        "type_id", "focal_week_start", maintain_order=True
    ).agg(
        pl.col("volume").max().alias("peak_volume"),
        pl.col("volume").filter(_valid_pair).sum().alias("paired_volume"),
        (pl.col("vwap").log() * pl.col("volume"))
        .filter(_valid_pair).sum().alias("weighted_log_sum"),
        pl.col("vwap").log().filter(_valid_pair).mean().alias("paired_log_mean"),
    )
    _activity_df = (
        _activity_summary_df.join(
            weekly_context_df.select(
                "type_id", "focal_week_start", "prior_volume_total", "focal_volume_total",
                "next_volume_total", "prior_order_count_total", "focal_order_count_total",
                "next_order_count_total",
            ),
            on=["type_id", "focal_week_start"],
        )
        .select(
            "type_id", "focal_week_start",
            pl.when(pl.col("prior_volume_total") > 0)
            .then(pl.col("focal_volume_total") / pl.col("prior_volume_total"))
            .alias("volume_ratio"),
            pl.when(pl.col("prior_volume_total") > 0)
            .then(pl.col("next_volume_total") / pl.col("prior_volume_total"))
            .alias("next_volume_ratio"),
            pl.when(pl.col("prior_order_count_total") > 0)
            .then(pl.col("focal_order_count_total") / pl.col("prior_order_count_total"))
            .alias("order_count_ratio"),
            pl.when(pl.col("prior_order_count_total") > 0)
            .then(pl.col("next_order_count_total") / pl.col("prior_order_count_total"))
            .alias("next_order_count_ratio"),
            pl.when(pl.col("focal_volume_total") > 0)
            .then(pl.col("peak_volume") / pl.col("focal_volume_total"))
            .alias("peak_day_volume_share"),
            pl.when(pl.col("paired_volume") > 0)
            .then(pl.col("weighted_log_sum") / pl.col("paired_volume") - pl.col("paired_log_mean"))
            .alias("price_activity_alignment"),
        )
    )

    weekly_descriptors_df = (
        weekly_context_df.select("type_id", "focal_week_start", "focal_week_end", "coverage_eligible")
        .join(item_metadata_df, on="type_id")
        .join(weekly_price_features_df, on=["type_id", "focal_week_start"], how="left")
        .join(_activity_df, on=["type_id", "focal_week_start"], how="left")
        .with_columns(
            pl.when(pl.col("coverage_eligible"))
            .then(pl.col(feature)).otherwise(None).alias(feature)
            for feature in FEATURE_COLUMNS
        )
        .select(
            "type_id", "region_id", "type_name", "study_category",
            "focal_week_start", "focal_week_end", *FEATURE_COLUMNS,
        )
        .sort("type_id", "focal_week_start")
    )
    return (weekly_descriptors_df,)


@app.cell
def feature_availability(
    FEATURE_COLUMNS,
    pl,
    weekly_context_df,
    weekly_descriptors_df,
):
    _eligible_df = weekly_descriptors_df.join(
        weekly_context_df.filter(pl.col("coverage_eligible")).select("type_id", "focal_week_start"),
        on=["type_id", "focal_week_start"], how="semi",
    )
    _finite_df = weekly_descriptors_df.select(
        pl.col(*FEATURE_COLUMNS).is_finite().fill_null(False).sum()
    ).unpivot(variable_name="feature", value_name="finite")
    _null_df = weekly_descriptors_df.select(
        pl.col(*FEATURE_COLUMNS).null_count()
    ).unpivot(variable_name="feature", value_name="null")
    _candidate_rows = weekly_descriptors_df.height
    _coverage_eligible_rows = _eligible_df.height
    availability_df = (
        _finite_df.join(_null_df, on="feature", maintain_order="left")
        .with_columns(
            (pl.lit(_candidate_rows) - pl.col("finite") - pl.col("null")).alias("nonfinite"),
            pl.lit(_candidate_rows).alias("candidate_rows"),
            pl.lit(_coverage_eligible_rows).alias("coverage_eligible_rows"),
        )
    )
    _eligible_null_df = _eligible_df.select(pl.col(*FEATURE_COLUMNS).null_count()).unpivot(
        variable_name="feature", value_name="eligible_null"
    )
    _eligible_nonfinite_df = _eligible_df.select(
        (~pl.col(*FEATURE_COLUMNS).is_finite()).fill_null(False).sum()
    ).unpivot(variable_name="feature", value_name="eligible_nonfinite")
    availability_df = availability_df.join(_eligible_null_df, on="feature", maintain_order="left").join(
        _eligible_nonfinite_df, on="feature", maintain_order="left"
    )
    return (availability_df,)


@app.cell(hide_code=True)
def analysis_introduction_header(mo):
    mo.md("""
    ## 1. Coverage and missingness
    """)
    return


@app.cell(hide_code=True)
def analysis_introduction(mo, pl, weekly_context_df):
    _candidate_count = weekly_context_df.height
    _eligible_count = weekly_context_df.filter(pl.col("coverage_eligible")).height
    _excluded_count = _candidate_count - _eligible_count
    mo.md(f"""
    **{_eligible_count:,} / {_candidate_count:,} item-weeks eligible** · {_excluded_count:,} excluded by coverage.
    Insufficient price coverage: prior {weekly_context_df.filter(pl.col("coverage_exclusions").list.contains("prior")).height:,},
    focal {weekly_context_df.filter(pl.col("coverage_exclusions").list.contains("focal")).height:,},
    next {weekly_context_df.filter(pl.col("coverage_exclusions").list.contains("next")).height:,} (overlapping reasons).
    """)
    return


@app.cell(hide_code=True)
def availability_view(FEATURE_LABELS, availability_df, mo, pl):
    _missing_df = (
        availability_df.filter((pl.col("eligible_null") + pl.col("eligible_nonfinite")) > 0)
        .select(
            pl.col("feature").replace_strict(FEATURE_LABELS).alias("Feature"),
            pl.col("eligible_null").alias("Missing"),
            pl.col("eligible_nonfinite").alias("Nonfinite"),
            ((pl.col("eligible_null") + pl.col("eligible_nonfinite")) / pl.col("coverage_eligible_rows"))
            .alias("Unavailable share"),
        )
    )
    _eligible_count = availability_df["coverage_eligible_rows"][0]
    _summary = (
        mo.md("No coverage-eligible item-weeks; feature availability cannot be assessed.")
        if _eligible_count == 0 else
        mo.md(f"All {availability_df.height} features are finite across the {_eligible_count:,} eligible item-weeks.")
        if _missing_df.is_empty() else
        mo.ui.table(
            _missing_df, label=f"Additional gaps among {_eligible_count:,} coverage-eligible item-weeks",
            selection=None, pagination=False, show_column_summaries=False,
            show_data_types=False, show_search=False, show_download=False,
            format_mapping={"Missing": "{:,.0f}", "Nonfinite": "{:,.0f}", "Unavailable share": "{:.1%}"},
        )
    )
    _summary  # noqa: B018
    return


@app.cell(hide_code=True)
def correlation_introduction_header(mo):
    mo.md("""
    ## 2. Correlation overview
    """)
    return


@app.cell(hide_code=True)
def correlation_introduction(mo):
    mo.md("""
    Pearson correlations across all 19 raw descriptors, ordered by feature family.
    Hover for feature names and finite pair counts. Each pair uses its own finite
    observations; blank tiles mean too few observations or a constant feature.
    """)
    return


@app.cell
def pairwise_correlations(FEATURE_COLUMNS, np, pl, weekly_descriptors_df):
    _rows = []
    for _x in FEATURE_COLUMNS:
        for _y in FEATURE_COLUMNS:
            _pair_df = weekly_descriptors_df.select(_x, _y) if _x != _y else weekly_descriptors_df.select(_x)
            _pair_df = _pair_df.filter(
                pl.col(_x).is_finite().fill_null(False) & pl.col(_y).is_finite().fill_null(False)
            )
            _a = _pair_df[_x].to_numpy()
            _b = _pair_df[_y].to_numpy()
            _n = len(_a)
            _correlation = (
                float(np.corrcoef(_a, _b)[0, 1])
                if _n >= 2 and np.ptp(_a) > 0 and np.ptp(_b) > 0 else None
            )
            _rows.append({"x": _x, "y": _y, "pairs": _n, "correlation": _correlation})
    correlations_df = pl.DataFrame(_rows)
    return (correlations_df,)


@app.cell(hide_code=True, expand_output=True)
def correlation_view(FEATURE_FAMILIES, FEATURE_LABELS, correlations_df, go):
    _features = [feature for family in FEATURE_FAMILIES.values() for feature in family]
    _lookup = {(row["x"], row["y"]): row for row in correlations_df.iter_rows(named=True)}
    _values = [[_lookup[x, y]["correlation"] for x in _features] for y in _features]
    _hover = [[[FEATURE_LABELS[x], FEATURE_LABELS[y], _lookup[x, y]["pairs"]]
               for x in _features] for y in _features]
    _figure = go.Figure(go.Heatmap(
        z=_values, x=list(range(len(_features))), y=list(range(len(_features))),
        customdata=_hover, zmin=-1, zmax=1, zmid=0, colorscale="RdBu_r",
        colorbar={"title": "Pearson r", "thickness": 14, "len": 0.75},
        hoverongaps=False,
        hovertemplate="%{customdata[1]} x %{customdata[0]}<br>r = %{z:.3f}<br>Finite pairs: %{customdata[2]:,}<extra></extra>",
    ))
    _labels = [FEATURE_LABELS[feature] for feature in _features]
    _figure.update_xaxes(tickmode="array", tickvals=list(range(len(_features))), ticktext=_labels,
                         tickangle=-50, side="bottom", showgrid=False, zeroline=False)
    _figure.update_yaxes(tickmode="array", tickvals=list(range(len(_features))), ticktext=_labels,
                         autorange="reversed", showgrid=False, zeroline=False)
    _boundary = 0
    for _family in list(FEATURE_FAMILIES.values())[:-1]:
        _boundary += len(_family)
        _figure.add_vline(x=_boundary - 0.5, line_width=1, line_color="#6b7280")
        _figure.add_hline(y=_boundary - 0.5, line_width=1, line_color="#6b7280")
    _figure.update_layout(
        template="plotly_white", height=820, font={"size": 11},
        margin={"l": 180, "r": 30, "t": 20, "b": 170},
    )
    _figure  # noqa: B018
    return


@app.cell(hide_code=True)
def raw_descriptors_introduction_header(mo):
    mo.md("""
    ## 3. Distributions and joint relationships
    """)
    return


@app.cell(hide_code=True)
def raw_descriptors_introduction(mo):
    mo.md("""
    Histograms on the diagonal; pairwise scatterplots above it. All finite observations
    are retained, with raw values and full ranges. Histograms count 30 bins over each
    feature's finite values; scatterplots use each pair's finite observations.
    **Box- or lasso-select scatterplot points** to compare original item-week histories
    to the right. Use **Reset state** in the chart toolbar to clear a selection; changing feature family starts a new one.
    """)
    return


@app.cell(hide_code=True)
def feature_family_picker(FEATURE_FAMILIES, mo):
    feature_family = mo.ui.dropdown(
        options=FEATURE_FAMILIES, value="Price movement", allow_select_none=False,
        label="Feature family",
    )
    feature_family  # noqa: B018
    return (feature_family,)


@app.cell(hide_code=True, expand_output=True)
def raw_descriptors_view(
    FEATURE_LABELS,
    feature_family,
    go,
    make_subplots,
    mo,
    np,
    pl,
    weekly_descriptors_df,
    wrap,
):
    _features = feature_family.value
    _size = len(_features)
    _specs = [[{} if col >= row else None for col in range(_size)] for row in range(_size)]
    _figure = make_subplots(
        rows=_size, cols=_size, specs=_specs,
        horizontal_spacing=0.03, vertical_spacing=0.03,
    )
    matrix_observations_df = weekly_descriptors_df.with_row_index("observation_id")
    matrix_trace_rows = {}
    _ranges = {}
    for _feature in _features:
        _values = matrix_observations_df[_feature].filter(matrix_observations_df[_feature].is_finite().fill_null(False))
        if _values.is_empty():
            _ranges[_feature] = None
        else:
            _low, _high = _values.min(), _values.max()
            _padding = (_high - _low) * 0.04 if _high > _low else max(abs(_low) * 0.04, 0.04)
            _ranges[_feature] = [_low - _padding, _high + _padding]

    for _row, _y in enumerate(_features, 1):
        for _col, _x in enumerate(_features, 1):
            if _col < _row:
                continue
            if _x == _y:
                _values = matrix_observations_df[_x].filter(matrix_observations_df[_x].is_finite().fill_null(False)).to_numpy()
                _counts, _edges = np.histogram(_values, bins=30)
                _figure.add_trace(go.Bar(
                    x=(_edges[:-1] + _edges[1:]) / 2, y=_counts,
                    width=np.diff(_edges), marker_color="#64748b", marker_line_width=0,
                    customdata=np.column_stack((_edges[:-1], _edges[1:])),
                    hovertemplate=(f"{FEATURE_LABELS[_x]}: %{{customdata[0]:.4g}} to %{{customdata[1]:.4g}}"
                                   "<br>Item-weeks: %{y:,}<extra></extra>"),
                ), row=_row, col=_col)
                _figure.update_yaxes(title_text="Count", title_font_size=10, row=_row, col=_col)
                _count = len(_values)
            else:
                _pair_df = matrix_observations_df.filter(
                    pl.col(_x).is_finite().fill_null(False) & pl.col(_y).is_finite().fill_null(False)
                )
                matrix_trace_rows[len(_figure.data)] = _pair_df["observation_id"].to_list()
                _figure.add_trace(go.Scattergl(
                    x=_pair_df[_x].to_numpy(), y=_pair_df[_y].to_numpy(), mode="markers",
                    marker={"size": 3, "opacity": 0.25, "color": "#475569"},
                    selected={"marker": {"opacity": 0.85, "color": "#2563eb"}},
                    unselected={"marker": {"opacity": 0.08}},
                    hovertemplate=(f"{FEATURE_LABELS[_x]}: %{{x:.4g}}"
                                   f"<br>{FEATURE_LABELS[_y]}: %{{y:.4g}}<extra></extra>"),
                ), row=_row, col=_col)
                _figure.update_yaxes(
                    range=_ranges[_y], title_text="<br>".join(wrap(FEATURE_LABELS[_y], 18)) if _col == _row + 1 else None,
                    title_font_size=10, row=_row, col=_col,
                )
                _count = _pair_df.height
            _figure.update_xaxes(
                range=_ranges[_x], title_text="<br>".join(wrap(FEATURE_LABELS[_x], 18)) if _row == _col else None,
                title_font_size=10, row=_row, col=_col,
            )
            if _count == 0:
                _axis_index = len(_figure.data)
                _suffix = str(_axis_index) if _axis_index > 1 else ""
                _figure.add_annotation(
                    text="No finite observations", x=0.5, y=0.5,
                    xref=f"x{_suffix} domain", yref=f"y{_suffix} domain",
                    showarrow=False, font={"size": 9},
                )

    _figure.update_xaxes(nticks=3, tickfont_size=9, zeroline=False)
    _figure.update_yaxes(nticks=3, tickfont_size=9, zeroline=False)
    _figure.update_layout(
        template="plotly_white", title={"text": feature_family.selected_key, "font": {"size": 16}},
        height=180 * _size + 80, showlegend=False, bargap=0, dragmode="select",
        margin={"l": 70, "r": 20, "t": 45, "b": 65},
    )
    descriptor_matrix = mo.ui.plotly(
        _figure, config={"displaylogo": False, "modeBarButtonsToAdd": ["select2d", "lasso2d"]},
    )
    return descriptor_matrix, matrix_observations_df, matrix_trace_rows


@app.cell(hide_code=True)
def feature_family_definitions(
    FEATURE_DESCRIPTIONS,
    FEATURE_LABELS,
    feature_family,
    mo,
):
    mo.accordion({
        "Feature definitions": mo.md("\n\n".join(
            f"**{FEATURE_LABELS[feature]}** — {FEATURE_DESCRIPTIONS[feature]}"
            for feature in feature_family.value
        ) + "\n\n[Full definitions and coverage rules](feature_sources.md)")
    })
    return


@app.cell(hide_code=True)
def selected_item_weeks(
    descriptor_matrix,
    matrix_observations_df,
    matrix_trace_rows,
    pl,
):
    _observation_ids = set()
    for _point in descriptor_matrix.points:
        _trace = _point.get("curveNumber")
        _point_index = _point.get("pointIndex", _point.get("pointNumber"))
        if _trace in matrix_trace_rows and isinstance(_point_index, int):
            _rows = matrix_trace_rows[_trace]
            if 0 <= _point_index < len(_rows):
                _observation_ids.add(_rows[_point_index])
    selected_item_weeks_df = (
        matrix_observations_df.filter(pl.col("observation_id").is_in(sorted(_observation_ids)))
        .sort("type_name", "focal_week_start", "type_id", "region_id")
    )
    return (selected_item_weeks_df,)


@app.cell(hide_code=True)
def selection_page_controls(mo, selected_item_weeks_df):
    _count = selected_item_weeks_df.height
    _pages = max(1, (_count + 5) // 6)
    selection_page = mo.ui.slider(
        start=1, stop=_pages, step=1, value=1, include_input=True, show_value=True,
        disabled=_pages == 1, label=f"Page (of {_pages:,})",
    )
    selection_controls_view = mo.vstack([
        mo.md(f"**Selected histories**\n\n**{_count:,} item-weeks selected** · Six per page · Original VWAP and volume values"),
        selection_page,
    ])
    return selection_controls_view, selection_page


@app.cell(hide_code=True)
def selection_history_page(
    applicable_history_df,
    pl,
    selected_item_weeks_df,
    selection_page,
):
    page_item_weeks_df = selected_item_weeks_df.slice((selection_page.value - 1) * 6, 6)
    page_history_df = (
        applicable_history_df.select("type_id", "region_id", "market_date", "vwap", "volume")
        .join(
            page_item_weeks_df.select("observation_id", "type_id", "region_id", "focal_week_start"),
            on=["type_id", "region_id"], how="inner",
        )
        .filter(pl.col("market_date").is_between(
            pl.col("focal_week_start") - pl.duration(days=7),
            pl.col("focal_week_start") + pl.duration(days=13),
        ))
        .with_columns(
            (pl.col("market_date") - pl.col("focal_week_start")).dt.total_days().alias("relative_day"),
            pl.when(pl.col("vwap").is_finite() & (pl.col("vwap") > 0)).then(pl.col("vwap")).alias("vwap"),
        )
        .select("observation_id", "market_date", "relative_day", "vwap", "volume")
        .sort("observation_id", "market_date")
    )
    return page_history_df, page_item_weeks_df


@app.cell(hide_code=True, expand_output=True)
def selection_histories_view(
    escape,
    go,
    make_subplots,
    mo,
    page_history_df,
    page_item_weeks_df,
    pl,
):
    if page_item_weeks_df.is_empty():
        _view = mo.md("Box- or lasso-select points in an upper-triangle scatterplot to compare their original price and volume histories.")
    else:
        _figures = []
        for _item in page_item_weeks_df.iter_rows(named=True):
            _figure = make_subplots(
                rows=2, cols=1, row_heights=[0.7, 0.3],
                vertical_spacing=0.06, shared_xaxes=True,
                subplot_titles=[
                    f"{escape(_item['type_name'])}<br>{_item['focal_week_start']:%b %d, %Y} to {_item['focal_week_end']:%b %d, %Y}",
                    "",
                ],
            )
            _history_df = page_history_df.filter(pl.col("observation_id") == _item["observation_id"])
            _dates = _history_df["market_date"].cast(pl.String).to_numpy()
            _figure.add_trace(go.Scatter(
                x=_history_df["relative_day"].to_numpy(), y=_history_df["vwap"].to_numpy(),
                mode="lines+markers", connectgaps=False,
                line={"color": "#2563eb", "width": 1.8}, marker={"size": 4},
                customdata=_dates,
                hovertemplate="%{customdata}<br>VWAP: %{y:,.2f} ISK<extra></extra>",
            ), row=1, col=1)
            _figure.add_trace(go.Bar(
                x=_history_df["relative_day"].to_numpy(), y=_history_df["volume"].to_numpy(),
                marker_color="#64748b", customdata=_dates,
                hovertemplate="%{customdata}<br>Volume: %{y:,.0f}<extra></extra>",
            ), row=2, col=1)
            for _row in (1, 2):
                _figure.add_vrect(
                    x0=-0.5, x1=6.5, fillcolor="#2563eb", opacity=0.08,
                    line_width=0, row=_row, col=1,
                )
            _figure.update_yaxes(title_text="VWAP (ISK)", title_font_size=10, row=1, col=1)
            _figure.update_yaxes(title_text="Volume", title_font_size=10, rangemode="tozero", row=2, col=1)
            _figure.update_xaxes(range=[-7.5, 13.5], tickvals=[-7, 0, 6, 13], tickfont_size=10)
            _figure.update_xaxes(title_text="Days from focal Sunday", title_font_size=10, showticklabels=True, row=2, col=1)
            _figure.update_yaxes(tickfont_size=10, nticks=4)
            _figure.update_annotations(font_size=12)
            _figure.update_layout(
                template="plotly_white", height=340, showlegend=False,
                margin={"l": 70, "r": 25, "t": 55, "b": 45}, bargap=0.12,
            )
            _figures.append(_figure)
        _view = mo.vstack([
            mo.md("Focal week shaded · Original values; axes scale independently"),
            *_figures,
        ], gap=0)
    selection_histories_display = _view
    return (selection_histories_display,)


@app.cell(hide_code=True)
def descriptor_selection_comparison(
    descriptor_matrix,
    mo,
    selection_controls_view,
    selection_histories_display,
):
    mo.hstack([descriptor_matrix, mo.vstack([selection_controls_view, selection_histories_display])], widths=[0.6, 0.4], align="start", gap=1)
    return


@app.cell
def _(mo):
    mo.md("""
    ## 4. Preprocessing
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    Select active descriptors and submit once to fit both projections on the same complete-finite item-weeks. Standardization uses the submitted population; no values are imputed or transformed beyond scaling.
    """)
    return


@app.cell
def projection_fit_form(FEATURE_COLUMNS, mo):
    projection_form = mo.ui.dictionary({
        "features": mo.ui.multiselect(options=list(FEATURE_COLUMNS), value=list(FEATURE_COLUMNS), label="Active descriptors"),
        "n_neighbors": mo.ui.number(start=2, step=1, value=15, label="UMAP neighbors"),
        "min_dist": mo.ui.number(start=0, stop=1, step=0.05, value=0.1, label="UMAP minimum distance"),
    }).form(submit_button_label="Fit projections")
    projection_form  # noqa: B018
    return (projection_form,)


@app.cell
def submitted_projection_settings(mo, projection_form):
    submitted_projection_config = projection_form.value
    mo.stop(submitted_projection_config is None, mo.md("Submit the form to fit projections."))
    return (submitted_projection_config,)


@app.cell
def _():
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from umap import UMAP

    return PCA, StandardScaler, UMAP


@app.cell
def validate_projection_config(
    FEATURE_COLUMNS,
    HISTORY_END,
    HISTORY_START,
    mo,
    submitted_projection_config,
):
    active_features = list(submitted_projection_config["features"])
    _neighbors = submitted_projection_config["n_neighbors"]
    _min_dist = submitted_projection_config["min_dist"]
    _config_error = None
    if len(active_features) < 2 or any(feature not in FEATURE_COLUMNS for feature in active_features) or len(set(active_features)) != len(active_features):
        _config_error = "Select at least two distinct, valid descriptors for the two-axis PCA view."
    elif _neighbors is None or int(_neighbors) != _neighbors or _neighbors < 2:
        _config_error = "UMAP neighbors must be an integer of at least 2."
    elif _min_dist is None or not 0 <= _min_dist <= 1:
        _config_error = "UMAP minimum distance must be between 0 and 1."
    mo.stop(_config_error is not None, mo.md(f"**Cannot fit:** {_config_error}"))
    projection_config = {
        "features": tuple(active_features), "n_neighbors": int(_neighbors),
        "min_dist": float(_min_dist), "metric": "euclidean", "random_state": 42,
        "n_jobs": 1, "n_components": 2, "compatibility_layout": True, "history_start": HISTORY_START, "history_end": HISTORY_END,
    }
    return active_features, projection_config


@app.cell
def standardize_projection_population(
    StandardScaler,
    active_features,
    mo,
    np,
    pl,
    projection_config,
    weekly_descriptors_df,
):
    _finite = pl.all_horizontal(pl.col(feature).is_finite().fill_null(False) for feature in active_features)
    projection_rows_df = weekly_descriptors_df.filter(_finite)
    projection_excluded_df = weekly_descriptors_df.filter(~_finite)
    projection_keys_df = projection_rows_df.select("type_id", "region_id", "focal_week_start")
    mo.stop(
        projection_rows_df.height <= max(projection_config["n_neighbors"], 3),
        mo.md(f"**Cannot fit:** {projection_rows_df.height:,} complete-finite item-weeks remain; UMAP requires more rows than its neighbor count ({projection_config['n_neighbors']}) and at least four rows."),
    )
    scaler = StandardScaler()
    standardized_descriptors = scaler.fit_transform(projection_rows_df.select(active_features).to_numpy())
    mo.stop(not np.any(scaler.var_ > 0), mo.md("**Cannot fit:** all active descriptors are constant in the complete-finite population."))
    return (
        projection_excluded_df,
        projection_keys_df,
        projection_rows_df,
        scaler,
        standardized_descriptors,
    )


@app.cell
def submitted_projection_summary(
    mo,
    projection_config,
    projection_excluded_df,
    projection_rows_df,
    scaler,
):
    mo.md(f"""
    **Fitted population:** {projection_rows_df.height:,} item-weeks · **Excluded:** {projection_excluded_df.height:,} with missing or non-finite active descriptors · **Scaled columns:** {len(scaler.mean_)}

    **Submitted descriptors:** {", ".join(projection_config["features"])}

    **Submitted UMAP settings:** {projection_config["n_neighbors"]} neighbors · minimum distance {projection_config["min_dist"]} · {projection_config["metric"]} distance · seed {projection_config["random_state"]} · {projection_config["n_jobs"]} thread
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## 5. PCA
    """)
    return


@app.cell
def fit_pca(PCA, standardized_descriptors):
    pca_model = PCA(svd_solver="full")
    pca_coordinates = pca_model.fit_transform(standardized_descriptors)
    return pca_coordinates, pca_model


@app.cell
def _(mo):
    mo.md("""
    ### 5.1 Explained variance
    """)
    return


@app.cell
def _(go, np, pca_model):
    _components = np.arange(1, len(pca_model.explained_variance_ratio_) + 1)
    _figure = go.Figure()
    _figure.add_bar(x=_components, y=pca_model.explained_variance_ratio_, name="Individual")
    _figure.add_scatter(x=_components, y=np.cumsum(pca_model.explained_variance_ratio_), mode="lines+markers", name="Cumulative")
    _figure.update_layout(template="plotly_white", xaxis_title="Principal component", yaxis_title="Explained variance ratio", yaxis_range=[0, 1.02], legend_title_text="Variance")
    _figure  # noqa: B018
    return


@app.cell
def _(mo):
    mo.md("""
    ### 5.2 Component coefficients
    """)
    return


@app.cell
def _(FEATURE_LABELS, active_features, go, pca_model):
    _figure = go.Figure(go.Heatmap(
        z=pca_model.components_, x=[FEATURE_LABELS[feature] for feature in active_features],
        y=[f"PC{i}" for i in range(1, pca_model.components_.shape[0] + 1)],
        colorscale="RdBu_r", zmid=0, zmin=-1, zmax=1,
        colorbar={"title": "Coefficient"},
        hovertemplate="%{y}<br>%{x}<br>Coefficient: %{z:.3f}<extra></extra>",
    ))
    _figure.update_layout(template="plotly_white", xaxis_title="Standardized descriptor", yaxis_title="Principal component", height=max(400, 25 * pca_model.components_.shape[0] + 160), margin={"b": 180})
    _figure.update_xaxes(tickangle=-50)
    _figure.update_yaxes(autorange="reversed")
    _figure  # noqa: B018
    return


@app.cell
def _(mo):
    mo.md("""
    ## 6. UMAP
    """)
    return


@app.cell
def fit_umap(UMAP, projection_config, standardized_descriptors):
    umap_model = UMAP(n_components=2, n_neighbors=projection_config["n_neighbors"], min_dist=projection_config["min_dist"], metric=projection_config["metric"], random_state=projection_config["random_state"], n_jobs=projection_config["n_jobs"], compatibility_layout=projection_config["compatibility_layout"])
    umap_coordinates = umap_model.fit_transform(standardized_descriptors)
    return umap_coordinates, umap_model


@app.cell
def _(mo, projection_config, umap_coordinates, umap_model):
    mo.md(f"""
    **UMAP fitted:** {len(umap_coordinates):,} item-weeks · {umap_model.n_neighbors} neighbors · minimum distance {projection_config['min_dist']} · Euclidean distance · seed {projection_config['random_state']} · one thread
    """)
    return


@app.cell(hide_code=True)
def projection_comparison_header(mo):
    mo.md("""
    ## 7. Projection comparison and original histories
    """)
    return


@app.cell(hide_code=True)
def projection_comparison_data(
    pca_coordinates,
    projection_keys_df,
    projection_rows_df,
    umap_coordinates,
):
    projection_comparison_df = projection_rows_df.with_row_index("observation_id")
    # The row index binds both coordinate arrays to the same fitted item-week keys.
    assert projection_comparison_df.height == len(pca_coordinates) == len(umap_coordinates)
    assert projection_comparison_df.select("type_id", "region_id", "focal_week_start").equals(projection_keys_df)
    return (projection_comparison_df,)


@app.cell(hide_code=True)
def projection_selection_state(mo, pca_model, umap_model):
    # Recreating this state on refit clears the previous selection.
    _projection_fit = (pca_model, umap_model)
    get_projection_selection, set_projection_selection = mo.state((None, ()))
    return get_projection_selection, set_projection_selection


@app.cell(hide_code=True)
def projection_axis_controls(mo, pca_model):
    _component_options = {
        f"PC{i + 1} ({variance:.1%} variance)": i
        for i, variance in enumerate(pca_model.explained_variance_ratio_)
    }
    pca_x_axis = mo.ui.dropdown(options=_component_options, value=next(iter(_component_options)), allow_select_none=False, label="PCA horizontal axis")
    pca_y_axis = mo.ui.dropdown(options=_component_options, value=list(_component_options)[1], allow_select_none=False, label="PCA vertical axis")
    return pca_x_axis, pca_y_axis


@app.cell(hide_code=True)
def pca_projection_view(
    go,
    mo,
    pca_coordinates,
    pca_model,
    pca_x_axis,
    pca_y_axis,
    pl,
    projection_comparison_df,
    set_projection_selection,
):
    _x = pca_x_axis.value
    _y = pca_y_axis.value
    _figure = go.Figure(go.Scattergl(
        x=pca_coordinates[:, _x], y=pca_coordinates[:, _y], mode="markers",
        marker={"size": 4, "opacity": 0.5},
        customdata=projection_comparison_df.select("type_name", "focal_week_start").cast({"focal_week_start": pl.String}).to_numpy(),
        hovertemplate="%{customdata[0]}<br>Week: %{customdata[1]}<extra></extra>",
    ))
    _figure.update_layout(template="plotly_white", height=420, margin={"l": 55, "r": 15, "t": 45, "b": 55}, title="PCA", dragmode="select", xaxis_title=f"PC{_x + 1} ({pca_model.explained_variance_ratio_[_x]:.1%})", yaxis_title=f"PC{_y + 1} ({pca_model.explained_variance_ratio_[_y]:.1%})")
    pca_projection = mo.ui.plotly(_figure, on_change=lambda points: set_projection_selection(("PCA", tuple(sorted({p.get("pointIndex", p.get("pointNumber")) for p in points if isinstance(p.get("pointIndex", p.get("pointNumber")), int)})))))
    return (pca_projection,)


@app.cell(hide_code=True)
def umap_projection_view(
    go,
    mo,
    pl,
    projection_comparison_df,
    set_projection_selection,
    umap_coordinates,
):
    _figure = go.Figure(go.Scattergl(
        x=umap_coordinates[:, 0], y=umap_coordinates[:, 1], mode="markers",
        marker={"size": 4, "opacity": 0.5},
        customdata=projection_comparison_df.select("type_name", "focal_week_start").cast({"focal_week_start": pl.String}).to_numpy(),
        hovertemplate="%{customdata[0]}<br>Week: %{customdata[1]}<extra></extra>",
    ))
    _figure.update_layout(template="plotly_white", height=420, margin={"l": 55, "r": 15, "t": 45, "b": 55}, title="UMAP", dragmode="select", xaxis_title="UMAP 1", yaxis_title="UMAP 2")
    umap_projection = mo.ui.plotly(_figure, on_change=lambda points: set_projection_selection(("UMAP", tuple(sorted({p.get("pointIndex", p.get("pointNumber")) for p in points if isinstance(p.get("pointIndex", p.get("pointNumber")), int)})))))
    return (umap_projection,)


@app.cell(hide_code=True)
def projection_selected_item_weeks(
    get_projection_selection,
    pl,
    projection_comparison_df,
):
    projection_selection_source, _indices = get_projection_selection()
    projection_selected_df = projection_comparison_df.filter(pl.col("observation_id").is_in(list(_indices))).sort("type_name", "focal_week_start", "type_id", "region_id")
    return projection_selected_df, projection_selection_source


@app.cell(hide_code=True)
def projection_page_controls(
    mo,
    projection_selected_df,
    projection_selection_source,
):
    _count = projection_selected_df.height
    _pages = max(1, (_count + 5) // 6)
    projection_page = mo.ui.slider(start=1, stop=_pages, step=1, value=1, include_input=True, show_value=True, disabled=_pages == 1, label=f"Page (of {_pages:,})")
    projection_controls_view = mo.vstack([mo.md(f"**Projection histories**\n**Source:** {projection_selection_source or 'none'} · **{_count:,} item-weeks selected** · Six per page · Original VWAP and volume values"), projection_page])
    return projection_controls_view, projection_page


@app.cell(hide_code=True)
def projection_history_page(
    applicable_history_df,
    pl,
    projection_page,
    projection_selected_df,
):
    projection_page_item_weeks_df = projection_selected_df.slice((projection_page.value - 1) * 6, 6)
    projection_page_history_df = (
        applicable_history_df.select("type_id", "region_id", "market_date", "vwap", "volume")
        .join(
            projection_page_item_weeks_df.select("observation_id", "type_id", "region_id", "focal_week_start"),
            on=["type_id", "region_id"], how="inner",
        )
        .filter(pl.col("market_date").is_between(
            pl.col("focal_week_start") - pl.duration(days=7),
            pl.col("focal_week_start") + pl.duration(days=13),
        ))
        .with_columns(
            (pl.col("market_date") - pl.col("focal_week_start")).dt.total_days().alias("relative_day"),
            pl.when(pl.col("vwap").is_finite() & (pl.col("vwap") > 0)).then(pl.col("vwap")).alias("vwap"),
        )
        .select("observation_id", "market_date", "relative_day", "vwap", "volume")
        .sort("observation_id", "market_date")
    )
    return projection_page_history_df, projection_page_item_weeks_df


@app.cell(hide_code=True)
def projection_histories_view(
    escape,
    go,
    make_subplots,
    mo,
    pl,
    projection_page_history_df,
    projection_page_item_weeks_df,
):
    if projection_page_item_weeks_df.is_empty():
        _view = mo.md("Box- or lasso-select points in either projection to compare their original price and volume histories.")
    else:
        _figures = []
        for _item in projection_page_item_weeks_df.iter_rows(named=True):
            _figure = make_subplots(
                rows=2, cols=1, row_heights=[0.7, 0.3],
                vertical_spacing=0.06, shared_xaxes=True,
                subplot_titles=[
                    f"{escape(_item['type_name'])}<br>{_item['focal_week_start']:%b %d, %Y} to {_item['focal_week_end']:%b %d, %Y}",
                    "",
                ],
            )
            _history_df = projection_page_history_df.filter(pl.col("observation_id") == _item["observation_id"])
            _dates = _history_df["market_date"].cast(pl.String).to_numpy()
            _figure.add_trace(go.Scatter(
                x=_history_df["relative_day"].to_numpy(), y=_history_df["vwap"].to_numpy(),
                mode="lines+markers", connectgaps=False,
                line={"color": "#2563eb", "width": 1.8}, marker={"size": 4},
                customdata=_dates,
                hovertemplate="%{customdata}<br>VWAP: %{y:,.2f} ISK<extra></extra>",
            ), row=1, col=1)
            _figure.add_trace(go.Bar(
                x=_history_df["relative_day"].to_numpy(), y=_history_df["volume"].to_numpy(),
                marker_color="#64748b", customdata=_dates,
                hovertemplate="%{customdata}<br>Volume: %{y:,.0f}<extra></extra>",
            ), row=2, col=1)
            for _row in (1, 2):
                _figure.add_vrect(
                    x0=-0.5, x1=6.5, fillcolor="#2563eb", opacity=0.08,
                    line_width=0, row=_row, col=1,
                )
            _figure.update_yaxes(title_text="VWAP (ISK)", title_font_size=10, row=1, col=1)
            _figure.update_yaxes(title_text="Volume", title_font_size=10, rangemode="tozero", row=2, col=1)
            _figure.update_xaxes(range=[-7.5, 13.5], tickvals=[-7, 0, 6, 13], tickfont_size=10)
            _figure.update_xaxes(title_text="Days from focal Sunday", title_font_size=10, showticklabels=True, row=2, col=1)
            _figure.update_yaxes(tickfont_size=10, nticks=4)
            _figure.update_annotations(font_size=12)
            _figure.update_layout(
                template="plotly_white", height=340, showlegend=False,
                margin={"l": 70, "r": 25, "t": 55, "b": 45}, bargap=0.12,
            )
            _figures.append(_figure)
        _view = mo.vstack([
            mo.md("Focal week shaded · Original values; axes scale independently"),
            *_figures,
        ], gap=0)
    projection_histories_display = _view
    return (projection_histories_display,)


@app.cell(hide_code=True)
def projection_comparison_view(
    mo,
    pca_projection,
    pca_x_axis,
    pca_y_axis,
    projection_controls_view,
    projection_histories_display,
    umap_projection,
):
    mo.vstack([
        mo.hstack([pca_x_axis, pca_y_axis], justify="start", gap=1),
        mo.hstack([
            pca_projection,
            umap_projection
        ], widths=[0.5, 0.5], align="start", gap=1),
        mo.vstack([projection_controls_view, projection_histories_display])
    ])
    # mo.hstack([
    #     mo.vstack([mo.hstack([], justify="start", gap=1), 
    #                pca_projection], justify="start", gap=1),
    #     umap_projection
    # ],  widths=[0.5, 0.5])
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
