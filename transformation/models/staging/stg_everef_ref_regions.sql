with source as (
  select
    cast(region_id as bigint) as region_id,
    cast(name_en as varchar) as name_en,
    cast(description_en as varchar) as description_en,
    cast(universe_id as varchar) as universe_id,
    cast(faction_id as bigint) as faction_id,
    cast(wormhole_class_id as bigint) as wormhole_class_id
  from {{ source('everef', 'raw_reference_regions') }}
)

select
  region_id,
  name_en,
  description_en,
  universe_id,
  faction_id,
  wormhole_class_id
from source
