with source as (
    select
        cast(date as date) as date,
        cast(region_id as bigint) as region_id,
        cast(type_id as bigint) as type_id,
        cast(average as double) as average,
        cast(highest as double) as highest,
        cast(lowest as double) as lowest,
        cast(order_count as bigint) as order_count,
        cast(volume as bigint) as volume
    from {{ source('everef', 'raw_market_history') }}
)

select
    date,
    region_id,
    type_id,
    average,
    highest,
    lowest,
    order_count,
    volume
from source
