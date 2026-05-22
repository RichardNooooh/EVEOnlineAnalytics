select *
from {{ ref('stg_everef_market_history_provenance') }}
where date != source_market_date
