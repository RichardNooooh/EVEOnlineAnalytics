with pub_groups as (
  select
    group_id,
    name_en,
    category_id
  from {{ ref("stg_everef_ref_groups") }}
  where published = true
)

select * from pub_groups
