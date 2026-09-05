with source as (
  select
    cast(order_id as bigint) as order_id,
    cast(type_id as bigint) as type_id,
    cast(issued as timestamp) as issued,
    cast(is_buy_order as boolean) as is_buy_order,
    cast(volume_remain as bigint) as volume_remain,
    cast(volume_total as bigint) as volume_total,
    cast(min_volume as bigint) as min_volume,
    cast(price as double) as price,
    cast(location_id as bigint) as location_id,
    cast(range as varchar) as order_range,
    cast(duration as bigint) as duration,
    cast(region_id as bigint) as region_id,
    cast(order_set_id as bigint) as order_set_id,
    cast(source_ref_id as varchar) as source_ref_id,
    cast(source_market_date as date) as source_market_date,
    cast(snapshot_ts as timestamp with time zone) as snapshot_ts
  from {{ source('everef', 'raw_fuzzwork_orders') }}
)

select
  order_id,
  type_id,
  issued,
  is_buy_order,
  volume_remain,
  volume_total,
  min_volume,
  price,
  location_id,
  order_range,
  duration,
  region_id,
  order_set_id,
  source_ref_id,
  source_market_date,
  snapshot_ts
from source
