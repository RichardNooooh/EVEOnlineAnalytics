with pub_types as (
  select
    type_id,
    group_id,
    category_id,
    market_group_id,
    name_en,
    description_en,
    volume
  from {{ ref("stg_everef_ref_types") }}
  where published = true
)

select * from pub_types
