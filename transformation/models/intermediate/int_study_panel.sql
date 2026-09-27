with panel as (
  select
    type_id,
    study_category
  from {{ ref('forge_study_panel') }}
),

types as (
  select
    type_id,
    name_en as type_name
  from {{ ref('stg_everef_ref_types') }}
)

select
  p.type_id,
  t.type_name,
  p.study_category
from panel as p
left join types as t on p.type_id = t.type_id
