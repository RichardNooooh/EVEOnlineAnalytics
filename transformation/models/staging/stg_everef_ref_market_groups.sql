with source as (
  select
    cast(market_group_id as bigint) as market_group_id,
    cast(name_en as varchar) as name_en,
    cast(description_en as varchar) as description_en,
    cast(parent_group_id as bigint) as parent_group_id,
    cast(has_types as boolean) as has_types,
    cast(icon_id as bigint) as icon_id
  from {{ source('everef', 'raw_reference_market_groups') }}
)

select
  market_group_id,
  name_en,
  description_en,
  parent_group_id,
  has_types,
  icon_id
from source
