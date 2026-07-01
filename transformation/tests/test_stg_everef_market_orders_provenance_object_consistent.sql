with inconsistent_object as (
    select
        source_ref_id,
        count(distinct source_market_date) as source_market_date_count,
        count(distinct snapshot_ts) as snapshot_count
    from {{ ref("stg_everef_market_orders_provenance") }}
    group by source_ref_id
    having source_market_date_count > 1 or snapshot_count > 1
)

select * from inconsistent_object
