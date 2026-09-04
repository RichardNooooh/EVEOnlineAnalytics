with source as (
  select
    cast(order_id as bigint) as order_id,
    cast(type_id as bigint) as type_id,
    cast(region_id as bigint) as region_id,
    cast(source_ref_id as varchar) as source_ref_id,
    cast(source_market_date as date) as source_market_date,
    cast(snapshot_ts as timestamp with time zone) as snapshot_ts
  from {{ source('everef', 'raw_fuzzwork_orders') }}
)

select
  order_id,
  type_id,
  region_id,
  source_ref_id,
  source_market_date,
  snapshot_ts
from source
