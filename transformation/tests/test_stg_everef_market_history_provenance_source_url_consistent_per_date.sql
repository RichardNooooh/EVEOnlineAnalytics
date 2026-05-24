select date
from {{ ref('stg_everef_market_history_provenance') }}
group by date
having count(distinct source_url) > 1
