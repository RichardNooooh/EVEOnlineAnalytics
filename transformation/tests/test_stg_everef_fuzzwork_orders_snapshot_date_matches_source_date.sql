select *
from {{ ref('stg_everef_fuzzwork_orders') }}
where cast(snapshot_ts as date) not in (source_market_date, source_market_date - interval 1 day)
