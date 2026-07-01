with source as (
    select
        cast(type_id as bigint) as type_id,
        cast(name_en as varchar) as name_en,
        cast(description_en as varchar) as description_en,
        cast(group_id as bigint) as group_id,
        cast(category_id as bigint) as category_id,
        cast(market_group_id as bigint) as market_group_id,
        cast(published as boolean) as published,
        cast(volume as double) as volume,
        cast(icon_id as bigint) as icon_id,
        cast(meta_group_id as bigint) as meta_group_id
    from {{ source('everef', 'raw_reference_types') }}
)

select
    type_id,
    name_en,
    description_en,
    group_id,
    category_id,
    market_group_id,
    published,
    volume,
    icon_id,
    meta_group_id
from source
