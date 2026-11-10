# Behavioral feature sources

Reference notes for the behavioral representation in notebook 02. Sources checked
on 2026-11-09. These establish mathematical precedents, not evidence that the
features improve this study's representation or will be weakly correlated here.

The available observations are daily VWAP, high, low, volume, and historical order
count. Historical order count must not be described as transaction count. Uses of
stock-market indicators below are adaptations to daily VWAP, not transfers of
their original economic interpretation or predictive claims.

## Peak-day volume share

**Definition:** `max(daily_volume) / sum(daily_volume)` within a trailing calendar
window of `h` days.

**Precedent:** This is mathematically the Berger–Parker dominance index, with days
substituted for categories and volume for abundance. The maintained ecodive
documentation defines the index as maximum proportional abundance and provides
the equivalent calculation `max(x / sum(x))`.

- [ecodive, *Berger-Parker Index*](https://cmmr.github.io/ecodive/reference/berger.html),
  “Details” and “Base R Equivalent.” The documentation cites Berger and Parker
  (1970), *Diversity of planktonic foraminifera in deep-sea sediments*;
  the original article was not independently reviewed for this note.

**Interpretation:** Within-window concentration of activity in the busiest day,
not activity level, liquidity, or the position of the burst within the window.
Unlike recent/prior volume ratios, it can distinguish windows with identical totals
but different daily allocations. A financial-market validation of this exact
rolling-volume application was not established in the bounded source check.

**Conventions and limitations:**

- Require a full window of finite, nonnegative daily volumes and a positive total.
  Applicable absent days remain zero activity. An all-zero window is undefined,
  not zero concentration.
- Equal daily activity gives `1/h`; a single active day gives `1`. More generally,
  with `a` active days, the minimum is `1/a`. Horizon and inactivity therefore
  affect the baseline.
- Tied peaks require no tie-breaking: use the largest individual daily value,
  not the sum of tied peaks.
- The feature ignores the order of days and most of the distribution outside the
  peak. Small total activity can still produce a value of one.

## Directional balance

**Definition:** `(positive_return_days - negative_return_days) / h` over `h`
consecutive valid daily VWAP returns. Exact flats contribute zero but remain in
the denominator. Obtaining `h` returns requires `h + 1` consecutive valid prices.

**Precedent:** Da, Gurun, and Warachka's information-discreteness measure is
`ID = sign(PRET) * (%negative - %positive)`. Directional balance is the negative
of its percentage difference before the cumulative-return-sign adjustment. It is
not the complete information-discreteness measure used in the paper.

- Zhi Da, Umit G. Gurun, and Mitch Warachka (2014),
  [*Frog in the Pan: Continuous Information and Momentum*](https://academicweb.nd.edu/~zda/Frog.pdf),
  *Review of Financial Studies* 27(7), 2171–2218;
  [DOI](https://doi.org/10.1093/rfs/hhu003). See Section 1, equation (1), and
  equation (3), which explicitly distinguishes normalization with and without
  zero-return days. The author's paper text and both equations were checked.
- Related indicator definition:
  [moomoo, *PSY Psychological Line*](https://www.moomoo.com/my/support/topic3_814),
  Section 2, defines `100 * positive_days / h`. This is supplementary indicator
  documentation, not primary academic evidence. It is only an affine equivalent
  of directional balance when there are no flat days.

**Interpretation:** Prevalence of positive versus negative daily movements,
separate from their magnitudes. The financial paper supplies a precedent for the
signed-day-frequency component, not validation of our 7/14/30/60-day VWAP use.

**Conventions and limitations:**

- Do not treat missing prices as flats or bridge missing calendar days.
- All-flat windows and equally balanced up/down windows both produce zero.
- The feature ignores ordering: alternating and grouped signs can have the same
  balance. Call it directional balance, not temporal persistence.
- Many small increases and one large loss can give positive balance but negative
  cumulative return. Short windows have a coarse set of possible values.
- If every nonzero return has equal absolute magnitude `a`, net log return is
  exactly `a * h * balance`. Distinct definitions do not guarantee independence.

## VWAP position within the daily range

**Candidate adaptation:** Calculate
`q = (2 * VWAP - high - low) / (high - low)` daily, then summarize within a window.
A trailing mean was the proposed summary, not an established choice for this data.

**Precedent:** Close Location Value uses the closing price in this expression.

- Joshua Ulrich, TTR,
  [*Close Location Value*: documentation and implementation](https://github.com/joshuaulrich/TTR/blob/master/R/CLV.R).
  The `CLV()` function supplies the exact close-based expression and maps
  undefined/infinite values to zero. That implementation policy is not approval
  to apply the same substitution here.

**Potential distinction:** Position inside the reported daily range, rather than
range width. It is not a closing-price indicator or evidence of buying pressure
when applied to VWAP.

**Limitations:** Zero-width ranges are undefined; small ranges can be sensitive to
rounding. The usual `[-1, 1]` bounds require `low <= VWAP <= high` and compatible
aggregation populations. Range/VWAP compatibility and flat-range frequency must
be checked before adopting this candidate. Flat-range handling and window
eligibility remain undecided.

## Lag-one return dependence

**Candidate:** Apply a lag-one autocorrelation statistic to consecutive daily log
returns, rather than price levels.

**Precedent:** tsfresh supplies an explicit estimator. With `n` observations,
whole-window mean `mu`, and population variance `v`, its lag-one expression is
`sum((r[t] - mu) * (r[t-1] - mu)) / ((n - 1) * v)`.

- [tsfresh, `autocorrelation`: equation and implementation](https://tsfresh.readthedocs.io/en/latest/_modules/tsfresh/feature_extraction/feature_calculators.html#autocorrelation).

**Potential distinction:** Whether adjacent returns continue or alternate relative
to the window mean. Existing path reversal, `sum(abs(r)) - abs(sum(r))`, does not
directly measure adjacency.

**Limitations:** Few adjacent pairs make short windows noisy and single episodes
influential. Constant-return windows are undefined. Estimator conventions matter:
the adjusted tsfresh expression is not guaranteed to stay within `[-1, 1]`, and
its numerical near-zero-variance cutoff is an implementation policy, not a chosen
rule for this study. No estimator or missing-window policy has been selected.

## Activity–movement alignment

**Candidate adaptation:** Spearman correlation between same-day absolute valid
daily log returns and daily volume. A historical-order-count analogue is possible
but should not automatically be added as another feature.

**Precedent:** Spearman correlation is an established rank association statistic;
the particular pairing here is a proposed application.

- [SciPy, `spearmanr`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html),
  definition, `ConstantInputWarning`, and small-sample p-value warning.
- [SciPy implementation, `spearmanr()`](https://github.com/scipy/scipy/blob/v1.18.0/scipy/stats/_stats_py.py#L5203-L5469),
  ranking followed by correlation of ranked inputs.

**Potential distinction:** Whether relatively busy days coincide with relatively
large price movements. Current movement and activity summaries do not explicitly
preserve that same-day alignment. This is not causal price impact, liquidity, or
signed order flow.

**Limitations:** Short windows, tied ranks, and prominent source disturbances can
make the statistic unstable. Constant activity or absolute returns make it
undefined. Missing prices invalidate the corresponding return pairing even if
activity is known. SciPy's asymptotic p-values are not appropriate for these short
windows; the candidate is a descriptive coefficient, not a significance test.
Coverage and constant-window policies remain undecided.
