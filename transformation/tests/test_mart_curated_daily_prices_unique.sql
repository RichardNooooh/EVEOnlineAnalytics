with duplicates as (
    select
        market_date,
        region_id,
        type_id,
        count(*) as row_count
    from {{ ref("mart_curated_daily_prices") }}
    group by market_date, region_id, type_id
    having row_count > 1
)

select * from duplicates
