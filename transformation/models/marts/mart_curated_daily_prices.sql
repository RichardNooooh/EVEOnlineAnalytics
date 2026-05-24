with market_history as (
    select *
    from {{ ref("fact_market_history") }}
)

select
    market_date as date,
    region_id,
    type_id,
    average as vwap_price,
    lowest,
    highest,
    total_isk_traded,
    (highest - lowest) as intraday_price_spread,
    case
        when average > 0 then (highest - lowest) / average
    end as intraday_volatility_ratio
from market_history
