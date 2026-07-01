---
title: Curated Market Overview
---

```sql price_summary
select
  max(market_date) as latest_date,
  count(*) as row_count,
  count(distinct region_id) as region_count,
  count(distinct type_id) as item_count
from curated_ducklake.curated_daily_prices
```

```sql volume_summary
select
  max(market_date) as latest_date,
  count(*) as row_count,
  sum(traded_units) as traded_units,
  sum(total_isk_traded) as total_isk_traded
from curated_ducklake.curated_trade_volume
```

```sql latest_price_trends
select
  market_date,
  avg(vwap_price) as avg_vwap_price,
  avg(intraday_volatility_ratio) as avg_intraday_volatility_ratio
from curated_ducklake.curated_daily_prices
group by 1
order by 1 desc
limit 30
```

```sql latest_volume_trends
select
  market_date,
  sum(traded_units) as traded_units,
  sum(total_isk_traded) as total_isk_traded
from curated_ducklake.curated_trade_volume
group by 1
order by 1 desc
limit 30
```

# Curated Market Overview

Read-only Evidence app over published curated DuckLake state.

## Dataset Checks

<DataTable data={price_summary} />

<DataTable data={volume_summary} />

## Recent Price Trend

<LineChart data={latest_price_trends} x=market_date y=avg_vwap_price yAxisTitle="Average VWAP" xFmt="yyyy-mm-dd" />

## Recent Volume Trend

<BarChart data={latest_volume_trends} x=market_date y=traded_units yAxisTitle="Traded Units" xFmt="yyyy-mm-dd" />

## Pages

- [Prices](/prices)
- [Volume](/volume)
