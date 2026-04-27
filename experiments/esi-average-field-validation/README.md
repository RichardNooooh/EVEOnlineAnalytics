# ESI Average Field Validation

## Purpose

This experiment records empirical evidence that the ESI market history `average`
field behaves as a volume-weighted average trade price, not as a median.

## Source Sample

- Source file: `eve-esi-sample-2026-04-27-10000002-87265-gleaned-static.json`
- Fetched/analyzed: 2026-04-27
- Endpoint: `GET /markets/{region_id}/history/?type_id={type_id}`
- Region: The Forge (`region_id = 10000002`)
- Type: Gleaned Static (`type_id = 87265`)

Gleaned Static is useful for this check because several rows have low
`order_count` and low `volume`, making the implied trade mix inferable from the
published `lowest`, `highest`, `volume`, and `average` fields.

## Proof Examples

### 2025-11-01

Observed row:

- `lowest = 1,578,000`
- `highest = 3,000,000`
- `order_count = 2`
- `volume = 6`
- `average = 2,763,000`

This exactly matches one unit at 1,578,000 and five units at 3,000,000:

```text
(1 x 1,578,000 + 5 x 3,000,000) / 6
= 16,578,000 / 6
= 2,763,000
```

A median-style interpretation would not produce `2,763,000`.

### 2025-12-26

Observed row:

- `lowest = 498.1`
- `highest = 302,000`
- `order_count = 2`
- `volume = 3`
- `average = 201,499.37`

This matches one unit at 498.1 and two units at 302,000:

```text
(1 x 498.1 + 2 x 302,000) / 3
= 604,498.1 / 3
= 201,499.366...
~= 201,499.37
```

A median-style interpretation would not produce `201,499.37`.

### 2026-02-03

Observed row:

- `lowest = 999.4`
- `highest = 3,000,000`
- `order_count = 2`
- `volume = 4`
- `average = 2,250,249.85`

This matches one unit at 999.4 and three units at 3,000,000:

```text
(1 x 999.4 + 3 x 3,000,000) / 4
= 9,000,999.4 / 4
= 2,250,249.85
```

A unit-weighted median would be `3,000,000`, not `2,250,249.85`.

## Conclusion

For this sample, the ESI market history `average` field behaves as:

```text
average = total ISK traded / total units traded
```

The most accurate semantic interpretation is therefore:

```text
volume_weighted_average_trade_price
```

Bronze/raw layers should preserve the source field name as `average` or
`esi_average`, while dataset contracts and documentation should describe the
field semantics as volume-weighted average price (VWAP). The in-game client may
label the corresponding value as `median`, but this sample supports VWAP as the
API field meaning.
