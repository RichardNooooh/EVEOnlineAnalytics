select
  market_date,
  region_id,
  type_id
from {{ ref('int_study_panel_history') }}
group by market_date, region_id, type_id
having count(*) > 1
