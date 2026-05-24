with market_history as (
    select *
    from {{ ref("stg_everef_market_history") }}
)

select
    *,
    (volume * average) as total_isk_traded,
    case
        when order_count > 0 then total_isk_traded / order_count
        else 0
    end as average_isk_per_order
from market_history
