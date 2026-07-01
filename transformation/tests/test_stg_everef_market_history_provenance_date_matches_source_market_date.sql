select *
from {{ ref('stg_everef_market_history_provenance') }}
where
    market_date != row_source_market_date
    or market_date != source_market_date
