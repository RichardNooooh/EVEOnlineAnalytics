with market_history as (
    select *
    from {{ ref("fact_market_history") }}
)

select
    market_date,
    region_id,
    type_id,
    volume as traded_units,
    order_count,
    total_isk_traded,
    average_isk_per_order
from market_history
