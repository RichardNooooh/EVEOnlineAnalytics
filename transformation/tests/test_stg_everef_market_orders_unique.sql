with duplicates as (
    select
        source_ref_id,
        order_id,
        count(*) as row_count
    from {{ ref("stg_everef_market_orders") }}
    group by source_ref_id, order_id
    having row_count > 1
)

select * from duplicates
