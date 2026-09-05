select market_date
from {{ ref('stg_everef_market_history_provenance') }}
group by market_date
having count(distinct source_url) > 1
