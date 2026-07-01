with source as (
    select
        cast(order_id as bigint) as order_id,
        cast(type_id as bigint) as type_id,
        cast(region_id as bigint) as region_id,
        cast(location_id as bigint) as location_id,
        cast(system_id as bigint) as system_id,
        cast(range as varchar) as order_range,
        cast(price as double) as price,
        cast(volume_remain as bigint) as volume_remain,
        cast(volume_total as bigint) as volume_total,
        cast(min_volume as bigint) as min_volume,
        cast(issued as timestamp) as issued,
        cast(expires as timestamp) as expires,
        cast(duration as bigint) as duration,
        cast(is_buy_order as boolean) as is_buy_order,
        cast(reported_by as bigint) as reported_by,
        cast(http_last_modified as timestamp) as http_last_modified,
        cast(station_id as bigint) as station_id,
        cast(constellation_id as bigint) as constellation_id,
        cast(source_ref_id as varchar) as source_ref_id,
        cast(source_market_date as date) as source_market_date,
        cast(snapshot_ts as timestamp with time zone) as snapshot_ts
    from {{ source('everef', 'raw_market_orders') }}
)

select
    order_id,
    type_id,
    region_id,
    location_id,
    system_id,
    order_range,
    price,
    volume_remain,
    volume_total,
    min_volume,
    issued,
    expires,
    duration,
    is_buy_order,
    reported_by,
    http_last_modified,
    station_id,
    constellation_id,
    source_ref_id,
    source_market_date,
    snapshot_ts
from source
