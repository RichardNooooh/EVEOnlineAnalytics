with cohort_regions as (
  select
    market_date,
    region_id,
    type_id,
    average,
    highest,
    lowest,
    order_count,
    volume,
    average * volume as estimated_traded_isk
  from {{ ref("stg_everef_market_history") }}
  where
    region_id = 10000002 -- The Forge
)

select * from cohort_regions
