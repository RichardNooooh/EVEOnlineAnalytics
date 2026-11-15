# Weekly behavioral feature definitions

Notebook 02 describes each item in a Sunday–Saturday focal week with its
immediately preceding and following weeks. VWAP is the source `average` field;
historical order count is not transaction count. These exploratory descriptors are
not validated predictive indicators. Next-week inputs make the representation
retrospective.

## Coverage and missingness

Each of the three weeks must have at least five positive finite VWAP observations,
including partial weeks at dataset boundaries. Applicable absent item-days have
zero activity and missing prices; observed nulls remain null. Price calculations
use available valid observations without imputation. Returns are timestamped on
focal-week days and use only valid prices on adjacent calendar days. Sunday's
return requires the actual preceding Saturday's valid price; the last valid
prior-week boundary price is never used to bridge a gap. Coverage counts for
each week's valid prices and the focal week's valid return pairs are metadata.

Activity totals use all applicable days in the respective week; an observed null,
negative or nonfinite activity makes its total unavailable. Ratios with unavailable
or zero prior totals are unavailable; zero focal or next totals are allowed. Weekly
activity totals are reference metadata, not absolute-level model features.

## Price path and shape

Let `b` be the last valid preceding-week price, `p` the chronological valid focal
prices, and `m0`, `m1`, `m2` the preceding, focal, and next weekly medians.

- `price_log_change`: `log(p[-1]/b)`; no return is fabricated across gaps.
- `upward_excursion`: `log(max(b, max(p))/b)`; `downward_excursion`:
  `log(b/min(b, min(p)))`.
- `median_shift`: concatenate `b` and `p`, split chronologically into
  non-overlapping halves with `floor(n/2)` early observations and the remainder
  late, then take `log(median(late)/median(early))`.
- `mean_relative_range`: mean `(highest-lowest)/VWAP` over valid focal prices
  with finite high and low, nonnegative low and high at least low.
- `peak_timing` and `trough_timing`: mean actual weekday index (Sunday 0 through
  Saturday 6), divided by 6, among exactly tied maximum or minimum focal prices.
  A complete flat week yields 0.5.
- For `x = log(p/m0)`, `upward_residence` is the mean of `max(x, 0)` divided by
  its maximum; `downward_residence` applies the same formula to `max(-x, 0)`.
  A direction without displacement is zero.
- `directional_balance`: mean sign of valid focal-day adjacent-calendar-day log returns,
  including zero returns in the denominator. `terminal_settling` is the mean
  absolute value of the last three such returns, or all when fewer exist. Both are
  unavailable if there are no returns.
- `focal_prior_price` is `log(m1/m0)` and `next_prior_price` is `log(m2/m0)`.

## Activity and alignment

- `volume_ratio`, `order_count_ratio`: focal/prior weekly totals.
  `next_volume_ratio`, `next_order_count_ratio`: next/prior totals.
- `peak_day_volume_share`: maximum focal daily volume divided by focal total;
  unavailable for a zero or unavailable total.
- `price_activity_alignment`: volume-weighted mean log VWAP minus ordinary mean
  log VWAP on the same valid focal price/nonnegative finite volume pairs; unavailable
  when paired volume sums to zero. This measures descriptive alignment, not impact.

## Representation and mathematical precedents

Only finite active features determine PCA eligibility. The active matrix is
standardized; magnitude coordinates use `c * asinh(z/c)` with `c=1.5`. When the
default ratio toggle is enabled, raw ratios replace their standardized coordinates
with `(r-1)/(r+1)`; other coordinates remain standardized. There is no subsequent
scaling. Feature selection is editable in the notebook.

### Peak-day volume share

This is mathematically the Berger–Parker dominance index, with days substituted
for categories and volume for abundance. The [ecodive *Berger-Parker Index*
documentation](https://cmmr.github.io/ecodive/reference/berger.html) gives maximum
proportional abundance and the equivalent `max(x / sum(x))`. It cites Berger and
Parker (1970), *Diversity of planktonic foraminifera in deep-sea sediments*; the
original article was not independently reviewed for this note.

The statistic measures concentration in the busiest day, not activity level,
liquidity, or timing. Tied peaks are not summed. It ignores day order and most of
the remaining distribution, and small total activity can still produce one. If
`a` days are active, its minimum is `1/a`. The source does not validate this
financial-market application.

### Directional balance

Da, Gurun, and Warachka's information-discreteness measure is
`ID = sign(PRET) * (%negative - %positive)`. Directional balance is the negative
of its signed-day-frequency difference before the cumulative-return-sign
adjustment, not the paper's complete measure.

- Zhi Da, Umit G. Gurun, and Mitch Warachka (2014), [*Frog in the Pan:
  Continuous Information and Momentum*](https://academicweb.nd.edu/~zda/Frog.pdf),
  *Review of Financial Studies* 27(7), 2171–2218,
  [DOI](https://doi.org/10.1093/rfs/hhu003). Section 1, equation (1), and
  equation (3) distinguish normalization with and without zero-return days.
- The supplementary [moomoo *PSY Psychological Line* definition](https://www.moomoo.com/my/support/topic3_814),
  section 2, gives `100 * positive_days / h`; it is an affine equivalent only
  when there are no flat days, not primary academic evidence.

Balance measures the prevalence of positive versus negative returns, not their
magnitudes or temporal persistence. All-flat and equally balanced up/down paths
both yield zero; grouped and alternating signs can also agree. Many small gains and
one large loss can give positive balance alongside negative net movement. Short
weeks yield coarse values, and the paper does not validate this VWAP application.

## Candidate and source-reference notes

The following are unadopted candidates, not active weekly features. Sources were
checked on 2026-11-09; their original financial interpretations and predictive
claims do not transfer automatically to daily VWAP.

### VWAP position within the daily range

The candidate `q = (2 * VWAP - high - low) / (high - low)` summarizes position
within the daily range, rather than range width. Joshua Ulrich's TTR
[*Close Location Value* documentation and implementation](https://github.com/joshuaulrich/TTR/blob/master/R/CLV.R)
uses closing price in this expression. Its substitution of zero for undefined or
infinite values is not an approved policy here.

Zero-width ranges are undefined and small ranges can be rounding-sensitive. The
usual `[-1, 1]` bounds require `low <= VWAP <= high` and compatible aggregation
populations. Compatibility and flat-range frequency need checking; flat-range
handling and eligibility are undecided. VWAP position is not evidence of buying
pressure or a closing-price indicator.

### Lag-one return dependence

One candidate measures lag-one autocorrelation of consecutive daily log returns.
The [tsfresh estimator and implementation](https://tsfresh.readthedocs.io/en/latest/_modules/tsfresh/feature_extraction/feature_calculators.html#autocorrelation)
uses `sum((r[t]-mu)*(r[t-1]-mu)) / ((n-1)*v)`, with whole-window mean `mu`
and population variance `v`. It describes adjacency, unlike a total path-reversal
summary.

Few pairs make short windows noisy; constant-return windows are undefined. This
adjusted estimator is not guaranteed to lie in `[-1, 1]`, and its numerical
near-zero-variance cutoff is an implementation choice. No estimator or
missing-window policy has been selected.

### Spearman activity–movement association

A separate candidate is Spearman correlation between same-day absolute valid
daily log returns and volume; an order-count analogue is not automatically
justified. The [SciPy `spearmanr` documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html)
describes the statistic, constant-input warning, and small-sample p-value warning;
the [implementation](https://github.com/scipy/scipy/blob/v1.18.0/scipy/stats/_stats_py.py#L5203-L5469)
ranks inputs before correlation. This differs from the active price–activity
alignment above and is not causal impact, liquidity, or signed order flow.

Short windows, ties, and disturbances can make this unstable; constant activity or
absolute returns make it undefined. Missing prices invalidate return pairs, and
asymptotic p-values are inappropriate for these short windows. Coverage and
constant-window policies remain undecided.

## Workflow precedents

- [tsfresh rolling mechanism](https://tsfresh.readthedocs.io/en/latest/text/forecasting.html#the-rolling-mechanism):
  organizes time-series windows for feature extraction.
- [sktime clustering composition](https://github.com/sktime/sktime/blob/v1.2.0/sktime/clustering/compose/_pipeline.py#L430-L447):
  illustrates composing transformations with clustering.
- [sktime `WindowSummarizer`](https://www.sktime.net/en/stable/api_reference/auto_generated/sktime.transformations.series.summarize.WindowSummarizer.html):
  provides configurable lagged and window-summary transformations.

These are workflow precedents, not validation of the active feature choices.

## Historical fourteen-day price-only trajectory experiments

The following records the former notebook 02 price-only experiments, removed in the
approved appendix cleanup. Their preparation and methods are historical, not current
workbench controls; they did not change the weekly feature bank or its missingness
rules above. The separate joint price–activity path family below remains available.

### Episode bank and interpolation

- Each observation is one item–region market over 14 consecutive calendar days.
  Starts are seven days apart, anchored to the first Sunday within the configured
  study period. Overlapping windows retain their full fitting weight.
- Prepare a separate copy of the daily history. Linearly interpolate missing VWAP
  only between observed finite prices within the same item–region history, before
  slicing episodes. Do not extrapolate leading or trailing gaps. Retain original
  prices and a daily interpolation flag.
- Retain complete episodes whose prepared prices are finite. Report incomplete
  windows and unresolved-price windows separately. Do not impose a minimum
  volatility, activity, or observed-price count for these path experiments.
- Standardize each episode independently as `(price - episode_mean) / episode_std`,
  using the population standard deviation. Exactly constant paths become zero
  vectors rather than being dropped. This removes price level and movement scale;
  small fluctuations can consequently become prominent in nearly flat windows.
- Indexed prices (`100 * price / first_episode_price`), volume, and historical order
  count remain available for interpretation. Activity is not a fitted channel and
  is not interpolated. The existing absent-day zero-activity convention is unchanged.
- Representative displays prefer the closest nonoverlapping intervals within an
  item–region market. This display selection does not remove overlapping windows
  from fitting or establish independent economic events.

### Method references

- [tslearn k-Shape documentation](https://tslearn.readthedocs.io/en/stable/gen_modules/clustering/tslearn.clustering.KShape.html)
  and [implementation](https://github.com/tslearn-team/tslearn/blob/f6072f2/tslearn/clustering/kshape.py):
  normalized cross-correlation with whole-sequence shifts and specialized fitted
  shape extraction. Shifting does not stretch local durations or wrap observations
  around the episode boundary.
- [sktime time-series k-medoids](https://www.sktime.net/en/stable/api_reference/auto_generated/sktime.clustering.k_medoids.TimeSeriesKMedoids.html)
  and [DTW guide](https://tslearn.readthedocs.io/en/stable/user_guide/dtw.html):
  local chronological alignment, with the notebook restricting matches to at most
  two calendar days of displacement. The installed sktime implementation returns
  accumulated squared local differences, without a final square root. Its medoid
  objective is the sum of those supplied costs; it is not directly comparable with
  k-Shape inertia or Euclidean motif distances.
- [STUMPY pattern matching](https://stumpy.readthedocs.io/en/latest/Tutorial_Pattern_Matching.html):
  representative-centered retrieval of recurring normalized subsequences, rather
  than a required partition of all episodes. Notebook candidates retain the same
  fourteen-day length and seven-day starts as the clustering experiments. Recurrence
  excludes overlapping windows from the same item–region market within each motif
  family; similar occurrences across different markets can remain.

The former notebook's motif search operated directly on this explicit candidate bank,
using blocked Euclidean-distance calculations rather than a full-series STUMPY
self-join. It selects a seed with the smallest admissible nearest-neighbor distance
among unassigned candidates, then retrieves cases using the documented initial
matching cutoff `max(mean(D) - 2 * std(D), min(D))`. Here `D` contains distances to
the seed's eligible, currently unassigned candidates. The initial search allows
four families and requires at least two nonoverlapping occurrences per family.
Matched windows are removed from subsequent searches; this is not an exhaustive
partition. Different families can still contain overlapping views of the same
market period. Position-aligned matching can also split one morphology into
families with different within-window timing.

These sources establish algorithm mechanics, not successful economic transfer.
The actual paths and activity context determine whether a grouping is
useful. TWE is deferred: the installed sktime implementation was found to mix the
two series in its deletion costs, producing asymmetric direct distances that its
pairwise routine can hide by mirroring one direction.

### Separate joint price–activity paths

The exploratory [`behavior_paths.py`](behavior_paths.py) preparation is a separate
input family from both the weekly descriptors and the price-only, independently
standardized trajectories above. Its provisional defaults use 14-day episodes,
seven-day Sunday-anchored starts, and the preceding 14 calendar days as reference.
The input is an already applicable, consecutive daily market panel; overlapping
episodes retain their weight.

- Reference price is the median of the **observed**, positive finite VWAP values
  in the prior 14 days, requiring at least 10; interpolated prices do not count.
  Reference activity is the mean of all 14 prior daily values, which must be finite,
  nonnegative, and have a positive mean. Volume is the default activity channel;
  historical order count is a separately configured alternative.
- Missing prices, including source-observed null prices, are linearly interpolated
  only between finite observations in the same market history; there is no
  extrapolation. Prepared episode prices must all be positive and finite. Activity
  is never interpolated: every episode value must be finite and nonnegative.
  Applicable absent days retain the upstream zero-activity convention; an observed
  null activity makes the relevant reference or episode ineligible.
- Each daily pair is `log(prepared_VWAP / reference_price)` and
  `log1p(activity / reference_activity)`. Zero activity stays zero without a
  pseudocount. Pooled population standard deviation across selected episodes and
  days scales each channel, with equal channel weights and no per-episode
  normalization. A zero or nonfinite pooled scale prevents fitting. This retains
  relative movement and activity magnitude rather than only shape.
- Candidate eligibility and rejection reasons, original and prepared values,
  optional source-observed flags, interpolation flags and exact endpoint dates,
  reference/episode support dates, references, transforms, scales, and selected
  keys are retained for inspection. Interpolation endpoints can lie outside an
  episode or its reference period.
- An optional seeded market/calendar-stratified subset is selected **before**
  fitting scales and used by both aligned and DTW comparisons. Around 2,000
  episodes is a suggested starting point for DTW, not a limit; `None` retains the
  full eligible population. Balancing changes sampling weights, and channel scales
  are fitted on the selected subset. Group occupancy describes selected windows,
  not unweighted full-population prevalence. Matrix memory is estimated, not enforced.
- Aligned distances compare the same daily vectors directly. Dependent DTW uses
  one shared alignment of both channels, a default two-day band, and the square
  root of accumulated squared paired-vector costs. This differs from the older
  price-only sktime accumulated-squared cost above; objectives are not directly
  comparable. Shared warping changes elapsed timing even though it preserves
  paired daily vectors; see the dependent/independent DTW reference below.

## Research references for further representation exploration

Sources reviewed on 2026-11-12. These references motivate experiments; they do not
validate the feature definitions, eligibility, transformations, or fitted channels
above. No reviewed source establishes a best representation for this panel's
short daily VWAP–quantity episodes.

### Feature representations and joint price–activity information

- Xiaozhe Wang, Kate A. Smith-Miles, and Rob J. Hyndman (2006),
  [*Characteristic-based clustering for time series data*](https://robjhyndman.com/publications/ts-clustering/)
  ([manuscript](https://robjhyndman.com/papers/ts-clustering.pdf)). Clusters extracted
  structural characteristics rather than raw paths, with interpretable benchmark
  results. This supports the representation family, not adoption of long-history
  seasonality, higher-moment, or nonlinear-dynamics features for fourteen days.
- Mohammad Shokoohi-Yekta et al. (2017),
  [*Generalizing DTW to the multi-dimensional case requires an adaptive approach*](https://pmc.ncbi.nlm.nih.gov/articles/PMC5668684/).
  Sections 2–3 distinguish dependent DTW, which shares an alignment across channels,
  from independent DTW, which aligns channels separately. The latter can ignore
  cross-channel lag differences. Shared alignment still changes elapsed durations;
  neither variant guarantees preservation of exact daily price–activity lags.
  The main empirical comparison is classification, not financial episode clustering.
- Andrew W. Lo and Jiang Wang (2000),
  [*Trading Volume: Definitions, Data Analysis, and Implications of Portfolio Theory*](https://www.nber.org/papers/w7625).
  Motivates share turnover for comparing equity trading activity. Raw quantities
  across heterogeneous instruments are not automatically comparable. Within-item
  relative activity is a possible alternative here, not equivalent to turnover;
  an outstanding-supply denominator and activity-reference policy are not supplied
  by this paper.
- John Y. Campbell, Sanford J. Grossman, and Jiang Wang (1993),
  [*Trading Volume and Serial Correlation in Stock Returns*](https://www.nber.org/papers/w4193),
  and Guillermo Llorente et al. (2002),
  [*Dynamic Volume-Return Relation of Individual Stocks*](https://www.nber.org/papers/w8312).
  Study volume-conditioned return dynamics, including reversal and continuation.
  They motivate joint price–activity information, not a validated episode feature
  vector, a universal direction of response, or a causal interpretation for this
  panel. Their fitted financial dynamics should not be estimated from a single
  fourteen-day window.

Separate price and activity summaries do not generally preserve their pairing or
sequence. Candidate joint timing summaries would need explicit definitions. With
fourteen prices there are at most thirteen within-window daily changes and fewer
lagged pairs; correlation features can be dominated by one movement. Constant
channels make correlations undefined, not zero. Daily VWAP and quantity do not
identify intraday sequencing, signed order flow, trader intent, or book liquidity.

### Empirical financial episode precedents

- Jiachen Ke, Renjie Xie, and Wei Xu (2023),
  [*Unsupervised Stock Clustering Based on Adversarial Learning and Its Application in Quantitative Investment*](https://dl.acm.org/doi/fullHtml/10.1145/3616712.3616765).
  Section 4.2 constructs stock-specific forty-trading-day price/turnover matrices
  with a twenty-day stride. InfoGAN produces clusters; PCA and t-SNE visualize
  the resulting assignments. This is a close stock–window sampling precedent,
  not anomaly-selected episode discovery. Evaluation concerns investment-strategy
  backtesting. Window construction, inputs, and visualization roles were checked
  through indexed publisher excerpts; full-text retrieval was blocked, and the
  exact normalization and cross-stock historical members remain unverified.
- Juwon Kim et al. (2025),
  [*From Patterns to Predictions: A Shapelet-Based Framework for Directional Forecasting in Noisy Financial Markets*](https://arxiv.org/html/2509.15040v1).
  Sections 4 and 6 describe 18–22-day multivariate subsequences, per-variable
  Min–Max normalization, dependent DTW, and DBA centroid updates. Inputs include
  closing price, volume, and RSI, with a price-plus-volume comparison. Some initial
  centers come from canonical chart-pattern prototypes; sparse clusters are
  discarded. This is recurring-pattern extraction for forecasting, not rare-event
  discovery. Experiments on several assets do not establish pooled cross-stock
  clustering. Shape normalization also removes economically relevant amplitude.
- Seyed Pendar Toufighi et al. (2025),
  [*Forecasting stock market anomalies in emerging markets: An OPTUNA-optimized isolation forest and K-means approach*](https://www.sciencedirect.com/science/article/pii/S2666827025001537).
  Uses Isolation Forest followed by K-means on detected unusual daily observations
  for Iran Khodro, 2001–2022. This supports anomaly selection followed by grouping
  as an empirical workflow, not multi-day cross-instrument episode clustering.
  Evidence was limited to publisher-indexed and repository material; complete
  feature preparation and validation were not independently established.
- Tobias Braun et al. (2018),
  [*Impact and recovery process of mini flash crashes: An empirical study*](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0196920).
  Identifies 5,529 ultrafast extreme events across stocks and dates and examines
  their next hundred trades. Recovery differs substantially across episodes.
  Event thresholds and recovery categories are predefined; learned behavioral
  clustering is not demonstrated. Intraday trades/quotes are not interchangeable
  with daily VWAP and quantity.
- A. G. Zawadowski, J. Kertész, and G. Andor (2004),
  [*Large price changes on small scales*](https://arxiv.org/html/cond-mat/0401055v2).
  Selects extreme intraday moves using absolute and stock/time-relative filters,
  then aligns price, volume, volatility, and spread responses across events.
  This is event-study aggregation by direction/exchange, not learned similarity
  groups. It is adjacent evidence for event-first analysis, not daily-window transfer.
- Eoin Cartwright, Martin Crane, and Heather J. Ruskin (2021),
  [*Financial Time Series: Market Analysis Techniques Based on Matrix Profiles*](https://doi.org/10.3390/engproc2021005045)
  ([full-text XML](https://mdpi-res.com/d_attachment/engproc/engproc-05-00045/article_deploy/engproc-05-00045.xml)).
  Retrieves recurring normalized stock/index price subsequences. Its empirical
  examples concern motifs, not anomaly-selected cross-asset clusters. Each asset's
  profile is calculated separately; coincident low profile values do not establish
  matching cross-asset paths. Historical interpretation is exploratory/visual.

These studies cover different parts of the intended task. None was verified to
combine unusual multi-day daily price–volume episodes, pooled across instruments
and noncontemporaneous dates, with validated, interpretable behavior groups.

### Nonlinear representations: visualization versus clustering input

- Leland McInnes, John Healy, and James Melville (2018; reviewed revision 2020),
  [*UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction*](https://arxiv.org/html/1802.03426v3).
  Sections 3–4 describe neighborhood-graph construction and lower-dimensional
  layout; section 6 discusses weaknesses. Output need not be two-dimensional.
  Input scaling/metric, neighborhood size, output dimension, and packing settings
  change the resulting geometry. The paper's quantitative representation evaluation
  includes classification, not proof of economic classes.
- [Official UMAP clustering guide](https://umap-learn.readthedocs.io/en/latest/clustering.html):
  demonstrates UMAP before HDBSCAN on MNIST, while explicitly warning about density
  distortion and false tears that create more groups than warranted. This is actual
  clustering evidence, but not for market descriptors or K-means. Example settings
  are not project defaults. The
  [reproducibility guide](https://umap-learn.readthedocs.io/en/latest/reproducibility.html)
  distinguishes repeatable execution from substantive stability; record actual
  versions, seeds, and execution settings. The
  [transform guide](https://umap-learn.readthedocs.io/en/latest/transform.html)
  supports mapping held-out observations into an existing fit, assuming adequate
  correspondence with the training distribution, not robustness to regime change.
- [scikit-learn t-SNE documentation](https://scikit-learn.org/stable/modules/generated/sklearn.manifold.TSNE.html):
  a nonlinear neighborhood visualization with a nonconvex objective. Its axes,
  island spacing, sizes, and densities are not economic coordinates. A differently
  arranged display does not change fitted cluster assignments. A t-SNE view of
  existing labels is distinct from clustering its two-dimensional coordinates.
- Pascal Vincent et al. (2010),
  [*Stacked Denoising Autoencoders: Learning Useful Representations in a Deep Network with a Local Denoising Criterion*](https://www.jmlr.org/papers/v11/vincent10a.html)
  ([paper](https://www.jmlr.org/papers/volume11/vincent10a/vincent10a.pdf)).
  Sections 2.3 and 3 explain why reconstruction alone is insufficient and how
  recovering clean inputs from corrupted inputs encourages useful dependencies.
  Main evidence concerns classification and learned features, not cluster recovery.
  Corruption type/strength defines the desired robustness; masking-style denoising
  is specifically cautioned against for very low-dimensional problems. It is not
  an automatic choice for a compact economic descriptor vector.
- Zhihan Yue et al. (2022),
  [*TS2Vec: Towards Universal Representation of Time Series*](https://arxiv.org/html/2106.10466).
  Learns contextual multivariate representations with hierarchical contrastive
  objectives. Classification uses a trained SVM on embeddings; forecasting and
  anomaly detection are also evaluated. Augmentation ablations show that imposed
  invariances can hurt. This is not evidence of superior unsupervised market-window
  clustering, and no training-data sufficiency threshold transfers to this panel.

An autoencoder's reconstruction objective does not identify a unique latent
distance geometry: encoder scaling can be compensated by the decoder. Unequal
directional scaling can change Euclidean clustering even when reconstruction is
similar. Feature scaling likewise changes both UMAP neighborhoods and squared-error
reconstruction weights. Regularization constrains solutions but does not supply an
economic similarity metric by itself.

The exploratory [`behavior_workbench.py` `Settings`](behavior_workbench.py#L120)
defines module defaults for comparing the eligible descriptor matrix through PCA,
UMAP, and an optional regularized autoencoder. The
[notebook controls](02_behavior_representation_exploration.ipynb) can override those
defaults; consult them and the execution summary for the actual configuration rather
than treating module defaults as notebook choices. Matching output dimensions controls
output size, not model capacity. Joint daily price–activity paths change the input
information and are a separate experiment.

One repetition supports browsing, not a conclusion about seed stability. Five
K-means initializations are a browsing starting point; shortlisted runs merit
stronger optimization and seed checks. Common-input silhouette measures compactness
in the reference Euclidean geometry, not an automatic ranking of nonlinear or
warped alternatives. Interpret it alongside group characterization.

The module disables the autoencoder by default; notebook controls may override that
choice. It runs on CPU when enabled. Its provisional
fully connected architecture is input–32–16–latent–16–32–input, with ReLU hidden
layers and linear bottleneck and output. It uses mean squared reconstruction error,
Adam (learning rate 0.001, weight decay 0.0001), batches of 256, at most 100 epochs,
and patience 10. For validation, the final 20% of distinct focal weeks are held out;
training rows whose preceding/focal/following-week support overlaps validation
support are purged, and preprocessing is fitted on the remaining training rows.
The selected epoch count is then used for a fresh full-population preprocessing and
model refit; the resulting embedding is not a held-out validation embedding.
The notebook's optional `ae_history` view shows retained validation loss, the best
epoch, and whether training stopped early or reached its epoch budget.

These settings are starting points, not a selected economic similarity metric.
Reconstruction loss alone cannot declare a clustering winner; inspect original
descriptor profiles and historical paths alongside diagnostics. The UMAP and
autoencoder references above motivate those cautions, and no inspected head-to-head
financial study establishes which representation should win here.

### Evaluation references and case-study use

- Shai Ben-David, Dávid Pál, and Hans Ulrich Simon (2007),
  [*Stability of k-Means Clustering*](https://dl.acm.org/doi/10.5555/1768841.1768847).
  Its theoretical finite-support setting challenges stability as proof of
  meaningful groups. Stability is robustness evidence, not economic validation;
  the result is not a theorem about this dependent window panel. Publisher abstract
  evidence was available; the full paper was not inspected.
- [Official `cluster::clusGap` documentation](https://stat.ethz.ch/R-manual/R-devel/library/cluster/html/clusGap.html),
  implementing Tibshirani, Walther, and Hastie (2001): the reference null is uniform
  on a bounding hypercube, optionally PCA-rotated, and selection can retain one
  group. That null does not preserve market dependence or heterogeneous activity.
- Dimitris N. Politis and Joseph P. Romano (1994),
  [*The Stationary Bootstrap*](https://doi.org/10.1080/01621459.1994.10476870),
  motivates block rather than independent-row resampling for weakly dependent
  stationary observations. Its assumptions and validity do not automatically
  extend to this pipeline. The bounded review used abstract-level evidence.
- David H. Bailey et al. (2017),
  [*The Probability of Backtest Overfitting*](https://scholarworks.wmich.edu/math_pubs/42),
  concerns investment-strategy selection, not clustering. It motivates guarding
  against repeated outcome-driven specification selection, not adopting its
  validation procedure here. The bounded review used repository abstract evidence.

Interpret groups through original descriptors and daily price–activity paths;
embedding separation and autoencoder reconstruction are supporting diagnostics.
Overlapping windows and neighboring-week context share observations. Calendar-held-out
checks must account for the full input/context support, rather than randomly split
rows. Characterization using fitted descriptors is not independent validation.

The existing [shared-event briefs](../.local/m1-shared-events/20261021-first-pass/grouping-10x3-related4x14/localized-review/findings.md)
and [review page](../.local/m1-shared-events/20261021-first-pass/grouping-10x3-related4x14/localized-review/review.html)
provide a case-study bridge, not tuning labels. Their frozen 100-item panel must be
reconciled with the current study population before reporting participation.
Simultaneous event participants need not share one price–activity behavior, and
consolidated candidate containers are review indexes, not episode-duration estimates.
A separate fit on nominated unusual windows asks about behavior conditional on
selection; refitting its scaling or representation would additionally change the
geometry. Selection-to-window mapping and those fit choices remain open.
