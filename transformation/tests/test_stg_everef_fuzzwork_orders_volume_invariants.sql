select *
from {{ ref('stg_everef_fuzzwork_orders') }}
where
    price < 0
    or volume_remain < 0
    or volume_total < 0
    or volume_remain > volume_total
    or min_volume < 0
    or duration < 0
