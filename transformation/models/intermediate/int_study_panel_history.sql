with history as (
  select *
  from {{ ref('int_forge_market_history') }}
  where market_date >= date '2022-06-01'
),

panel as (
  select
    type_id,
    type_name,
    study_category
  from {{ ref('int_study_panel') }}
)

select
  h.market_date,
  h.region_id,
  h.type_id,
  p.type_name,
  p.study_category,
  h.average,
  h.highest,
  h.lowest,
  h.order_count,
  h.volume,
  h.estimated_traded_isk
from history as h
inner join panel as p on h.type_id = p.type_id
