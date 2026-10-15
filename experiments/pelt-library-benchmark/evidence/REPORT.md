# PELT library benchmark

The original benchmark ran in `/tmp/opencode/pelt-library-benchmark/` with an
isolated vendor overlay. Its measured evidence is retained here; no notebook,
project dependency, or dataset publication was changed by that benchmark. New
runs write to ignored `experiments/.local/pelt-library-benchmark/`.

## Purpose and Scope

The user observed roughly 1.5 hours for an outer configuration of the
detection notebook's full grid. That reported end-to-end runtime is not a
timing in this report. A bounded profile found that repeated sktime L1 median
calculations consumed about 98% of the profiled time.

After research identified skchange, this benchmark changed only the PELT
backend. It kept the standardized daily inputs, explicit penalties, and
14-day minimum-segment semantics unchanged. The timings below are bounded
per-fit measurements, not a full-grid runtime estimate. Their parity checks
and speedups support selecting skchange for the accepted solution; they do not
claim a measured full-grid speedup.

## Method

- sktime 1.2.0 versus skchange 0.18.0; 2 warm repetitions per configuration with randomized backend order.
- Both use the same standardized float64 daily arrays, explicit numeric penalties, minimum segment length 14, step size 1, and pruning enabled.
- Timings include detector construction, fit, and predict; exclude imports, input extraction/scaling, and result checks.
- First invocation per backend/cost is separate from warm timings. L2 can reuse shared kernels compiled by L1. A fresh temporary Numba cache was used.
- Both backends use supported Numba 0.67.0 in the historical temporary vendor overlay; the notebook environment at measurement time had Numba 0.68.0.
- Four cases come from one representative item (Tritanium). This is not a full-panel timing estimate.

## First-invocation timings

| Cost | Backend | Seconds |
| --- | --- | ---: |
| L1 | sktime | 5.6540 |
| L1 | skchange | 5.9819 |
| L2 | sktime | 3.0711 |
| L2 | skchange | 1.0647 |

## Warm median timings

| Case | n | Cost | Penalty multiplier | sktime seconds | skchange seconds | Speedup | Boundaries | Same positions |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| tritanium_activity_700 | 700 | L1 | 0.5 | 5.5013 | 0.5898 | 9.33x | 1 | True |
| tritanium_activity_700 | 700 | L1 | 1 | 5.7269 | 0.6741 | 8.50x | 0 | True |
| tritanium_activity_700 | 700 | L1 | 2 | 6.1958 | 0.6749 | 9.18x | 0 | True |
| tritanium_activity_700 | 700 | L2 | 0.5 | 0.0748 | 0.0247 | 3.03x | 2 | True |
| tritanium_activity_700 | 700 | L2 | 1 | 0.0654 | 0.0191 | 3.43x | 2 | True |
| tritanium_activity_700 | 700 | L2 | 2 | 0.0683 | 0.0203 | 3.37x | 2 | True |
| tritanium_activity_full | 1554 | L1 | 0.5 | 24.4766 | 3.6281 | 6.75x | 3 | True |
| tritanium_activity_full | 1554 | L1 | 1 | 34.8371 | 6.6226 | 5.26x | 2 | True |
| tritanium_activity_full | 1554 | L1 | 2 | 34.9364 | 6.8069 | 5.13x | 1 | True |
| tritanium_activity_full | 1554 | L2 | 0.5 | 0.1674 | 0.0534 | 3.14x | 4 | True |
| tritanium_activity_full | 1554 | L2 | 1 | 0.1721 | 0.0504 | 3.42x | 2 | True |
| tritanium_activity_full | 1554 | L2 | 2 | 0.1709 | 0.0529 | 3.23x | 2 | True |
| tritanium_price_first | 457 | L1 | 0.5 | 0.7452 | 0.0391 | 19.08x | 7 | True |
| tritanium_price_first | 457 | L1 | 1 | 0.9532 | 0.0481 | 19.83x | 4 | True |
| tritanium_price_first | 457 | L1 | 2 | 1.4037 | 0.0662 | 21.20x | 2 | True |
| tritanium_price_first | 457 | L2 | 0.5 | 0.0453 | 0.0177 | 2.56x | 7 | True |
| tritanium_price_first | 457 | L2 | 1 | 0.0460 | 0.0172 | 2.68x | 5 | True |
| tritanium_price_first | 457 | L2 | 2 | 0.0459 | 0.0161 | 2.84x | 2 | True |
| tritanium_price_long | 1095 | L1 | 0.5 | 2.7549 | 0.1266 | 21.76x | 14 | True |
| tritanium_price_long | 1095 | L1 | 1 | 3.4476 | 0.1680 | 20.53x | 10 | True |
| tritanium_price_long | 1095 | L1 | 2 | 7.5631 | 0.4972 | 15.21x | 4 | True |
| tritanium_price_long | 1095 | L2 | 0.5 | 0.1151 | 0.0438 | 2.63x | 13 | True |
| tritanium_price_long | 1095 | L2 | 1 | 0.1209 | 0.0440 | 2.75x | 10 | True |
| tritanium_price_long | 1095 | L2 | 2 | 0.1176 | 0.0442 | 2.66x | 4 | True |

## Validation

- Both backends agree with direct NumPy interval costs on 81 intervals per case/cost.
- Both agree with an independent exact dynamic-programming oracle on minimum-length, level-step, flat/tied, and spike/reversal examples, across both costs and all three penalties.
- 0 boundary-position mismatches across recorded checks. Objective tolerance: rtol=1e-9, atol=1e-8.
- Every fitted segment satisfies the minimum length; terminal positions and run starts are not returned as boundaries.

Raw repetitions, boundary dates, objectives, metadata, and frozen benchmark arrays are in `results.json`, `metadata.json`, and `inputs.npz`.
