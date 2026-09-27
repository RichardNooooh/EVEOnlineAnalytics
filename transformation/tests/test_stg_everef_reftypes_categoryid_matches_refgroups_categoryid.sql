with types as (
  select
    type_id,
    name_en as type_name,
    group_id,
    category_id
  from {{ ref('stg_everef_ref_types') }}
),

groups as (
  select
    group_id,
    name_en as group_name,
    category_id
  from {{ ref('stg_everef_ref_groups') }}
)

-- Do the category_ids on each type match the category_id listed on the type's group?
select
  types.type_id,
  types.type_name,
  groups.group_id,
  groups.group_name
from types
inner join groups
  on types.group_id = groups.group_id
where types.category_id != groups.category_id
