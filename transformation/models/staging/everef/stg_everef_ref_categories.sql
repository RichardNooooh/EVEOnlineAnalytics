with source as (
    select
        cast(category_id as bigint) as category_id,
        cast(name_en as varchar) as name_en,
        cast(published as boolean) as published,
        cast(icon_id as bigint) as icon_id
    from {{ source('everef', 'raw_reference_categories') }}
)

select
    category_id,
    name_en,
    published,
    icon_id
from source
