with source as (
  select
    cast(group_id as bigint) as group_id,
    cast(name_en as varchar) as name_en,
    cast(category_id as bigint) as category_id,
    cast(published as boolean) as published,
    cast(icon_id as bigint) as icon_id
  from {{ source('everef', 'raw_reference_groups') }}
)

select
  group_id,
  name_en,
  category_id,
  published,
  icon_id
from source
