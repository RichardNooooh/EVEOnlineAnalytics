---
title: Trade Volume
---

```sql latest_volume
select
  date,
  region_id,
  type_id,
  traded_units,
  order_count,
  total_isk_traded,
  average_isk_per_order
from curated_ducklake.curated_trade_volume
order by date desc, traded_units desc
limit 200
```

```sql volume_trend
select
  date,
  sum(traded_units) as traded_units,
  sum(total_isk_traded) as total_isk_traded,
  sum(order_count) as order_count
from curated_ducklake.curated_trade_volume
group by 1
order by 1 desc
limit 90
```

# Trade Volume

<BarChart data={volume_trend} x=date y=traded_units yAxisTitle="Traded Units" xFmt="yyyy-mm-dd" />

<DataTable data={latest_volume} />
