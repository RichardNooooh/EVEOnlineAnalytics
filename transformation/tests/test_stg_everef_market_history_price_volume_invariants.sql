select *
from {{ ref('stg_everef_market_history') }}
where
    average < 0
    or highest < 0
    or lowest < 0
    or highest < lowest
    or order_count < 0
    or volume < 0
