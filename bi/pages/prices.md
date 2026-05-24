---
title: Daily Prices
---

```sql latest_prices
select
  date,
  region_id,
  type_id,
  vwap_price,
  lowest,
  highest,
  intraday_price_spread,
  intraday_volatility_ratio,
  total_isk_traded
from curated_ducklake.curated_daily_prices
order by date desc, total_isk_traded desc
limit 200
```

```sql price_trend
select
  date,
  avg(vwap_price) as avg_vwap_price,
  avg(intraday_volatility_ratio) as avg_intraday_volatility_ratio
from curated_ducklake.curated_daily_prices
group by 1
order by 1 desc
limit 90
```

# Daily Prices

<LineChart data={price_trend} x=date y=avg_vwap_price yAxisTitle="Average VWAP" xFmt="yyyy-mm-dd" />

<DataTable data={latest_prices} />
