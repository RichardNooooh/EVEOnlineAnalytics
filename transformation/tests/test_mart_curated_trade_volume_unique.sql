with duplicates as (
    select
        date,
        region_id,
        type_id,
        count(*) as row_count
    from {{ ref("mart_curated_trade_volume") }}
    group by date, region_id, type_id
    having row_count > 1
)

select * from duplicates
